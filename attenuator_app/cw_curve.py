"""CW (continuous-wave) angular attenuation curve — non-interactive CLI.

One command -> one PNG with the angular dependence of attenuation A(theta) for a
MONOCHROMATIC continuous-wave source at a single frequency. This is a thin
assembly layer over the existing CLIENT CORE (`attenuator_app.core.*`,
`attenuator_app.api`): no new physics is introduced here.

Run from the repository root:

    python -m attenuator_app.cw_curve --freq 0.2 --detector coherent --analyzer H
    python -m attenuator_app.cw_curve --detector power --source depolarized --out /tmp/x.png
    python -m attenuator_app.cw_curve --selftest        # numeric self-check, no PNG

Two INDEPENDENT physical toggles (owner requirement 2026-08-22):

  1. DETECTOR (`--detector`):
       coherent  polarization-SENSITIVE receiver (photoconductive antenna, EO
                 sampling). Has an analyzer axis `--analyzer`; projects the FIELD.
       power     polarization-INSENSITIVE receiver (bolometer, pyroelectric,
                 Golay cell). Sums the total power of both components; the
                 analyzer axis is ignored.

  2. SOURCE (`--source`):
       linear       linearly polarized generator (DOP = 1), azimuth `--src-deg`.
       depolarized  unpolarized / depolarized generator (DOP = 0).
     Implemented by REUSING the existing degree-of-polarization mechanism
     (`Setup.dop` + the unpolarized branch of `forward.intensity()`); no new
     physics — linear -> dop=1.0, depolarized -> dop=0.0.

Analyzer presets for the sensitive detector (`--analyzer`):
       H   horizontal, aligned with the (horizontal) source  -> det axis 0 deg
       V   vertical, crossed with the source                 -> det axis 90 deg
       <number>  arbitrary analyzer axis in degrees

Two-rotator angle convention (see docs/attenuator_app/09_CW_CURVE.md and the
passport calibration_note). The device is TWO wire-grid polarizers: the first is
aligned with the beam polarization (theta1 = 0), the second (analyzer) rotates;
attenuation is set by the RELATIVE angle theta = theta2 - theta1. The calibrated
scheme is S0 (single rotating WGP + coherent detector), which the alignment
theorem (`selftest` check 6, S1==S0 with aligned axis) makes equivalent to the
two-WGP stack. The swept variable here is that relative angle theta, matching the
main app's `curve` command exactly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from .core.forward import (Setup, attenuation_db, ideal_cos4_db)
from .core.passport import Passport
from .core import plots

HERE = Path(__file__).resolve().parent
DEFAULT_PASSPORT = HERE / "passports" / "SAMPLE.json"

# Analyzer-axis presets, in degrees relative to the (horizontal) source axis.
ANALYZER_PRESETS = {"H": 0.0, "V": 90.0}


# ---------------------------------------------------------------------------
def _analyzer_deg(value: str) -> float:
    """Parse --analyzer: preset H/V or an arbitrary angle in degrees."""
    key = value.strip().upper()
    if key in ANALYZER_PRESETS:
        return ANALYZER_PRESETS[key]
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"analyzer must be H, V, or an angle in degrees, got {value!r}")


def build_setup(passport: Passport, *, detector: str, source: str,
                det_deg: float, src_deg: float) -> Setup:
    """Assemble a Setup from the two independent toggles. No new physics."""
    dop = 1.0 if source == "linear" else 0.0
    src_key = "linear" if source == "linear" else "unpolarized"
    setup = Setup(scheme=passport.fit_scheme, detector=detector, source=src_key,
                  psi_deg=src_deg, dop=dop, det_deg=det_deg)
    setup.validate()
    return setup


def compute_curve(passport: Passport, setup: Setup, freq_thz: float,
                  theta: np.ndarray, *, mode: str = "relative",
                  ref_deg: float = 0.0):
    """A(theta) at a single CW frequency. Returns (att_db, ideal_db).

    A length-1 frequency grid IS the CW case: attenuation is computed per
    frequency, so one frequency = the monochromatic value at that frequency.
    """
    freqs = np.array([float(freq_thz)], dtype=float)
    ref = None if mode == "absolute" else float(ref_deg)
    db, _clipped = attenuation_db(theta, freqs, passport, setup,
                                  ref_theta1_deg=ref)
    att = db[:, 0]
    ideal = ideal_cos4_db(theta, ref_deg if mode == "relative" else 0.0)
    return att, ideal


def _default_out(detector: str, source: str, analyzer: str, freq_thz: float) -> str:
    key = analyzer.strip().upper()
    if key in ANALYZER_PRESETS:
        ana = key
    else:
        d = float(analyzer)
        ana = f"{'m' if d < 0 else 'p'}{abs(d):.0f}deg"
    ghz = int(round(freq_thz * 1000))
    return f"cw_{detector}_{source}_{ana}_{ghz}GHz.png"


# ---------------------------------------------------------------------------
def render(args) -> Path:
    passport = Passport.load(args.passport)
    det_deg = _analyzer_deg(args.analyzer)
    setup = build_setup(passport, detector=args.detector, source=args.source,
                        det_deg=det_deg, src_deg=args.src_deg)

    theta = np.arange(args.theta_min, args.theta_max + args.theta_step / 2.0,
                      args.theta_step)
    att, ideal = compute_curve(passport, setup, args.freq, theta,
                               mode=args.mode, ref_deg=args.ref_deg)

    if not plots.available():
        raise RuntimeError("matplotlib is required for PNG output "
                           "(install matplotlib); nothing was written")

    out = Path(args.out) if args.out else Path(
        _default_out(args.detector, args.source, args.analyzer, args.freq))
    out.parent.mkdir(parents=True, exist_ok=True)

    analyzer_txt = (f"analyzer {args.analyzer.upper()} ({det_deg:+.0f} deg)"
                    if args.detector == "coherent" else "analyzer n/a (power)")
    footer = (f"CW {args.freq:.3f} THz · {args.detector} detector · "
              f"{args.source} source · {analyzer_txt} · {args.mode} mode · "
              f"passport {passport.serial}")

    slope = None
    if args.slope:
        with np.errstate(invalid="ignore"):
            slope = np.gradient(att, theta)

    plots.angular_curve(out, theta, att, ideal, slope=slope, footer=footer,
                        mode=args.mode)
    return out


# ---------------------------------------------------------------------------
def selfcheck() -> int:
    """Numeric invariants for the CW curve. No PNG, no file I/O.

    Reuses the shipped default passport. Reference laws hold in the reliable
    angular region where the finite-extinction leakage floor is negligible.
    """
    print("=== attenuator_app.cw_curve: self-check ===\n")
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))

    p = Passport.load(DEFAULT_PASSPORT)
    freq = 0.2
    theta = np.arange(-90.0, 90.0 + 0.5, 1.0)
    mid = np.abs(theta) <= 60.0
    midc = np.abs(theta) <= 45.0

    def curve(detector, source, det_deg, mode="relative", ref_deg=0.0):
        s = build_setup(p, detector=detector, source=source,
                        det_deg=det_deg, src_deg=0.0)
        att, ideal = compute_curve(p, s, freq, theta, mode=mode, ref_deg=ref_deg)
        return att, ideal

    # 1. Insensitive (power) + linear -> Malus cos^2 law: A = -20*log10|cos|.
    #    That is exactly HALF (in dB) of the coherent-aligned cos^4 ideal.
    att, ideal = curve("power", "linear", 0.0)
    err1 = float(np.max(np.abs(att[mid] - 0.5 * ideal[mid])))
    check("power + linear = Malus cos^2 (= 0.5 x ideal cos^4)", err1 < 0.3,
          f"max |dA| = {err1:.4f} dB over |theta|<=60")

    # 2. Sensitive (coherent) + analyzer H (aligned) + linear -> cos^4 ideal.
    att, ideal = curve("coherent", "linear", ANALYZER_PRESETS["H"])
    err2 = float(np.max(np.abs(att[midc] - ideal[midc])))
    a0 = float(att[np.argmin(np.abs(theta))])
    check("coherent + analyzer H + linear = ideal cos^4", err2 < 0.5 and abs(a0) < 1e-6,
          f"max |dA| = {err2:.4f} dB over |theta|<=45, A(0) = {a0:.2e} dB")

    # 3. Sensitive + analyzer V (crossed) + linear -> extinction AT the cross
    #    (theta=0), absolute mode so theta=0 is not the reference itself.
    att, _ = curve("coherent", "linear", ANALYZER_PRESETS["V"], mode="absolute")
    a0 = float(att[np.argmin(np.abs(theta))])
    a45 = float(att[np.argmin(np.abs(theta - 45.0))])
    check("coherent + analyzer V = deep extinction at theta=0 (cross)",
          a0 > a45 + 10.0, f"A(0) = {a0:.2f} dB, A(45) = {a45:.2f} dB")

    # 4. Depolarized + power -> rotationally invariant, flat 0 dB (relative).
    #    Unpolarized light through a single element transmits |a|^2+|b|^2
    #    independent of angle -> the relative curve is exactly flat.
    att, _ = curve("power", "depolarized", 0.0)
    err4 = float(np.max(np.abs(att)))
    check("depolarized + power = flat (rotational invariance)", err4 < 1e-6,
          f"max |A| = {err4:.2e} dB over the full sweep")

    # 5. CW single-point value == broadband spectrum sampled at the same freq.
    s = build_setup(p, detector="coherent", source="linear",
                    det_deg=ANALYZER_PRESETS["H"], src_deg=0.0)
    freqs_bb = np.linspace(0.05, 2.0, 40)          # contains 0.2 exactly? -> nearest
    idx = int(np.argmin(np.abs(freqs_bb - freq)))
    f_on_grid = float(freqs_bb[idx])
    theta5 = np.array([0.0, 20.0, 45.0, 70.0])
    db_bb, _ = attenuation_db(theta5, freqs_bb, p, s, ref_theta1_deg=0.0)
    db_cw, _ = attenuation_db(theta5, np.array([f_on_grid]), p, s, ref_theta1_deg=0.0)
    err5 = float(np.max(np.abs(db_bb[:, idx] - db_cw[:, 0])))
    check("CW point == broadband spectrum at the same frequency", err5 < 1e-9,
          f"max |dA| = {err5:.2e} dB at {f_on_grid:.4f} THz")

    bad = [n for n, ok, _ in results if not ok]
    print(f"\n=== {len(results) - len(bad)}/{len(results)} passed ===")
    if bad:
        print("FAILED: " + ", ".join(bad))
    return 1 if bad else 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m attenuator_app.cw_curve",
        description="CW angular attenuation curve -> PNG (non-interactive).")
    ap.add_argument("--passport", default=str(DEFAULT_PASSPORT),
                    help="device passport JSON (default: shipped ATT-11-16-CA85 (образец))")
    ap.add_argument("--freq", type=float, default=0.2,
                    help="CW frequency, THz (default: 0.2)")
    ap.add_argument("--detector", choices=("coherent", "power"), default="coherent",
                    help="receiver type: coherent = polarization-sensitive "
                         "(has analyzer), power = insensitive (default: coherent)")
    ap.add_argument("--source", choices=("linear", "depolarized"), default="linear",
                    help="generator type (default: linear)")
    ap.add_argument("--analyzer", default="H",
                    help="analyzer axis for the coherent detector: H, V, or an "
                         "angle in degrees (default: H)")
    ap.add_argument("--src-deg", type=float, default=0.0,
                    help="linear source azimuth, degrees (default: 0 = horizontal)")
    ap.add_argument("--theta-min", type=float, default=-90.0,
                    help="sweep start, degrees (default: -90)")
    ap.add_argument("--theta-max", type=float, default=90.0,
                    help="sweep end, degrees (default: +90)")
    ap.add_argument("--theta-step", type=float, default=1.0,
                    help="sweep step, degrees (default: 1.0)")
    ap.add_argument("--mode", choices=("relative", "absolute"), default="relative",
                    help="relative (referenced to --ref-deg) or absolute "
                         "(referenced to unit input) (default: relative)")
    ap.add_argument("--ref-deg", type=float, default=0.0,
                    help="reference angle for relative mode, degrees (default: 0)")
    ap.add_argument("--slope", action="store_true",
                    help="add a |dA/dtheta| slope panel (default: off)")
    ap.add_argument("--out", default=None,
                    help="output PNG path (default: auto-named in the CWD)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the numeric self-check and exit (no PNG)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selfcheck()
    out = render(args)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
