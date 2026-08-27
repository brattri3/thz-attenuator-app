# -*- coding: utf-8 -*-
"""Приёмка расчётного слоя CW-приложения. Без Qt, без окна, только числа.

Проверяет ровно то, что ломается при передаче параметров из интерфейса в ядро:
перепутанные углы, потерянная нормировка, не доехавший тип источника. Физику
сверять незачем -- она проверена приёмкой сервисного ядра
(`attenuator_app.tools.service_selftest`); здесь проверяется обвязка.

Ни одного `unittest.mock`: импортируются ровно те модули, что уйдут в .exe.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe -m attenuator_app.cwapp.selftest
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.tools.service_calc import (           # noqa: E402
    Metric, attenuation_db_pair, load_calibration)
from attenuator_app.cwapp.model import CwModel, CwResult, theta_grid   # noqa: E402
from attenuator_app.cwapp.state import (                  # noqa: E402
    CwParams, disabled_reason, enabled_fields, passport_candidates, program_dir)


def _check(res: list, name: str, ok: bool, note: str = "") -> None:
    res.append(bool(ok))
    print(("  [OK] " if ok else "  [FAIL] ") + name + (("   " + note) if note else ""))


def selfcheck() -> int:                                    # noqa: C901
    res: list[bool] = []
    print("=== CW-приложение: расчётный слой ===\n")

    # M1. Числа совпадают с прямым вызовом ядра -- обвязка ничего не считает.
    m = CwModel()
    p = CwParams(freq_thz=0.200, theta1_deg=30.0, theta2_deg=0.0)
    r = m.compute(p)
    cal = load_calibration()
    cal.off1_deg = cal.off2_deg = 0.0
    cal.source_kind, cal.source_psi_deg, cal.source_dop = "linear", 0.0, 1.0
    cal.detector_kind, cal.detector_axis_deg = "coherent", 0.0
    metric = Metric("single", a=0.200)
    ref = float(attenuation_db_pair(np.array([0.0]), np.array([0.0]), cal, metric, "pmax")[0])
    want = float(attenuation_db_pair(np.array([30.0]), np.array([0.0]),
                                     cal, metric, "pmax")[0]) - ref
    _check(res, "M1  значение в точке == прямой вызов ядра",
           abs(r.value_db - want) < 1e-12, "%.6f dB" % r.value_db)

    # M2. Нормировка при psi = 0: максимум стоит в нуле обеих шкал, поэтому
    # там ровно 0 дБ и 100 %. После решения П-2 (опора -- максимум, а не отсчёт
    # при theta = 0) это уже НЕ определение опоры, а её следствие: проверка
    # осталась зелёной именно потому, что при неповёрнутом источнике максимум
    # и нуль шкал совпадают. Случай psi != 0 разбирают M18…M20.
    r0 = m.compute(CwParams(theta1_deg=0.0, theta2_deg=0.0))
    _check(res, "M2  нормировка: (0, 0) даёт 0 дБ и 100 %",
           abs(r0.value_db) < 1e-12 and abs(r0.value_percent - 100.0) < 1e-9,
           "%.3e dB, %.6f %%" % (r0.value_db, r0.value_percent))

    # M3. Сечения проходят через точку: два графика согласованы между собой.
    th = list(theta_grid())
    i1, i2 = th.index(30.0), th.index(0.0)
    r = m.compute(CwParams(theta1_deg=30.0, theta2_deg=0.0))
    _check(res, "M3  оба сечения проходят через одну точку",
           abs(r.vs_theta1_db[i1] - r.value_db) < 1e-12
           and abs(r.vs_theta2_db[i2] - r.value_db) < 1e-12,
           "%.6f / %.6f dB" % (r.vs_theta1_db[i1], r.vs_theta2_db[i2]))

    # M4. Углы не перепутаны местами: у когерентного приёмника вращение WGP1
    #     даёт cos^4, вращение WGP2 -- cos^2, вдвое по децибелам.
    rp = m.compute(CwParams(theta1_deg=0.0, theta2_deg=0.0, detector="power"))
    a45_1 = float(rp.vs_theta1_db[th.index(45.0)])
    a45_2 = float(rp.vs_theta2_db[th.index(45.0)])
    _check(res, "M4  вращение WGP1 вдвое глубже вращения WGP2 (cos^4 / cos^2)",
           abs(a45_1 / a45_2 - 2.0) < 5e-3,
           "%.3f / %.3f dB, отношение %.4f" % (a45_1, a45_2, a45_1 / a45_2))

    # M5. Тип источника доезжает до ядра. Проверяется расщеплением задачи:
    #     у ДЕПОЛЯРИЗОВАННОГО источника результат зависит только от взаимного
    #     угла, у линейного -- ещё и от их положения относительно азимута.
    #     (Инвариант «плоская кривая» верен для ОДНОГО поляризатора, здесь их
    #     два, и он не применим -- ошибка в первой редакции этой проверки.)
    def at(a, b, src):
        return m.compute(CwParams(theta1_deg=float(a), theta2_deg=float(b),
                                  source=src, detector="power")).value_db

    same = [at(a, b, "unpolarized") for a, b in ((0, 45), (20, 65), (-30, 15))]
    spread_dep = max(same) - min(same)
    spread_lin = abs(at(0, 45, "linear") - at(20, 65, "linear"))
    _check(res, "M5  деполяризованный источник расщепляет задачу, линейный -- нет",
           spread_dep < 1e-9 and spread_lin > 0.1,
           "разброс при равной разности углов: деполяризованный %.1e dB, "
           "линейный %.3f dB" % (spread_dep, spread_lin))

    # M6. Проценты и децибелы -- одна величина в двух видах.
    r = m.compute(CwParams(theta1_deg=30.0, theta2_deg=0.0))
    back = 10.0 * np.log10(r.value_percent / 100.0)
    _check(res, "M6  проценты обратимы в децибелы",
           abs(back - r.value_db) < 1e-12, "%.4f %%" % r.value_percent)

    # M7. Цена ошибки угла: у первого угла вдвое больше, чем у второго,
    #     и обе стороны имеют разные знаки (точка не в экстремуме).
    e1 = max(abs(x) for x in r.err_theta1_db)
    e2 = max(abs(x) for x in r.err_theta2_db)
    _check(res, "M7  ошибка 1 град по WGP1 примерно вдвое дороже, чем по WGP2",
           abs(e1 / e2 - 2.0) < 0.15,
           "%.4f / %.4f dB, отношение %.3f; совместно ±%.4f dB"
           % (e1, e2, e1 / e2, r.combined_error_db))

    # M8. Мусор отвергается с внятным текстом, а не считается.
    bad = [("частота 0", CwParams(freq_thz=0.0)),
           ("частота < 0", CwParams(freq_thz=-1.0)),
           ("угол вне диапазона", CwParams(theta1_deg=120.0)),
           ("неизвестный источник", CwParams(source="magic")),
           ("неизвестный приёмник", CwParams(detector="magic")),
           ("DOP вне 0..1", CwParams(source="partial", dop=1.7))]
    caught = []
    for note, params in bad:
        try:
            m.compute(params)
            caught.append(note)
        except ValueError:
            pass
    _check(res, "M8  негодные параметры отвергаются", not caught,
           "прошло молча: " + ", ".join(caught) if caught else "все шесть случаев")

    # M9. Матрица гашения полей -- чистая функция, проверяется без окна.
    cases = [
        (CwParams(detector="power"), "analyzer_deg", False),
        (CwParams(detector="coherent"), "analyzer_deg", True),
        (CwParams(source="unpolarized"), "psi_deg", False),
        (CwParams(source="linear"), "psi_deg", True),
        (CwParams(source="linear"), "dop", False),
        (CwParams(source="partial"), "dop", True),
    ]
    wrong = [(p.source, p.detector, f) for p, f, want in cases
             if (f in enabled_fields(p)) is not want]
    _check(res, "M9  матрица гашения полей", not wrong, str(wrong) if wrong else "6/6")

    # M10. У каждого погашенного поля есть объяснение в терминах физики.
    missing = [f for p, f, want in cases
               if not want and not disabled_reason(p, f)]
    _check(res, "M10 у погашенного поля есть причина", not missing,
           str(missing) if missing else "все объяснены")

    # M11. Расчётный слой не тянет Qt: приёмка обязана идти без него.
    qt = [name for name in sys.modules if name.startswith(("PySide6", "PyQt"))]
    _check(res, "M11 расчётный слой не импортирует Qt", not qt, str(qt) if qt else "чисто")

    # M12. Предупреждение о выходе за полосу калибровки.
    m.compute(CwParams(freq_thz=0.140))
    out_of_band = m.band_warning()
    m.compute(CwParams(freq_thz=0.800))
    in_band = m.band_warning()
    _check(res, "M12 частота вне полосы помечается как экстраполяция",
           out_of_band is not None and in_band is None,
           (out_of_band or "").split(" — ")[0])

    # M13. Порядок поиска паспорта: явный выбор идёт первым, дальше каталог
    # рядом с программой -- сначала подкаталог `passports/`, затем сам каталог.
    base = Path(tempfile.mkdtemp())
    try:
        (base / "passports").mkdir()
        (base / "passports" / "b.json").write_text("{}", encoding="utf-8")
        (base / "a.json").write_text("{}", encoding="utf-8")
        order = [c.name for c in passport_candidates("explicit.json", base=base)]
        _check(res, "M13 порядок поиска паспорта: явный, passports/, рядом",
               order == ["explicit.json", "b.json", "a.json"], str(order))

        # M14. Ловушка PyInstaller. «Рядом с программой» под сборкой -- это
        # каталог `sys.executable`, а НЕ каталог `__file__`: последний
        # указывает во временный `_MEIPASS`, паспорт оператора там не лежит
        # никогда, и приложение молча считает по зашитому образцу. Из
        # исходников дефект не проявляется вовсе -- отсюда поддельный frozen.
        meipass = Path(tempfile.mkdtemp())
        sys.frozen = True                                  # как под PyInstaller
        exe_before = sys.executable
        sys.executable = str(base / "cwapp.exe")
        try:
            frozen_dir = program_dir()
            frozen_seen = [c.name for c in passport_candidates()]
        finally:
            sys.executable = exe_before
            del sys.frozen
            shutil.rmtree(meipass, ignore_errors=True)
        _check(res, "M14 «рядом с программой» под сборкой -- каталог .exe, не _MEIPASS",
               frozen_dir == base and frozen_seen == ["b.json", "a.json"],
               "%s -> %s" % (frozen_dir.name, frozen_seen))

        # M15. Явно выбранный негодный файл отказывает ГРОМКО, а найденный
        # рядом -- пропускается. Тихая подмена выбранного паспорта образцом
        # даёт неверные числа при внешне исправном окне.
        wrong = base / "wrong.json"
        wrong.write_text('{"hello": 1}', encoding="utf-8")
        try:
            CwModel(wrong)
            loud = False
        except ValueError:
            loud = True
        quiet = CwModel(calibration_path=None)
        _check(res, "M15 явный негодный паспорт -- отказ, найденный рядом -- пропуск",
               loud and quiet.cal.device_id == "SAMPLE",
               "отказ: %s, без выбора: %s" % (loud, quiet.cal.device_id))

        # M16. Годный паспорт рядом с программой действительно берётся, и в
        # строке состояния видно, какой файл взят.
        cal_src = json.loads((REPO / "attenuator_app" / "tools" / "calibration"
                              / "SAMPLE.json").read_text(encoding="utf-8"))
        cal_src["device_id"] = "UNIT-TEST"
        chosen = base / "unit.json"
        chosen.write_text(json.dumps(cal_src), encoding="utf-8")
        m4 = CwModel(chosen)
        _check(res, "M16 выбранный паспорт взят и назван в строке состояния",
               m4.cal.device_id == "UNIT-TEST" and "unit.json" in m4.device_line(),
               m4.device_line())
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # M17. Зашитый образец -- последний рубеж, и он назван образцом вслух:
    # на нём можно считать, но нельзя измерять.
    fallback = CwModel()
    _check(res, "M17 без паспорта берётся образец и он назван образцом",
           fallback.cal.device_id == "SAMPLE" and "SAMPLE" in fallback.passport_note,
           fallback.passport_note)

    # M18. Нормировка на максимум: НИ ОДНО значение не превышает 0 дБ ни при
    # каком азимуте источника. До решения П-2 опора стояла в нуле шкал, и при
    # psi = 45° кривая поднималась до +2.11 дБ, то есть «пропускание 163 %».
    worst = []
    for psi in (0.0, 10.0, 20.0, 45.0, -37.0, 90.0):
        r = m.compute(CwParams(freq_thz=0.9, source="linear", psi_deg=psi,
                               detector="coherent"))
        top = max(float(np.max(r.vs_theta1_db)), float(np.max(r.vs_theta2_db)),
                  r.value_db)
        worst.append((psi, top))
    over = [(psi, top) for psi, top in worst if top > 1e-9]
    _check(res, "M18 нормировка на максимум: выше 0 дБ не поднимается ни при каком psi",
           not over, "худший подъём %+.2e дБ при psi = %+.0f°"
           % max(worst, key=lambda t: t[1])[::-1])

    # M19. Максимум ДОСТИГАЕТСЯ, а не только не превышается: при psi = 45°
    # опора стоит не в нуле шкал, и ровно 0 дБ обязано где-то найтись.
    p45 = CwParams(freq_thz=0.9, source="linear", psi_deg=45.0,
                   detector="coherent")
    m.compute(p45)
    at = m.reference_at()
    # ноль ищется В ТОЧКЕ максимума, а не в сечении: сечение идёт при
    # закреплённом theta2, и через максимум поверхности оно проходит лишь
    # тогда, когда закреплённый угол сам равен максимуму
    here = m.compute(p45.with_(theta1_deg=at[0], theta2_deg=at[1])).value_db
    at_zero = m.compute(p45.with_(theta1_deg=0.0, theta2_deg=0.0)).value_db
    _check(res, "M19 при psi = 45° опора уехала с нуля шкал и достигается",
           at is not None and abs(at[0]) > 1.0 and abs(here) < 1e-9 and at_zero < -0.5,
           "максимум %+.2e дБ в (%+.2f, %+.2f), в нуле шкал %+.3f дБ"
           % (here, at[0], at[1], at_zero) if at else "опора не найдена")

    # M20. Опора не зависит от того, какие углы выставлены сейчас: она берётся
    # по всей поверхности. Опора «по текущему сечению» ездила бы вверх-вниз при
    # каждом движении второго ротатора, и кривая ползала бы сама по себе.
    p_a = CwParams(freq_thz=0.9, source="linear", psi_deg=30.0,
                   detector="coherent", theta1_deg=0.0, theta2_deg=0.0)
    probe = p_a.with_(theta1_deg=12.0, theta2_deg=-3.0)
    m.compute(p_a)
    peak_a, val_a = m.reference_at(), m.compute(probe).value_db
    # заходим в ту же пробную точку издалека: если бы опора считалась по
    # текущему сечению, показание в одной и той же точке зависело бы от того,
    # где ротаторы стояли до неё
    m.compute(p_a.with_(theta1_deg=-70.0, theta2_deg=55.0))
    peak_b, val_b = m.reference_at(), m.compute(probe).value_db
    _check(res, "M20 опора не зависит от выставленных углов",
           peak_a == peak_b and abs(val_a - val_b) < 1e-12,
           "опора (%+.2f, %+.2f) в обоих случаях, показание в пробной точке "
           "%+.4f дБ, расхождение %.1e дБ"
           % (peak_a[0], peak_a[1], val_a, abs(val_a - val_b))
           if peak_a else "опора не найдена")

    # M21. При psi = 0 новая опора совпадает со старой до последнего знака:
    # прежние протоколы и опорная точка сверки с CLI не тронуты сменой
    # конвенции. Старая опора -- прямой вызов ядра в нуле шкал.
    p0 = CwParams(freq_thz=0.8, theta1_deg=40.0, theta2_deg=0.0, source="linear",
                  psi_deg=0.0, detector="coherent")
    r_new = m.compute(p0)
    cal_old = load_calibration()
    cal_old.off1_deg = cal_old.off2_deg = 0.0
    cal_old.source_kind, cal_old.source_psi_deg, cal_old.source_dop = "linear", 0.0, 1.0
    cal_old.detector_kind, cal_old.detector_axis_deg = "coherent", 0.0
    met = Metric("single", a=0.8)
    old_ref = float(attenuation_db_pair(np.array([0.0]), np.array([0.0]),
                                        cal_old, met, "pmax")[0])
    old_val = float(attenuation_db_pair(np.array([40.0]), np.array([0.0]),
                                        cal_old, met, "pmax")[0]) - old_ref
    _check(res, "M21 при psi = 0 смена опоры не сдвинула ни одного числа",
           abs(r_new.value_db - old_val) < 1e-12,
           "%+.4f dB против прежних %+.4f dB (опорная точка CLI -4.77 дБ)"
           % (r_new.value_db, old_val))

    ok, total = sum(res), len(res)
    print("\n=== %d/%d пройдено ===" % (ok, total))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(selfcheck())
