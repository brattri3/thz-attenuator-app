"""Desktop GUI ТГц-аттенюатора (tkinter, поверх attenuator_app.api.Attenuator).

Запуск из корня THz-Unified-Optimizer:
    .venv\\Scripts\\python.exe -m attenuator_app.gui

Практичное подмножество CLI (`cli.py`) для оператора прибора: паспорт устройства,
выбор схемы/детектора/источника, SET ZERO/AUTO-ZERO/AUTO-CROSS, прямая и обратная
задачи, спектр/кривая затухания, проверки применимости F1..F8.

Зависимости: только tkinter (стандартная библиотека) + numpy, как и у CLI. matplotlib
опционален — если недоступен, графики рисуются вручную на tkinter.Canvas (сильно
упрощённо, но без внешних библиотек); при полном отсутствии данных выводится текст.
Это то же самое сознательное решение, что и в `core/plots.py`: приложение должно
запускаться у покупателя без научного стека.

GUI НЕ содержит собственной физики: все числа получены вызовами `api.Attenuator`,
как и в `cli.py`. Комментарии в коде — по-русски, весь пользовательский текст — на
английском (решение владельца от 2026-07-28, см. `attenuator_app/STATE.md`).
"""
from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .api import Attenuator, MotionCommand
from .core import plots
from .core.forward import DETECTORS, SCHEMES, SOURCES, ideal_cos4_db
from .core.limits import slope_db_per_deg
from .core.limits import uncertainty as calc_uncertainty
from .core.passport import Passport
from .core.weights import PRESETS

HERE = Path(__file__).resolve().parent
DEFAULT_PASSPORT = HERE / "passports" / "SAMPLE.json"

# -- палитра (та же, что в core/plots.py, для согласованности Canvas-фолбэка) ----
C_SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
C_BAND = "#cfe1f7"
C_INK = "#0b0b0b"
C_INK2 = "#52514e"
C_MUTED = "#898781"
C_AXIS = "#c3c2b7"


# =============================================================================
def _load_png_photo(path):
    """PNG -> объект, который можно вставить в tk.Label. Pillow если есть, иначе Tk PNG."""
    try:
        from PIL import Image, ImageTk
        return ImageTk.PhotoImage(Image.open(path))
    except Exception:
        return tk.PhotoImage(file=str(path))


class CanvasPlot(ttk.Frame):
    """Ручной линейный график на tkinter.Canvas — фолбэк, когда matplotlib недоступен.

    Не претендует на качество core/plots.py: только линии, коридор 95 % заливкой,
    подписи осей и легенда. Этого достаточно, чтобы оператор увидел форму кривой.
    """

    def __init__(self, parent, height=360):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, height=height, bg="white",
                                 highlightthickness=1, highlightbackground=C_AXIS)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self._series = []
        self._band = None
        self._xlabel = self._ylabel = self._title = ""

    def plot(self, series, *, band=None, xlabel="", ylabel="", title=""):
        """series: список (xs, ys, color, label, dash_or_None)."""
        self._series = series
        self._band = band
        self._xlabel, self._ylabel, self._title = xlabel, ylabel, title
        self._redraw()

    def clear(self):
        self._series = []
        self._band = None
        self._redraw()

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 640
        h = c.winfo_height() or 360
        if not self._series:
            c.create_text(w / 2, h / 2, text="(no data yet)", fill=C_MUTED)
            return

        xs_all = np.concatenate([np.asarray(s[0], dtype=float) for s in self._series])
        ys_parts = [np.asarray(s[1], dtype=float) for s in self._series]
        if self._band is not None:
            ys_parts += [np.asarray(self._band[1], dtype=float),
                         np.asarray(self._band[2], dtype=float)]
        ys_all = np.concatenate(ys_parts)
        ys_all = ys_all[np.isfinite(ys_all)]
        if xs_all.size == 0 or ys_all.size == 0:
            c.create_text(w / 2, h / 2, text="(no finite data)", fill=C_MUTED)
            return
        x0, x1 = float(xs_all.min()), float(xs_all.max())
        y0, y1 = float(ys_all.min()), float(ys_all.max())
        if x1 <= x0:
            x1 = x0 + 1.0
        if y1 <= y0:
            y1 = y0 + 1.0
        pad = 0.06 * (y1 - y0)
        y0, y1 = y0 - pad, y1 + pad

        pad_l, pad_r, pad_t, pad_b = 58, 18, 26, 36
        plot_w = max(w - pad_l - pad_r, 10)
        plot_h = max(h - pad_t - pad_b, 10)

        def X(x):
            return pad_l + (x - x0) / (x1 - x0) * plot_w

        def Y(y):
            return h - pad_b - (y - y0) / (y1 - y0) * plot_h

        c.create_rectangle(pad_l, pad_t, w - pad_r, h - pad_b, outline=C_AXIS)
        for i in range(5):
            xv = x0 + i / 4 * (x1 - x0)
            xp = X(xv)
            c.create_line(xp, h - pad_b, xp, h - pad_b + 4, fill=C_MUTED)
            c.create_text(xp, h - pad_b + 14, text=f"{xv:.2f}", fill=C_INK2,
                          font=("TkDefaultFont", 8))
        for i in range(5):
            yv = y0 + i / 4 * (y1 - y0)
            yp = Y(yv)
            c.create_line(pad_l - 4, yp, pad_l, yp, fill=C_MUTED)
            c.create_text(pad_l - 8, yp, text=f"{yv:.1f}", fill=C_INK2, anchor="e",
                          font=("TkDefaultFont", 8))

        if self._band is not None:
            bx, lo, hi = self._band
            bx = np.asarray(bx, dtype=float)
            top = [(X(x), Y(v)) for x, v in zip(bx, hi)]
            bot = [(X(x), Y(v)) for x, v in zip(bx, lo)][::-1]
            flat = [v for p in (top + bot) for v in p]
            if len(flat) >= 6:
                c.create_polygon(*flat, fill=C_BAND, outline="")

        for xs, ys, color, label, dash in self._series:
            xs = np.asarray(xs, dtype=float)
            ys = np.asarray(ys, dtype=float)
            pts = []
            for x, y in zip(xs, ys):
                if not np.isfinite(y):
                    if len(pts) >= 2:
                        c.create_line(*[v for p in pts for v in p], fill=color,
                                     width=2, dash=dash or ())
                    pts = []
                    continue
                pts.append((X(x), Y(y)))
            if len(pts) >= 2:
                c.create_line(*[v for p in pts for v in p], fill=color, width=2,
                             dash=dash or ())

        c.create_text(w / 2, 12, text=self._title, fill=C_INK, font=("TkDefaultFont", 9, "bold"))
        c.create_text(w / 2, h - 8, text=self._xlabel, fill=C_INK2, font=("TkDefaultFont", 8))
        c.create_text(12, h / 2, text=self._ylabel, fill=C_INK2, angle=90,
                      font=("TkDefaultFont", 8))
        ly = pad_t + 8
        for xs, ys, color, label, dash in self._series:
            if not label:
                continue
            c.create_line(w - pad_r - 92, ly, w - pad_r - 72, ly, fill=color, width=2,
                          dash=dash or ())
            c.create_text(w - pad_r - 68, ly, text=label, anchor="w", fill=C_INK,
                          font=("TkDefaultFont", 8))
            ly += 15


