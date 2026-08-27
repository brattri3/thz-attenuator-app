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

import sys
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
    CwParams, disabled_reason, enabled_fields)


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

    # M2. Нормировка: в нуле обоих шкал ровно 0 дБ и 100 %.
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

    ok, total = sum(res), len(res)
    print("\n=== %d/%d пройдено ===" % (ok, total))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(selfcheck())
