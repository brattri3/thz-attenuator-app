"""Сеанс работы: уникальная папка, метафайл с выборами пользователя, артефакты.

Любая цифра в дБ бессмысленна задним числом без контекста: от какого нуля
отсчитано, каким паспортом, в какой схеме, с каким весом источника. Поэтому
каждый artefact сопровождается метафайлом, а ASCII-графики пишутся файлами,
а не только в терминал.

Раскладка:
    runs/2026-07-27_181530_a3f1/
        meta.json     полное состояние: паспорт, схема, детектор, источник,
                      вес, режим, ноль, полоса, версия ядра — и история изменений
        log.txt       журнал введённых команд с временными метками
        plots/        ASCII-графики, каждый со своей шапкой контекста
        data/         числовые выгрузки (CSV) к тем же графикам
"""
from __future__ import annotations

import json
import os
import platform
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np


class Session:
    def __init__(self, root=None, tag=""):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        uid = uuid.uuid4().hex[:4]
        name = f"{stamp}_{uid}" + (f"_{tag}" if tag else "")
        self.dir = Path(root or Path.cwd() / "runs") / name
        (self.dir / "plots").mkdir(parents=True, exist_ok=True)
        (self.dir / "data").mkdir(parents=True, exist_ok=True)
        self.started = datetime.now().isoformat(timespec="seconds")
        self.meta = {
            "session": name, "started": self.started,
            "host": platform.node(), "python": platform.python_version(),
            "cwd": str(Path.cwd()),
            "choices": {},          # текущее состояние выборов пользователя
            "history": [],          # что и когда меняли
            "artifacts": [],
        }
        self._n = 0
        self._write_meta()
        (self.dir / "log.txt").write_text(
            f"# session {name}, started {self.started}\n", encoding="utf-8")

    # ------------------------------------------------------------------
    def _write_meta(self):
        (self.dir / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def choose(self, **kw):
        """Зафиксировать выбор пользователя (схема, детектор, ноль, вес, ...)."""
        now = datetime.now().isoformat(timespec="seconds")
        for k, v in kw.items():
            if self.meta["choices"].get(k) != v:
                self.meta["history"].append({"t": now, "key": k,
                                             "from": self.meta["choices"].get(k), "to": v})
            self.meta["choices"][k] = v
        self._write_meta()

    def log(self, line: str):
        with (self.dir / "log.txt").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')}  {line}\n")

    # ------------------------------------------------------------------
    def header(self, title: str) -> str:
        c = self.meta["choices"]
        w = []
        for k in ("passport", "scheme", "detector", "source", "mode", "zero_deg",
                  "band_thz", "weight", "scale_division_deg"):
            if k in c:
                w.append(f"# {k:<18} {c[k]}")
        return (f"# {title}\n# session {self.meta['session']}   "
                f"{datetime.now().isoformat(timespec='seconds')}\n" + "\n".join(w) + "\n")

    def save_plot(self, title: str, body: str, slug: str) -> Path:
        self._n += 1
        path = self.dir / "plots" / f"{self._n:02d}_{slug}.txt"
        path.write_text(self.header(title) + "\n" + body + "\n", encoding="utf-8")
        self.meta["artifacts"].append({"file": str(path.relative_to(self.dir)),
                                       "title": title,
                                       "t": datetime.now().isoformat(timespec="seconds")})
        self._write_meta()
        return path

    def save_csv(self, slug: str, columns: dict) -> Path:
        self._n += 1
        path = self.dir / "data" / f"{self._n:02d}_{slug}.csv"
        keys = list(columns)
        n = len(columns[keys[0]])
        with path.open("w", encoding="utf-8") as f:
            f.write(self.header(slug))
            f.write(",".join(keys) + "\n")
            for i in range(n):
                f.write(",".join(_fmt(columns[k][i]) for k in keys) + "\n")
        self.meta["artifacts"].append({"file": str(path.relative_to(self.dir)),
                                       "title": slug,
                                       "t": datetime.now().isoformat(timespec="seconds")})
        self._write_meta()
        return path

    def close(self):
        self.meta["finished"] = datetime.now().isoformat(timespec="seconds")
        self._write_meta()


def _fmt(v):
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (float, np.floating)):
        return f"{v:.6g}"
    return str(v)


# ---------------------------------------------------------------------------
def ascii_plot(x, y, *, width=64, height=18, xlabel="x", ylabel="y",
               marks=None, ref=None, ref_label="reference"):
    """ASCII-график y(x). marks — [(x, символ, подпись)], ref — вторая кривая."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 2:
        return "(not enough points)"

    ys = [y] + ([np.asarray(ref, dtype=float)[ok]] if ref is not None else [])
    lo = min(float(np.nanmin(a)) for a in ys)
    hi = max(float(np.nanmax(a)) for a in ys)
    if hi - lo < 1e-12:
        hi = lo + 1.0

    grid = [[" "] * width for _ in range(height)]

    def put(px, py, ch):
        col = int(round((px - x[0]) / (x[-1] - x[0]) * (width - 1)))
        row = int(round((hi - py) / (hi - lo) * (height - 1)))
        if 0 <= col < width and 0 <= row < height:
            grid[row][col] = ch

    if ref is not None:
        for px, py in zip(x, np.asarray(ref, dtype=float)[ok]):
            put(px, py, ".")
    for px, py in zip(x, y):
        put(px, py, "*")
    for m in (marks or []):
        put(float(m[0]), float(np.interp(m[0], x, y)), m[1])

    out = [f"  {ylabel}"]
    for r, row in enumerate(grid):
        val = hi - r * (hi - lo) / (height - 1)
        out.append(f"{val:8.2f} |" + "".join(row))
    out.append(" " * 8 + " +" + "-" * width)
    lbl = f"{x[0]:.2f}"
    mid = f"{0.5*(x[0]+x[-1]):.2f}"
    end = f"{x[-1]:.2f}"
    axis = lbl + mid.rjust(width // 2 - len(lbl) + len(mid)) + end.rjust(width // 2 - len(mid) + len(end))
    out.append(" " * 10 + axis[:width])
    out.append(" " * 10 + xlabel)
    legend = "  * - model"
    if ref is not None:
        legend += f",  . - {ref_label}"
    for m in (marks or []):
        legend += f",  {m[1]} — {m[2]}" if len(m) > 2 else ""
    out.append(legend)
    return "\n".join(out)
