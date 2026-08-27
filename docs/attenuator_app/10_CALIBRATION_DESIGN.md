# 10 — Instrument calibration algorithm (DESIGN-ONLY)

**Status: design note / pseudocode. NOT implemented.** The bench-side part of
this note is developed into a concrete procedure in
[`12_BENCH_CALIBRATION.md`](12_BENCH_CALIBRATION.md) (owner's own setup as the
worked example); the dynamic-range reasoning below remains the source. Scope: how one would
calibrate the CW angular attenuation of the two-WGP attenuator on a real bench,
how the setup's **dynamic range (DR)** limits deep-extinction measurements, and
how DR is itself determined during the same procedure. No code is added by this
note; it is a specification for a future task.

## 1. What "calibration" means here

Two goals, kept separate:

1. **Angle zero (θ₀ / SET ZERO).** Find the mechanical reading at which the two
   grids are co-aligned (maximum transmission). The scale reading there is θ₀; all
   attenuation is quoted relative to it. This already exists as a manual step
   (`api.Attenuator.set_zero` / `auto_zero`); calibration here means *measuring* θ₀
   physically rather than assuming the scale is honest.
2. **Attenuation transfer curve A(θ).** A table of measured attenuation versus
   relative angle, to be compared against the model `forward.attenuation_db`. The
   residuals (measured − model) validate the passport and expose leakage, tilt of
   a fixed element, and reflections.

## 2. Standard angle/value set on the measuring instrument

The operator records, at each set angle θ_i, the instrument reading R_i (lock-in
amplitude, spectrometer peak, or power meter value — all reduce to a transmitted
power P_i after squaring/averaging). A **standard grid** balances coverage against
bench time:

```
coarse  θ = 0, ±10, ±20, ±30, ±40, ±50, ±60            # shape of the curve
fine    θ = ±70, ±75, ±80, ±85, ±88, ±90               # where slope |dA/dθ| is large
repeat  N_rep >= 3 full sweeps                          # session spread -> sigma
```

Rationale for the non-uniform grid: `|dA/dθ|` grows monotonically with angle
(`selftest` check 9), so a fixed angular error costs many more dB near the cross.
The fine grid is placed exactly where the curve is steep and where DR runs out.
`N_rep ≥ 3` because the passport uncertainties come from *between-session spread*,
not one fit's covariance (see `STATE.md`, "two key decisions").

```
measure_curve(angles, N_rep):
    for rep in 1..N_rep:
        for theta in angles:
            set_scale(theta)                 # manual rotator, division = passport.scale
            P[rep, theta] = read_instrument() # transmitted power (bg-subtracted)
    return P
```

## 3. Zero and normalization

```
theta0 = argmax_theta  mean_rep P[:, theta]        # co-aligned position
P0     = P[:, theta0]                               # reference power
A_meas(theta) = -10 * log10( P[:, theta] / P0 )    # dB, power, relative mode
sigma_A(theta) = spread over reps (std / sqrt(N_rep) or full-range/2, conservative)
```

The fit/validation then compares `A_meas(theta)` to `forward.attenuation_db(theta,
freqs=[f_cw], passport, setup, ref_theta1_deg=theta0)` and reports residual
statistics (bias, RMSE, residuals-vs-angle for structure). This mirrors the
existing `tools/validate.py` acceptance (69/69), but for the CW single-frequency
case instead of the broadband fit.

## 4. Dynamic range (DR) — the hard part

At deep extinction the transmitted power P(θ) drops toward the **noise/leakage
floor of the whole setup**, not toward zero. Beyond that floor the instrument
reads noise, and the measured A(θ) *saturates* and then becomes meaningless — you
cannot measure 60 dB of extinction with a setup that only has 40 dB of DR.

### 4.1 Determining DR during calibration

DR is measured in the same session, at no extra hardware cost:

```
# (a) blocked / dark reading: shutter closed or beam blocked
P_dark = read_instrument()                 # additive noise floor of detector+electronics

# (b) reference reading at co-alignment
P0 = mean_rep P[:, theta0]                 # brightest achievable through the device

DR_db = 10 * log10( P0 / P_dark )          # setup dynamic range, dB (power)
```

`P_dark` is the same quantity `api.Attenuator.load_background` /
`limits.dynamic_range_db` already consume from a background TDS scan; for a CW
power meter it is simply the blocked-beam reading. A conservative DR uses the
*standard deviation* of the dark reading rather than its mean, to leave margin.

### 4.2 Using DR to guard deep-extinction points

```
for theta in angles:
    A_i   = -10*log10(P_i / P0)
    A_cap = DR_db - MARGIN_DB               # MARGIN_DB ~ 3..6 dB headroom
    if A_i >= A_cap or P_i <= K * P_dark:   # K ~ 3 (3-sigma above the floor)
        flag(theta, "beyond dynamic range - lower bound only")
        A_i = A_cap                          # report as ">= A_cap", not a point value
```

Points flagged this way are **lower bounds**, not measurements: the true
extinction is at least `A_cap` but the setup cannot resolve it. On the plot they
would be drawn distinctly (e.g. down-arrows at the DR ceiling), analogous to how
`core/plots.py` already draws a "setup dynamic range" reference line on the
spectrum. The model's own finite floor (`auto_cross`, ~40 dB for this passport)
should be *compared against* DR: if the model floor is below `A_cap`, the deep
angles are genuinely unmeasurable on this bench and must be quoted as bounds.

### 4.3 Extending DR (options to note, not to auto-apply)

* **Averaging / longer integration** raises `P0/P_dark` by ~`10·log10(√N_avg)`.
* **Reference attenuator swap**: measure the bright half of the curve at low
  source power, the dark half at full power, and stitch with a known offset — the
  classic "two-range" trick. Requires a calibrated source-power ratio.
* **Crossed-analyzer subtraction** of the coherent leakage term (only meaningful
  for `detector=coherent`), using the fitted `t_par` leakage from the passport.

## 5. Output of the calibration

```
calibration_result = {
    "theta0_deg": theta0,  "sigma_theta0_deg": ...,
    "A_meas": [(theta, A, sigma_A, flag), ...],
    "DR_db": DR_db,  "P_dark": P_dark,  "N_rep": N_rep,
    "residual_stats": {bias, rmse, structure_test},   # vs forward model
    "freq_thz": f_cw,
}
```

This feeds a future passport update (`tools/make_passport.py` is the analogous
offline step for the broadband fit) and lets the CW curve command draw a measured
overlay with an explicit DR ceiling.

## 6. Open questions (see `coordination/QUESTIONS.md`)

* `C-8` — is the ≥3-repeat between-session spread the right σ source for CW, or
  should DR-limited points use a different treatment?
* `C-9` — the MARGIN_DB / K thresholds above are placeholders pending a real bench.
