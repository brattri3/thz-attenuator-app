"""Публичный фасад библиотеки — то, что встраивают в чужие проекты.

    from attenuator_app.api import Attenuator
    att = Attenuator.from_passport("attenuator_app/passports/ATT-356-01.json")
    att.set_zero(0.0)
    print(att.attenuation(theta_deg=60))
    for s in att.solve(target_db=20):
        print(s)

Задел на моторизацию: solve() возвращает Solution с полем theta_set_deg, а
`motion_plan()` превращает решения в список команд поворота. Пока ротаторов нет,
команды печатаются как инструкция оператору; когда появится привод, тот же
список уйдёт в драйвер без изменения вызывающего кода.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from .core import inverse, limits, weights
from .core.forward import (Setup, attenuation_db, attenuation_integral_db,
                           ideal_cos4_db, output_polarization)
from .core.passport import Passport

__all__ = ["Attenuator", "Setup", "Passport", "MotionCommand"]


@dataclass
class MotionCommand:
    axis: str               # 'wgp1' | 'wgp2'
    target_deg: float
    from_deg: float
    note: str = ""

    def as_operator_instruction(self) -> str:
        d = self.target_deg - self.from_deg
        way = "clockwise" if d < 0 else "counterclockwise"
        return (f"[{self.axis}] rotate by {abs(d):.1f} deg {way} "
                f"-> set {self.target_deg:+.1f} deg"
                + (f"   ({self.note})" if self.note else ""))


class Attenuator:
    """Один прибор + одна оптическая схема + текущее состояние."""

    def __init__(self, passport: Passport, setup: Setup | None = None,
                 freqs_thz=None):
        self.passport = passport
        self.setup = setup or Setup(scheme=passport.fit_scheme,
                                    detector=passport.fit_detector)
        self.setup.validate()
        self.freqs = (np.linspace(*passport.band_thz, 128)
                      if freqs_thz is None else np.asarray(freqs_thz, dtype=float))
        self.zero_deg: float | None = None
        self.theta_deg: float = 0.0
        self.weight = None
        self.weight_desc = "not set"
        self._dr = None

    # -- конструкторы --------------------------------------------------
    @classmethod
    def from_passport(cls, path, **kw):
        return cls(Passport.load(path), **kw)

    # -- состояние -----------------------------------------------------
    def set_zero(self, theta_deg: float | None = None) -> float:
        """SET ZERO: объявить положение опорным (0 дБ по определению)."""
        self.zero_deg = self.theta_deg if theta_deg is None else float(theta_deg)
        return self.zero_deg

    def auto_zero(self, span=(-20.0, 20.0), n=401) -> float:
        """AUTO-ZERO: найти МАКСИМУМ пропускания (механический ноль ≠ параллельность)."""
        th = np.linspace(*span, n)
        db, _ = attenuation_db(th, self.freqs, self.passport, self.setup)
        self.zero_deg = float(th[int(np.argmin(db.mean(axis=1)))])
        return self.zero_deg

    def auto_cross(self, span=(60.0, 120.0), n=601):
        """AUTO-CROSS: найти МИНИМУМ пропускания. Он лежит НЕ обязательно на 90°."""
        floor_db, th_ext = limits.attenuation_floor(
            self.passport, self.setup, self.freqs, weight=self.weight,
            ref_theta_deg=self.zero_deg or 0.0, integral=self.weight is not None,
            span=span, n=n)
        return th_ext, floor_db

    def set_weight(self, kind="preset", **kw):
        self.weight = weights.build(self.freqs, kind, **kw)
        self.weight_desc = f"{kind}({', '.join(f'{k}={v}' for k, v in kw.items())})"
        return weights.effective_band(self.freqs, self.weight)

    def load_background(self, path):
        """Фон для оценки динамического диапазона установки (проверка F3)."""
        self._dr = limits.dynamic_range_db(path, self.freqs)
        return None if self._dr is None else float(np.min(self._dr))

    # -- прямая задача -------------------------------------------------
    def attenuation(self, theta_deg=None, *, relative=True, integral=False):
        """Затухание в дБ по мощности + консервативный 95 % интервал."""
        th = self.theta_deg if theta_deg is None else float(theta_deg)
        ref = (self.zero_deg if self.zero_deg is not None else 0.0) if relative else None
        if integral:
            if self.weight is None:
                raise ValueError("integral attenuation requires a spectral weight "
                                 "(set_weight): without w(nu) the value is undefined")
            val = float(attenuation_integral_db(th, self.freqs, self.weight,
                                                self.passport, self.setup,
                                                ref_theta1_deg=ref)[0])
        else:
            db, _ = attenuation_db(th, self.freqs, self.passport, self.setup,
                                   ref_theta1_deg=ref)
            val = float(db.mean())
        u = limits.uncertainty(th, self.passport, self.setup, self.freqs,
                               weight=self.weight, ref_theta_deg=ref, integral=integral)
        return {"theta_deg": th, "att_db": val, "sigma_db": u.sigma_db,
                "ci95_db": (u.lo_db, u.hi_db), "relative": relative,
                "integral": integral, "field_ratio": 10 ** (-val / 20),
                "power_ratio": 10 ** (-val / 10),
                "ideal_cos4_db": float(ideal_cos4_db(th, ref or 0.0)),
                "parts": u.parts}

    def spectrum(self, theta_deg=None, *, relative=True):
        th = self.theta_deg if theta_deg is None else float(theta_deg)
        ref = (self.zero_deg if self.zero_deg is not None else 0.0) if relative else None
        db, clipped = attenuation_db(th, self.freqs, self.passport, self.setup,
                                     ref_theta1_deg=ref)
        az, el = output_polarization(th, self.freqs, self.passport, self.setup)
        return {"freq_thz": self.freqs, "att_db": db[0], "zone": self.passport.zone(self.freqs),
                "clipped": clipped, "azimuth_deg": az[0], "ellipticity_deg": el[0],
                "extrapolated": (self.freqs < self.passport.band_thz[0])
                                | (self.freqs > self.passport.band_thz[1])}

    # -- обратная задача -----------------------------------------------
    def solve(self, target_db: float, *, integral=False, policy="monotone_then_precision",
              snap=True):
        if integral and self.weight is None:
            raise ValueError("integral inverse problem requires a spectral weight")
        return inverse.solve(float(target_db), self.passport, self.setup, self.freqs,
                             weight=self.weight,
                             ref_theta_deg=self.zero_deg if self.zero_deg is not None else 0.0,
                             integral=integral, current_theta_deg=self.theta_deg,
                             policy=policy, snap=snap)

    def checks(self, target_db, theta_deg=None, *, integral=False, **tol):
        floor_th, floor_db = self.auto_cross()      # порядок: (угол, дБ)
        return limits.run_checks(
            float(target_db), theta_deg, self.passport, self.setup, self.freqs,
            weight=self.weight,
            ref_theta_deg=self.zero_deg if self.zero_deg is not None else 0.0,
            integral=integral, dr_db=self._dr,
            floor_db=floor_db, floor_theta=floor_th, **tol)

    def sweep(self, targets_db, **kw):
        return inverse.sweep(targets_db, self.passport, self.setup, self.freqs,
                             weight=self.weight,
                             ref_theta_deg=self.zero_deg if self.zero_deg is not None else 0.0,
                             current_theta_deg=self.theta_deg, **kw)

    # -- движение ------------------------------------------------------
    def motion_plan(self, solution) -> list[MotionCommand]:
        """Решение -> команды поворота. Сейчас инструкция оператору, потом — драйверу."""
        cmds = [MotionCommand("wgp2", solution.theta_set_deg, self.theta_deg,
                              f"scale division {self.passport.scale.division_deg:g} deg")]
        return cmds

    def apply(self, solution):
        self.theta_deg = solution.theta_set_deg
        return self.theta_deg

    # -- сводка --------------------------------------------------------
    def device_summary(self) -> dict:
        p = self.passport
        return {
            "serial": p.serial, "model": p.model, "aperture_mm": p.aperture_mm,
            "P_um": p.P_um.value, "D_eff_um": p.D_eff_um.value,
            "D_eff_over_D_phys": p.D_eff_um.value / p.D_phys_um if p.D_phys_um else None,
            "band_thz": p.band_thz, "scheme_calibrated": p.fit_scheme,
            "nu_anomaly_thz": p.nu_anomaly_thz,
            "zone_green_max_thz": p.zone_green_max_thz,
            "scale_division_deg": p.scale.division_deg,
            "sigma_angle_deg": p.scale.sigma_total_deg(),
            "film": p.film.name if p.film else None,
        }
