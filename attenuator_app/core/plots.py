"""Научные графики (matplotlib). Опциональная зависимость.

Ядро приложения остаётся numpy-only: этот модуль импортируется лениво, и если
matplotlib не установлен, CLI молча возвращается к ASCII-псевдографике.

Палитра и правила оформления — из общей дизайн-системы, прошли валидацию
(3 категориальных слота, all-pairs: CVD dE 9.2, normal-vision dE 24.0).
Сознательные ограничения, которым следует каждый график:
  * НИКОГДА две оси Y — вторая величина уходит на отдельную панель;
  * легенда всегда при двух и более сериях;
  * зоны применимости — не «ещё один цвет серии», а статусная палитра
    (good / warning / critical), и они всегда подписаны словами;
  * экстраполяция за полосу калибровки кодируется ВТОРЫМ каналом (пунктир),
    а не только цветом;
  * текст — в чернильных токенах, не в цвете серии.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# --- палитра -------------------------------------------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]      # blue, orange, aqua
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

ZONE_COLOR = {"green": STATUS["good"], "amber": STATUS["warning"], "red": STATUS["critical"]}
ZONE_LABEL = {"green": "reliable", "amber": "polarization degradation", "red": "grid diffracts"}


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.labelsize": 9.5, "axes.titlesize": 10.5, "axes.titleweight": "600",
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "xtick.direction": "out", "ytick.direction": "out",
        "grid.color": GRID, "grid.linewidth": 0.7,
        "legend.frameon": False, "legend.fontsize": 8.5,
        "figure.dpi": 170, "savefig.dpi": 170, "savefig.bbox": "tight",
    })
    return plt


def _finish(ax, xlabel, ylabel, title=None, sub=None):
    ax.grid(True, which="major", alpha=0.9)
    ax.grid(True, which="minor", alpha=0.4, linewidth=0.5)
    ax.minorticks_on()
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        # подзаголовок живёт НАД осью, поэтому заголовку нужен запас, иначе они
        # накладываются друг на друга
        ax.set_title(title, loc="left", color=INK, pad=22 if sub else 8)
    if sub:
        ax.text(0.0, 1.012, sub, transform=ax.transAxes, fontsize=8.2,
                color=MUTED, va="bottom")


def _legend(ax, loc="lower left", ncol=1):
    """Легенда внутри поля, в свободном углу, с подложкой.

    Над полем она спорит с подзаголовком, справа вверху — с подписями зон.
    Подложка нужна потому, что коридор неопределённости занимает почти весь
    прямоугольник и без неё текст ложится прямо на заливку.
    """
    leg = ax.legend(loc=loc, ncol=ncol, fontsize=8.2, columnspacing=1.4,
                    handlelength=1.9, frameon=True, framealpha=0.9,
                    facecolor=SURFACE, edgecolor="none", borderpad=0.6)
    leg.set_zorder(8)
    return leg


def _footer(fig, text):
    fig.text(0.005, -0.02, text, fontsize=7.4, color=MUTED, va="top")


def _zones(ax, freqs, zones):
    """Фоновая заливка зон применимости + подпись словом.

    Если весь диапазон лежит в одной зоне, заливать нечего — сплошной фон не
    несёт информации и только мешает читать данные. Тогда возвращается имя
    зоны, чтобы вынести его в подзаголовок.
    """
    z = np.asarray(zones, dtype=object)
    nu = np.asarray(freqs, dtype=float)
    names = set(str(v) for v in z)
    if len(names) <= 1:
        return next(iter(names)) if names else None

    edges = np.where(z[1:] != z[:-1])[0] + 1
    starts = np.concatenate([[0], edges])
    ends = np.concatenate([edges, [len(z)]])
    seen = set()
    for a, b in zip(starts, ends):
        name = str(z[a])
        x1 = nu[min(b, len(nu) - 1)]
        ax.axvspan(nu[a], x1, color=ZONE_COLOR.get(name, MUTED),
                   alpha=0.07, lw=0, zorder=0)
        if name not in seen and (x1 - nu[a]) > 0.12 * (nu[-1] - nu[0]):
            ax.text(0.5 * (nu[a] + x1), 0.985, ZONE_LABEL.get(name, name),
                    transform=ax.get_xaxis_transform(), ha="center", va="top",
                    fontsize=7.6, color=MUTED)
            seen.add(name)
    return None


def _band(ax, band, freqs):
    """Границы полосы калибровки — только те, что реально видны на графике.

    Когда рабочий диапазон целиком внутри полосы, границы совпадают с краями
    осей: рисовать их бессмысленно, а подпись перекроет данные.
    """
    nu = np.asarray(freqs, dtype=float)
    span = nu[-1] - nu[0]
    drawn = [x for x in band if nu[0] + 0.02 * span < x < nu[-1] - 0.02 * span]
    for x in drawn:
        ax.axvline(x, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)
    if drawn:
        ax.text(drawn[0], 0.02, " calibration boundary",
                transform=ax.get_xaxis_transform(), ha="left", va="bottom",
                fontsize=7.6, color=MUTED)
    return bool(drawn)


def _split_extrap(x, y, inside):
    """Разбить кривую на сплошную (в полосе) и пунктирную (экстраполяция)."""
    x, y, inside = np.asarray(x), np.asarray(y), np.asarray(inside, dtype=bool)
    solid = np.where(inside, y, np.nan)
    dashed = np.where(inside, np.nan, y)
    # склейка на стыке, чтобы не было разрыва
    idx = np.where(inside[1:] != inside[:-1])[0]
    for i in idx:
        solid[i], solid[i + 1] = y[i], y[i + 1]
        dashed[i], dashed[i + 1] = y[i], y[i + 1]
    return solid, dashed


# ---------------------------------------------------------------------------
def spectrum(path, freqs, att_db, *, lo_db=None, hi_db=None, zones=None,
             band=None, extrapolated=None, dr_db=None, theta_deg=None,
             mode="relative", footer=""):
    """A(nu): кривая, коридор 95 %, зоны применимости, полоса калибровки, DR."""
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    nu = np.asarray(freqs, dtype=float)

    single_zone = _zones(ax, nu, zones) if zones is not None else None
    if lo_db is not None and hi_db is not None:
        ax.fill_between(nu, lo_db, hi_db, color=SERIES[0], alpha=0.14, lw=0,
                        label="95 % interval", zorder=2)
    if extrapolated is not None and np.any(extrapolated):
        solid, dashed = _split_extrap(nu, att_db, ~np.asarray(extrapolated, dtype=bool))
        ax.plot(nu, solid, color=SERIES[0], lw=2.0, zorder=4, label="model (in band)")
        ax.plot(nu, dashed, color=SERIES[0], lw=2.0, ls=(0, (5, 2.5)), zorder=4,
                label="extrapolation")
    else:
        ax.plot(nu, att_db, color=SERIES[0], lw=2.0, zorder=4, label="model")
    if dr_db is not None:
        ax.plot(nu, dr_db, color=SERIES[1], lw=1.6, ls=(0, (1.5, 2)), zorder=3,
                label="setup dynamic range")
    if band is not None:
        _band(ax, band, nu)

    sub = (f"theta = {theta_deg:+.2f} deg, {mode} mode" if theta_deg is not None else mode)
    if single_zone:
        sub += f" · whole band in zone '{ZONE_LABEL.get(single_zone, single_zone)}'"
    _finish(ax, "frequency, THz", "attenuation, dB (power)", "Attenuation spectrum", sub)
    _legend(ax, loc="lower left")
    if footer:
        _footer(fig, footer)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)


def angular_curve(path, theta, att_db, ideal_db, *, lo_db=None, hi_db=None,
                  slope=None, mark=None, footer="", mode="relative"):
    """A(theta) против идеальной cos^4; крутизна — ОТДЕЛЬНОЙ панелью, не второй осью."""
    plt = _mpl()
    if slope is not None:
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7.4, 5.9), sharex=True,
                                      gridspec_kw={"height_ratios": [2.6, 1]})
    else:
        fig, ax = plt.subplots(figsize=(7.4, 4.3))
        ax2 = None
    th = np.asarray(theta, dtype=float)

    if lo_db is not None and hi_db is not None:
        ax.fill_between(th, lo_db, hi_db, color=SERIES[0], alpha=0.14, lw=0,
                        label="95 % interval", zorder=2)
    ax.plot(th, ideal_db, color=MUTED, lw=1.5, ls=(0, (5, 2.5)), zorder=3,
            label="ideal cos^4 limit")
    ax.plot(th, att_db, color=SERIES[0], lw=2.0, zorder=4, label="device model")
    if mark is not None:
        mx, my, mlabel = mark
        ax.plot([mx], [my], marker="o", ms=7, mfc=SERIES[1], mec=SURFACE, mew=1.6,
                zorder=6, linestyle="none", label=mlabel)
    # Идеальная cos^4 уходит в полюс у скрещённого положения и, если дать ей
    # задать масштаб, придавит всю рабочую часть кривой к нулю. Масштаб задаёт
    # модель прибора; идеал обрезается сам.
    top = float(np.nanmax(hi_db if hi_db is not None else att_db))
    ax.set_ylim(bottom=min(-1.0, float(np.nanmin(att_db)) - 1.0), top=top * 1.12 + 2.0)

    _finish(ax, "" if ax2 is not None else "angle, deg",
            "attenuation, dB (power)", "Angular characteristic",
            "relative mode, referenced to zero" if mode == "relative"
            else "absolute mode, referenced to unit input")
    _legend(ax, loc="upper left")

    if ax2 is not None:
        sl = np.abs(slope)
        ax2.plot(th, sl, color=SERIES[2], lw=2.0, zorder=4)
        ax2.fill_between(th, 0, sl, color=SERIES[2], alpha=0.12, lw=0)
        ax2.set_ylim(0, float(np.nanmax(sl)) * 1.35 + 0.05)
        _finish(ax2, "angle, deg", "|dA/dtheta|, dB/deg")
        ax2.text(0.01, 0.92, "slope: how many dB one degree of error costs",
                 transform=ax2.transAxes, ha="left", va="top",
                 fontsize=7.8, color=MUTED)
    if footer:
        _footer(fig, footer)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)


def validation(path, rows, *, footer=""):
    """Измерено против модели: верх — обе кривые, низ — остатки. rows из validate.py."""
    plt = _mpl()
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7.4, 6.1), sharex=True,
                                  gridspec_kw={"height_ratios": [2.4, 1]})
    groups = {}
    for ds, a, meas, pred, lo, hi, inside in rows:
        groups.setdefault("second (analyzer)" if ds.startswith("356") else "first",
                          []).append((a, meas, pred, lo, hi, inside))

    # коридор строится по всем точкам, отсортированным по углу
    allr = sorted([r for g in groups.values() for r in g], key=lambda r: r[0])
    aa = np.array([r[0] for r in allr])
    lo = np.array([r[3] for r in allr])
    hi = np.array([r[4] for r in allr])
    pr = np.array([r[2] for r in allr])
    ax.fill_between(aa, lo, hi, color=SERIES[0], alpha=0.14, lw=0,
                    label="model 95 % interval", zorder=2)
    ax.plot(aa, pr, color=SERIES[0], lw=2.0, zorder=4, label="model")

    for i, (name, g) in enumerate(sorted(groups.items())):
        g = sorted(g, key=lambda r: r[0])
        x = np.array([r[0] for r in g])
        y = np.array([r[1] for r in g])
        ax.plot(x, y, linestyle="none", marker="o" if i == 0 else "^", ms=5.5,
                mfc=SERIES[1 + i], mec=SURFACE, mew=1.0, zorder=5,
                label=f"measured, {name} polarizer rotated")
        ax2.plot(x, y - np.array([r[2] for r in g]), linestyle="none",
                 marker="o" if i == 0 else "^", ms=5.5,
                 mfc=SERIES[1 + i], mec=SURFACE, mew=1.0, zorder=5)

    _finish(ax, "", "attenuation, dB (power)",
            "Model check against measurements",
            f"{len(allr)} points, relative mode, SET ZERO at 0 deg")
    _legend(ax, loc="upper left")

    dev = np.array([r[1] - r[2] for r in allr])
    half = 0.5 * (hi - lo)
    ax2.fill_between(aa, -half, half, color=SERIES[0], alpha=0.14, lw=0, zorder=2)
    ax2.axhline(0, color=AXIS, lw=1.0, zorder=3)
    _finish(ax2, "angle, deg", "measured - model, dB")
    ax2.text(0.99, 0.06, f"bias {dev.mean():+.2f} dB, RMSE {np.sqrt((dev**2).mean()):.2f} dB",
             transform=ax2.transAxes, ha="right", va="bottom", fontsize=8, color=INK2)
    if footer:
        _footer(fig, footer)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)


def polarization(path, freqs, azimuth, ellipticity, *, zones=None, band=None,
                 theta_deg=None, footer=""):
    """Состояние поляризации на выходе: азимут и эллиптичность, две панели."""
    plt = _mpl()
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7.4, 5.6), sharex=True)
    nu = np.asarray(freqs, dtype=float)
    for a, y, lab, col in ((ax, azimuth, "azimuth, deg", SERIES[0]),
                           (ax2, ellipticity, "ellipticity, deg", SERIES[2])):
        if zones is not None:
            _zones(a, nu, zones)
        a.plot(nu, y, color=col, lw=2.0, zorder=4)
        a.axhline(0, color=AXIS, lw=1.0, zorder=3)
        a.margins(y=0.12)          # иначе кривая ложится на верхнюю рамку
        if band is not None:
            _band(a, band, nu)
    _finish(ax, "", "azimuth, deg", "Output polarization",
            (f"theta = {theta_deg:+.2f} deg" if theta_deg is not None else None))
    _finish(ax2, "frequency, THz", "ellipticity, deg")
    if footer:
        _footer(fig, footer)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)


def angle_map(path, th1, th2, att_db, *, footer=""):
    """Карта A(theta1, theta2) — последовательная шкала одного тона (схема S2)."""
    plt = _mpl()
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list(
        "seq_blue", ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"])
    fig, ax = plt.subplots(figsize=(6.6, 5.2))
    m = ax.pcolormesh(th1, th2, np.asarray(att_db).T, cmap=cmap, shading="auto")
    cs = ax.contour(th1, th2, np.asarray(att_db).T, levels=8, colors=SURFACE,
                    linewidths=0.7, alpha=0.75)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.0f")
    cb = fig.colorbar(m, ax=ax, pad=0.02)
    cb.set_label("attenuation, dB (power)", color=INK2)
    cb.outline.set_edgecolor(AXIS)
    _finish(ax, "WGP1 angle, deg", "WGP2 angle, deg", "Attenuation map",
            "contour labels in dB")
    if footer:
        _footer(fig, footer)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)
