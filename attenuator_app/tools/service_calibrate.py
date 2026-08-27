"""Калибровка аттенюатора оператором: пять процедур на живом стенде.

Что это
-------
Приложение C9 брало все параметры схемы из зашитого JSON и постулировало
лабораторную раму нулями: азимут источника 0, ось приёмника 0, WGP2 в нуле
своей шкалы. Когда оба поляризатора стоят в ротаторах и «крутят руками по
обстановке» (владелец, 2026-08-24), эти нули взять неоткуда -- их надо мерить.
Здесь собраны процедуры, которые оператор физически проделывает на стенде, и
разбор их результатов.

    П0  тёмный отсчёт            -> уровень и разброс шума
    П1  относительный ноль       -> взаимный офсет шкал WGP1 и WGP2
    П2  лабораторная рама        -> азимут источника psi и ось приёмника d
    П3  границы рабочего окна    -> зашкал и граница чувствительности
    П4  приёмка                  -> статистика остатков и sigma по прогонам

Почему базис 4-го порядка, а не 3-параметрический Малюс
-------------------------------------------------------
П1 и П2 достают углы из ФАЗЫ гармоник. Схема складывает поля и лишь потом
берёт квадрат модуля, поэтому точный базис пятимерный:

    U(t) = c0 + a2 cos2t + b2 sin2t + a4 cos4t + b4 sin4t

Учебная 3-параметрическая форма верна для интенсивностной (некогерентной)
композиции и здесь систематически неверна. В этом проекте цена уже измерена
дважды: смещение углового офсета до -12.6 град и экстинкция 17.06 дБ вместо
28.20 (`track_viewer/core/fit_malus.py`, `docs/track_viewer/01_FORMATS.md`
§6.3). Подгонка линейна по коэффициентам, поэтому решается одним нормальным
уравнением -- без итераций, стартовой точки и мультистарта.

Метод выведен сессией A (`research/two_wgp/NOTE_malus_linearization.md`); здесь
он реализован ЗАНОВО в минимальном виде, а не импортирован: рантайм сервисного
приложения не должен зависеть ни от `track_viewer`, ни от `research/` -- тот же
принцип изоляции, по которому написан `service_calc`.

Две независимые оценки угла и зачем они
---------------------------------------
Офсет достаётся и из 2-й гармоники, и из 4-й. Это две НЕЗАВИСИМЫЕ оценки одной
величины: они обязаны совпасть, и расхождение -- бесплатная проверка на угловую
систематику. Сравнение делается по модулю 45 град, потому что 4-я гармоника
определяет угол лишь с точностью до четверти периода.

Запуск из корня репозитория:
    python -m attenuator_app.tools.service_calibrate --plan     # что делать руками
    python -m attenuator_app.tools.service_calibrate --demo     # разбор на синтетике
    python -m attenuator_app.tools.service_calibrate --selftest # проверки
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.tools import service_limits as sl          # noqa: E402
from attenuator_app.tools import service_model as sm           # noqa: E402

#: минимум различимых углов для устойчивой подгонки пятимерного базиса
MIN_ANGLES = 5


# --- гармонический базис ----------------------------------------------
def harmonic_fit(theta_deg, y, order: int = 4) -> dict:
    """Линейная подгонка U(t) в гармоническом базисе; замкнутое решение.

    `order=4` -- точный базис для когерентной схемы (5 коэффициентов),
    `order=2` -- учебная форма (3 коэффициента), оставлена только для
    демонстрации ловушки, рабочим режимом не является.
    """
    t = np.deg2rad(np.asarray(theta_deg, dtype=float))
    y = np.asarray(y, dtype=float)
    if t.size != y.size:
        raise ValueError("углы и показания должны быть одной длины")
    if np.unique(np.round(t, 9)).size < MIN_ANGLES:
        raise ValueError(f"нужно хотя бы {MIN_ANGLES} различных углов, "
                         f"есть {np.unique(np.round(t, 9)).size}")
    cols = [np.ones_like(t), np.cos(2 * t), np.sin(2 * t)]
    if order == 4:
        cols += [np.cos(4 * t), np.sin(4 * t)]
    X = np.column_stack(cols)
    p, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ p
    out = {"c0": float(p[0]), "a2": float(p[1]), "b2": float(p[2]),
           "a4": float(p[3]) if order == 4 else 0.0,
           "b4": float(p[4]) if order == 4 else 0.0,
           "resid_rms": float(np.sqrt(np.mean(resid ** 2))),
           "cond": float(np.linalg.cond(X.T @ X)), "order": order,
           "n": int(t.size)}
    out["amp2"] = float(np.hypot(out["a2"], out["b2"]))
    out["amp4"] = float(np.hypot(out["a4"], out["b4"]))
    #: положение максимума 2-й гармоники -- основная оценка угла
    out["angle_h2_deg"] = float(np.degrees(np.arctan2(out["b2"], out["a2"])) / 2.0)
    #: независимая оценка по 4-й гармонике, определена по модулю 45 град
    out["angle_h4_deg"] = float(np.degrees(np.arctan2(out["b4"], out["a4"])) / 4.0)
    d = (out["angle_h4_deg"] - out["angle_h2_deg"] + 22.5) % 45.0 - 22.5
    out["angle_discrepancy_deg"] = float(d)
    return out


# --- П0: тёмный отсчёт --------------------------------------------------
def analyze_dark(readings) -> dict:
    """Уровень и разброс шума по отсчётам с перекрытым пучком."""
    r = np.asarray(readings, dtype=float)
    if r.size < 5:
        raise ValueError(f"тёмных отсчётов {r.size}, нужно хотя бы 5")
    return {"dark_level": float(r.mean()),
            "dark_sigma": float(r.std(ddof=1)),
            "n": int(r.size)}


# --- П1: относительный ноль --------------------------------------------
def _pair_from_fit(f: dict) -> dict:
    """Неупорядоченная пара осей из гармоник для отклика cos^2(a-X) cos^2(a-Y).

    Фаза 4-й гармоники даёт полусумму осей, отношение амплитуд -- модуль
    полуразности. Годится и для П1 (пара «ось WGP1, ось приёмника»), и для П2
    (пара «азимут источника, ось приёмника»): функциональная форма одна и та же.
    """
    if f["amp4"] <= 0.0:
        raise ValueError("4-я гармоника нулевая: прогон не несёт информации об осях")
    half_sum = f["angle_h4_deg"]
    c = float(np.clip(f["amp2"] / (4.0 * f["amp4"]), 0.0, 1.0))
    half_diff = float(np.degrees(np.arccos(c)) / 2.0)
    return {"half_sum_deg": float(half_sum), "half_difference_deg": half_diff,
            "pair_deg": (float(half_sum - half_diff), float(half_sum + half_diff)),
            "cos_difference": c,
            "aligned": bool(half_diff < 1.0),
            #: у совмещённых осей arccos вырожден -- разность недостоверна,
            #: и порознь называть углы нельзя, только их полусумму
            "difference_reliable": bool(c < 0.999)}


def analyze_relative_zero(theta2_deg, measured, theta1_fixed_deg: float = 0.0,
                          detector_kind: str = "coherent") -> dict:
    """Взаимный офсет шкал: при каком показании WGP2 его ось совпала с WGP1.

    WGP1 стоит неподвижно, вращается WGP2, ищется максимум пропускания.
    Минимум обязан лежать на 90 град от максимума; отклонение больше 2 град
    означает перекос или не-Малюсову асимметрию (у образца Specac измерено
    ~6 град) и служит поводом остановиться, а не продолжать калибровку.

    ⚠ КОГДА МАКСИМУМ НЕ ЕСТЬ СОВМЕЩЕНИЕ. У КОГЕРЕНТНОГО приёмника отклик при
    вращении WGP2 идёт как

        I ~ cos^2(a - ось WGP1) * cos^2(a - ось приёмника)

    -- второй множитель даёт проекция поля на анализатор. Если ось приёмника не
    совпадает с осью WGP1, максимум лежит РОВНО ПОСЕРЕДИНЕ между ними, а не на
    совмещении, и наивный `argmax` даёт смещённый ноль. Проверено на синтетике:
    при оси WGP1 в нуле и приёмнике под 12 град максимум встаёт на 6.00 град.

    Поэтому из того же прогона достаётся и НЕУПОРЯДОЧЕННАЯ ПАРА осей
    {ось WGP1, ось приёмника} (`pair_deg`), а флаг `max_is_alignment` говорит,
    можно ли доверять максимуму как совмещению. У мощностного приёмника
    анализатора нет, второго множителя тоже, и максимум всегда есть совмещение.
    """
    f = harmonic_fit(theta2_deg, measured, order=4)
    th_max = f["angle_h2_deg"]
    delta0 = _wrap180(th_max - float(theta1_fixed_deg))
    th = np.asarray(theta2_deg, dtype=float)
    me = np.asarray(measured, dtype=float)
    emp_max = float(th[np.argmax(me)])
    emp_min = float(th[np.argmin(me)])

    # Разнос минимума и максимума считается по ПОДОГНАННОЙ кривой, а не по
    # сырым argmax/argmin. У дна кривая почти плоская, и на реальном шаге шкалы
    # сырой argmin гуляет на единицы градусов -- проверка ловила бы шум, а не
    # асимметрию. Подгонка использует все точки; при этом ровно 90 град разнос
    # даёт только чистая 2-я гармоника, а не-Малюсова асимметрия сидит в 4-й и
    # разнос сдвигает -- то есть проверка остаётся содержательной.
    grid = np.linspace(-90.0, 90.0, 3601)
    t = np.deg2rad(grid)
    curve = (f["c0"] + f["a2"] * np.cos(2 * t) + f["b2"] * np.sin(2 * t)
             + f["a4"] * np.cos(4 * t) + f["b4"] * np.sin(4 * t))
    fit_max, fit_min = float(grid[np.argmax(curve)]), float(grid[np.argmin(curve)])
    sep = abs(_wrap180(fit_min - fit_max))
    contrast = float(curve.max() - curve.min())
    # если дно утоплено в шуме, положение минимума неопределимо -- тогда честнее
    # сказать «не определяется», чем объявить асимметрию
    resolvable = contrast > 5.0 * f["resid_rms"]
    out = {"delta0_deg": float(delta0), "theta_max_deg": float(th_max),
           "empirical_max_deg": emp_max, "empirical_min_deg": emp_min,
           "fitted_max_deg": fit_max, "fitted_min_deg": fit_min,
           "min_max_separation_deg": float(sep),
           "separation_resolvable": bool(resolvable),
           "separation_ok": bool(abs(sep - 90.0) <= 2.0) if resolvable else None,
           "angle_discrepancy_deg": f["angle_discrepancy_deg"],
           "extinction_ratio": float((f["c0"] + f["amp2"]) /
                                     max(f["c0"] - f["amp2"], 1e-300)),
           "detector_kind": detector_kind, "fit": f}
    if detector_kind == "power":
        out.update(pair_deg=None, max_is_alignment=True, axes_aligned=None)
        return out
    pair = _pair_from_fit(f)
    out.update(pair_deg=pair["pair_deg"], axes_aligned=pair["aligned"],
               half_difference_deg=pair["half_difference_deg"],
               difference_reliable=pair["difference_reliable"],
               #: максимум совпадает с совмещением только когда ось приёмника
               #: и ось WGP1 сошлись -- иначе он стоит посередине между ними
               max_is_alignment=pair["aligned"])
    return out


# --- П2: лабораторная рама ---------------------------------------------
def analyze_lab_frame(alpha_deg, measured, detector_kind: str = "coherent") -> dict:
    """Азимут источника psi и ось приёмника d по прогону СЦЕПЛЕННОЙ пары.

    Оператор фиксирует взаимный угол на нуле (оси WGP1 и WGP2 совмещены после
    П1) и вращает обе решётки вместе на угол alpha. Тогда

        мощностной приёмник:  I ~ cos^2(alpha - psi)
        когерентный:          I ~ cos^2(alpha - psi) * cos^2(alpha - d)

    Второй случай разложим точно:

        cos^2 A cos^2 B = 1/4 [1 + cos2A + cos2B + 1/2 cos(2(d-psi))
                                 + 1/2 cos(4alpha - 2psi - 2d)]

    отсюда фаза 4-й гармоники даёт СУММУ psi+d, а отношение амплитуд --
    модуль разности: |cos(d-psi)| = amp2 / (4 amp4). Пара {psi, d}
    восстанавливается как неупорядоченная -- какой из двух углов чей, угловой
    прогон различить не может, и это ограничение метода, а не недоделка.

    ⚠ СУММА И РАЗНОСТЬ ОБУСЛОВЛЕНЫ ПО-РАЗНОМУ. Сумма берётся из фазы и точна
    всегда. Разность берётся через `arccos`, а он у единицы вырожден:
    производная `d(arccos c)/dc = -1/sqrt(1-c^2)` расходится при `c -> 1`,
    то есть ровно там, где оси почти совмещены. Поэтому у совмещённых осей
    метод честно говорит «совмещены», но не берётся называть их порознь:
    поле `difference_reliable` says False, а `psi_deg`/`d_deg` в этом случае
    стоит понимать как «оба примерно равны полусумме». Проверено на синтетике:
    при истинных (12.0, 12.0) метод даёт (11.29, 12.71) -- полусумма верна до
    0.001 град, разность шумит на градус. При разведённых осях (-8, +22)
    восстановление точное: (-8.02, +22.02).

    При psi == d выражение вырождается в чистый cos^4 -- это и есть проверка
    выравнивания на живом приборе.
    """
    f = harmonic_fit(alpha_deg, measured, order=4)
    if detector_kind == "power":
        psi = f["angle_h2_deg"]
        return {"detector_kind": detector_kind, "psi_deg": float(psi),
                "d_deg": None, "pair_deg": None, "aligned": None,
                "half_difference_deg": 0.0, "fit": f}

    pair = _pair_from_fit(f)
    psi, d = pair["pair_deg"]
    return {"detector_kind": detector_kind, "psi_deg": psi, "d_deg": d,
            **pair, "fit": f}


# --- П3: границы рабочего окна -----------------------------------------
def analyze_window(theta_deg, measured, model, **kw) -> dict:
    """Зашкал и граница чувствительности -- обёртка над `service_limits`."""
    return sl.detect_plateaus(theta_deg, model, measured, **kw)


# --- П4: приёмка --------------------------------------------------------
def analyze_acceptance(theta_deg, runs, model, verdicts=None) -> dict:
    """Статистика остатков по нескольким прогонам одного набора углов.

    `runs` -- список массивов показаний, по одному на прогон. Неопределённость
    берётся по РАЗБРОСУ МЕЖДУ ПРОГОНАМИ, а не по ковариации одной подгонки:
    формальная ошибка одного фита в этом проекте занижена примерно в 25 раз
    (`attenuator_app/core/passport.py`). Точки с вердиктами «зашкал» и «ниже
    чувствительности» в статистику НЕ входят -- они не измерения.
    """
    R = np.atleast_2d(np.asarray(runs, dtype=float))
    if R.shape[0] < 2:
        raise ValueError("для разброса между прогонами нужно хотя бы 2 прогона")
    model = np.asarray(model, dtype=float)
    keep = np.ones(model.shape, dtype=bool)
    if verdicts is not None:
        keep = np.asarray([v == sl.OK for v in verdicts], dtype=bool)
    if keep.sum() < 3:
        raise ValueError("годных точек меньше трёх -- приёмка невозможна")

    mean = R.mean(axis=0)
    scale = float(np.sum(mean[keep] * model[keep]) / np.sum(model[keep] ** 2))
    resid = mean[keep] - scale * model[keep]
    with np.errstate(divide="ignore", invalid="ignore"):
        resid_db = 10.0 * np.log10(np.maximum(mean[keep], 1e-300) /
                                   np.maximum(scale * model[keep], 1e-300))
    return {"n_runs": int(R.shape[0]), "n_points": int(keep.sum()),
            "n_excluded": int((~keep).sum()), "scale": scale,
            "bias_db": float(np.mean(resid_db)),
            "rmse_db": float(np.sqrt(np.mean(resid_db ** 2))),
            "between_run_sigma": float(np.mean(R[:, keep].std(axis=0, ddof=1))),
            "resid": resid, "resid_db": resid_db,
            "theta_kept_deg": np.asarray(theta_deg, dtype=float)[keep]}


def _wrap180(a: float) -> float:
    return (float(a) + 90.0) % 180.0 - 90.0


# --- инструкция оператору ----------------------------------------------
PLAN = """\
ПОРЯДОК КАЛИБРОВКИ АТТЕНЮАТОРА НА СТЕНДЕ

