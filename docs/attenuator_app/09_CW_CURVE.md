# 09 — CW angular curve (`attenuator_app.cw_curve`)

Non-interactive CLI command: one invocation renders a single PNG with the angular
dependence of attenuation **A(θ)** for a **monochromatic continuous-wave (CW)**
source at one frequency. It is a thin assembly layer over the existing client
core (`attenuator_app/core/*`, `attenuator_app/api.py`) — **no new physics**. The
interactive `cli.py` is untouched.

Bench-side calibration for the CW application — which of the two rotators to
sweep, what each sweep reveals about the source azimuth and the mount offsets,
and where the setup saturates — is in
[`12_BENCH_CALIBRATION.md`](12_BENCH_CALIBRATION.md).

## Run

From the repository root:

```
python -m attenuator_app.cw_curve --freq 0.2 --detector coherent --analyzer H
python -m attenuator_app.cw_curve --detector power --source depolarized --out out.png
python -m attenuator_app.cw_curve --selftest        # numeric self-check, no PNG
```

Default passport: `attenuator_app/passports/SAMPLE.json` — the same
default the interactive `cli.py` uses (`DEFAULT_PASSPORT`).

## Arguments

| flag | default | meaning |
|---|---|---|
| `--freq` | `0.2` | CW frequency, THz. A length-1 frequency grid **is** the CW case. |
| `--detector` | `coherent` | receiver type — see toggle 1 below. |
| `--source` | `linear` | generator type — see toggle 2 below. |
| `--analyzer` | `H` | analyzer axis for the coherent detector: `H`, `V`, or an angle in degrees. |
| `--src-deg` | `0.0` | linear-source azimuth (0 = horizontal, matching the passport). |
| `--theta-min` / `--theta-max` | `-90` / `+90` | angular sweep bounds, degrees. |
| `--theta-step` | `1.0` | sweep step, degrees. |
| `--mode` | `relative` | `relative` (referenced to `--ref-deg`) or `absolute` (referenced to unit input). |
| `--ref-deg` | `0.0` | reference angle for relative mode. |
| `--slope` | off | add a `|dA/dθ|` slope panel (default: off, per owner). |
| `--out` | auto | output PNG path. |
| `--passport` | shipped default | device passport JSON. |
| `--selftest` | — | run numeric invariants and exit (no PNG). |

## The two independent physical toggles

These are **two separate knobs** (owner requirement, 2026-08-22): the receiver and
the generator are set independently, giving four combinations.

### 1. Detector — `--detector` (already in `core/forward.py`)

* `coherent` — polarization-**sensitive** receiver (photoconductive antenna, EO
  sampling). It projects the **field** onto the analyzer axis `--analyzer`, so the
  analyzer orientation matters.
* `power` — polarization-**insensitive** receiver (bolometer, pyroelectric, Golay
  cell). It sums the total power of both components; the analyzer axis is ignored.

### 2. Source — `--source` (reuses the existing DOP mechanism)

* `linear` — linearly polarized generator, degree of polarization DOP = 1, azimuth
  `--src-deg`.
* `depolarized` — unpolarized / depolarized generator, DOP = 0.

Implemented by **reusing** `Setup.dop` and the unpolarized branch of
`forward.intensity()` (`I = dop·one(ψ) + (1-dop)·½[one(ψ)+one(ψ+90°)]`):
`linear → dop=1.0`, `depolarized → dop=0.0`. No new physics was written; the
existing degree-of-polarization machinery was sufficient.

### Analyzer presets (coherent detector only)

* `H` — horizontal, aligned with the (horizontal) source → detector axis `0°`.
* `V` — vertical, crossed with the source → detector axis `90°`.
* `<number>` — arbitrary analyzer axis, in degrees.

## Two-rotator angle convention

The device is **two** wire-grid polarizers, both mountable in rotators. Per the
passport `calibration_note`: the **first** WGP is aligned with the beam
polarization (θ₁ = 0), the **second** (analyzer) rotates, and attenuation is set
by the **relative angle θ = θ₂ − θ₁**. The swept variable in this command is that
relative angle θ.

The calibrated optical scheme in the passport is **S0** (a single rotating WGP
followed by the coherent detector). The alignment theorem — proved numerically in
`selftest` check 6, "S1 == S0 with aligned axis" — makes S0 equivalent to the
two-WGP stack S1 when the fixed polarizer is aligned with the coherent detector
axis. The command therefore uses `passport.fit_scheme` (S0) and sweeps θ, exactly
reproducing the main app's `curve` command.

This convention (sweep the relative angle, first polarizer fixed at the source
axis) is a **reasonable default** taken directly from the passport + code. It is
recorded as non-blocking question `C-7` in `coordination/QUESTIONS.md` for owner
confirmation.

## What the four combinations look like (physics)

At small/mid angles the finite-extinction leakage floor is negligible and the
curves follow analytic laws (verified in `--selftest`):

| detector | source | analyzer | law near θ=0 | note |
|---|---|---|---|---|
| coherent | linear | H (aligned) | `−40·log₁₀|cosθ|` (cos⁴) | classic extinction curve, deep at ±90° |
| coherent | linear | V (crossed) | extinction **at** θ=0 | use `--mode absolute` (θ=0 is the minimum) |
| power | linear | — | `−20·log₁₀|cosθ|` (cos², Malus) | half of the cos⁴ ideal, in dB |
| power | depolarized | — | flat, 0 dB | rotational invariance: unpolarized light through one grid is angle-independent |
| coherent | depolarized | H | `−20·log₁₀|cosθ|` (cos²) | depolarization removes one Malus factor |

The dashed grey "ideal cos⁴ limit" on every plot is the coherent-aligned ideal
reference (`forward.ideal_cos4_db`); for the power/crossed/depolarized cases the
device curve sits below it, which is expected and informative.

## Self-check

`python -m attenuator_app.cw_curve --selftest` runs five numeric invariants
(power=Malus cos², coherent-H=cos⁴, coherent-V=extinction at the cross,
depolarized+power=flat, and CW-point==broadband-spectrum-at-same-frequency). It is
independent of and does not touch `attenuator_app/selftest.py` (still 13/13).

Example PNGs: `research/results/cw_attenuator/`.
