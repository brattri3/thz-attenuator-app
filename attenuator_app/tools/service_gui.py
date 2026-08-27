"""tkinter GUI поверх `service_calc.py` -- обслуживание аттенюатора в THz-TDS
спектрометре (задача C9, санкция владельца 2026-08-19). Один сценарий:
двунаправленный калькулятор (дБ<->угол), три опорные мощности, выбираемая
метрика полосы, без доверительного интервала.

Соглашения (владелец 2026-08-18) -- подробности в docstring `service_calc`:
  * затухание -- ОТРИЦАТЕЛЬНЫЕ децибелы по мощности (10*log10 T);
  * SET OFFSET (theta0) -- физический офсет совмещения WGP1/WGP2, зашит в
    калибровку, подгоночный параметр модели; автокалибровка -- следующая версия;
  * SET ZERO -- рабочая точка отсчёта на кривой, от которой оператор считает
    добавочное затухание/усиление; по умолчанию = SET OFFSET;
  * опора T: `P_0` (вход аттенюатора) / `P_max` (совмещённое положение) /
    `P_zero` (рабочая точка). Первые две от SET ZERO не зависят, третья на неё
    нормирует -- именно она даёт выход в усиление (>100 %, >0 дБ).

Работа со сдвинутой рабочей точкой показывается в трёх местах сразу:
  * окно результатов -- таблица «SET ZERO / запрос» во ВСЕХ трёх опорах плюс
    строка добавочной величины (дБ, во сколько раз по мощности и по полю);
  * график -- рабочая точка отмечена своим цветом (вертикаль + горизонталь на
    её уровне), область выше её уровня подсвечена как зона усиления, а между
    уровнем рабочей точки и уровнем запроса рисуется двусторонняя стрелка с
    подписью добавочной величины;
  * переключатель шкалы -- «затухание» держит жёсткие 0-100 % и 0...-45 дБ,
    «с усилением» раздвигает верх, чтобы кривая выше рабочей точки поместилась.

НЕ клиентский `attenuator_app.gui`/`cli` (v0.2/v0.3, отдельный трек, не
трогается) -- самостоятельный инструмент поверх модели C8
(`measured_curve.py`), обвязка не пересчитывает физику заново, только вызывает
`service_calc`.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe -m attenuator_app.tools.service_gui
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure                              # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.tools.service_calc import (            # noqa: E402
    FULL, REF_LABEL, REF_SHORT, REFS, Metric,
    angle_for_db, attenuation_db_array, describe_point, fmt_db_bound,
    load_calibration, pair_response)

#: (kind, подпись в списке, [(подпись поля, значение по умолчанию), ...])
METRIC_ITEMS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("full", "полная мощность (вся записанная полоса)", []),
    ("single", "одна частота", [("частота, ТГц", "0.800")]),
    ("band_cw", "полоса: центр + ширина", [("центр, ТГц", "0.800"), ("ширина, ТГц", "0.400")]),
    ("band_minmax", "полоса: мин + макс", [("f_min, ТГц", "0.300"), ("f_max, ТГц", "1.500")]),
]
METRIC_BY_LABEL = {label: (kind, fields) for kind, label, fields in METRIC_ITEMS}

#: режимы шкалы графика (переключатель, автоскейла нет ни в одном)
SCALE_ITEMS = [
    ("clamp", "затухание: 0-100 %, 0...-45 дБ (жёстко)"),
    ("gain", "с усилением: верх по кривой (>100 %, >0 дБ)"),
]
#: допуск сравнения углов: шкала ротатора точнее 0.0001 град не читается,
#: а поля ввода округляют -- без него «= SET OFFSET» считался бы сдвигом
ANGLE_ATOL = 1e-4
PCT_LIM = (0.0, 100.0)      # жёсткая шкала пропускания, %
DB_LIM = (-45.0, 0.0)       # жёсткая шкала затухания, дБ

C_BRIGHT = "#2a78d6"        # выбранная метрика, панель %
C_BRIGHT_DB = "#eb6834"     # выбранная метрика, панель дБ
C_DIM = "#c2c2c2"           # полная мощность, фоном
C_MARK = "#12996a"          # точка запроса
C_ZERO = "#8e44ad"          # рабочая точка SET ZERO
C_GAIN = "#eaf7ef"          # заливка зоны усиления


def _annotate_point(ax, x: float, y: float, x_text: str, y_text: str,
                    color: str = C_MARK, draw_h: bool = True) -> None:
    """Отметить точку (x, y): вертикальный отрезок вниз до оси X и
    горизонтальный влево до оси Y (оба ЗАКАНЧИВАЮТСЯ на графике, а не уходят в
    бесконечность), подписи посередине каждого отрезка. Подписи отодвигаются
    внутрь при приближении к границе поля, значение вне шкалы помечается."""
    xlo, xhi = ax.get_xlim()
    ylo, yhi = ax.get_ylim()
    xspan, yspan = xhi - xlo, yhi - ylo
    off_scale = not (ylo <= y <= yhi)
    y_draw = float(np.clip(y, ylo, yhi))

    ax.plot([x, x], [ylo, y_draw], color=color, lw=1.1, alpha=0.9, zorder=4)
    if draw_h:
        ax.plot([xlo, x], [y_draw, y_draw], color=color, lw=1.1, alpha=0.9, zorder=4)
    if not off_scale:
        ax.plot([x], [y_draw], "o", color=color, ms=4.5, zorder=5)

    box = dict(boxstyle="round,pad=0.18", fc="white", ec=color, lw=0.6, alpha=0.88)
    # подпись угла -- посередине вертикального отрезка, уводим влево у правого края
    near_right = (x - xlo) / xspan > 0.80
    ax.text(x + (-0.012 if near_right else 0.012) * xspan, (ylo + y_draw) / 2.0,
            x_text, ha="right" if near_right else "left", va="center",
            fontsize=8, color=color, bbox=box, zorder=6)
    # подпись значения -- посередине горизонтального отрезка, уводим вниз у верха
    if draw_h:
        near_top = (y_draw - ylo) / yspan > 0.88
        label = y_text + (" (вне шкалы)" if off_scale else "")
        ax.text((xlo + x) / 2.0, y_draw + (-0.02 if near_top else 0.02) * yspan,
                label, ha="center", va="top" if near_top else "bottom",
                fontsize=8, color=color, bbox=box, zorder=6)


def _delta_arrow(ax, x: float, y_from: float, y_to: float, text: str) -> None:
    """Двусторонняя стрелка между уровнем рабочей точки и уровнем запроса --
    визуальная «добавочная величина». Рисуется, только если оба уровня в поле."""
    xlo, xhi = ax.get_xlim()
    ylo, yhi = ax.get_ylim()
    if not (ylo <= y_from <= yhi and ylo <= y_to <= yhi):
        return
    if abs(y_to - y_from) < 0.015 * (yhi - ylo):
        return
    ax.annotate("", xy=(x, y_to), xytext=(x, y_from), zorder=7,
                arrowprops=dict(arrowstyle="<->", color=C_ZERO, lw=1.3,
                                shrinkA=0, shrinkB=0))
    ax.text(x + 0.012 * (xhi - xlo), (y_from + y_to) / 2.0, text,
            ha="left", va="center", fontsize=8, color=C_ZERO, zorder=8,
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=C_ZERO, lw=0.6, alpha=0.9))


class ServiceGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Аттенюатор -- обслуживание THz-TDS спектрометра")
        self.geometry("1320x860")
        self.minsize(1040, 660)

        self.cal = load_calibration()
        self.offset: float = self.cal.theta0_calibration_deg   # SET OFFSET (физика)
        self.zero: float = self.offset                          # SET ZERO (точка отсчёта)
        self._markers: list[float] = []
        self._field_vars: list[tk.StringVar] = []

        controls = ttk.Frame(self, padding=8)
        controls.pack(fill="x")

        info = ttk.LabelFrame(controls, text="устройство (зашитая калибровка)", padding=6)
        info.pack(fill="x")
        ttk.Label(info, justify="left", text=(
            f"{self.cal.device_id}  --  калибровка {self.cal.dataset} ({self.cal.generated})\n"
            f"P={self.cal.P_um:.2f} мкм, D={self.cal.D_um:.2f} мкм, "
            f"потери={self.cal.loss_db:.3f} дБ/ТГц^{self.cal.gamma:.2f}, "
            f"полоса {self.cal.band_thz[0]:.2f}-{self.cal.band_thz[1]:.2f} ТГц\n"
            # схема тракта: до 2026-08-24 она была зашита допущениями (линейный
            # источник вдоль x, когерентный приёмник вдоль x) и нигде не
            # показывалась, хотя меняет закон кривой вдвое по децибелам
            f"{self.cal.describe_setup()}")
        ).pack(anchor="w")

        # --- два разных нуля -------------------------------------------
        zeros = ttk.Frame(controls, padding=(0, 4, 0, 0))
        zeros.pack(fill="x")

        offf = ttk.LabelFrame(zeros, text="SET OFFSET (theta0) -- физический офсет "
                                         "совмещения WGP1/WGP2, входит в модель", padding=6)
        offf.pack(side="left", fill="both", expand=True, padx=(0, 4))
        ttk.Label(offf, justify="left", font=("TkDefaultFont", 8), text=(
            "подобран по калибровочной серии и зашит; менять только если прибор\n"
            "переустановили в роторе (автокалибровка офсета -- следующая версия)")
        ).pack(anchor="w")
        r1 = ttk.Frame(offf)
        r1.pack(fill="x", pady=(4, 0))
        self.offset_var = tk.StringVar(value=f"{self.offset:.4f}")
        ttk.Entry(r1, textvariable=self.offset_var, width=10).pack(side="left")
        ttk.Button(r1, text="применить", command=self._apply_offset).pack(side="left", padx=(6, 0))
        ttk.Button(r1, text="из калибровки", command=self._restore_offset).pack(side="left", padx=(4, 0))
        self.offset_status = tk.StringVar()
        ttk.Label(r1, textvariable=self.offset_status, foreground="#357").pack(side="left", padx=(10, 0))

        zerf = ttk.LabelFrame(zeros, text="SET ZERO -- рабочая точка отсчёта на кривой",
                              padding=6)
        zerf.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ttk.Label(zerf, justify="left", font=("TkDefaultFont", 8), text=(
            "от неё считается ДОБАВОЧНОЕ затухание (или усиление, если идти\n"
            "к совмещению); опора P_zero дополнительно на неё нормирует")
        ).pack(anchor="w")
        r2 = ttk.Frame(zerf)
        r2.pack(fill="x", pady=(4, 0))
        self.zero_var = tk.StringVar(value=f"{self.zero:.4f}")
        ttk.Entry(r2, textvariable=self.zero_var, width=10).pack(side="left")
        ttk.Button(r2, text="SET ZERO", command=self._apply_zero).pack(side="left", padx=(6, 0))
        ttk.Button(r2, text="= SET OFFSET", command=self._reset_zero).pack(side="left", padx=(4, 0))
        ttk.Button(r2, text="сюда текущий угол", command=self._zero_from_angle).pack(side="left", padx=(4, 0))
        self.zero_status = tk.StringVar()
        ttk.Label(r2, textvariable=self.zero_status, foreground="#357").pack(side="left", padx=(10, 0))

        # --- опора, шкала, метрика -------------------------------------
        opts = ttk.LabelFrame(controls, text="опора T (что в знаменателе)", padding=6)
        opts.pack(fill="x", pady=(6, 0))
        self.ref_var = tk.StringVar(value="pmax")
        for value in REFS:
            ttk.Radiobutton(opts, text=f"{REF_SHORT[value]} -- {REF_LABEL[value]}",
                            value=value, variable=self.ref_var,
                            command=self._redraw_plot).pack(side="left", padx=(0, 12))

        sc = ttk.Frame(controls, padding=(0, 4, 0, 0))
        sc.pack(fill="x")
        ttk.Label(sc, text="шкала:").pack(side="left")
        self.scale_var = tk.StringVar(value="clamp")
        for value, label in SCALE_ITEMS:
            ttk.Radiobutton(sc, text=label, value=value, variable=self.scale_var,
                            command=self._redraw_plot).pack(side="left", padx=(4, 12))

        met = ttk.Frame(controls, padding=(0, 4, 0, 0))
        met.pack(fill="x")
        ttk.Label(met, text="метрика:").pack(side="left")
        self.metric_var = tk.StringVar(value=METRIC_ITEMS[0][1])
        cb = ttk.Combobox(met, textvariable=self.metric_var, state="readonly", width=38,
                          values=[label for _, label, _ in METRIC_ITEMS])
        cb.pack(side="left", padx=(6, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_metric_fields())
        self.metric_fields = ttk.Frame(met)
        self.metric_fields.pack(side="left")
        ttk.Button(met, text="обновить график", command=self._redraw_plot).pack(side="left", padx=(10, 0))

        # --- калькулятор ------------------------------------------------
        calc = ttk.Frame(controls, padding=(0, 6, 0, 0))
        calc.pack(fill="x")
        fwd = ttk.LabelFrame(calc, text="угол -> затухание", padding=6)
        fwd.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(fwd, text="угол WGP1, град:").pack(side="left")
        self.angle_var = tk.StringVar(value="")
        e = ttk.Entry(fwd, textvariable=self.angle_var, width=10)
        e.pack(side="left", padx=(6, 10))
        e.bind("<Return>", lambda _e: self._forward())
        ttk.Button(fwd, text="Вычислить затухание", command=self._forward).pack(side="left")

        inv = ttk.LabelFrame(calc, text="затухание -> угол (дБ отрицательные)", padding=6)
        inv.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Label(inv, text="желаемое затухание, дБ:").pack(side="left")
        self.db_var = tk.StringVar(value="")
        e2 = ttk.Entry(inv, textvariable=self.db_var, width=10)
        e2.pack(side="left", padx=(6, 10))
        e2.bind("<Return>", lambda _e: self._inverse())
        ttk.Button(inv, text="Вычислить угол", command=self._inverse).pack(side="left")

        body = ttk.Frame(self, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        self.plot_frame = ttk.Frame(body)
        self.plot_frame.pack(side="left", fill="both", expand=True)
        self.canvas = None

        outf = ttk.LabelFrame(body, text="результат", padding=6)
        outf.pack(side="right", fill="y", padx=(8, 0))
        self.text = tk.Text(outf, wrap="none", font=("Consolas", 9), width=64)
        self.text.pack(fill="both", expand=True)

        self._sync_status()
        self._rebuild_metric_fields()

    # -- вспомогательное -------------------------------------------------
    def _log(self, msg: str = "") -> None:
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def _ref(self) -> str:
        return self.ref_var.get()

    def _sync_status(self) -> None:
        same_off = np.isclose(self.offset, self.cal.theta0_calibration_deg, atol=ANGLE_ATOL)
        self.offset_status.set(f"{self.offset:+.3f} град "
                               f"({'из калибровки' if same_off else 'вручную'})")
        same_zero = np.isclose(self.zero, self.offset, atol=ANGLE_ATOL)
        self.zero_status.set(f"{self.zero:+.3f} град "
                             f"({'= SET OFFSET' if same_zero else 'СДВИНУТА'})")

    def _rebuild_metric_fields(self) -> None:
        for w in self.metric_fields.winfo_children():
            w.destroy()
        kind, fields = METRIC_BY_LABEL[self.metric_var.get()]
        self._field_vars = []
        for label, default in fields:
            ttk.Label(self.metric_fields, text=label + ":").pack(side="left", padx=(0, 4))
            var = tk.StringVar(value=default)
            ent = ttk.Entry(self.metric_fields, textvariable=var, width=9)
            ent.pack(side="left", padx=(0, 10))
            ent.bind("<Return>", lambda _e: self._redraw_plot())
            self._field_vars.append(var)
        self._redraw_plot()

    def _metric(self) -> Metric:
        """Собрать метрику из выпадающего списка и полей. ValueError при мусоре."""
        kind, fields = METRIC_BY_LABEL[self.metric_var.get()]
        vals: list[float] = []
        for var, (label, _) in zip(self._field_vars, fields):
            s = var.get().strip()
            if not s:
                raise ValueError(f"не заполнено поле «{label}»")
            try:
                vals.append(float(s))
            except ValueError:
                raise ValueError(f"поле «{label}»: ожидается число, получено {s!r}") from None
        return Metric(kind, *(vals + [None, None])[:2])

    def _describe(self, theta: float, metric: Metric, ref: str) -> dict:
        return describe_point(theta, self.offset, self.zero, self.cal, metric, ref)

    # -- окно результатов: показать работу со сдвинутой точкой ----------
    def _log_zero_block(self, theta: float, metric: Metric, ref: str) -> None:
        q = self._describe(theta, metric, ref)
        z = self._describe(self.zero, metric, ref)
        shifted = not np.isclose(self.zero, self.offset, atol=ANGLE_ATOL)
        self._log(f"  {'точка':<9}{'угол':>9}  {'T/P_0':>8} {'T/P_max':>9} {'T/P_zero':>9}"
                  f"  {'дБ ' + REF_SHORT[ref]:>10}")
        for name, d in ((f"SET ZERO{'*' if shifted else ' '}", z), ("запрос   ", q)):
            self._log(f"  {name:<9}{d['theta_deg']:>+8.3f}°  {d['pct_p0']:>7.2f}% "
                      f"{d['pct_pmax']:>8.2f}% {d['pct_pzero']:>8.2f}%  {d['db_sel']:>+9.2f}")
        dz = q["delta_zero_db"]
        kind = "УСИЛЕНИЕ" if dz > 0 else "затухание"
        self._log(f"  добавочно к рабочей точке: {dz:+.2f} дБ -- {kind}")
        self._log(f"    мощность x{q['delta_power_ratio']:.4g}, "
                  f"поле x{q['delta_field_ratio']:.4g}")
        if shifted:
            self._log("  * рабочая точка сдвинута относительно SET OFFSET")

    # -- график ------------------------------------------------------
    def _redraw_plot(self) -> None:
        ref = self._ref()
        try:
            metric = self._metric()
            metric_err = None
        except ValueError as e:
            metric, metric_err = FULL, str(e)

        grid = np.linspace(self.offset - 90.0, self.offset + 90.0, 721)
        try:
            db_sel = attenuation_db_array(grid, self.offset, self.cal, metric, ref, self.zero)
        except ValueError as e:                       # напр. пустая полоса
            metric, metric_err = FULL, str(e)
            db_sel = attenuation_db_array(grid, self.offset, self.cal, FULL, ref, self.zero)
        db_full = (db_sel if metric.kind == "full" else
                   attenuation_db_array(grid, self.offset, self.cal, FULL, ref, self.zero))
        pct_sel, pct_full = 10.0 ** (db_sel / 10.0) * 100.0, 10.0 ** (db_full / 10.0) * 100.0

        z = self._describe(self.zero, metric, ref)
        shifted = not np.isclose(self.zero, self.offset, atol=ANGLE_ATOL)

        fig = Figure(figsize=(6.8, 6.6), dpi=100)
        ax1 = fig.add_subplot(211)
        ax2 = fig.add_subplot(212, sharex=ax1)

        for ax, y_full, y_sel, color in ((ax1, pct_full, pct_sel, C_BRIGHT),
                                         (ax2, db_full, db_sel, C_BRIGHT_DB)):
            if metric.kind != "full":
                ax.plot(grid, y_full, color=C_DIM, lw=1.4, zorder=1, label="полная мощность")
            ax.plot(grid, y_sel, color=color, lw=1.8, zorder=2, label=metric.label)
            ax.axvline(self.offset, color="#9aa", ls="--", lw=1, zorder=0)
            ax.grid(alpha=0.25, lw=0.6)

        # --- шкалы: переключатель, автоскейла нет ни в одном режиме ---
        gain_mode = self.scale_var.get() == "gain"
        top_pct = max(PCT_LIM[1], float(np.nanmax(pct_sel)) * 1.06) if gain_mode else PCT_LIM[1]
        top_db = max(DB_LIM[1], float(np.nanmax(db_sel)) + 1.5) if gain_mode else DB_LIM[1]
        ax1.set_xlim(grid[0], grid[-1])
        ax1.set_ylim(PCT_LIM[0], top_pct)
        ax2.set_ylim(DB_LIM[0], top_db)
        clipped = (not gain_mode) and (float(np.nanmax(pct_sel)) > PCT_LIM[1] + 1e-9)

        # --- рабочая точка: уровень, зона усиления над ним --------------
        for ax, y_zero in ((ax1, z["pct_sel"]), (ax2, z["db_sel"])):
            ylo, yhi = ax.get_ylim()
            if ylo <= y_zero <= yhi:
                ax.axhspan(y_zero, yhi, color=C_GAIN, zorder=0)
                ax.axhline(y_zero, color=C_ZERO, ls=":", lw=1.2, zorder=3)
            if shifted:
                ax.axvline(self.zero, color=C_ZERO, ls=":", lw=1.4, zorder=3)
                ax.plot([self.zero], [float(np.clip(y_zero, ylo, yhi))], "s",
                        color=C_ZERO, ms=5, zorder=6)

        ax1.set_ylabel(f"пропускание T = P/{REF_SHORT[ref]}, %")
        title = (f"опора {REF_SHORT[ref]} -- {REF_LABEL[ref]}\n"
                 f"SET OFFSET {self.offset:+.2f}°   SET ZERO {self.zero:+.2f}°"
                 f"{'  (сдвинута; выше пунктира -- усиление)' if shifted else ''}")
        if clipped:
            title += "\n[кривая выходит за шкалу -- переключите на «с усилением»]"
        ax1.set_title(title, fontsize=8)
        ax1.legend(fontsize=7.5, loc="best")
        ax2.set_ylabel("затухание, дБ по мощности")
        ax2.set_xlabel("угол WGP1 (показание шкалы ротатора), град")

        # --- точки запроса + стрелка добавочной величины ---------------
        drawn: list[float] = []
        for theta in self._markers:
            q = self._describe(theta, metric, ref)
            draw_h = not any(abs(q["db_sel"] - d) < 1e-3 for d in drawn)
            drawn.append(q["db_sel"])
            _annotate_point(ax1, theta, q["pct_sel"], f"{theta:+.2f}°",
                            f"T = {q['pct_sel']:.2f} %", draw_h=draw_h)
            _annotate_point(ax2, theta, q["db_sel"], f"{theta:+.2f}°",
                            f"{q['db_sel']:+.2f} дБ", draw_h=draw_h)
            if draw_h and abs(theta - self.zero) > ANGLE_ATOL:
                x_arrow = (theta + self.zero) / 2.0
                dz = q["delta_zero_db"]
                _delta_arrow(ax1, x_arrow, z["pct_sel"], q["pct_sel"],
                             f"x{q['delta_power_ratio']:.3g}")
                _delta_arrow(ax2, x_arrow, z["db_sel"], q["db_sel"], f"{dz:+.2f} дБ")

        fig.tight_layout()
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        self.canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        if metric_err:
            self._log(f"[!] метрика: {metric_err} -- график по полной мощности")

    # -- действия ----------------------------------------------------
    def _apply_offset(self) -> None:
        try:
            v = float(self.offset_var.get())
        except ValueError:
            messagebox.showerror("Неверное значение", "SET OFFSET должен быть числом")
            return
        # SET ZERO -- точка на шкале ротатора: если она была привязана к офсету,
        # едет вместе с ним, иначе остаётся там, где её поставил оператор
        was_bound = bool(np.isclose(self.zero, self.offset, atol=ANGLE_ATOL))
        self.offset = v
        if was_bound:
            self.zero = v
            self.zero_var.set(f"{v:.4f}")
        self._markers.clear()
        self._sync_status()
        self._log(f"SET OFFSET = {self.offset:+.3f} град")
        self._log("")
        self._redraw_plot()

    def _restore_offset(self) -> None:
        self.offset_var.set(f"{self.cal.theta0_calibration_deg:.4f}")
        self._apply_offset()

    def _apply_zero(self) -> None:
        try:
            v = float(self.zero_var.get())
        except ValueError:
            messagebox.showerror("Неверное значение", "SET ZERO должен быть числом")
            return
        self.zero = v
        self._sync_status()
        try:
            metric = self._metric()
        except ValueError:
            metric = FULL
        z = self._describe(self.zero, metric, self._ref())
        self._log(f"SET ZERO = {self.zero:+.3f} град "
                  f"(от SET OFFSET {self.zero - self.offset:+.3f})")
        self._log(f"  в этой точке: {z['pct_p0']:.2f} % от P_0, "
                  f"{z['pct_pmax']:.2f} % от P_max ({z['db_pmax']:+.2f} дБ)")
        self._log("  дальше отсчёт добавочного затухания/усиления идёт от неё")
        self._log("")
        self._redraw_plot()

    def _reset_zero(self) -> None:
        self.zero_var.set(f"{self.offset:.4f}")
        self._apply_zero()

    def _zero_from_angle(self) -> None:
        """Поставить рабочую точку в угол из поля прямой задачи -- типовой ход:
        выставили начальное затухание, объявили его нулём, дальше добавляем."""
        s = self.angle_var.get().strip()
        if not s:
            messagebox.showinfo("Пусто", "сначала введите угол в поле «угол WGP1»")
            return
        self.zero_var.set(s)
        self._apply_zero()

    def _forward(self) -> None:
        try:
            theta = float(self.angle_var.get())
        except ValueError:
            messagebox.showerror("Неверное значение", "угол должен быть числом")
            return
        try:
            metric = self._metric()
        except ValueError as e:
            messagebox.showerror("Метрика", str(e))
            return
        ref = self._ref()
        w = metric.warning(self.cal)
        if w:
            self._log(w)

        # метрика может оказаться неразрешимой уже на сетке спектра (полоса
        # целиком вне записанной) -- `_metric()` этого не видит, там только
        # разбор чисел. `_redraw_plot` и `_inverse` такой отказ ловят, а здесь
        # он уходил необработанным исключением из коллбэка кнопки: оператор
        # жал «Вычислить затухание» и не получал НИЧЕГО -- ни диалога, ни
        # строки в окне результата
        try:
            q = self._describe(theta, metric, ref)
        except ValueError as e:
            messagebox.showerror("Метрика", str(e))
            return
        self._log(f"[опора {REF_SHORT[ref]}] {metric.label}")
        self._log(f"  угол WGP1 = {theta:+.3f}°  (от OFFSET {theta - self.offset:+.3f}, "
                  f"от ZERO {theta - self.zero:+.3f})")
        self._log(f"  затухание = {q['db_sel']:+.2f} дБ, "
                  f"T = P/{REF_SHORT[ref]} = {q['pct_sel']:.3f} %")
        self._log_output_state(theta, metric)
        self._log_zero_block(theta, metric, ref)
        self._log("")
        self._markers = [theta]
        self._redraw_plot()

    def _log_output_state(self, theta1_deg: float, metric) -> None:
        """Состояние поляризации НА ВЫХОДЕ аттенюатора.

        Плоскость поляризации задаёт второй поляризатор. Показывается всегда, в
        том числе при мощностном приёмнике: ему азимут безразличен, а образцу и
        оптике ниже по тракту -- нет.
        """
        try:
            th2 = np.array([self.cal.off2_deg])
            r = pair_response(np.array([theta1_deg]), th2, self.cal, metric)
            self._log(f"  на выходе: азимут {float(np.ravel(r['azimuth_deg'])[0]):+.3f}°, "
                      f"эллиптичность {float(np.ravel(r['ellipticity_deg'])[0]):+.3f}°, "
                      f"степень поляризации {float(np.ravel(r['dop'])[0]):.4f}")
        except Exception as e:                       # noqa: BLE001
            # состояние на выходе -- справочная величина; её отказ не должен
            # рушить основной ответ про затухание
            self._log(f"  (состояние на выходе не посчитано: {e})")

    def _inverse(self) -> None:
        try:
            target = float(self.db_var.get())
        except ValueError:
            messagebox.showerror("Неверное значение", "затухание должно быть числом")
            return
        try:
            metric = self._metric()
        except ValueError as e:
            messagebox.showerror("Метрика", str(e))
            return
        ref = self._ref()
        w = metric.warning(self.cal)
        if w:
            self._log(w)
        try:
            sol = angle_for_db(target, self.offset, self.cal, metric, ref, self.zero)
        except ValueError as e:
            messagebox.showerror("Недостижимо", str(e))
            return

        self._log(f"[опора {REF_SHORT[ref]}] {metric.label}")
        # границы печатаются округлёнными ВНУТРЬ достижимого: иначе окно само
        # называло недостижимое число (дно -40.908 -> «-40.91»), оператор вводил
        # его обратно и получал «недостижимо: минимум -40.91»
        self._log(f"  цель {target:+.2f} дБ; диапазон "
                  f"[{fmt_db_bound(sol['db_min'], True)}, "
                  f"{fmt_db_bound(sol['db_max'], False)}] дБ")
        self._log(f"  угол WGP1 = {sol['theta_plus_deg']:+.3f}°  "
                  f"или {sol['theta_minus_deg']:+.3f}°")
        self._log("  (два симметричных решения -- выбрать ближе к текущему положению)")
        self._log_zero_block(sol["theta_plus_deg"], metric, ref)
        self._log("")

        self._markers = [sol["theta_plus_deg"], sol["theta_minus_deg"]]
        self._redraw_plot()


def main() -> int:
    app = ServiceGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