Общее: записывайте ПОКАЗАНИЯ ШКАЛ обоих ротаторов как есть, не пересчитывая в
«настоящие» углы -- пересчёт сделает программа. Между процедурами ничего не
переставляйте: П1 и П2 связаны, и сбитая установка обесценит обе.

П0. ТЁМНЫЙ ОТСЧЁТ                                              ~1 минута
    Перекройте пучок до аттенюатора. Снимите не меньше 20 отсчётов подряд.
    Даёт уровень и разброс шума. Без него не работают два вердикта из трёх:
    «зашкал» и «ниже чувствительности».

П1. ОТНОСИТЕЛЬНЫЙ НОЛЬ                                        ~10 минут
    WGP1 закрепите и не трогайте. Вращайте только WGP2: сначала грубо, шагом
    10 град по всему обороту, затем вокруг найденного максимума шагом 1 град.
    Даёт взаимный офсет шкал.
    ПРОВЕРКА НА МЕСТЕ: минимум обязан лежать на 90 град от максимума.
    Разошлось больше чем на 2 град -- остановитесь: это перекос или
    не-Малюсова асимметрия, дальше калибровать бессмысленно.

П2. ЛАБОРАТОРНАЯ РАМА                                         ~10 минут
    Сцепите оба ротатора на найденном в П1 совмещении (взаимный угол = 0) и
    вращайте ОБА ВМЕСТЕ, шагом 5 град, не меньше 180 град.
    Даёт азимут источника, а для когерентного приёмника -- ещё и ось
    анализатора. Единственный способ узнать раму, когда оба элемента в
    ротаторах и вынуть из пучка нечего.

