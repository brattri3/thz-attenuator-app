"""Интерактивный CLI ТГц-аттенюатора (бесконечный цикл).

Запуск из корня THz-Unified-Optimizer:
    .venv\\Scripts\\python.exe -m attenuator_app.cli
    .venv\\Scripts\\python.exe -m attenuator_app.cli --passport attenuator_app/passports/<файл>.json

Все затухания — в дБ ПО МОЩНОСТИ (10*log10). Отношение по полю показывается
справочно рядом. Углы вводятся в градусах; прибор с ручной установкой угла,
поэтому решения привязываются к делениям шкалы из паспорта.
"""
from __future__ import annotations

import argparse
import shlex
import sys
import traceback
from pathlib import Path

import numpy as np

from .api import Attenuator
from .core.forward import DETECTORS, SCHEMES, SOURCES, ideal_cos4_db
from .core.passport import Passport
from .core import plots
from .core.limits import uncertainty
from .core.session import Session, ascii_plot
from .core.weights import PRESETS

HERE = Path(__file__).resolve().parent
DEFAULT_PASSPORT = HERE / "passports" / "SAMPLE.json"

HELP = """
Commands
  dev                          device summary and current configuration
  scheme [S0|S1|S2|S3]         optical scheme (no argument - list)
  det    [coherent|power]      detector type
  src    [linear|unpolarized]  source type
  psi <deg> | dop <0..1>       source polarization azimuth and degree
  band <f1> <f2> [N]           working frequency grid, THz
  w <kind> [options]           source spectral weight: preset <name> | flat <f1> <f2>
                               | gauss <nu0> <dnu> | bg <file>
  bg <file>                    background scan -> dynamic range (check F3)

  zero [deg]                   SET ZERO: declare position as reference (0 dB)
  autozero                     AUTO-ZERO: find transmission maximum
  autocross                    AUTO-CROSS: find extinction point (NOT at 90 deg)
  set <deg>                    assume the device is at this angle now
  mode abs|rel                 attenuation reference mode

  a <deg>                      forward problem: attenuation at a point
  ai <deg>                     same, integral over the source spectrum
  spec <deg>                   attenuation spectrum + zones + output polarization
  curve [step]                 A(theta) table next to the ideal cos^4
  solve <dB> [-i]              inverse problem (-i = integral)
  check <dB> [deg]             applicability checks F1..F8
  sweep <dB,dB,...>            level sweep, monotonic traversal
  plan <dB>                    solution + operator instruction
  pol <deg>                    output polarization (azimuth, ellipticity)

  ascii on|off                 print ASCII plots to the terminal
  help | q
"""


def bar(v, lo, hi, width=34, ch="#"):
    if not np.isfinite(v):
        return ""
    x = 0.0 if hi <= lo else (v - lo) / (hi - lo)
    return ch * int(np.clip(x, 0, 1) * width)


