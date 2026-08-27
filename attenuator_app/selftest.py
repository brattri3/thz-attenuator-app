"""Приёмочные проверки физики. Запуск:

    .venv\\Scripts\\python.exe -m attenuator_app.selftest

Часть проверок перенесена из research/two_wgp/model_2wgp.py:selftest() —
там они уже прошли 10/10 на исследовательской модели.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .api import Attenuator
from .core import blanco
from .core.forward import Setup, attenuation_db, intensity, ideal_cos4_db
from .core.passport import Passport, Param, ScaleSpec

HERE = Path(__file__).resolve().parent
RESULTS: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def ideal_passport(ideal=True):
    """Прибор с идеальными элементами (t_perp = 1, t_par = 0)."""
    return Passport(serial="IDEAL", ideal_elements=ideal,
                    P_um=Param(15.5, 0.0, "fixed"),
                    D_eff_um=Param(4.48, 0.0, "fixed"), D_phys_um=11.0,
                    loss_factor=Param(0.0, 0.0, "fixed"),
                    gamma=Param(2.0, 0.0, "fixed"), gamma_range=(2.0, 2.0),
                    tau_ps=Param(0.0, 0.0, "fixed"),
                    tau_par_ps=Param(0.0, 0.0, "fixed"),
                    angle_offset_deg=Param(0.0, 0.0, "fixed"),
                    band_thz=(0.2, 1.5), scale=ScaleSpec(1.0, 0.0), film=None)


def main():
    print("=== attenuator_app: acceptance checks ===\n")
    nu = np.linspace(0.2, 1.5, 24)
    th = np.linspace(0, 90, 46)

    # 1. Идеальный предел -> закон cos^4.
    #    Элементы идеализированы (t_perp=1, t_par=0), поэтому совпадение точное;
    #    у РЕАЛЬНОЙ решётки пол задаётся утечкой и от полюса cos^4 отходит
    #    (см. проверку F2).
    p = ideal_passport()
    s = Setup(scheme="S0", detector="coherent", use_film=False)
    th_id = np.linspace(0, 85, 36)
    db, _ = attenuation_db(th_id, nu, p, s, ref_theta1_deg=0.0)
    err = float(np.max(np.abs(db.mean(axis=1) - ideal_cos4_db(th_id, 0.0))))
    check("ideal limit = cos^4 (S0, ideal elements)", err < 1e-9,
          f"max |dA| = {err:.4f} dB")

    # 2. Энергия не растёт: |E_out|^2 <= |E_in|^2
    worst = 0.0
    for P, D in [(15.5, 4.48), (15.5, 11.0), (38.8, 18.0), (24.9, 14.0)]:
        pp = ideal_passport()
        pp.P_um, pp.D_eff_um = Param(P, 0, "fixed"), Param(D, 0, "fixed")
        I, _ = intensity(th, nu, pp, Setup(scheme="S0", detector="power", use_film=False))
        worst = max(worst, float(I.max()))
    check("energy conservation in S0", worst <= 1.0 + 1e-9, f"max |E_out|^2 = {worst:.6f}")

    # 3. Относительный режим НЕ зависит от рассеяния (loss, gamma сокращаются)
    #    — ключевое физическое утверждение docs/attenuator_app/02_SCENARIOS.md §2.2
    att = Attenuator.from_passport(HERE / "passports" / "SAMPLE.json")
    att.set_zero(0.0)
    base = att.attenuation(60, relative=True)["att_db"]
    hold = att.passport.loss_factor.value, att.passport.gamma.value
    att.passport.loss_factor = Param(hold[0] * 4 + 1.0, 0.0, "fixed")
    att.passport.gamma = Param(3.0, 0.0, "fixed")
    alt = att.attenuation(60, relative=True)["att_db"]
    att.passport.loss_factor = Param(hold[0], 0.0, "fixed")
    att.passport.gamma = Param(hold[1], 0.0, "fixed")
    check("relative mode does not depend on loss/gamma",
          abs(base - alt) < 1e-9, f"|dA| = {abs(base-alt):.2e} dB")

    # 4. Абсолютный режим ЗАВИСИТ от рассеяния (иначе п.3 был бы тривиален)
    a1 = att.attenuation(60, relative=False)["att_db"]
    att.passport.loss_factor = Param(hold[0] * 4 + 1.0, 0.0, "fixed")
    a2 = att.attenuation(60, relative=False)["att_db"]
    att.passport.loss_factor = Param(hold[0], 0.0, "fixed")
    check("absolute mode depends on loss (non-degeneracy of check 3)",
          abs(a1 - a2) > 0.5, f"|dA| = {abs(a1-a2):.3f} dB")

    # 5. Мощностной детектор в S0 на 45 град даёт ровно на 3 дБ меньше
    att.setup = Setup(scheme="S0", detector="coherent", use_film=False)
    c45 = att.attenuation(45, relative=True)["att_db"]
    att.setup = Setup(scheme="S0", detector="power", use_film=False)
    p45 = att.attenuation(45, relative=True)["att_db"]
    check("S0: power vs coherent at 45 deg = 3 dB",
          abs((c45 - p45) - 3.0) < 0.15, f"difference {c45-p45:.3f} dB")

    # 6. Теорема выравнивания: второй WGP вдоль оси детектора почти ничего не меняет
    att.setup = Setup(scheme="S0", detector="coherent", use_film=False)
    a_one = att.attenuation(45, relative=True)["att_db"]
    att.setup = Setup(scheme="S1", detector="coherent", use_film=False)
    a_two = att.attenuation(45, relative=True)["att_db"]
    check("alignment theorem: S1 == S0 with aligned axis",
          abs(a_one - a_two) < 0.05, f"difference {a_two-a_one:+.4f} dB")

    # 7. Обратная задача обращает прямую
    att.setup = Setup(scheme="S3", detector="coherent")
    att.set_zero(0.0)
    errs = []
    for t in (10.0, 30.0, 55.0, 70.0):
        target = att.attenuation(t, relative=True)["att_db"]
        sols = att.solve(target, snap=False)
        if sols:
            errs.append(min(abs(s.theta_deg - t) for s in sols))
    check("inverse(forward(theta)) == theta", errs and max(errs) < 0.05,
          f"max |dtheta| = {max(errs):.4f} deg" if errs else "no solutions")

    # 8. Пол затухания конечен и лежит НЕ на 90 град ровно
    th_ext, floor = att.auto_cross()
    check("attenuation floor is finite", 10.0 < floor < 80.0,
          f"{floor:.2f} dB at theta = {th_ext:.2f} deg")

    # 9. Крутизна растёт с углом (обоснование проверки F4)
    from .core.limits import slope_db_per_deg
    sl = [slope_db_per_deg(t, att.passport, att.setup, att.freqs, ref_theta_deg=0.0)
          for t in (30, 50, 70, 85)]
    check("slope dA/dtheta grows monotonically", all(np.diff(sl) > 0),
          " -> ".join(f"{x:.2f}" for x in sl) + " dB/deg")

    # 10. Экстраполяция расширяет интервал неопределённости
    from .core.limits import uncertainty
    u_in = uncertainty(60, att.passport, att.setup, np.array([1.0]), ref_theta_deg=0.0)
    u_out = uncertainty(60, att.passport, att.setup, np.array([4.0]), ref_theta_deg=0.0)
    check("interval widens outside the calibration band",
          u_out.sigma_db > u_in.sigma_db,
          f"sigma {u_in.sigma_db:.3f} -> {u_out.sigma_db:.3f} dB")

    # 10b. Интервал ОБЯЗАН содержать само показываемое значение.
    #      Регрессия: uncertainty() считала по первой частоте, а attenuation()
    #      усредняла по полосе -> при 90 град интервал не содержал значение.
    bad = []
    for t in (0.0, 30.0, 60.0, 85.0, 90.0, 95.0):
        r = att.attenuation(t, relative=True)
        lo, hi = r["ci95_db"]
        if not (lo - 1e-9 <= r["att_db"] <= hi + 1e-9):
            bad.append((t, r["att_db"], lo, hi))
    check("95 % interval contains the value itself", not bad,
          "all angles" if not bad else f"violated at theta = {[b[0] for b in bad]}")

    # 11. Софт-клип ограничивает степенной закон и непрерывен
    f_lo, f_hi = 0.2, 1.5
    x = np.linspace(1.0, 40.0, 400)
    y = blanco.soft_clip(x, f_hi, f_lo, "soft")
    check("soft clip is bounded and monotonic",
          y.max() < 6 * f_hi and np.all(np.diff(y) >= -1e-12),
          f"nu 40 THz -> nu_eff {y[-1]:.2f} THz")

    # 12. Кэш Бланко работает
    blanco.clear_cache()
    for _ in range(5):
        blanco.blanco_t(nu, 15.5, 4.48)
    st = blanco.cache_stats()
    check("Blanco cache", st["hits"] == 4 and st["misses"] == 1, str(st))

    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n=== {len(RESULTS)-len(bad)}/{len(RESULTS)} passed ===")
    if bad:
        print("FAILED: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
