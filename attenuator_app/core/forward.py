"""Оптические схемы и прямая задача: затухание, поляризация выхода.

Все углы — ориентация ОСИ ПРОПУСКАНИЯ элемента (перпендикулярно проводам),
в градусах, против часовой стрелки. Провода лежат под angle + 90.
Отступление от этой конвенции — источник ошибки на 90 град.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import blanco
from .passport import Passport

# ---------------------------------------------------------------------------
SCHEMES = {
    "S0": "single WGP(theta) -> detector",
    "S1": "WGP(theta) -> WGP(phi2 fixed) -> detector",
    "S2": "WGP(theta1) -> WGP(theta2) -> detector (both movable)",
    "S3": "film(0) -> WGP(theta) -> film(0) -> detector  [calibration scheme]",
}
DETECTORS = {
    "coherent": "coherent (photoconductive antenna, EO sampling) - FIELD projection onto axis d",
    "power": "power (bolometer, pyroelectric, Golay cell) - total power of both components",
}
SOURCES = {
    "linear": "linearly polarized source (angle psi)",
    "unpolarized": "unpolarized / partially polarized (DOP)",
}


@dataclass
class Setup:
    """Конфигурация оптической схемы и приёмного тракта."""
    scheme: str = "S3"
    detector: str = "coherent"
    source: str = "linear"
    psi_deg: float = 0.0          # азимут поляризации источника
    dop: float = 1.0              # степень поляризации источника
    det_deg: float = 0.0          # ось чувствительности детектора
    phi2_deg: float = 0.0         # ось второго WGP (S1) / плёнок (S3)
    use_film: bool = True         # учитывать плёночные поляризаторы в S3

    def validate(self):
        if self.scheme not in SCHEMES:
            raise ValueError(f"unknown scheme {self.scheme!r}, available {list(SCHEMES)}")
        if self.detector not in DETECTORS:
            raise ValueError(f"unknown detector {self.detector!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown source {self.source!r}")
        if not 0.0 <= self.dop <= 1.0:
            raise ValueError("DOP must be within [0, 1]")


# ---------------------------------------------------------------------------
def _jones(phi_deg, a, b):
    """Матрица Джонса элемента: ось пропускания phi, амплитуды (a, b).

    phi_deg : скаляр или (n_ang,);  a, b : (n_f,) или скаляр
    возврат : (n_ang, n_f, 2, 2)
    """
    phi = np.atleast_1d(np.asarray(phi_deg, dtype=float))[:, None]
    phi = np.deg2rad(phi)
    a = np.asarray(a, dtype=complex)[None, :] if np.ndim(a) else np.asarray(a, dtype=complex)
    b = np.asarray(b, dtype=complex)[None, :] if np.ndim(b) else np.asarray(b, dtype=complex)
    c, s = np.cos(phi), np.sin(phi)
    cc, ss, cs = c * c, s * s, c * s
    j00, j11, j01 = np.broadcast_arrays(a * cc + b * ss, a * ss + b * cc, (a - b) * cs)
    return np.stack([np.stack([j00, j01], -1), np.stack([j01, j11], -1)], -2)


def _mul(A, B):
    return np.einsum("...ij,...jk->...ik", A, B)


def _unit(angle_deg):
    t = np.deg2rad(float(angle_deg))
    return np.array([np.cos(t), np.sin(t)], dtype=complex)


def chain(theta1_deg, freqs_thz, passport: Passport, setup: Setup,
          theta2_deg=None, *, d_eff=None, loss=None, gamma=None):
    """Полная матрица Джонса схемы. Возврат (n_ang, n_f, 2, 2) + маска clip."""
    nu = np.ascontiguousarray(freqs_thz, dtype=float)
    if getattr(passport, "ideal_elements", False):
        tp = np.ones(nu.shape, dtype=complex)
        ta = np.zeros(nu.shape, dtype=complex)
        clipped = np.zeros(nu.shape, dtype=bool)
    else:
        tp, ta, clipped = blanco.dressed_t(
            nu, **passport.model_kwargs(d_eff=d_eff, loss=loss, gamma=gamma))

    th1 = np.atleast_1d(np.asarray(theta1_deg, dtype=float)) - passport.angle_offset_deg.value
    sch = setup.scheme

    if sch == "S0":
        M = _jones(th1, tp, ta)
    elif sch == "S1":
        M = _mul(_jones(setup.phi2_deg, tp, ta), _jones(th1, tp, ta))
    elif sch == "S2":
        th2 = np.atleast_1d(np.asarray(
            setup.phi2_deg if theta2_deg is None else theta2_deg, dtype=float))
        th2 = np.broadcast_to(th2, th1.shape) - passport.angle_offset_deg.value
        M = _mul(_jones(th2, tp, ta), _jones(th1, tp, ta))
    elif sch == "S3":
        M = _jones(th1, tp, ta)
        if setup.use_film and passport.film is not None:
            fa, fb = passport.film.amps(nu)
            F = _jones(setup.phi2_deg, np.full(nu.shape, fa, dtype=complex),
                       np.asarray(fb, dtype=complex))
            M = _mul(F[0][None], _mul(M, F[0][None]))
    else:
        raise ValueError(f"scheme {sch!r} is not implemented")

    if passport.tau_ps.value:
        M = M * np.exp(-1j * 2 * np.pi * nu * passport.tau_ps.value)[None, :, None, None]
    return M, clipped


def intensity(theta1_deg, freqs_thz, passport: Passport, setup: Setup,
              theta2_deg=None, **kw):
    """Интенсивность на детекторе, (n_ang, n_f). Учитывает тип детектора и DOP."""
    M, clipped = chain(theta1_deg, freqs_thz, passport, setup, theta2_deg, **kw)

    def one(psi_deg):
        E = np.einsum("...ij,j->...i", M, _unit(psi_deg))
        if setup.detector == "coherent":
            return np.abs(np.einsum("...i,i->...", E, _unit(setup.det_deg))) ** 2
        return np.sum(np.abs(E) ** 2, axis=-1)

    I = setup.dop * one(setup.psi_deg)
    if setup.dop < 1.0:
        # неполяризованная доля: некогерентная сумма двух ортогональных, по 1/2
        unpol = 0.5 * (one(setup.psi_deg) + one(setup.psi_deg + 90.0))
        I = I + (1.0 - setup.dop) * unpol
    return I, clipped


def output_polarization(theta1_deg, freqs_thz, passport: Passport, setup: Setup,
                        theta2_deg=None):
    """Азимут (град) и эллиптичность (град) поля на выходе. (n_ang, n_f) каждая."""
    M, _ = chain(theta1_deg, freqs_thz, passport, setup, theta2_deg)
    E = np.einsum("...ij,j->...i", M, _unit(setup.psi_deg))
    Ex, Ey = E[..., 0], E[..., 1]
    # параметры Стокса полностью поляризованного поля
    s1 = np.abs(Ex) ** 2 - np.abs(Ey) ** 2
    s2 = 2 * np.real(Ex * np.conj(Ey))
    s3 = -2 * np.imag(Ex * np.conj(Ey))
    s0 = np.abs(Ex) ** 2 + np.abs(Ey) ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        azim = 0.5 * np.degrees(np.arctan2(s2, s1))
        ellip = 0.5 * np.degrees(np.arcsin(np.clip(s3 / np.maximum(s0, 1e-300), -1, 1)))
    return azim, ellip


# ---------------------------------------------------------------------------
def attenuation_db(theta1_deg, freqs_thz, passport: Passport, setup: Setup,
                   *, theta2_deg=None, ref_theta1_deg=None, ref_theta2_deg=None,
                   **kw):
    """Спектральное затухание в дБ ПО МОЩНОСТИ.

    ref_theta1_deg=None -> абсолютный режим (референс = единичный вход).
    иначе                -> относительный (референс = интенсивность при опорных углах).
    """
    I, clipped = intensity(theta1_deg, freqs_thz, passport, setup, theta2_deg, **kw)
    if ref_theta1_deg is None:
        I_ref = np.ones_like(I[:1])
    else:
        I_ref, _ = intensity(ref_theta1_deg, freqs_thz, passport, setup,
                             ref_theta2_deg, **kw)
    with np.errstate(divide="ignore"):
        db = -10.0 * np.log10(np.maximum(I, 1e-300) / np.maximum(I_ref, 1e-300))
    return db, clipped


def attenuation_integral_db(theta1_deg, freqs_thz, weight, passport: Passport,
                            setup: Setup, *, theta2_deg=None,
                            ref_theta1_deg=None, ref_theta2_deg=None, **kw):
    """Интегральное (широкополосное) затухание по энергии импульса, дБ.

    weight — спектральный вес источника w(nu) той же длины, что freqs_thz.
    """
    nu = np.asarray(freqs_thz, dtype=float)
    w = np.asarray(weight, dtype=float)
    I, _ = intensity(theta1_deg, nu, passport, setup, theta2_deg, **kw)
    num = np.trapezoid(I * w[None, :], nu, axis=1)
    if ref_theta1_deg is None:
        den = np.trapezoid(w, nu)
    else:
        I_ref, _ = intensity(ref_theta1_deg, nu, passport, setup, ref_theta2_deg, **kw)
        den = np.trapezoid(I_ref * w[None, :], nu, axis=1)
    with np.errstate(divide="ignore"):
        return -10.0 * np.log10(np.maximum(num, 1e-300) / np.maximum(den, 1e-300))


IDEAL_DB_CAP = 99.0     # у идеальной cos^4 в скрещённом положении полюс


def ideal_cos4_db(theta_deg, ref_deg=0.0):
    """Идеальный предел: A = -40*log10(cos(dtheta)) — опорная кривая для сравнения.

    В скрещённом положении величина расходится (идеальные поляризаторы гасят
    нацело), поэтому результат ограничен IDEAL_DB_CAP: показывать 650 дБ
    бессмысленно, реальный пол задаётся утечкой и лежит около 40 дБ.
    """
    d = np.deg2rad(np.asarray(theta_deg, dtype=float) - ref_deg)
    val = -40.0 * np.log10(np.maximum(np.abs(np.cos(d)), 1e-300))
    return np.minimum(val, IDEAL_DB_CAP)
