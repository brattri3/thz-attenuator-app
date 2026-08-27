"""Пределы прибора: зашкал, граница чувствительности, рабочее угловое окно.

Задача
------
У сервисного приложения (C9) не было ни одной проверки применимости: оно
одинаково уверенно печатало угол и там, где приёмник зашкалил, и там, где
сигнал ушёл под шум. Здесь обе границы определяются ПО ФОРМЕ измеренной
кривой, а не по абсолютным порогам (решение владельца 2026-08-24: «границу
чувствительности можно определить по принципу угол ещё не близок к 90, но
сигнал похож на шумовое плато значений»).

Почему не абсолютные пороги. Классический критерий «K сигм над тёмным
отсчётом» и запас MARGIN под динамический диапазон (см. проектную заметку
`docs/attenuator_app/10_CALIBRATION_DESIGN.md`, вопрос C-10) требуют
аттестованных уровней, которых на стенде нет, и оба числа так и остались
плейсхолдерами. Форма кривой доступна всегда -- её даёт тот же угловой прогон,
которым прибор и калибруют.

Критерий плато -- пара условий, а не одно
-----------------------------------------
Плато объявляется там, где **измерение уже не меняется, а модель ещё меняется**:

    измерение плоское :  |наклон по углу| * размах_угла  <  k_flat * сигма
    модель движется   :  max(модель) / min(модель)  >  ratio_tol

Второе условие обязательно. Без него в плато попал бы физический пол утечки --
там кривая тоже выполаживается, но выполаживается и модель, и никакого
приборного предела нет. Именно пара «модель ещё меняется -- измерение уже нет»
отличает предел ПРИБОРА от предела прибора-как-объекта.

Наклон измеряется ПО УГЛУ, а не по модельному значению. Это принципиально: у
самого дна модель меняется на величины меньше шума, регрессия на неё там
вырождается, и плато, которое оператор видит глазами, не обнаруживается.
Угол же расставлен равномерно и обусловлен одинаково хорошо на всём прогоне.
Условие «модель движется» проверяется не по окну, а по ОТНОШЕНИЮ модельных
значений на всём плато -- отношение осмысленно и там, где абсолютная разность
уже тонет в шуме.

Обе границы ищутся симметрично и только ОТ КРАЯ: зашкал -- максимальный
префикс точек, начиная с самой яркой; граница чувствительности -- максимальный
суффикс, начиная с самой тёмной. Рост останавливается на первой же точке, где
условие плато нарушено: плато посреди прогона -- это не предел прибора, а
что-то другое, и молча объявлять его пределом нельзя.

Запуск самопроверки из корня репозитория:
    python -m attenuator_app.tools.service_limits --selftest
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np

#: вердикт точки
OK = "ok"
SATURATED = "saturated"
BELOW_SENSITIVITY = "below_sensitivity"

VERDICT_RU = {
    OK: "годна",
    SATURATED: "зашкал -- верхняя оценка",
    BELOW_SENSITIVITY: "ниже чувствительности -- нижняя оценка",
}

#: размер скользящего окна и два порога значимости; вынесены сюда, чтобы их
#: можно было поменять из процедуры калибровки, а не править код
DEFAULT_WINDOW = 5
DEFAULT_K_FLAT = 2.0
#: во сколько раз модель обязана измениться на плато, чтобы плато считалось
#: пределом ПРИБОРА, а не физическим полом самой кривой
DEFAULT_RATIO_TOL = 1.5


@dataclass
class Plateau:
    """Найденное плато на одном из концов диапазона."""

    kind: str                 # SATURATED или BELOW_SENSITIVITY
    n_points: int             # сколько точек попало в плато
    theta_deg: float          # угол ГРАНИЦЫ плато со стороны годных точек
    theta_span: tuple         # (min, max) углов, попавших в плато
    level: float              # средний уровень показания на плато
    scatter: float            # разброс внутри плато

    def __str__(self) -> str:
        lo, hi = self.theta_span
        return (f"{VERDICT_RU[self.kind]}: {self.n_points} точек "
                f"({lo:+.1f}°…{hi:+.1f}°), граница {self.theta_deg:+.2f}°, "
                f"уровень {self.level:.4g} ± {self.scatter:.2g}")


def estimate_gain(model, measured, lo: float = 0.25, hi: float = 0.75) -> float:
    """Коэффициент тракта G из регрессии измеренного на модельное.

    Берётся средняя по рангу модельного значения доля точек `[lo, hi]`: сверху
    может быть зашкал, снизу -- шум, а середина свободна и от того, и от другого.
    """
    model = np.asarray(model, dtype=float)
    measured = np.asarray(measured, dtype=float)
    if model.size < 3:
        raise ValueError("для оценки коэффициента тракта нужно хотя бы 3 точки")
    r = np.argsort(np.argsort(model)) / max(model.size - 1, 1)
    m = (r >= lo) & (r <= hi)
    if m.sum() < 3:
        m = np.ones_like(r, dtype=bool)
    x, y = model[m], measured[m]
    sxx = float(((x - x.mean()) ** 2).sum())
    if sxx <= 0.0:
        raise ValueError("модельные значения в средней доле не меняются")
    return float(((x - x.mean()) * (y - y.mean())).sum() / sxx)


def _is_flat(theta, y_meas, k_flat: float) -> bool:
    """Плоское ли измерение на этом участке -- регрессия ПО УГЛУ.

    «Плоское» значит: изменение, которое даёт подогнанный наклон на всём
    размахе углов участка, меньше собственного разброса точек вокруг этой же
    прямой. То есть тренда, различимого на фоне шума, нет.
    """
    n = theta.size
    if n < 3:
        return False
    tm = theta - theta.mean()
    stt = float((tm ** 2).sum())
    span = float(theta.max() - theta.min())
    if stt <= 0.0 or span <= 0.0:
        return False
    slope = float((tm * (y_meas - y_meas.mean())).sum() / stt)
    resid = y_meas - (y_meas.mean() + slope * tm)
    sigma = float(np.sqrt((resid ** 2).sum() / max(n - 2, 1)))
    if sigma <= 0.0:
        # идеально ровные значения: тренда нет по определению
        return slope == 0.0
    return abs(slope) * span < k_flat * sigma


def _model_moves(model_vals, ratio_tol: float) -> bool:
    """Меняется ли модель на участке -- по ОТНОШЕНИЮ, а не по разности.

    Отношение осмысленно и у самого дна, где абсолютная разность модельных
    значений уже меньше шума измерения.
    """
    hi = float(np.max(model_vals))
    lo = float(np.min(model_vals))
    if hi <= 0.0:
        return False
    if lo <= 0.0:
        return True                              # модель уходит в ноль -- меняется
    return hi / lo > ratio_tol


def detect_plateaus(theta_deg, model, measured, *, window: int = DEFAULT_WINDOW,
                    k_flat: float = DEFAULT_K_FLAT,
                    ratio_tol: float = DEFAULT_RATIO_TOL,
                    gain: float | None = None) -> dict:
    """Найти зашкал и границу чувствительности по угловому прогону.

    `theta_deg`, `model`, `measured` -- массивы одной длины: угол (любой из двух
    ротаторов, лишь бы согласованно), предсказание модели и показание прибора.
    Порядок точек произволен -- внутри они сортируются от самой яркой к самой
    тёмной по МОДЕЛЬНОМУ значению.

    Возвращает словарь: `saturation`, `sensitivity` (`Plateau` или None),
    `verdicts` (массив строк в исходном порядке точек), `gain`, `window_deg`
    (границы годного участка по углу) и `n_ok`.
    """
    theta_deg = np.asarray(theta_deg, dtype=float)
    model = np.asarray(model, dtype=float)
    measured = np.asarray(measured, dtype=float)
    if not (theta_deg.shape == model.shape == measured.shape):
        raise ValueError("theta_deg, model и measured должны быть одной длины")
    n = theta_deg.size
    if n < window:
        raise ValueError(f"точек {n}, а окно {window} -- прогон слишком короткий")

    g = estimate_gain(model, measured) if gain is None else float(gain)
    order = np.argsort(model)[::-1]              # от яркой к тёмной
    th, mo, me = theta_deg[order], model[order], measured[order]

    def grow(from_start: bool) -> int:
        """Максимальный участок ОТ КРАЯ, целиком удовлетворяющий условиям плато.

        Рост идёт по признаку «измерение плоское» и прекращается на первом же
        нарушении: плато посреди прогона -- не предел прибора, и объявлять его
        пределом нельзя. Условие «модель движется» проверяется ОДИН РАЗ на
        готовом участке, а не на каждом префиксе: у любого короткого префикса
        модель ещё не успевает измениться, и пошаговая проверка зарубила бы
        плато в самом начале роста.
        """
        best = 0
        for size in range(window, n + 1):
            sl = slice(0, size) if from_start else slice(n - size, n)
            if _is_flat(th[sl], me[sl], k_flat):
                best = size
            else:
                break
        if not best:
            return 0
        sl = slice(0, best) if from_start else slice(n - best, n)
        return best if _model_moves(mo[sl], ratio_tol) else 0

    n_sat, n_sen = grow(True), grow(False)
    if n_sat + n_sen > n:                        # прогон целиком вырожден
        n_sat = min(n_sat, n - n_sen)

    verdict_sorted = np.array([OK] * n, dtype=object)
    if n_sat:
        verdict_sorted[:n_sat] = SATURATED
    if n_sen:
        verdict_sorted[n - n_sen:] = BELOW_SENSITIVITY

    def make(kind, sl) -> Plateau | None:
        if sl.stop - sl.start <= 0:
            return None
        vals, angs = me[sl], th[sl]
        # граница плато -- та его точка, что примыкает к годному участку:
        # у зашкала это самая тусклая из зашкаленных, у предела
        # чувствительности -- самая яркая из утонувших в шуме
        edge = th[sl.stop - 1] if kind == SATURATED else th[sl.start]
        return Plateau(kind, int(vals.size), float(edge),
                       (float(angs.min()), float(angs.max())),
                       float(vals.mean()),
                       float(vals.std(ddof=1)) if vals.size > 1 else 0.0)

    sat = make(SATURATED, slice(0, n_sat))
    sen = make(BELOW_SENSITIVITY, slice(n - n_sen, n))

    ok = verdict_sorted == OK
    win = (float(th[ok].min()), float(th[ok].max())) if ok.any() else (float("nan"),) * 2

    verdicts = np.empty(n, dtype=object)
    verdicts[order] = verdict_sorted
    return {"saturation": sat, "sensitivity": sen, "verdicts": verdicts,
            "gain": g, "window_deg": win, "n_ok": int(ok.sum())}


def format_report(result: dict) -> str:
    """Человекочитаемая сводка по результату `detect_plateaus`."""
    lines = [f"  коэффициент тракта G = {result['gain']:.4g}",
             f"  годных точек: {result['n_ok']}"]
    for key, title in (("saturation", "зашкал"), ("sensitivity", "чувствительность")):
        p = result[key]
        lines.append(f"  {title}: {p if p is not None else 'не обнаружено'}")
    lo, hi = result["window_deg"]
    if np.isnan(lo):
        lines.append("  рабочее окно: ПУСТО -- годных точек нет")
    else:
        lines.append(f"  рабочее окно по углу: {lo:+.2f}° … {hi:+.2f}°")
    return "\n".join(lines)


# --- самопроверка ------------------------------------------------------
def _synth(n=91, gain=1.0, dark=2.0e-4, noise=1.5e-5, sat=None, floor=1.0e-6,
           seed=12345):
    """Синтетический прогон: cos^4 с шумом, при желании -- с обрезкой сверху.

    `floor` -- собственный пол модели (утечка). Он важен для смысла проверок:
    если пол модели ЛЕЖИТ ВЫШЕ шума, прибор ни в чём не виноват и границы
    чувствительности быть не должно; если ниже -- измерение упирается в шум
    раньше, чем кривая доходит до своего пола, и вот это и есть предел прибора.
    """
    rng = np.random.default_rng(seed)
    th = np.linspace(0.0, 90.0, n)
    model = np.cos(np.deg2rad(th)) ** 4 + floor
    meas = gain * model + dark + rng.normal(0.0, noise, n)
    if sat is not None:
        meas = np.minimum(meas, sat)
    return th, model, meas


def selfcheck() -> int:
    print("\n=== attenuator_app.tools.service_limits: самопроверка ===\n")
    res = []

    def check(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print(f"  [{'OK' if ok else '!!'}] {name}   {detail}")

    # T1. Чистый прогон без зашкала и с большим запасом по шуму: плато нет.
    th, mo, me = _synth(noise=1e-9, dark=0.0)
    r = detect_plateaus(th, mo, me)
    check("T1  чистый прогон -- ни зашкала, ни границы чувствительности",
          r["saturation"] is None and r["sensitivity"] is None and r["n_ok"] == th.size,
          f"годных {r['n_ok']}/{th.size}, G = {r['gain']:.4f}")

    # T2. Обрезка сверху: зашкал найден, начинается на самом ярком конце, и его
    #     граница близка к истинной точке обрезки. Небольшой перехлёст в
    #     БЕЗОПАСНУЮ сторону (лишний градус объявлен зашкаленным) допустим:
    #     проверка флатности терпит тренд, не различимый на фоне шума.
    th, mo, me = _synth(sat=0.55)
    r = detect_plateaus(th, mo, me)
    sat = r["saturation"]
    clipped = mo + 2.0e-4 > 0.55                     # где сигнал упирался в потолок
    true_edge = float(th[clipped].max())
    check("T2  обрезка сверху -- зашкал найден на ярком конце",
          sat is not None and sat.theta_span[0] == 0.0
          and 0.0 <= sat.theta_deg - true_edge <= 5.0,
          f"{sat}, истинная граница {true_edge:.1f}°" if sat else "не найден")

    # T3. Шумовое плато снизу: граница чувствительности найдена ДО 90 град --
    #     ровно тот признак, который назвал владелец («угол ещё не близок к 90,
    #     а сигнал уже похож на плоское шумовое плато»).
    th, mo, me = _synth(dark=2e-4, noise=3e-5, floor=1e-6)
    r = detect_plateaus(th, mo, me)
    sen = r["sensitivity"]
    check("T3  шумовое плато снизу -- граница найдена, и она не на 90°",
          sen is not None and sen.theta_deg < 88.0 and r["n_ok"] > 10,
          f"{sen}, годных {r['n_ok']}" if sen else "не найдена")

    # T4. Физический пол САМОЙ МОДЕЛИ пределом прибора не считается: если пол
    #     утечки лежит выше шума, кривая выполаживается вместе с моделью, и
    #     винить приёмник не в чем.
    th, mo, me = _synth(dark=2e-6, noise=1e-7, floor=1e-2)
    r = detect_plateaus(th, mo, me)
    check("T4  пол модели выше шума -> границы чувствительности нет",
          r["sensitivity"] is None,
          f"годных {r['n_ok']}/{th.size}, sensitivity = {r['sensitivity']}")

    # T4b. Вырожденный случай: модель вообще не меняется -- плато не объявляется
    #      ни с одного конца, сколько бы ровным ни было измерение.
    th_f = np.linspace(0.0, 90.0, 91)
    r = detect_plateaus(th_f, np.full_like(th_f, 0.3), np.full_like(th_f, 0.3))
    check("T4b модель стоит на месте -> ни зашкала, ни границы",
          r["saturation"] is None and r["sensitivity"] is None,
          f"годных {r['n_ok']}/{th_f.size}")

    # T5. Оба предела разом: остаётся непустое окно между ними.
    th, mo, me = _synth(sat=0.55, dark=2e-4, noise=3e-5, floor=1e-6)
    r5 = detect_plateaus(th, mo, me)
    lo, hi = r5["window_deg"]
    check("T5  зашкал и шум вместе -- окно между ними непусто",
          r5["saturation"] is not None and r5["sensitivity"] is not None
          and r5["n_ok"] > 5 and lo < hi,
          f"окно {lo:+.1f}°…{hi:+.1f}°, годных {r5['n_ok']}")

    # T6. Результат не зависит от порядка точек на входе: вердикты возвращаются
    #     привязанными к своим точкам, а не к позиции в отсортированном массиве.
    perm = np.random.default_rng(7).permutation(th.size)
    rp = detect_plateaus(th[perm], mo[perm], me[perm])
    back = np.empty_like(rp["verdicts"])
    back[perm] = rp["verdicts"]
    check("T6  вердикты не зависят от порядка точек на входе",
          bool(np.all(back == r5["verdicts"])),
          f"совпало {int(np.sum(back == r5['verdicts']))}/{th.size}")

    bad = [n for n, ok, _ in res if not ok]
    print(f"\n=== {len(res) - len(bad)}/{len(res)} пройдено ===")
    if bad:
        print("НЕ ПРОШЛИ: " + ", ".join(bad))
    return 1 if bad else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selfcheck()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