П3. ГРАНИЦЫ РАБОЧЕГО ОКНА                                     ~15 минут
    От скрещенного положения к совмещённому, шагом 5 град. Отдельного
    эксперимента не нужно: оба плато -- зашкал сверху и шум снизу -- находятся
    по этому же прогону.

П4. ПРИЁМКА                                                   ~30 минут
    Контрольный набор: грубо 0, +-10 ... +-60 град, часто +-70, +-75, +-80,
    +-85, +-88, +-90 -- там крутизна максимальна и цена ошибки угла выше.
    НЕ МЕНЬШЕ ТРЁХ полных прогонов: неопределённость берётся по разбросу
    МЕЖДУ прогонами, одного прогона недостаточно.
"""


# --- демонстрация на синтетике -----------------------------------------
def _simulate(cal_like, kind="relative_zero", n=None, noise=2e-4, seed=4242):
    """Синтетический прогон для демонстрации и проверок."""
    rng = np.random.default_rng(seed)
    P, D = cal_like["P_um"], cal_like["D_um"]
    kw = dict(loss_factor=cal_like["loss"], gamma=cal_like["gamma"])
    nu = np.array([0.8])
    src = sm.PolState.linear(cal_like["psi"])
    ana = sm.Analyzer(cal_like["detector"], cal_like["d"])
    if kind == "relative_zero":
        th2 = np.arange(-90.0, 90.0, 2.0) if n is None else np.linspace(-90, 90, n)
        th1 = np.full_like(th2, cal_like["off1"])
        I = sm.response(th1, th2, nu, P, D, off1_deg=cal_like["off1"],
                        off2_deg=cal_like["off2"], source=src, analyzer=ana,
                        **kw)["intensity"][:, 0]
        return th2, I + rng.normal(0, noise, th2.size)
    if kind == "lab_frame":
        al = np.arange(0.0, 180.0, 5.0)
        th1 = cal_like["off1"] + al
        th2 = cal_like["off2"] + al
        I = sm.response(th1, th2, nu, P, D, off1_deg=cal_like["off1"],
                        off2_deg=cal_like["off2"], source=src, analyzer=ana,
                        **kw)["intensity"][:, 0]
        return al, I + rng.normal(0, noise, al.size)
    raise ValueError(f"неизвестный вид прогона {kind!r}")


_DEMO = {"P_um": 32.94766016244776, "D_um": 9.920978256304087,
         "loss": 0.26069787616947165, "gamma": 0.5691763812786808,
         "off1": -0.5617433589197959, "off2": 0.0,
         "psi": 0.0, "d": 0.0, "detector": "coherent"}


def demo() -> int:
    """Разбор всех процедур на синтетическом стенде с известным ответом."""
    print("\n=== разбор процедур на синтетике (истина известна) ===\n")
    #: приёмник выставлен по нулю лабораторной рамы, источник повёрнут на 12° --
    #: типовой стенд: анализатор выставлен по прибору, источник как встал
    truth = dict(_DEMO, psi=12.0, d=0.0)

    print("П0  тёмный отсчёт")
    dk = analyze_dark(np.random.default_rng(1).normal(2.0e-4, 3.0e-5, 40))
    print(f"    уровень {dk['dark_level']:.3e}  разброс {dk['dark_sigma']:.2e}"
          f"  по {dk['n']} отсчётам\n")

    print("П1  относительный ноль")
    th2, me = _simulate(truth, "relative_zero")
    r1 = analyze_relative_zero(th2, me, theta1_fixed_deg=truth["off1"],
                               detector_kind=truth["detector"])
    print(f"    взаимный офсет {r1['delta0_deg']:+.3f}°   (истина "
          f"{_wrap180(truth['off2'] - truth['off1']):+.3f}°)")
    print(f"    максимум = совмещение: {r1['max_is_alignment']}"
          f"   (ось приёмника и ось WGP1 сошлись)")
    verdict = ("не определяется -- дно в шуме" if r1["separation_ok"] is None
               else ("норма" if r1["separation_ok"] else "ВНЕ ДОПУСКА"))
    print(f"    минимум от максимума на {r1['min_max_separation_deg']:.2f}° -- {verdict}")
    print(f"    расхождение оценок по 2-й и 4-й гармонике "
          f"{r1['angle_discrepancy_deg']:+.4f}°\n")

    print("П2  лабораторная рама")
    al, me2 = _simulate(truth, "lab_frame")
    r2 = analyze_lab_frame(al, me2, truth["detector"])
    print(f"    пара {{psi, d}} = ({r2['psi_deg']:+.3f}°, {r2['d_deg']:+.3f}°)"
          f"   истина ({truth['psi']:+.1f}°, {truth['d']:+.1f}°)")
    print(f"    разность достоверна: {r2['difference_reliable']}"
          f"   (полуразность {r2['half_difference_deg']:.3f}°)\n")

    print("П3  границы рабочего окна")
    th, mo, meas = sl._synth(sat=0.55, dark=2e-4, noise=3e-5, floor=1e-6)
    r3 = analyze_window(th, meas, mo)
    print(sl.format_report(r3) + "\n")

    print("П4  приёмка")
    runs = [mo * 0.98 + np.random.default_rng(s).normal(0, 3e-5, mo.size)
            for s in (11, 12, 13)]
    r4 = analyze_acceptance(th, runs, mo, r3["verdicts"])
    print(f"    прогонов {r4['n_runs']}, точек {r4['n_points']}, "
          f"исключено по вердиктам {r4['n_excluded']}")
    print(f"    смещение {r4['bias_db']:+.3f} дБ, RMSE {r4['rmse_db']:.3f} дБ, "
          f"разброс между прогонами {r4['between_run_sigma']:.2e}")
    return 0


# --- самопроверка ------------------------------------------------------
def selfcheck() -> int:
    print("\n=== attenuator_app.tools.service_calibrate: самопроверка ===\n")
    res = []

    def check(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print(f"  [{'OK' if ok else '!!'}] {name}   {detail}")

    # K1. Базис 4-го порядка точен для когерентной схемы: остаток машинный.
    truth = dict(_DEMO, psi=0.0, d=0.0)
    th2, me = _simulate(truth, "relative_zero", noise=0.0)
    f4 = harmonic_fit(th2, me, order=4)
    f2 = harmonic_fit(th2, me, order=2)
    check("K1  базис 4-го порядка точен, 2-го -- нет",
          f4["resid_rms"] < 1e-12 < f2["resid_rms"],
          f"остаток порядка 4: {f4['resid_rms']:.1e}, порядка 2: {f2['resid_rms']:.1e}")

    # K2. П1 достаёт взаимный офсет; две оценки угла согласуются.
    tr = dict(_DEMO, off1=-0.5617433589197959, off2=7.0, psi=0.0, d=0.0)
    th2, me = _simulate(tr, "relative_zero", noise=1e-5)
    r1 = analyze_relative_zero(th2, me, theta1_fixed_deg=tr["off1"])
    want = _wrap180(tr["off2"] - tr["off1"])
    check("K2  П1 находит взаимный офсет шкал",
          abs(_wrap180(r1["delta0_deg"] - want)) < 0.1
          and abs(r1["angle_discrepancy_deg"]) < 0.1,
          f"получено {r1['delta0_deg']:+.4f}°, истина {want:+.4f}°, "
          f"расхождение гармоник {r1['angle_discrepancy_deg']:+.4f}°")

    # K3. П1 ловит нарушение «минимум на 90 град от максимума».
    th_bad = np.arange(-90.0, 90.0, 2.0)
    bad = np.cos(np.deg2rad(th_bad - 5.0)) ** 4 + 0.4 * np.cos(np.deg2rad(th_bad - 60.0)) ** 2
    r1b = analyze_relative_zero(th_bad, bad)
    check("K3  П1 отмечает нарушение расстояния минимум-максимум",
          r1b["separation_ok"] is False and r1b["separation_resolvable"],
          f"разнос {r1b['min_max_separation_deg']:.1f}° вместо 90°, "
          f"определимо: {r1b['separation_resolvable']}")

    # K4. П2 восстанавливает пару {psi, d} при СОВМЕЩЁННЫХ осях.
    tr = dict(_DEMO, psi=12.0, d=12.0)
    al, me2 = _simulate(tr, "lab_frame", noise=1e-5)
    r2 = analyze_lab_frame(al, me2, "coherent")
    #     Полусумма обязана быть точной, разность у совмещённых осей -- нет:
    #     arccos у единицы вырожден. Метод должен это признавать сам.
    check("K4  П2: у совмещённых осей точна полусумма, разность помечена ненадёжной",
          abs(_wrap180(r2["half_sum_deg"] - 12.0)) < 0.05 and r2["aligned"]
          and not r2["difference_reliable"],
          f"полусумма {r2['half_sum_deg']:+.4f}° (истина +12.0000°), пара "
          f"({r2['psi_deg']:+.2f}°, {r2['d_deg']:+.2f}°), "
          f"разность достоверна: {r2['difference_reliable']}")

    # K5. П2 разводит оси, когда они РАЗНЫЕ: сумма и модуль разности верны.
    tr = dict(_DEMO, psi=-8.0, d=22.0)
    al, me3 = _simulate(tr, "lab_frame", noise=1e-5)
    r3 = analyze_lab_frame(al, me3, "coherent")
    got = sorted((r3["psi_deg"], r3["d_deg"]))
    check("K5  П2 разводит несовмещённые оси (пара неупорядочена)",
          abs(got[0] - (-8.0)) < 1.0 and abs(got[1] - 22.0) < 1.0 and not r3["aligned"],
          f"пара ({got[0]:+.2f}°, {got[1]:+.2f}°), истина (-8.00°, +22.00°)")

    # K6. П2 с мощностным приёмником даёт азимут источника напрямую.
    tr = dict(_DEMO, psi=17.0, d=0.0, detector="power")
    al, me4 = _simulate(tr, "lab_frame", noise=1e-5)
    r4 = analyze_lab_frame(al, me4, "power")
    check("K6  П2 с мощностным приёмником даёт psi напрямую",
          abs(_wrap180(r4["psi_deg"] - 17.0)) < 0.5,
          f"psi = {r4['psi_deg']:+.3f}°, истина +17.00°")

    # K7. П4 исключает точки с вердиктами и требует не меньше двух прогонов.
    th, mo, meas = sl._synth(sat=0.55, dark=2e-4, noise=3e-5, floor=1e-6)
    w = analyze_window(th, meas, mo)
    runs = [mo + np.random.default_rng(s).normal(0, 3e-5, mo.size) for s in (1, 2, 3)]
    acc = analyze_acceptance(th, runs, mo, w["verdicts"])
    one_run_rejected = False
    try:
        analyze_acceptance(th, [runs[0]], mo, w["verdicts"])
    except ValueError:
        one_run_rejected = True
    check("K7  П4 исключает негодные точки и требует >= 2 прогонов",
          acc["n_excluded"] > 0 and acc["n_points"] == w["n_ok"] and one_run_rejected,
          f"точек {acc['n_points']}, исключено {acc['n_excluded']}, "
          f"один прогон отвергнут: {one_run_rejected}")

    # K8. Несовмещённый приёмник СМЕЩАЕТ максимум в П1: он встаёт ровно
    #     посередине между осью WGP1 и осью анализатора. Наивный argmax дал бы
    #     неверный ноль -- процедура обязана это распознавать, а не молчать.
    tr = dict(_DEMO, psi=0.0, d=12.0)                # ось WGP1 в нуле, приёмник под 12°
    th2, me8 = _simulate(tr, "relative_zero", noise=1e-5)
    r8 = analyze_relative_zero(th2, me8, theta1_fixed_deg=tr["off1"],
                               detector_kind="coherent")
    axis_max = _wrap180(r8["theta_max_deg"] - tr["off2"])
    pair8 = sorted(r8["pair_deg"])
    check("K8  несовмещённый приёмник смещает максимум, пара осей восстановлена",
          abs(axis_max - 6.0) < 0.2 and not r8["max_is_alignment"]
          and abs(pair8[0]) < 1.0 and abs(pair8[1] - 12.0) < 1.0,
          f"максимум на {axis_max:+.3f}° вместо совмещения 0°, "
          f"пара ({pair8[0]:+.2f}°, {pair8[1]:+.2f}°), "
          f"max_is_alignment = {r8['max_is_alignment']}")

    bad_names = [n for n, ok, _ in res if not ok]
    print(f"\n=== {len(res) - len(bad_names)}/{len(res)} пройдено ===")
    if bad_names:
        print("НЕ ПРОШЛИ: " + ", ".join(bad_names))
    return 1 if bad_names else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selfcheck()
    if "--demo" in argv:
        return demo()
    print(PLAN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
