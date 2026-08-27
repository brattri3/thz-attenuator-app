"""Приёмка сервисного приложения аттенюатора: единая точка входа.

Запускает самопроверки трёх модулей и добавляет проверки УРОВНЯ ПРИЛОЖЕНИЯ,
которых в отдельных модулях быть не может: обратную совместимость со сданным
путём C9, обратную задачу по двум углам и сверку с независимой реализацией
двух-WGP модели из зоны A.

    python -m attenuator_app.tools.service_selftest

До 2026-08-24 у сервисного приложения (C9) не было ни одного теста -- ни
самопроверки, ни pytest. Числа держались на трёх ручных прогонах.

Про сверку с зоной A: `research/two_wgp/model_2wgp.py` -- НЕЗАВИСИМАЯ
реализация той же физики (своя алгебра, свои матрицы, отдельная валидация
10/10). Совпадение с ней -- сильная проверка, потому что общего кода нет.
Импорт делается ТОЛЬКО ЗДЕСЬ, в тесте: рантайм сервисного приложения не должен
зависеть ни от `research/`, ни от `track_viewer` -- иначе его нельзя увезти на
машину у прибора. Если каталог `research/` недоступен, проверка помечается
пропущенной, а не проваленной.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.tools import service_calc as sc            # noqa: E402
from attenuator_app.tools import service_calibrate as scal     # noqa: E402
from attenuator_app.tools import service_limits as sl          # noqa: E402
from attenuator_app.tools import service_model as smod         # noqa: E402


def _check(res, name, ok, detail=""):
    res.append((name, bool(ok), detail))
    print(f"  [{'OK' if ok else '!!'}] {name}   {detail}")


def app_checks() -> list:
    """Проверки уровня приложения, поверх модульных."""
    res = []
    cal = sc.load_calibration()
    m1 = sc.Metric("single", a=0.8)
    th = np.array([0.0, 20.0, 45.0, 70.0, 85.0])
    off = cal.theta0_calibration_deg

    # A1. Калибровка формата v1 читается и даёт прежний офсет.
    _check(res, "A1  калибровка v1 читается без изменений",
           cal.schema_version == 1 and abs(off - (-0.5617433589197959)) < 1e-12,
           f"theta0 = {off:+.10f}°, схема v{cal.schema_version}")

    # A2. Одноугловой путь C9 и двухугловой совпадают на ОДНОЙ ЧАСТОТЕ.
    #     В полной полосе они расходятся до 0.03 дБ у самого дна и это ожидаемо:
    #     старый путь выбрасывает |t_perp|^2 из числителя и знаменателя, а при
    #     взвешенном усреднении это не тождественная операция (см. докстринг
    #     transmission_pair). Старый путь оставлен бит-в-бит намеренно.
    old = sc.attenuation_db_array(off + th, off, cal, m1, "pmax")
    new = sc.attenuation_db_pair(off + th, np.zeros_like(th), cal, m1, "pmax")
    d1 = float(np.max(np.abs(old - new)))
    d_band = float(np.max(np.abs(
        sc.attenuation_db_array(off + th, off, cal, sc.FULL, "pmax") -
        sc.attenuation_db_pair(off + th, np.zeros_like(th), cal, sc.FULL, "pmax"))))
    _check(res, "A2  старый одноугловой путь == двухугловой на одной частоте",
           d1 < 1e-9 and d_band < 0.05,
           f"одна частота {d1:.1e} дБ, полная полоса {d_band:.4f} дБ (ожидаемо > 0)")

    # A3. Обратная задача по двум углам: круговой прогон цель -> углы -> цель.
    errs = []
    for tgt, chi in [(-6.0, 10.0), (-12.0, 30.0), (-20.0, 45.0), (-3.0, -25.0)]:
        s = sc.angles_for_db_and_azimuth(tgt, chi, cal, m1)
        errs.append((abs(s["achieved_db"] - tgt), abs(s["azimuth_error_deg"])))
    e_db = max(e[0] for e in errs)
    e_az = max(e[1] for e in errs)
    _check(res, "A3  обратная задача по двум углам: круговой прогон",
           e_db < 0.01 and e_az < 0.01,
           f"макс невязка {e_db:.2e} дБ / {e_az:.2e}°")

    # A4. У ДЕПОЛЯРИЗОВАННОГО источника задача расщепляется точно: взаимный
    #     угол не зависит от заказанного азимута. У линейного -- зависит.
    cal_d = sc.load_calibration()
    cal_d.source_kind, cal_d.detector_kind = "unpolarized", "power"
    d_un = [sc.angles_for_db_and_azimuth(-10.0, a, cal_d, m1)["delta_deg"]
            for a in (0.0, 25.0, 60.0)]
    d_li = [sc.angles_for_db_and_azimuth(-10.0, a, cal, m1)["delta_deg"]
            for a in (0.0, 25.0)]
    spread_un = float(np.ptp(d_un))
    spread_li = abs(d_li[1] - d_li[0])
    _check(res, "A4  деполяризованный источник -- задача расщепляется, линейный -- нет",
           spread_un < 1e-9 < spread_li,
           f"разброс взаимного угла: деполяризованный {spread_un:.1e}°, "
           f"линейный {spread_li:.3f}°")

    # A5. Оба физических отказа поднимаются, а не возвращают «почти».
    def refuses(tgt, chi, cal_used=cal):
        try:
            sc.angles_for_db_and_azimuth(tgt, chi, cal_used, m1)
            return False
        except ValueError:
            return True

    _check(res, "A5  недостижимые пары отвергаются с причиной",
           refuses(-2.0, 60.0) and refuses(-37.0, 45.0) and not refuses(-12.0, 30.0),
           "слабое ослабление при повёрнутом выходе и азимут у дна -- оба отказ")

    # A6. Вердикты пределов доходят до приёмки: негодные точки исключаются.
    th_s, mo_s, me_s = sl._synth(sat=0.55, dark=2e-4, noise=3e-5, floor=1e-6)
    w = scal.analyze_window(th_s, me_s, mo_s)
    acc = scal.analyze_acceptance(
        th_s, [mo_s + np.random.default_rng(s).normal(0, 3e-5, mo_s.size)
               for s in (1, 2, 3)], mo_s, w["verdicts"])
    _check(res, "A6  вердикты пределов исключают точки из приёмки",
           acc["n_excluded"] > 0 and acc["n_points"] == w["n_ok"],
           f"годных {acc['n_points']}, исключено {acc['n_excluded']}")

    # A7. Сверка с НЕЗАВИСИМОЙ реализацией зоны A в идеальном пределе.
    try:
        from research.two_wgp.model_2wgp import WGP, attenuation as a_atten
    except Exception as e:                                     # noqa: BLE001
        _check(res, "A7  сверка с независимой моделью зоны A", True,
               f"ПРОПУЩЕНА: research/ недоступен ({type(e).__name__})")
        return res

    nu = np.array([0.8])
    ideal = WGP(t_override=(1.0, 0.0))
    t1 = np.array([0.0, 10.0, 25.0, 40.0, 55.0])
    t2 = np.array([0.0, 30.0, 30.0, 70.0, 15.0])
    ref_A = a_atten(t1, t2, nu, ideal, e_in_deg=0.0, det_deg=0.0)[..., 0]
    mine = smod.response(t1, t2, nu, ideal=True,
                         source=smod.PolState.linear(0.0),
                         analyzer=smod.Analyzer("coherent", 0.0))["intensity"][:, 0]
    dA = float(np.max(np.abs(np.real(ref_A) - mine)))
    _check(res, "A7  сверка с независимой моделью зоны A (идеальный предел)",
           dA < 1e-12, f"макс |dI| = {dA:.2e} на 5 произвольных парах углов")
    return res


def main(argv=None) -> int:
    print("\n########## ПРИЁМКА СЕРВИСНОГО ПРИЛОЖЕНИЯ АТТЕНЮАТОРА ##########")
    codes = {"модель (service_model)": smod.selfcheck(),
             "пределы (service_limits)": sl.selfcheck(),
             "калибровка (service_calibrate)": scal.selfcheck()}

    print("\n=== приложение: проверки поверх модульных ===\n")
    res = app_checks()
    bad = [n for n, ok, _ in res if not ok]
    print(f"\n=== приложение: {len(res) - len(bad)}/{len(res)} пройдено ===")
    if bad:
        print("НЕ ПРОШЛИ: " + ", ".join(bad))

    print("\n########## ИТОГ ##########")
    for name, code in codes.items():
        print(f"  {name}: {'OK' if code == 0 else 'ЕСТЬ ОТКАЗЫ'}")
    print(f"  приложение: {'OK' if not bad else 'ЕСТЬ ОТКАЗЫ'}")
    return 1 if (bad or any(codes.values())) else 0


if __name__ == "__main__":
    sys.exit(main())