class Shell:
    def __init__(self, att: Attenuator, sess=None):
        self.att = att
        self.relative = True
        self.sess = sess
        self.ascii_plots = True
        self.sync_choices()

    def sync_choices(self):
        """Записать текущее состояние выборов в метафайл сеанса."""
        if not self.sess:
            return
        a, s, p = self.att, self.att.setup, self.att.passport
        self.sess.choose(
            passport=f"{p.serial}", scheme=s.scheme, detector=s.detector,
            source=s.source, psi_deg=s.psi_deg, dop=s.dop, det_deg=s.det_deg,
            phi2_deg=s.phi2_deg, use_film=s.use_film,
            mode="relative" if self.relative else "absolute",
            zero_deg=a.zero_deg, theta_deg=a.theta_deg,
            band_thz=[float(a.freqs[0]), float(a.freqs[-1]), len(a.freqs)],
            weight=a.weight_desc, scale_division_deg=p.scale.division_deg,
            sigma_angle_deg=round(p.scale.sigma_total_deg(), 3),
            model_rmse_db=p.model_rmse_db)

    # -- вывод ---------------------------------------------------------
    def dev(self):
        s = self.att.device_summary()
        p = self.att.passport
        print(f"\nDevice {s['serial']}  {s['model']}")
        print(f"  aperture     {s['aperture_mm']:g} mm -> scale {s['scale_division_deg']:g} deg, "
              f"sigma(angle) {s['sigma_angle_deg']:.2f} deg")
        print(f"  P            {s['P_um']:.3f} um")
        print(f"  D_eff        {p.D_eff_um.value:.3f} +- {p.D_eff_um.sigma:.3f} um "
              f"(D_eff/D_phys = {s['D_eff_over_D_phys']:.3f}; EFFECTIVE, not geometric)")
        print(f"  loss         {p.loss_factor.value:.3f} +- {p.loss_factor.sigma:.3f} dB/THz^{p.gamma.value:g}"
              f"  (gamma range {p.gamma_range[0]}..{p.gamma_range[1]} -> envelope)")
        print(f"  offset       {p.angle_offset_deg.value:+.2f} +- {p.angle_offset_deg.sigma:.2f} deg")
        print(f"  calibration band {p.band_thz[0]}-{p.band_thz[1]} THz, scheme {p.fit_scheme}, "
              f"detector {p.fit_detector}")
        print(f"  anomaly nu   {s['nu_anomaly_thz']:.1f} THz; green zone up to {s['zone_green_max_thz']:.2f} THz")
        if p.film:
            print(f"  films        {p.film.name}: K1={p.film.K1:.2f}, "
                  f"ER {p.film.er_db(0.5):.0f} dB @0.5 THz / {p.film.er_db(2.0):.0f} dB @2 THz")
        print(f"\nConfiguration: scheme {self.att.setup.scheme} ({SCHEMES[self.att.setup.scheme]})")
        print(f"  detector {self.att.setup.detector}, source {self.att.setup.source} "
              f"(psi={self.att.setup.psi_deg:g} deg, DOP={self.att.setup.dop:g})")
        print(f"  grid {self.att.freqs[0]:.2f}-{self.att.freqs[-1]:.2f} THz, {len(self.att.freqs)} points")
        print(f"  source weight: {self.att.weight_desc}")
        print(f"  mode: {'relative' if self.relative else 'absolute'}; "
              f"zero: {'not set' if self.att.zero_deg is None else f'{self.att.zero_deg:+.2f} deg'}; "
              f"current angle {self.att.theta_deg:+.2f} deg")
        if p.calibration_note:
            print(f"\n  {p.calibration_note}")

    def show_att(self, theta, integral=False):
        r = self.att.attenuation(theta, relative=self.relative, integral=integral)
        kind = "integral" if integral else "band average"
        print(f"\n  theta = {r['theta_deg']:+.2f} deg   ({kind}, "
              f"{'relative to zero' if r['relative'] else 'absolute'})")
        print(f"  ATTENUATION  {r['att_db']:.2f} dB   "
              f"[95%: {r['ci95_db'][0]:.2f} ... {r['ci95_db'][1]:.2f}]  sigma={r['sigma_db']:.2f} dB")
        print(f"  power x{r['power_ratio']:.4g}   field x{r['field_ratio']:.4g}   "
              f"ideal cos^4: {r['ideal_cos4_db']:.2f} dB")
        if r["parts"]:
            print("  uncertainty contributions (95% bounds, dB):")
            for k, (lo, hi) in r["parts"].items():
                print(f"     {k:<14} {lo:7.2f} ... {hi:7.2f}")

    def spec(self, theta):
        s = self.att.spectrum(theta, relative=self.relative)
        db, nu, z = s["att_db"], s["freq_thz"], s["zone"]
        m = z != "red"
        lo, hi = (np.nanmin(db[m]), np.nanmax(db[m])) if m.any() else (0, 1)
        title = (f"attenuation spectrum at theta = {theta:+.2f} deg "
                 f"({'relative' if self.relative else 'absolute'} mode)")
        lines = [f"  {'THz':>6} {'dB':>8} {'zone':>6} {'extra':>6} {'azim':>7} {'ellip':>7}"]
        step = max(1, len(nu) // 24)
        for i in range(0, len(nu), step):
            lines.append(f"  {nu[i]:6.2f} {db[i]:8.2f} {str(z[i]):>6} "
                         f"{'yes' if s['extrapolated'][i] else '  ':>6} "
                         f"{s['azimuth_deg'][i]:7.2f} {s['ellipticity_deg'][i]:7.2f}  "
                         f"{bar(db[i], lo, hi)}")
        if m.any():
            lines.append(f"  peak-to-peak in the applicable range: "
                         f"{db[m].max()-db[m].min():.2f} dB p-p")
        n_ex = int(s["extrapolated"].sum())
        if n_ex:
            lines.append(f"  WARNING: {n_ex} points outside the calibration band "
                         f"{self.att.passport.band_thz[0]}-{self.att.passport.band_thz[1]} THz")
        body = "\n".join(lines)
        print(f"\n  {title}\n{body}")

        # коридор 95 % по частотам — для заливки на графике
        lo_db, hi_db = [], []
        for f in nu:
            u = uncertainty(theta, self.att.passport, self.att.setup, np.array([f]),
                            ref_theta_deg=self.att.zero_deg if self.relative else None)
            lo_db.append(u.lo_db)
            hi_db.append(u.hi_db)
        dr = None
        if self.att._dr is not None:
            dr = np.atleast_1d(self.att._dr)
            dr = dr if len(dr) == len(nu) else None

        self.emit(title, body, "spectrum",
                  ascii_plot(nu, db, xlabel="frequency, THz", ylabel="attenuation, dB"),
                  {"freq_thz": nu, "att_db": db, "lo_db": lo_db, "hi_db": hi_db,
                   "zone": [str(v) for v in z],
                   "extrapolated": s["extrapolated"], "azimuth_deg": s["azimuth_deg"],
                   "ellipticity_deg": s["ellipticity_deg"]},
                  png=lambda path: plots.spectrum(
                      path, nu, db, lo_db=lo_db, hi_db=hi_db, zones=z,
                      band=self.att.passport.band_thz, extrapolated=s["extrapolated"],
                      dr_db=dr, theta_deg=theta,
                      mode="relative" if self.relative else "absolute",
                      footer=self.footer()))

    def curve(self, step=10.0):
        from .core.limits import slope_db_per_deg
        ref = self.att.zero_deg or 0.0
        th = np.arange(ref, ref + 90.0 + 1e-9, step)
        cols = {"theta_deg": [], "att_db": [], "lo_db": [], "hi_db": [],
                "ideal_cos4_db": [], "slope_db_per_deg": []}
        lines = [f"  {'theta':>7} {'model,dB':>10} {'95% interval':>18} "
                 f"{'ideal cos^4':>12} {'slope':>10}"]
        for t in th:
            r = self.att.attenuation(t, relative=True)
            ideal = float(ideal_cos4_db(t, ref))
            sl = slope_db_per_deg(t, self.att.passport, self.att.setup, self.att.freqs,
                                  ref_theta_deg=ref)
            lines.append(f"  {t:7.1f} {r['att_db']:10.2f} "
                         f"[{r['ci95_db'][0]:7.2f},{r['ci95_db'][1]:7.2f}] "
                         f"{ideal:12.2f} {sl:9.2f}/deg")
            for k, v in zip(cols, (t, r["att_db"], r["ci95_db"][0], r["ci95_db"][1],
                                   ideal, sl)):
                cols[k].append(v)
        body = "\n".join(lines)
        print("\n" + body)

        # Таблица печатается с шагом пользователя, а кривая строится на плотной
        # сетке: при шаге 10 град график получается ломаным и врёт про форму.
        fine = np.arange(ref, ref + 90.0 + 1e-9, 2.0)
        f = {"theta_deg": fine, "att_db": [], "lo_db": [], "hi_db": [],
             "ideal_cos4_db": [], "slope_db_per_deg": []}
        for t in fine:
            r = self.att.attenuation(t, relative=True)
            f["att_db"].append(r["att_db"])
            f["lo_db"].append(r["ci95_db"][0])
            f["hi_db"].append(r["ci95_db"][1])
            f["ideal_cos4_db"].append(float(ideal_cos4_db(t, ref)))
            f["slope_db_per_deg"].append(
                slope_db_per_deg(t, self.att.passport, self.att.setup,
                                 self.att.freqs, ref_theta_deg=ref))

        self.emit("angular attenuation curve", body, "curve",
                  ascii_plot(cols["theta_deg"], cols["att_db"],
                             xlabel="angle, deg", ylabel="attenuation, dB",
                             ref=cols["ideal_cos4_db"], ref_label="ideal cos^4"),
                  cols,
                  png=lambda path: plots.angular_curve(
                      path, f["theta_deg"], f["att_db"], f["ideal_cos4_db"],
                      lo_db=f["lo_db"], hi_db=f["hi_db"],
                      slope=f["slope_db_per_deg"], footer=self.footer()))

    def emit(self, title, body, slug, plot=None, cols=None, png=None):
        """Показать результат и сохранить его в папку сеанса.

        ASCII-график печатается в терминал всегда (там его и читают), а
        matplotlib-версия — если библиотека доступна: она нужна для отчётов и
        приложений к паспорту, где псевдографика неуместна.
        """
        if plot and self.ascii_plots:
            print("\n" + plot)
        if not self.sess:
            return
        self.sync_choices()
        p = self.sess.save_plot(title, (body + "\n\n" + plot) if plot else body, slug)
        if cols:
            self.sess.save_csv(slug, cols)
        saved = [f"plots/{p.name}"]
        if png is not None and plots.available():
            try:
                fig_dir = self.sess.dir / "figures"
                fig_dir.mkdir(exist_ok=True)
                out = png(fig_dir / f"{p.stem}.png")
                saved.append(f"figures/{Path(out).name}")
                self.sess.meta["artifacts"].append(
                    {"file": f"figures/{Path(out).name}", "title": title, "kind": "png"})
            except Exception as e:
                print(f"  [figure not rendered: {type(e).__name__}: {e}]")
        print(f"\n  saved: {self.sess.dir.name}/{{{', '.join(saved)}}}")

    def footer(self):
        """Подпись под графиком: без неё число в дБ не интерпретируется."""
        p, s, a = self.att.passport, self.att.setup, self.att
        return (f"{p.serial} · scheme {s.scheme} · detector {s.detector} · "
                f"scale {p.scale.division_deg:g} deg (sigma {p.scale.sigma_total_deg():.2f} deg) · "
                f"calibration band {p.band_thz[0]}-{p.band_thz[1]} THz · "
                f"zero {a.zero_deg if a.zero_deg is not None else '-'} deg · "
                f"weight {a.weight_desc} · session {self.sess.dir.name if self.sess else '-'}")

    def pol(self, theta):
        """Состояние поляризации на выходе: азимут и эллиптичность по спектру."""
        s = self.att.spectrum(theta, relative=self.relative)
        nu, az, el = s["freq_thz"], s["azimuth_deg"], s["ellipticity_deg"]
        lines = [f"  {'THz':>6} {'azim':>9} {'ellip':>9} {'zone':>7}"]
        step = max(1, len(nu) // 20)
        for i in range(0, len(nu), step):
            lines.append(f"  {nu[i]:6.2f} {az[i]:9.2f} {el[i]:9.2f} {str(s['zone'][i]):>7}")
        lines.append(f"  max |azimuth| = {np.max(np.abs(az)):.2f} deg, "
                     f"|ellipticity| = {np.max(np.abs(el)):.2f} deg")
        body = "\n".join(lines)
        print("\n  output polarization\n" + body)
        self.emit("output polarization", body, "polarization",
                  ascii_plot(nu, az, xlabel="frequency, THz", ylabel="azimuth, deg"),
                  {"freq_thz": nu, "azimuth_deg": az, "ellipticity_deg": el,
                   "zone": [str(v) for v in s["zone"]]},
                  png=lambda path: plots.polarization(
                      path, nu, az, el, zones=s["zone"],
                      band=self.att.passport.band_thz, theta_deg=theta,
                      footer=self.footer()))

    def solve(self, target, integral=False):
        sols = self.att.solve(target, integral=integral)
        if not sols:
            print(f"\n  TARGET {target:.2f} dB IS UNREACHABLE")
            th_ext, floor = self.att.auto_cross()
            print(f"  device maximum: {floor:.2f} dB at theta = {th_ext:.1f} deg")
            print("  remedies: HR-Si wafer (-3.01 dB, broadband); "
                  "grid with smaller D/P; narrow the band")
            return
        print(f"\n  solutions for target {target:.2f} dB "
              f"({'integral' if integral else 'band average'}, "
              f"scale {self.att.passport.scale.division_deg:g} deg):")
        for s in sols:
            flag = "" if abs(s.achieved_db - target) < 0.5 else "  <- scale cannot do better"
            print(f"   {s.rank}. {s}{flag}")
        best = sols[0]
        print(f"\n  RECOMMENDATION: set {best.theta_set_deg:+.2f} deg "
              f"-> {best.achieved_db:.2f} dB [95%: {best.lo_db:.2f} ... {best.hi_db:.2f}]")

    def check(self, target, theta=None):
        if theta is None:
            s = self.att.solve(target)
            theta = s[0].theta_set_deg if s else None
            if theta is not None:
                print(f"  (angle taken from the inverse-problem solution: {theta:+.2f} deg)")
        print()
        checks = self.att.checks(target, theta)
        for c in checks:
            print("  " + str(c).replace("\n", "\n  "))
        bad = [c.code for c in checks if not c.ok]
        print(f"\n  VERDICT: {'REACHABLE' if not bad else 'REFUSED by ' + ', '.join(bad)}")

    def sweep(self, targets):
        rows = self.att.sweep(targets)
        print(f"\n  level sweep (traversal by increasing angle, no reversals)")
        print(f"  {'target,dB':>9} {'theta':>8} {'got,dB':>9} {'95% interval':>20} {'slope':>10}")
        for t, s in rows:
            if s is None:
                print(f"  {t:9.1f} {'--':>8} {'UNREACHABLE':>9}")
            else:
                print(f"  {t:9.1f} {s.theta_set_deg:8.2f} {s.achieved_db:9.2f} "
                      f"  [{s.lo_db:7.2f} ...{s.hi_db:7.2f}] {s.slope_db_per_deg:9.2f}")

    def plan(self, target):
        sols = self.att.solve(target)
        if not sols:
            print("  unreachable - see solve")
            return
        s = sols[0]
        print(f"\n  PLAN for {target:.2f} dB:")
        for c in self.att.motion_plan(s):
            print("   " + c.as_operator_instruction())
        print(f"   expected attenuation {s.achieved_db:.2f} dB "
              f"[95%: {s.lo_db:.2f} ... {s.hi_db:.2f}]")
        self.att.apply(s)
        print(f"   current angle is now {self.att.theta_deg:+.2f} deg")

    # -- цикл ----------------------------------------------------------
    def run(self):
        print(f"THz Attenuator CLI  (passport {self.att.passport.serial}).  "
              f"help - command list, q - quit")
        while True:
            try:
                line = input("\natt> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if self.sess:
                self.sess.log(line)
            try:
                res = self.dispatch(shlex.split(line))
                self.sync_choices()
                if res is False:
                    if self.sess:
                        self.sess.close()
                        print(f"  session saved: {self.sess.dir}")
                    return
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                if "--debug" in sys.argv:
                    traceback.print_exc()

    def dispatch(self, argv):
        c, a = argv[0].lower(), argv[1:]
        A, S = self.att, self.att.setup

        if c in ("q", "quit", "exit"):
            return False
        elif c in ("help", "?", "h"):
            print(HELP)
        elif c == "dev":
            self.dev()
        elif c == "scheme":
            if a:
                S.scheme = a[0].upper(); S.validate(); print(f"  scheme {S.scheme}: {SCHEMES[S.scheme]}")
            else:
                for k, v in SCHEMES.items():
                    print(f"  {k}: {v}")
        elif c == "det":
            if a:
                S.detector = a[0].lower(); S.validate(); print(f"  {DETECTORS[S.detector]}")
            else:
                for k, v in DETECTORS.items():
                    print(f"  {k}: {v}")
        elif c == "src":
            if a:
                S.source = a[0].lower(); S.validate(); print(f"  {SOURCES[S.source]}")
            else:
                for k, v in SOURCES.items():
                    print(f"  {k}: {v}")
        elif c == "psi":
            S.psi_deg = float(a[0]); print(f"  psi = {S.psi_deg:g} deg")
        elif c == "dop":
            S.dop = float(a[0]); S.validate(); print(f"  DOP = {S.dop:g}")
        elif c == "band":
            n = int(a[2]) if len(a) > 2 else 128
            A.freqs = np.linspace(float(a[0]), float(a[1]), n)
            A.weight = None; A.weight_desc = "not set (grid changed)"
            print(f"  grid {A.freqs[0]:.3f}-{A.freqs[-1]:.3f} THz, {n} points")
        elif c == "w":
            kind = a[0].lower()
            if kind == "preset":
                lo, hi = A.set_weight("preset", name=a[1] if len(a) > 1 else "pca")
            elif kind == "flat":
                lo, hi = A.set_weight("flat", f1=float(a[1]), f2=float(a[2]))
            elif kind == "gauss":
                lo, hi = A.set_weight("gauss", nu0=float(a[1]), dnu=float(a[2]))
            elif kind == "bg":
                lo, hi = A.set_weight("bg_file", path=a[1])
            else:
                print(f"  presets: {list(PRESETS)}"); return
            print(f"  weight: {A.weight_desc}; effective band {lo:.2f}-{hi:.2f} THz")
        elif c == "bg":
            dr = A.load_background(a[0])
            print("  DR undefined (no high-frequency tail)" if dr is None
                  else f"  setup dynamic range: min {dr:.1f} dB over the grid")
        elif c == "zero":
            z = A.set_zero(float(a[0]) if a else None)
            print(f"  SET ZERO: reference angle {z:+.2f} deg, 0 dB by definition")
        elif c == "autozero":
            z = A.auto_zero(); print(f"  AUTO-ZERO: transmission maximum at {z:+.2f} deg")
        elif c == "autocross":
            th, fl = A.auto_cross()
            d = abs(th - (A.zero_deg or 0.0))
            print(f"  AUTO-CROSS: extinction at {th:.2f} deg, floor {fl:.2f} dB")
            print(f"  distance from zero {d:.2f} deg"
                  + ("" if abs(d - 90) <= 2 else
                     f"  <- differs from 90 by {d-90:+.1f} deg: misalignment or non-Malus behavior"))
        elif c == "set":
            A.theta_deg = float(a[0]); print(f"  current angle {A.theta_deg:+.2f} deg")
        elif c == "mode":
            self.relative = a[0].lower().startswith("rel")
            print(f"  mode: {'relative' if self.relative else 'absolute'}")
        elif c == "a":
            self.show_att(float(a[0]) if a else A.theta_deg)
        elif c == "ai":
            self.show_att(float(a[0]) if a else A.theta_deg, integral=True)
        elif c == "spec":
            self.spec(float(a[0]) if a else A.theta_deg)
        elif c == "ascii":
            self.ascii_plots = not a or a[0].lower() in ("on", "1", "yes")
            print(f"  ASCII plots in terminal: {'on' if self.ascii_plots else 'off'}"
                  + ("" if plots.available() else "  (matplotlib unavailable!)"))
        elif c == "pol":
            self.pol(float(a[0]) if a else A.theta_deg)
        elif c == "curve":
            self.curve(float(a[0]) if a else 10.0)
        elif c == "solve":
            self.solve(float(a[0]), integral=("-i" in a))
        elif c == "check":
            self.check(float(a[0]), float(a[1]) if len(a) > 1 else None)
        elif c == "sweep":
            self.sweep([float(x) for x in ",".join(a).replace(";", ",").split(",") if x])
        elif c == "plan":
            self.plan(float(a[0]))
        else:
            print(f"  unknown command {c!r}; help - command list")
        return True


def main():
    ap = argparse.ArgumentParser(description="THz attenuator - interactive calculator")
    ap.add_argument("--passport", default=str(DEFAULT_PASSPORT))
    ap.add_argument("--scheme", default=None)
    ap.add_argument("--detector", default=None)
    ap.add_argument("--runs", default=None, help="root of session folders (default ./runs)")
    ap.add_argument("--tag", default="", help="session folder name suffix")
    ap.add_argument("--no-session", action="store_true", help="do not keep a session folder")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    p = Passport.load(args.passport)
    att = Attenuator(p)
    if args.scheme:
        att.setup.scheme = args.scheme.upper()
    if args.detector:
        att.setup.detector = args.detector
    att.setup.validate()
    att.set_zero(0.0)

    sess = None if args.no_session else Session(args.runs, args.tag)
    if sess:
        print(f"session: {sess.dir}")
    Shell(att, sess).run()


if __name__ == "__main__":
    main()