class PlotPanel(ttk.Frame):
    """Показывает PNG (matplotlib, через core/plots.py) либо ручной Canvas-график."""

    def __init__(self, parent):
        super().__init__(parent)
        self._photo = None
        self.mpl_available = plots.available()
        if self.mpl_available:
            self._label = ttk.Label(self, text="(no plot yet)", anchor="center")
            self._label.pack(fill="both", expand=True)
            self._canvas_plot = None
        else:
            note = ttk.Label(self, text="matplotlib not available - manual plot",
                             foreground=C_MUTED)
            note.pack(anchor="w")
            self._label = None
            self._canvas_plot = CanvasPlot(self)
            self._canvas_plot.pack(fill="both", expand=True)

    def show_png(self, path):
        if self._label is None:
            return
        img = _load_png_photo(path)
        self._photo = img          # держать ссылку, иначе tkinter соберёт мусор
        self._label.configure(image=img, text="")

    def show_series(self, series, **kw):
        if self._canvas_plot is not None:
            self._canvas_plot.plot(series, **kw)


# =============================================================================
class AttenuatorGUI(tk.Tk):
    """Главное окно. Одна конфигурация прибора, один текущий угол — как в cli.Shell."""

    def __init__(self):
        super().__init__()
        self.title("THz Attenuator Calculator")
        self.geometry("1150x760")
        self.minsize(900, 620)

        self.att: Attenuator | None = None
        self.relative = tk.BooleanVar(value=True)
        self._tmpdir = Path(tempfile.mkdtemp(prefix="att_gui_"))

        self._build_menu()
        self._build_layout()
        self._set_status("starting up...")

        try:
            self._load_passport(DEFAULT_PASSPORT)
        except Exception as e:
            self._set_status(f"could not load default passport: {e}", error=True)

    # -- каркас окна -----------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self)
        filem = tk.Menu(m, tearoff=0)
        filem.add_command(label="Open passport...", command=self._browse_passport)
        filem.add_separator()
        filem.add_command(label="Exit", command=self.destroy)
        m.add_cascade(label="File", menu=filem)
        self.config(menu=m)

    def _build_layout(self):
        root = ttk.Frame(self, padding=6)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Passport:").pack(side="left")
        self.passport_var = tk.StringVar(value="(none)")
        ttk.Label(top, textvariable=self.passport_var, foreground=C_INK2).pack(
            side="left", padx=(4, 10))
        ttk.Button(top, text="Browse...", command=self._browse_passport).pack(side="left")

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)

        self.notebook = ttk.Notebook(body)
        self.notebook.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._build_tab_device()
        self._build_tab_forward()
        self._build_tab_inverse()
        self._build_tab_spectrum()
        self._build_tab_curve()
        self._build_tab_checks()

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(6, 0))
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(status, textvariable=self.status_var, foreground=C_INK2)
        self.status_label.pack(side="left")

    # -- боковая панель: конфигурация + ноль/режим ------------------------
    def _build_sidebar(self, parent):
        side = ttk.Frame(parent, width=290)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        cfg = ttk.LabelFrame(side, text="Setup", padding=6)
        cfg.pack(fill="x", pady=(0, 6))

        ttk.Label(cfg, text="Scheme").grid(row=0, column=0, sticky="w")
        self.scheme_var = tk.StringVar()
        cb = ttk.Combobox(cfg, textvariable=self.scheme_var, values=list(SCHEMES),
                          state="readonly", width=18)
        cb.grid(row=0, column=1, sticky="ew", pady=1)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_scheme())

        ttk.Label(cfg, text="Detector").grid(row=1, column=0, sticky="w")
        self.detector_var = tk.StringVar()
        cb = ttk.Combobox(cfg, textvariable=self.detector_var, values=list(DETECTORS),
                          state="readonly", width=18)
        cb.grid(row=1, column=1, sticky="ew", pady=1)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_detector())

        ttk.Label(cfg, text="Source").grid(row=2, column=0, sticky="w")
        self.source_var = tk.StringVar()
        cb = ttk.Combobox(cfg, textvariable=self.source_var, values=list(SOURCES),
                          state="readonly", width=18)
        cb.grid(row=2, column=1, sticky="ew", pady=1)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_source())

        ttk.Label(cfg, text="psi, deg").grid(row=3, column=0, sticky="w")
        self.psi_var = tk.StringVar(value="0")
        ttk.Entry(cfg, textvariable=self.psi_var, width=10).grid(row=3, column=1, sticky="w")

        ttk.Label(cfg, text="DOP 0..1").grid(row=4, column=0, sticky="w")
        self.dop_var = tk.StringVar(value="1")
        ttk.Entry(cfg, textvariable=self.dop_var, width=10).grid(row=4, column=1, sticky="w")

        ttk.Button(cfg, text="Apply psi/DOP", command=self._apply_psi_dop).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        cfg.columnconfigure(1, weight=1)

        band = ttk.LabelFrame(side, text="Frequency grid, THz", padding=6)
        band.pack(fill="x", pady=(0, 6))
        self.band_f1 = tk.StringVar(value="0.20")
        self.band_f2 = tk.StringVar(value="1.50")
        self.band_n = tk.StringVar(value="128")
        row = ttk.Frame(band)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.band_f1, width=6).pack(side="left")
        ttk.Label(row, text="-").pack(side="left")
        ttk.Entry(row, textvariable=self.band_f2, width=6).pack(side="left")
        ttk.Label(row, text="N=").pack(side="left")
        ttk.Entry(row, textvariable=self.band_n, width=5).pack(side="left")
        ttk.Button(band, text="Apply grid", command=self._apply_band).pack(fill="x", pady=(3, 0))

        wgt = ttk.LabelFrame(side, text="Spectral weight (for integral)", padding=6)
        wgt.pack(fill="x", pady=(0, 6))
        self.weight_preset = tk.StringVar(value="pca")
        ttk.Combobox(wgt, textvariable=self.weight_preset, values=list(PRESETS),
                     state="readonly", width=18).pack(fill="x")
        ttk.Button(wgt, text="Apply weight", command=self._apply_weight).pack(
            fill="x", pady=(3, 0))
        self.weight_label = ttk.Label(wgt, text="not set", foreground=C_MUTED,
                                      wraplength=250, justify="left")
        self.weight_label.pack(fill="x", pady=(3, 0))

        zero = ttk.LabelFrame(side, text="Zero / mode", padding=6)
        zero.pack(fill="x", pady=(0, 6))
        self.state_label = ttk.Label(zero, text="", foreground=C_INK2, justify="left",
                                     wraplength=260)
        self.state_label.pack(fill="x", pady=(0, 4))

        row = ttk.Frame(zero)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="relative", variable=self.relative, value=True,
                        command=self._refresh_status).pack(side="left")
        ttk.Radiobutton(row, text="absolute", variable=self.relative, value=False,
                        command=self._refresh_status).pack(side="left")

        row = ttk.Frame(zero)
        row.pack(fill="x", pady=(4, 0))
        self.zero_entry = tk.StringVar()
        ttk.Entry(row, textvariable=self.zero_entry, width=8).pack(side="left")
        ttk.Button(row, text="SET ZERO", command=self._set_zero).pack(side="left", padx=(3, 0))

        row = ttk.Frame(zero)
        row.pack(fill="x", pady=(3, 0))
        ttk.Button(row, text="AUTO-ZERO", command=self._auto_zero).pack(side="left")
        ttk.Button(row, text="AUTO-CROSS", command=self._auto_cross).pack(side="left", padx=(3, 0))

        row = ttk.Frame(zero)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="set current angle:").pack(side="left")
        self.set_angle_entry = tk.StringVar()
        ttk.Entry(row, textvariable=self.set_angle_entry, width=8).pack(side="left", padx=(3, 0))
        ttk.Button(row, text="Set", command=self._set_current_angle).pack(side="left", padx=(3, 0))

    # -- вкладка Device -----------------------------------------------------
    def _build_tab_device(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Device")
        self.device_text = tk.Text(tab, wrap="word", state="disabled", height=30,
                                   font=("Consolas", 9))
        self.device_text.pack(fill="both", expand=True)
        ttk.Button(tab, text="Refresh", command=self._refresh_device_tab).pack(
            anchor="w", pady=(4, 0))

    # -- вкладка Forward ------------------------------------------------
    def _build_tab_forward(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Forward (angle -> dB)")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="theta, deg:").pack(side="left")
        self.fwd_theta = tk.StringVar(value="45")
        ttk.Entry(row, textvariable=self.fwd_theta, width=10).pack(side="left", padx=(3, 10))
        self.fwd_integral = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="integral over source spectrum", variable=self.fwd_integral
                        ).pack(side="left")
        ttk.Button(row, text="Compute", command=self._do_forward).pack(side="left", padx=(10, 0))

        self.fwd_text = tk.Text(tab, wrap="word", state="disabled", height=24,
                                font=("Consolas", 9))
        self.fwd_text.pack(fill="both", expand=True, pady=(6, 0))

    # -- вкладка Inverse ------------------------------------------------
    def _build_tab_inverse(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Inverse (dB -> angle)")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="target, dB:").pack(side="left")
        self.inv_target = tk.StringVar(value="20")
        ttk.Entry(row, textvariable=self.inv_target, width=10).pack(side="left", padx=(3, 10))
        self.inv_integral = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="integral over source spectrum", variable=self.inv_integral
                        ).pack(side="left")
        ttk.Button(row, text="Solve", command=self._do_inverse).pack(side="left", padx=(10, 0))

        cols = ("rank", "theta", "achieved", "ci95")
        self.inv_tree = ttk.Treeview(tab, columns=cols, show="headings", height=6)
        for c, w, t in zip(cols, (50, 90, 90, 170),
                          ("#", "theta, deg", "achieved, dB", "95% interval, dB")):
            self.inv_tree.heading(c, text=t)
            self.inv_tree.column(c, width=w, anchor="center")
        self.inv_tree.pack(fill="x", pady=(6, 4))

        row = ttk.Frame(tab)
        row.pack(fill="x")
        self.inv_apply = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="apply best solution to current angle after planning",
                        variable=self.inv_apply).pack(side="left")
        ttk.Button(row, text="Plan (best solution)", command=self._do_plan).pack(
            side="left", padx=(10, 0))

        self.inv_text = tk.Text(tab, wrap="word", state="disabled", height=14,
                                font=("Consolas", 9))
        self.inv_text.pack(fill="both", expand=True, pady=(6, 0))

    # -- вкладка Spectrum -------------------------------------------------
    def _build_tab_spectrum(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Spectrum")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="theta, deg:").pack(side="left")
        self.spec_theta = tk.StringVar(value="45")
        ttk.Entry(row, textvariable=self.spec_theta, width=10).pack(side="left", padx=(3, 10))
        ttk.Button(row, text="Plot", command=self._do_spectrum).pack(side="left")

        self.spec_plot = PlotPanel(tab)
        self.spec_plot.pack(fill="both", expand=True, pady=(6, 4))
        self.spec_warn = ttk.Label(tab, text="", foreground="#b45a00", wraplength=760,
                                   justify="left")
        self.spec_warn.pack(fill="x")

    # -- вкладка Curve --------------------------------------------------
    def _build_tab_curve(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Curve A(theta)")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="table step, deg:").pack(side="left")
        self.curve_step = tk.StringVar(value="10")
        ttk.Entry(row, textvariable=self.curve_step, width=10).pack(side="left", padx=(3, 10))
        ttk.Button(row, text="Plot", command=self._do_curve).pack(side="left")

        self.curve_plot = PlotPanel(tab)
        self.curve_plot.pack(fill="both", expand=True, pady=(6, 4))

    # -- вкладка Checks ---------------------------------------------------
    def _build_tab_checks(self):
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Applicability checks")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="target, dB:").pack(side="left")
        self.chk_target = tk.StringVar(value="20")
        ttk.Entry(row, textvariable=self.chk_target, width=10).pack(side="left", padx=(3, 10))
        ttk.Label(row, text="theta, deg (blank = from solve):").pack(side="left")
        self.chk_theta = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.chk_theta, width=10).pack(side="left", padx=(3, 10))
        ttk.Button(row, text="Run checks (F1..F8)", command=self._do_checks).pack(
            side="left", padx=(10, 0))

        self.chk_text = tk.Text(tab, wrap="word", state="disabled", height=24,
                                font=("Consolas", 9))
        self.chk_text.pack(fill="both", expand=True, pady=(6, 0))
        self.chk_text.tag_configure("ok", foreground="#0ca30c")
        self.chk_text.tag_configure("bad", foreground="#d03b3b")
        self.chk_text.tag_configure("bold", font=("Consolas", 9, "bold"))

    # =====================================================================
    # -- служебное ---------------------------------------------------------
    def _set_status(self, text, error=False):
        self.status_var.set(text)
        self.status_label.configure(foreground="#d03b3b" if error else C_INK2)

    def _set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _need_att(self) -> bool:
        if self.att is None:
            messagebox.showerror("No device", "Load a passport first (File -> Open passport).")
            return False
        return True

    def _footer(self) -> str:
        if self.att is None:
            return ""
        p, s, a = self.att.passport, self.att.setup, self.att
        return (f"{p.serial} - scheme {s.scheme} - detector {s.detector} - "
                f"scale {p.scale.division_deg:g} deg (sigma {p.scale.sigma_total_deg():.2f} deg) - "
                f"calibration band {p.band_thz[0]}-{p.band_thz[1]} THz - "
                f"zero {a.zero_deg if a.zero_deg is not None else '-'} deg - "
                f"weight {a.weight_desc}")

    # -- загрузка паспорта --------------------------------------------------
    def _browse_passport(self):
        start = str((HERE / "passports")) if (HERE / "passports").exists() else str(HERE)
        path = filedialog.askopenfilename(
            title="Open instrument passport", initialdir=start,
            filetypes=[("Passport JSON", "*.json"), ("All files", "*.*")])
        if path:
            try:
                self._load_passport(Path(path))
            except Exception as e:
                messagebox.showerror("Failed to load passport", str(e))
                self._set_status(f"failed to load passport: {e}", error=True)

    def _load_passport(self, path: Path):
        p = Passport.load(path)
        self.att = Attenuator(p)
        self.att.setup.validate()
        self.att.set_zero(0.0)
        self.passport_var.set(str(path))

        self.scheme_var.set(self.att.setup.scheme)
        self.detector_var.set(self.att.setup.detector)
        self.source_var.set(self.att.setup.source)
        self.psi_var.set(f"{self.att.setup.psi_deg:g}")
        self.dop_var.set(f"{self.att.setup.dop:g}")
        self.band_f1.set(f"{self.att.freqs[0]:g}")
        self.band_f2.set(f"{self.att.freqs[-1]:g}")
        self.band_n.set(str(len(self.att.freqs)))

        self._refresh_device_tab()
        self._refresh_status()
        self._set_status(f"loaded passport {p.serial}")

    # -- конфигурация схемы -------------------------------------------------
    def _apply_scheme(self):
        if not self._need_att():
            return
        try:
            self.att.setup.scheme = self.scheme_var.get()
            self.att.setup.validate()
            self._set_status(f"scheme: {self.att.setup.scheme}")
        except Exception as e:
            messagebox.showerror("Invalid scheme", str(e))

    def _apply_detector(self):
        if not self._need_att():
            return
        try:
            self.att.setup.detector = self.detector_var.get()
            self.att.setup.validate()
            self._set_status(f"detector: {self.att.setup.detector}")
        except Exception as e:
            messagebox.showerror("Invalid detector", str(e))

    def _apply_source(self):
        if not self._need_att():
            return
        try:
            self.att.setup.source = self.source_var.get()
            self.att.setup.validate()
            self._set_status(f"source: {self.att.setup.source}")
        except Exception as e:
            messagebox.showerror("Invalid source", str(e))

    def _apply_psi_dop(self):
        if not self._need_att():
            return
        try:
            self.att.setup.psi_deg = float(self.psi_var.get())
            self.att.setup.dop = float(self.dop_var.get())
            self.att.setup.validate()
            self._set_status(f"psi={self.att.setup.psi_deg:g} deg, DOP={self.att.setup.dop:g}")
        except Exception as e:
            messagebox.showerror("Invalid psi/DOP", str(e))

    def _apply_band(self):
        if not self._need_att():
            return
        try:
            f1, f2, n = float(self.band_f1.get()), float(self.band_f2.get()), int(self.band_n.get())
            self.att.freqs = np.linspace(f1, f2, n)
            self.att.weight = None
            self.att.weight_desc = "not set (grid changed)"
            self.weight_label.configure(text="not set (grid changed)")
            self._set_status(f"grid {f1:g}-{f2:g} THz, {n} points")
        except Exception as e:
            messagebox.showerror("Invalid grid", str(e))

    def _apply_weight(self):
        if not self._need_att():
            return
        try:
            lo, hi = self.att.set_weight("preset", name=self.weight_preset.get())
            self.weight_label.configure(
                text=f"{self.att.weight_desc}\neffective band {lo:.2f}-{hi:.2f} THz")
            self._set_status("spectral weight applied")
        except Exception as e:
            messagebox.showerror("Failed to set weight", str(e))

    # -- ноль / режим ---------------------------------------------------
    def _set_zero(self):
        if not self._need_att():
            return
        try:
            txt = self.zero_entry.get().strip()
            z = self.att.set_zero(float(txt) if txt else None)
            self._set_status(f"SET ZERO: reference angle {z:+.2f} deg, 0 dB by definition")
        except Exception as e:
            messagebox.showerror("SET ZERO failed", str(e))
        self._refresh_status()

    def _auto_zero(self):
        if not self._need_att():
            return
        try:
            z = self.att.auto_zero()
            self._set_status(f"AUTO-ZERO: transmission maximum at {z:+.2f} deg")
        except Exception as e:
            messagebox.showerror("AUTO-ZERO failed", str(e))
        self._refresh_status()

    def _auto_cross(self):
        if not self._need_att():
            return
        try:
            th, fl = self.att.auto_cross()
            d = abs(th - (self.att.zero_deg or 0.0))
            msg = f"AUTO-CROSS: extinction at {th:.2f} deg, floor {fl:.2f} dB, distance from zero {d:.2f} deg"
            if abs(d - 90) > 2:
                msg += f"  (differs from 90 by {d - 90:+.1f} deg: misalignment or non-Malus behavior)"
            self._set_status(msg)
        except Exception as e:
            messagebox.showerror("AUTO-CROSS failed", str(e))
        self._refresh_status()

    def _set_current_angle(self):
        if not self._need_att():
            return
        try:
            self.att.theta_deg = float(self.set_angle_entry.get())
            self._set_status(f"current angle set to {self.att.theta_deg:+.2f} deg")
        except Exception as e:
            messagebox.showerror("Invalid angle", str(e))
        self._refresh_status()

    def _refresh_status(self):
        if self.att is None:
            self.state_label.configure(text="(no device loaded)")
            return
        a = self.att
        zero_txt = "not set" if a.zero_deg is None else f"{a.zero_deg:+.2f} deg"
        self.state_label.configure(
            text=(f"mode: {'relative' if self.relative.get() else 'absolute'}\n"
                  f"zero: {zero_txt}\n"
                  f"current angle: {a.theta_deg:+.2f} deg"))

    # -- Device tab -------------------------------------------------------
    def _refresh_device_tab(self):
        if self.att is None:
            self._set_text(self.device_text, "(no device loaded)")
            return
        s = self.att.device_summary()
        p = self.att.passport
        lines = [
            f"Device {s['serial']}  {s['model']}",
            f"  aperture     {s['aperture_mm']:g} mm -> scale {s['scale_division_deg']:g} deg, "
            f"sigma(angle) {s['sigma_angle_deg']:.2f} deg",
            f"  P            {s['P_um']:.3f} um",
            f"  D_eff        {p.D_eff_um.value:.3f} +- {p.D_eff_um.sigma:.3f} um "
            f"(D_eff/D_phys = {s['D_eff_over_D_phys']:.3f}; EFFECTIVE, not geometric)",
            f"  loss         {p.loss_factor.value:.3f} +- {p.loss_factor.sigma:.3f} "
            f"dB/THz^{p.gamma.value:g}  (gamma range {p.gamma_range[0]}..{p.gamma_range[1]})",
            f"  offset       {p.angle_offset_deg.value:+.2f} +- {p.angle_offset_deg.sigma:.2f} deg",
            f"  calibration band {p.band_thz[0]}-{p.band_thz[1]} THz, scheme {p.fit_scheme}, "
            f"detector {p.fit_detector}",
            f"  anomaly nu   {s['nu_anomaly_thz']:.1f} THz; green zone up to "
            f"{s['zone_green_max_thz']:.2f} THz",
        ]
        if p.film:
            lines.append(f"  films        {p.film.name}: K1={p.film.K1:.2f}, "
                        f"ER {p.film.er_db(0.5):.0f} dB @0.5 THz / {p.film.er_db(2.0):.0f} dB @2 THz")
        lines += [
            "",
            f"Configuration: scheme {self.att.setup.scheme} ({SCHEMES[self.att.setup.scheme]})",
            f"  detector {self.att.setup.detector}, source {self.att.setup.source} "
            f"(psi={self.att.setup.psi_deg:g} deg, DOP={self.att.setup.dop:g})",
            f"  grid {self.att.freqs[0]:.2f}-{self.att.freqs[-1]:.2f} THz, {len(self.att.freqs)} points",
            f"  source weight: {self.att.weight_desc}",
        ]
        if p.calibration_note:
            lines += ["", f"  {p.calibration_note}"]
        self._set_text(self.device_text, "\n".join(lines))

    # -- Forward ----------------------------------------------------------
    def _do_forward(self):
        if not self._need_att():
            return
        try:
            theta = float(self.fwd_theta.get())
            r = self.att.attenuation(theta, relative=self.relative.get(),
                                     integral=self.fwd_integral.get())
        except Exception as e:
            messagebox.showerror("Forward problem failed", str(e))
            return
        kind = "integral" if r["integral"] else "band average"
        lines = [
            f"theta = {r['theta_deg']:+.2f} deg   ({kind}, "
            f"{'relative to zero' if r['relative'] else 'absolute'})",
            "",
            f"ATTENUATION  {r['att_db']:.2f} dB   "
            f"[95%: {r['ci95_db'][0]:.2f} ... {r['ci95_db'][1]:.2f}]  sigma={r['sigma_db']:.2f} dB",
            f"power  x{r['power_ratio']:.4g}",
            f"field  x{r['field_ratio']:.4g}",
            f"ideal cos^4 limit: {r['ideal_cos4_db']:.2f} dB",
        ]
        if r["parts"]:
            lines += ["", "uncertainty contributions (95% bounds, dB):"]
            for k, (lo, hi) in r["parts"].items():
                lines.append(f"   {k:<14} {lo:7.2f} ... {hi:7.2f}")
        self._set_text(self.fwd_text, "\n".join(lines))
        self._set_status(f"forward: {r['att_db']:.2f} dB at {theta:+.2f} deg")

    # -- Inverse ------------------------------------------------------
    def _do_inverse(self):
        if not self._need_att():
            return
        for i in self.inv_tree.get_children():
            self.inv_tree.delete(i)
        try:
            target = float(self.inv_target.get())
            sols = self.att.solve(target, integral=self.inv_integral.get())
        except Exception as e:
            messagebox.showerror("Inverse problem failed", str(e))
            return
        if not sols:
            th_ext, floor = self.att.auto_cross()
            self._set_text(self.inv_text,
                           f"TARGET {target:.2f} dB IS UNREACHABLE\n"
                           f"device maximum: {floor:.2f} dB at theta = {th_ext:.1f} deg\n"
                           f"remedies: HR-Si wafer (-3.01 dB, broadband); "
                           f"grid with smaller D/P; narrow the band")
            self._set_status(f"target {target:.2f} dB unreachable", error=True)
            return
        for s in sols:
            self.inv_tree.insert("", "end", values=(
                s.rank, f"{s.theta_set_deg:+.2f}", f"{s.achieved_db:.2f}",
                f"[{s.lo_db:.2f} ... {s.hi_db:.2f}]"))
        best = sols[0]
        self._set_text(self.inv_text,
                       f"solutions for target {target:.2f} dB "
                       f"({'integral' if self.inv_integral.get() else 'band average'}, "
                       f"scale {self.att.passport.scale.division_deg:g} deg)\n\n"
                       f"RECOMMENDATION: set {best.theta_set_deg:+.2f} deg -> "
                       f"{best.achieved_db:.2f} dB [95%: {best.lo_db:.2f} ... {best.hi_db:.2f}]")
        self._set_status(f"solve: {len(sols)} candidate(s), best {best.theta_set_deg:+.2f} deg")
        self._last_solution = best

    def _do_plan(self):
        if not self._need_att():
            return
        sel = self.inv_tree.selection()
        best = None
        if sel:
            vals = self.inv_tree.item(sel[0], "values")
            try:
                theta = float(vals[1])
                for s in self.att.solve(float(self.inv_target.get()),
                                        integral=self.inv_integral.get()):
                    if abs(s.theta_set_deg - theta) < 1e-6:
                        best = s
                        break
            except Exception:
                best = None
        if best is None:
            best = getattr(self, "_last_solution", None)
        if best is None:
            messagebox.showinfo("Plan", "Run Solve first (or select a row in the table).")
            return
        cmds: list[MotionCommand] = self.att.motion_plan(best)
        lines = [f"PLAN for {best.achieved_db:.2f} dB (target row selected):", ""]
        for c in cmds:
            lines.append("  " + c.as_operator_instruction())
        lines.append(f"\nexpected attenuation {best.achieved_db:.2f} dB "
                    f"[95%: {best.lo_db:.2f} ... {best.hi_db:.2f}]")
        if self.inv_apply.get():
            self.att.apply(best)
            lines.append(f"\ncurrent angle is now {self.att.theta_deg:+.2f} deg (applied)")
        else:
            lines.append("\n(not applied - checkbox unchecked, current angle unchanged)")
        self._set_text(self.inv_text, "\n".join(lines))
        self._refresh_status()
        self._set_status("motion plan generated")

    # -- Spectrum -----------------------------------------------------
    def _do_spectrum(self):
        if not self._need_att():
            return
        try:
            theta = float(self.spec_theta.get())
            s = self.att.spectrum(theta, relative=self.relative.get())
        except Exception as e:
            messagebox.showerror("Spectrum failed", str(e))
            return
        nu, db, z = s["freq_thz"], s["att_db"], s["zone"]

        lo_db, hi_db = [], []
        ref = self.att.zero_deg if self.relative.get() else None
        for f in nu:
            u = calc_uncertainty(theta, self.att.passport, self.att.setup, np.array([f]),
                                 ref_theta_deg=ref)
            lo_db.append(u.lo_db)
            hi_db.append(u.hi_db)

        n_ex = int(s["extrapolated"].sum())
        warn = ""
        if n_ex:
            warn = (f"WARNING: {n_ex} of {len(nu)} points lie outside the calibration band "
                   f"{self.att.passport.band_thz[0]}-{self.att.passport.band_thz[1]} THz "
                   f"(extrapolated, wider uncertainty)")
        self.spec_warn.configure(text=warn)

        title = f"Attenuation spectrum at theta={theta:+.2f} deg"
        if self.spec_plot.mpl_available:
            path = self._tmpdir / "spectrum.png"
            plots.spectrum(path, nu, db, lo_db=lo_db, hi_db=hi_db, zones=z,
                           band=self.att.passport.band_thz, extrapolated=s["extrapolated"],
                           theta_deg=theta,
                           mode="relative" if self.relative.get() else "absolute",
                           footer=self._footer())
            self.spec_plot.show_png(path)
        else:
            self.spec_plot.show_series(
                [(nu, db, C_SERIES[0], "model", None)],
                band=(nu, lo_db, hi_db), xlabel="frequency, THz",
                ylabel="attenuation, dB", title=title)
        self._set_status(f"spectrum plotted at theta={theta:+.2f} deg")

    # -- Curve ----------------------------------------------------------
    def _do_curve(self):
        if not self._need_att():
            return
        try:
            step = float(self.curve_step.get())
        except Exception as e:
            messagebox.showerror("Invalid step", str(e))
            return
        ref = self.att.zero_deg or 0.0
        fine = np.arange(ref, ref + 90.0 + 1e-9, 2.0)
        att_db, lo_db, hi_db, ideal_db, slope = [], [], [], [], []
        for t in fine:
            r = self.att.attenuation(t, relative=True)
            att_db.append(r["att_db"])
            lo_db.append(r["ci95_db"][0])
            hi_db.append(r["ci95_db"][1])
            ideal_db.append(float(ideal_cos4_db(t, ref)))
            slope.append(slope_db_per_deg(t, self.att.passport, self.att.setup,
                                          self.att.freqs, ref_theta_deg=ref))

        if self.curve_plot.mpl_available:
            path = self._tmpdir / "curve.png"
            plots.angular_curve(path, fine, att_db, ideal_db, lo_db=lo_db, hi_db=hi_db,
                                slope=slope, footer=self._footer())
            self.curve_plot.show_png(path)
        else:
            self.curve_plot.show_series(
                [(fine, att_db, C_SERIES[0], "device model", None),
                 (fine, ideal_db, C_MUTED, "ideal cos^4", (5, 3))],
                band=(fine, lo_db, hi_db), xlabel="angle, deg",
                ylabel="attenuation, dB", title="Angular attenuation curve")
        self._set_status(f"curve plotted, step {step:g} deg (fine grid used for the plot itself)")

    # -- Checks -----------------------------------------------------------
    def _do_checks(self):
        if not self._need_att():
            return
        try:
            target = float(self.chk_target.get())
        except Exception as e:
            messagebox.showerror("Invalid target", str(e))
            return
        theta_txt = self.chk_theta.get().strip()
        theta = None
        note = ""
        if theta_txt:
            try:
                theta = float(theta_txt)
            except Exception as e:
                messagebox.showerror("Invalid angle", str(e))
                return
        else:
            sols = self.att.solve(target)
            if sols:
                theta = sols[0].theta_set_deg
                note = f"(angle taken from the inverse-problem solution: {theta:+.2f} deg)\n\n"
        try:
            checks = self.att.checks(target, theta)
        except Exception as e:
            messagebox.showerror("Checks failed", str(e))
            return

        self.chk_text.configure(state="normal")
        self.chk_text.delete("1.0", "end")
        if note:
            self.chk_text.insert("end", note)
        bad = []
        for c in checks:
            tag = "ok" if c.ok else "bad"
            if not c.ok:
                bad.append(c.code)
            self.chk_text.insert("end", str(c) + "\n\n", tag)
        verdict = "REACHABLE" if not bad else "REFUSED by " + ", ".join(bad)
        self.chk_text.insert("end", f"VERDICT: {verdict}\n",
                             ("ok" if not bad else "bad", "bold"))
        self.chk_text.configure(state="disabled")
        self._set_status(f"checks: {verdict}", error=bool(bad))


# =============================================================================
def main():
    app = AttenuatorGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
