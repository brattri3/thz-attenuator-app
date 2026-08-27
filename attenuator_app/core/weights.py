"""Спектральный вес источника w(nu) для интегрального затухания.

Без w(nu) интегральное затухание НЕ ОПРЕДЕЛЕНО: одно и то же положение углов
даёт разное интегральное затухание для узкополосного и широкополосного
источника (Kaltenecker 2019, Fig. 5).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Пресеты: (центр ТГц, ширина ТГц по 1/e, верхняя граница полезной полосы)
PRESETS = {
    "pca":      (0.8, 0.6, 3.0),    # фотопроводящая антенна (штатный источник калибровки)
    "linbo3":   (0.8, 0.7, 2.0),    # LiNbO3, tilted pulse front
    "organic":  (2.0, 1.6, 5.0),    # органический нелинейный кристалл
    "plasma":   (6.0, 6.0, 20.0),   # двухцветная воздушная плазма
}


def flat(freqs_thz, f1=None, f2=None):
    """Прямоугольное окно — самый честный вариант при неизвестном спектре."""
    nu = np.asarray(freqs_thz, dtype=float)
    w = np.ones(nu.shape)
    if f1 is not None:
        w[nu < f1] = 0.0
    if f2 is not None:
        w[nu > f2] = 0.0
    return w


def gaussian(freqs_thz, nu0, dnu):
    nu = np.asarray(freqs_thz, dtype=float)
    return np.exp(-((nu - nu0) / max(dnu, 1e-9)) ** 2)


def preset(freqs_thz, name):
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}, available {list(PRESETS)}")
    nu0, dnu, fmax = PRESETS[name]
    w = gaussian(freqs_thz, nu0, dnu)
    w[np.asarray(freqs_thz) > fmax] = 0.0
    return w


def from_tds_file(freqs_thz, path):
    """Вес из измеренного фона: w(nu) = |E_bg(nu)|^2 (энергия по Парсевалю).

    Файл — две колонки: время (пс), поле. Формат data_pool этого проекта.
    """
    raw = np.loadtxt(Path(path))
    t, E = raw[:, 0], raw[:, 1]
    E = E - np.mean(E[:50])
    dt = float(t[1] - t[0])
    spec = np.abs(np.fft.rfft(E)) ** 2
    f = np.fft.rfftfreq(len(t), dt)
    return np.interp(np.asarray(freqs_thz, dtype=float), f, spec, left=0.0, right=0.0)


def effective_band(freqs_thz, weight, frac=0.99):
    """Полоса, в которой сосредоточена доля frac энергии веса."""
    nu = np.asarray(freqs_thz, dtype=float)
    w = np.asarray(weight, dtype=float)
    if w.sum() <= 0:
        return float(nu[0]), float(nu[-1])
    c = np.cumsum(w) / w.sum()
    lo = float(nu[np.searchsorted(c, (1 - frac) / 2)])
    hi = float(nu[min(np.searchsorted(c, 1 - (1 - frac) / 2), len(nu) - 1)])
    return lo, hi


def build(freqs_thz, kind="preset", **kw):
    """Единая точка входа: kind = flat | gauss | preset | bg_file."""
    if kind == "flat":
        return flat(freqs_thz, kw.get("f1"), kw.get("f2"))
    if kind == "gauss":
        return gaussian(freqs_thz, kw["nu0"], kw["dnu"])
    if kind == "preset":
        return preset(freqs_thz, kw.get("name", "pca"))
    if kind == "bg_file":
        return from_tds_file(freqs_thz, kw["path"])
    raise ValueError(f"unknown weight kind {kind!r}")
