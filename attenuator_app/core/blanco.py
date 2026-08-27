"""Электродинамическое ядро: коэффициенты пропускания проволочной решётки.

Модель Бланко 1986 (эквивалентные схемы) + поверхностный импеданс металла (Друде).
Векторизовано по частоте, с LRU-кэшем по (сетка частот, P, D, N, drude).

Модуль самодостаточен: зависит только от numpy. Это сознательно — библиотека
предназначена для встраивания в чужие проекты (см. attenuator_app/api.py).

Единицы: частота — ТГц, геометрия — микрометры.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

EPS = 1e-12
C_LIGHT = 3e8          # м/с — то же значение, что в калибровочном коде
Z0 = 376.7303          # Ом, импеданс вакуума

# Друде для вольфрама (материал проволок)
SIGMA0_W = 1.8e7       # См/м
TAU_W = 8.0e-15        # с

_CACHE: "OrderedDict[tuple, tuple]" = OrderedDict()
_CACHE_MAX = 256
_STATS = {"hits": 0, "misses": 0}


def cache_stats() -> dict:
    return {**_STATS, "size": len(_CACHE)}


def clear_cache() -> None:
    _CACHE.clear()
    _STATS.update(hits=0, misses=0)


def _drude_z(freqs_thz: np.ndarray, use_drude: bool) -> np.ndarray:
    """Нормализованный поверхностный импеданс Z_s/Z_0."""
    if not use_drude:
        return np.zeros(freqs_thz.shape, dtype=complex)
    omega = freqs_thz * 2 * np.pi * 1e12
    mu0 = 4 * np.pi * 1e-7
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_omega = SIGMA0_W / (1.0 - 1j * omega * TAU_W)
        Z_s = np.sqrt(1j * omega * mu0 / sigma_omega)
    return np.where(freqs_thz > 0, Z_s / Z0, 0j)


def _tt(freqs_thz: np.ndarray, p_um: float, d_um: float, N: int,
        use_drude: bool):
    """(t_perp, t_par) на всей сетке частот. p_um, d_um — микрометры."""
    d_over_p = d_um / p_um
    lam_um = C_LIGHT / (freqs_thz * 1e12) * 1e6
    pol = p_um / lam_um                       # P/lambda
    Z_drude = _drude_z(freqs_thz, use_drude)
    ones = np.ones(freqs_thz.shape)

    if d_over_p <= 0 or d_over_p >= 1:
        fa, fb, fc, fd = ones * 1e6, ones * -1e6, ones * 0.0, ones * 0.0
    else:
        pidl = np.pi * d_over_p * pol
        slog = np.log(max(1.0 / (np.pi * d_over_p), EPS))

        sum_inv = np.zeros(freqs_thz.shape, dtype=complex)
        sum_a2 = np.zeros(freqs_thz.shape, dtype=complex)
        for m in range(1, N + 1):
            C_m = np.sqrt((m ** 2 - pol ** 2) + 1j * 1e-9)
            sum_inv = sum_inv + (1.0 / C_m - 1.0 / m)
            sum_a2 = sum_a2 + (m - 0.5 / m * pol ** 2 - C_m)

        A1 = 1.0 + 0.5 * pidl ** 2 * (slog + 0.75) + 0.5 * pidl ** 2 * sum_inv
        A2 = (1.0 + 0.5 * pidl ** 2 * (11.0 / 4.0 - slog)
              + (1.0 / 24.0) * pidl ** 2 - pidl ** 2 * sum_a2)

        ok_a2 = np.abs(A2) >= EPS
        A2s = np.where(ok_a2, A2, 1.0)
        ok_pol = np.abs(pol) >= EPS
        pols = np.where(ok_pol, pol, 1.0)

        fa = np.where(ok_a2, 0.5 * pol * (np.pi * d_over_p) ** 2 / A2s, 1e6)
        fb = np.where(ok_a2 & ok_pol,
                      2.0 / pols * (1.0 / (np.pi * d_over_p)) ** 2 * A1
                      - pol / 4.0 * (np.pi * d_over_p) ** 2 / A2s, -1e6)
        fc = pol * (slog + sum_inv)
        fd = pol * (np.pi * d_over_p) ** 2

    # --- перпендикулярная поляризация (пропускается) ---
    ok_fa, ok_fb = np.abs(fa) > EPS, np.abs(fb) > EPS
    Za = np.where(ok_fa, -1j / np.where(ok_fa, fa, 1.0) + Z_drude, -1e9j)
    Zb = np.where(ok_fb, -1j / np.where(ok_fb, fb, 1.0) + Z_drude, -1e9j)

    num1 = Za ** 2 + Za * Zb + Za ** 2 * Zb
    den1 = 2.0 * Za + Za ** 2 + Zb + Za * Zb
    ok = np.abs(den1) > EPS
    Z1 = np.where(ok, num1 / np.where(ok, den1, 1.0), 0j)
    ok = np.abs(1.0 + Za) > EPS
    Z2 = np.where(ok, Za / np.where(ok, 1.0 + Za, 1.0), 1.0 + 0j)

    den_t = (1.0 + Z1) * (Zb + Z2)
    ok = np.abs(den_t) > EPS
    t_perp = np.where(ok, 2.0 * Z1 * Z2 / np.where(ok, den_t, 1.0), 0j)

    # --- параллельная поляризация (гасится) ---
    Zc = 1j * fc + Z_drude
    Zd = -1j * fd + Z_drude
    den34 = 1.0 + Zc + Zd
    ok34 = np.abs(den34) >= EPS
    den34s = np.where(ok34, den34, 1.0)
    Z3 = (Zd + 2.0 * Zc * Zd + Zd ** 2 + Zc) / den34s
    Z4 = (Zc + Zc * Zd) / den34s
    den_p = (1.0 + Z3) * (Zd + Z4) * (1.0 + Zd)
    okp = np.abs(den_p) > EPS
    t_par = np.where(ok34 & okp, 2.0 * Z3 * Z4 / np.where(okp, den_p, 1.0), 0j)

    return t_perp, t_par


def blanco_t(freqs_thz, p_um: float, d_um: float, N: int = 15,
             use_drude: bool = True):
    """Кэшированные (t_perp, t_par). Возвращает read-only массивы."""
    freqs_thz = np.ascontiguousarray(freqs_thz, dtype=float)
    key = (freqs_thz.tobytes(), freqs_thz.shape,
           float(p_um), float(d_um), int(N), bool(use_drude))
    hit = _CACHE.get(key)
    if hit is not None:
        _STATS["hits"] += 1
        _CACHE.move_to_end(key)
        return hit
    _STATS["misses"] += 1

    tp, ta = _tt(freqs_thz, p_um, d_um, N, use_drude)
    tp.flags.writeable = False
    ta.flags.writeable = False
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.popitem(last=False)
    _CACHE[key] = (tp, ta)
    return tp, ta


# ---------------------------------------------------------------------------
# Феноменологические поправки поверх ядра
# ---------------------------------------------------------------------------
def soft_clip(freqs_thz: np.ndarray, f_hi: float, f_lo: float,
              mode: str = "soft") -> np.ndarray:
    """Ограничитель аргумента степенных законов вне полосы калибровки.

    Показатели вида nu^gamma, подогнанные в узкой полосе, при экстраполяции
    вверх уходят в нефизичные значения (gamma до 4.2 по нашим фитам).
    Ниже f_lo феноменология ЗАМОРАЖИВАЕТСЯ всегда: продлевать eta0*nu^a вниз
    означало бы получить «идеальный поляризатор» на низких частотах.

    mode: 'off' — без ограничения; 'soft' — насыщение; 'freeze' — заморозка на f_hi.
    """
    nu = np.asarray(freqs_thz, dtype=float)
    out = np.maximum(nu, f_lo)                       # снизу — всегда заморозка
    if mode == "off":
        return np.where(nu < f_lo, f_lo, nu)
    if mode == "freeze":
        return np.minimum(out, f_hi)
    over = out > f_hi
    d_soft = max(f_hi, 1e-6)
    out = np.where(over, f_hi + (out - f_hi) / (1.0 + (out - f_hi) / d_soft), out)
    return out


def dressed_t(freqs_thz, p_um, d_um, *, loss_factor=0.0, gamma=2.0,
              eta0=0.0, eta_exp=1.0, delta0=0.0, tau_leak_ps=0.0,
              tau_par_ps=0.0, N=15, use_drude=True,
              band=None, clip_mode="soft"):
    """(t_perp, t_par) с рассеянием, утечкой и фазовыми задержками.

    band=(f_lo, f_hi) — полоса калибровки; вне её аргумент степенных законов
    ограничивается (см. soft_clip). Возвращает также маску `clipped`.
    """
    nu = np.ascontiguousarray(freqs_thz, dtype=float)
    tp, ta = blanco_t(nu, p_um, d_um, N, use_drude)
    tp, ta = tp.copy(), ta.copy()

    if band is None:
        nu_eff = nu
        clipped = np.zeros(nu.shape, dtype=bool)
    else:
        f_lo, f_hi = band
        nu_eff = soft_clip(nu, f_hi, f_lo, clip_mode)
        clipped = ~np.isclose(nu_eff, nu, rtol=1e-12, atol=0.0)

    if eta0 != 0.0:
        ta = ta + eta0 * nu_eff ** eta_exp * np.exp(
            1j * (delta0 + 2 * np.pi * nu * tau_leak_ps))
    if tau_par_ps != 0.0:
        ta = ta * np.exp(-1j * 2 * np.pi * nu * tau_par_ps)
    if loss_factor != 0.0:
        # loss_factor задан в дБ/ТГц^gamma ПО МОЩНОСТИ:
        #   4.343 = 10/ln10 (дБ -> неперы по мощности), 0.5 — переход к амплитуде
        amp = np.exp(-0.5 * (loss_factor / 4.343) * nu_eff ** gamma)
        tp, ta = tp * amp, ta * amp

    return tp, ta, clipped
