"""Обратная задача: какой угол выставить для заданного затухания.

Задача НЕ решается слепым оптимизатором: A(θ) немонотонна (растёт до точки
экстинкции, затем падает), поэтому решений несколько. Здесь:
  1) аналитическое начальное приближение из идеального предела cos^4;
  2) поиск ВСЕХ ветвей сканированием + бисекция на каждой;
  3) привязка к делениям шкалы (прибор с ручной установкой угла);
  4) ранжирование по политике.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .forward import Setup, attenuation_db, attenuation_integral_db
from .limits import slope_db_per_deg, uncertainty
from .passport import Passport


@dataclass
class Solution:
    theta_deg: float               # точное решение модели
    theta_set_deg: float           # что реально выставить по шкале
    achieved_db: float             # затухание при theta_set_deg
    target_db: float
    sigma_db: float
    lo_db: float
    hi_db: float
    slope_db_per_deg: float
    branch: str                    # 'monotone' | 'mirror' | 'beyond'
    move_deg: float
    rank: int = 0
    parts: dict = field(default_factory=dict)

    def __str__(self):
        return (f"theta = {self.theta_set_deg:+7.2f} deg  ->  {self.achieved_db:6.2f} dB "
                f"[95%: {self.lo_db:6.2f} ... {self.hi_db:6.2f}]  "
                f"slope {self.slope_db_per_deg:5.2f} dB/deg  "
                f"branch {self.branch}, move {self.move_deg:+.1f} deg")


def analytic_guess_deg(target_db: float) -> float:
    """Идеальный предел: A = -40 log10(cos Δθ)  ->  Δθ = arccos(10^(-A/40))."""
    x = 10.0 ** (-abs(target_db) / 40.0)
    return float(np.degrees(np.arccos(np.clip(x, 0.0, 1.0))))


def snap_to_scale(theta_deg: float, passport: Passport, ref_deg: float = 0.0) -> float:
    """Ближайшее деление шкалы (прибор с ручной установкой угла)."""
    d = passport.scale.division_deg
    return ref_deg + round((theta_deg - ref_deg) / d) * d


def _curve(thetas, passport, setup, freqs, weight, ref_theta, integral):
    if integral:
        return attenuation_integral_db(thetas, freqs, weight, passport, setup,
                                       ref_theta1_deg=ref_theta)
    db, _ = attenuation_db(thetas, freqs, passport, setup, ref_theta1_deg=ref_theta)
    return db.mean(axis=1)


def solve(target_db: float, passport: Passport, setup: Setup, freqs, *,
          weight=None, ref_theta_deg=0.0, integral=False,
          current_theta_deg=0.0, span=(-180.0, 180.0), n_scan=1441,
          snap=True, policy="monotone_then_precision", max_solutions=4):
    """Все решения обратной задачи, ранжированные. Пустой список — недостижимо."""
    nu = np.atleast_1d(np.asarray(freqs, dtype=float))
    th = np.linspace(span[0], span[1], n_scan)
    a = _curve(th, passport, setup, nu, weight, ref_theta_deg, integral)

    # пересечения кривой с уровнем target
    g = a - target_db
    idx = np.where(np.sign(g[:-1]) * np.sign(g[1:]) <= 0)[0]

    roots = []
    for i in idx:
        lo, hi = th[i], th[i + 1]
        glo = g[i]
        for _ in range(60):                     # бисекция
            mid = 0.5 * (lo + hi)
            gm = _curve(np.array([mid]), passport, setup, nu,
                        weight, ref_theta_deg, integral)[0] - target_db
            if np.sign(gm) == np.sign(glo):
                lo, glo = mid, gm
            else:
                hi = mid
            if hi - lo < 1e-4:
                break
        roots.append(0.5 * (lo + hi))

    if not roots:
        return []

    # дедупликация
    uniq = []
    for r in sorted(roots):
        if not uniq or abs(r - uniq[-1]) > 0.05:
            uniq.append(r)

    theta_ext = float(th[int(np.argmax(a))])
    sols = []
    for r in uniq:
        set_deg = snap_to_scale(r, passport, ref_theta_deg) if snap else r
        ach = float(_curve(np.array([set_deg]), passport, setup, nu,
                           weight, ref_theta_deg, integral)[0])
        u = uncertainty(set_deg, passport, setup, nu, weight=weight,
                        ref_theta_deg=ref_theta_deg, integral=integral)
        sl = slope_db_per_deg(set_deg, passport, setup, nu, weight=weight,
                              ref_theta_deg=ref_theta_deg, integral=integral)
        if abs(r) > abs(theta_ext) + 1e-6:
            branch = "beyond"
        elif r < ref_theta_deg:
            branch = "mirror"
        else:
            branch = "monotone"
        sols.append(Solution(
            theta_deg=r, theta_set_deg=set_deg, achieved_db=ach, target_db=target_db,
            sigma_db=u.sigma_db, lo_db=u.lo_db, hi_db=u.hi_db,
            slope_db_per_deg=sl, branch=branch,
            move_deg=set_deg - current_theta_deg, parts=u.parts))

    order = {"monotone": 0, "mirror": 1, "beyond": 2}
    if policy == "min_move":
        sols.sort(key=lambda s: (abs(s.move_deg), order[s.branch]))
    elif policy == "max_precision":
        sols.sort(key=lambda s: (abs(s.slope_db_per_deg), order[s.branch]))
    else:   # monotone_then_precision
        sols.sort(key=lambda s: (order[s.branch], abs(s.slope_db_per_deg)))
    for k, s in enumerate(sols[:max_solutions], 1):
        s.rank = k
    return sols[:max_solutions]


def sweep(targets_db, passport: Passport, setup: Setup, freqs, **kw):
    """Развёртка уровней: список целей -> лучшие решения, обход по возрастанию угла.

    Монотонный обход без реверсов убирает люфт как источник ошибки — на глубоких
    затуханиях это единицы дБ.
    """
    rows = []
    for t in targets_db:
        s = solve(float(t), passport, setup, freqs, **kw)
        rows.append((float(t), s[0] if s else None))
    rows.sort(key=lambda r: (r[1].theta_set_deg if r[1] else 1e9))
    return rows
