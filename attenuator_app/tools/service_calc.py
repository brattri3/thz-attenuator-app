"""Библиотека + CLI: калькулятор аттенюатора для обслуживания в THz-TDS
спектрометре (задача C9, санкция владельца 2026-08-19, начата после C8).

Один сценарий эксплуатации, двунаправленный:
  (а) дБ -> угол:  оператор вводит желаемое затухание, получает угол(ы),
      на которые поставить WGP1;
  (б) угол -> дБ:  оператор вводит текущий угол WGP1 (по шкале ротатора),
      получает предсказанное затухание.
Только точечное предсказание, БЕЗ доверительного интервала (санкция владельца
2026-08-19: минимальный масштаб задачи).

ЗНАК. Затухание -- ОТРИЦАТЕЛЬНЫЕ децибелы (владелец 2026-08-18):
`attenuation_db = 10*log10(T)`, т.е. T=1 -> 0 дБ, T=0.5 -> -3.01 дБ. Величина
положительна только при усилении относительно опорной точки (см. `pzero` ниже).
Децибелы -- ПО МОЩНОСТИ (10*log10), не по амплитуде поля (20*log10);
`power_field_ratios()` возвращает обе величины сразу.

ДВА РАЗНЫХ НУЛЯ -- не путать (владелец 2026-08-18):
  SET OFFSET (`offset_deg`, он же theta0) -- ФИЗИЧЕСКИЙ офсет: показание шкалы
      ротатора, при котором оси WGP1 и WGP2 совмещены. Входит в саму формулу
      Джонса как `d = theta_reading - offset`. Определяется ПОДБОРОМ ПАРАМЕТРОВ
      модели и ЗАШИТ в калибровку (`theta0_calibration_deg` в JSON). Оператор
      его обычно не трогает; алгоритм автоматической калибровки офсета -- задача
      следующей версии.
  SET ZERO (`zero_deg`) -- РАБОЧАЯ ТОЧКА ОТСЧЁТА: точка на угловой кривой, от
      которой оператор считает ДОБАВОЧНОЕ затухание (или усиление, если идти к
      совмещённому положению). В физику не входит. По умолчанию = SET OFFSET.

ТРИ ОПОРНЫЕ МОЩНОСТИ `ref` -- что стоит в знаменателе T (владелец 2026-08-18:
переключатель абсолютное/относительное развёрнут в три позиции, потому что
относительных нормировок на самом деле две -- к максимуму и к рабочей точке):
  'p0'    -- АБСОЛЮТНАЯ: T = P/P_0, доля мощности, падающей на аттенюатор (до
      WGP1). Включает СОБСТВЕННУЮ вносимую потерю пары WGP даже в совмещённом
      положении (T(offset) ~ 92 %, т.е. -0.36 дБ), поэтому 0 дБ недостижим.
      От SET ZERO не зависит.
  'pmax'  -- ОТНОСИТЕЛЬНАЯ К МАКСИМУМУ (по умолчанию): T = P/P_max, нормировка
      на совмещённое положение WGP1||WGP2, там ровно 0 дБ. Прежний режим
      «relative»: общий множитель потерь и |t_perp|^4 сокращаются ТОЧНО, поэтому
      режим устойчив к экстраполяции (см. `attenuator_app/STATE.md`, «Два
      ключевых решения»). От SET ZERO не зависит.
  'pzero' -- ОТНОСИТЕЛЬНАЯ К РАБОЧЕЙ ТОЧКЕ: T = P/P_zero, нормировка на SET
      ZERO, там ровно 0 дБ. Движение от рабочей точки к совмещению даёт T > 1
      (положительные дБ) -- это и есть «выход в усиление». При zero == offset
      совпадает с 'pmax'.
Во ВСЕХ трёх режимах добавочная величина относительно рабочей точки считается
одинаково: `delta = att(theta) - att(zero)` -- она от выбора `ref` не зависит
(общий знаменатель сокращается), см. `relative_to_zero_db`.

Метрика `Metric` -- по какой полосе усредняется пропускание, 4 варианта:
  full         -- полная мощность: вся записанная полоса с весом |E_ref(nu)|^2
                  (теорема Парсеваля, FINDINGS п.4);
  single       -- одна частота;
  band_cw      -- полоса, заданная центром и шириной;
  band_minmax  -- полоса, заданная минимумом и максимумом.
Полосы усредняются тем же весом |E_ref(nu)|^2, но только по точкам сетки,
попавшим внутрь полосы.

Физика -- полная Джонс-матричная модель схемы S1 (два ИДЕНТИЧНЫХ WGP) из
`attenuator_app/tools/measured_curve.py`; вывод формулы и обоснование --
`FINDINGS_measured_curve_2026-08-19.md`, п.1 (I_perp=|t_perp|^4, не |t_perp|^2
одного WGP). Параметры устройства ЗАШИТЫ в
`calibration/SAMPLE.json` (как получено --
`calibration/build_service_calibration.py`). Рантайм `data_pool/` не читает и
зависит только от numpy + `attenuator_app.core.blanco` (тот же принцип изоляции
от научного стека, что у клиента v0.2).

НЕ часть клиентского `attenuator_app.gui`/`cli` (v0.2/v0.3, отдельный трек) --
самостоятельный инструмент поверх модели C8.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe -m attenuator_app.tools.service_calc --to-db -12
    .venv\\Scripts\\python.exe -m attenuator_app.tools.service_calc --from-angle 35 --freq 0.8
    .venv\\Scripts\\python.exe -m attenuator_app.tools.service_calc --from-angle 35 --band 0.4 1.2
    .venv\\Scripts\\python.exe -m attenuator_app.tools.service_calc --from-angle 2 --zero 40 --ref pzero
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.core.blanco import dressed_t          # noqa: E402
from attenuator_app.tools import service_model as sm      # noqa: E402

DEFAULT_CALIBRATION_PATH = HERE / "calibration" / "SAMPLE.json"

#: опорная мощность в знаменателе T -- см. docstring модуля
REFS = ("p0", "pmax", "pzero")
REF_SHORT = {"p0": "P_0", "pmax": "P_max", "pzero": "P_zero"}
REF_LABEL = {
    "p0": "абсолютная: T = P/P_0 (мощность на входе аттенюатора)",
    "pmax": "к максимуму: T = P/P_max (совмещённое положение, 0 дБ)",
    "pzero": "к рабочей точке: T = P/P_zero (SET ZERO, 0 дБ)",
}
#: зависит ли кривая от положения SET ZERO
REF_USES_ZERO = {"p0": False, "pmax": False, "pzero": True}

METRIC_KINDS = ("full", "single", "band_cw", "band_minmax")


class Calibration:
    """Зашитая конфигурация устройства -- см. `calibration/*.json`.

    Формат v2 добавляет к v1 три необязательных блока -- `source`, `detector`,
    `offsets` -- и не ломает старые файлы: при их отсутствии подставляются
    ровно те допущения, на которых написан исходный C9 (линейный полностью
    поляризованный источник вдоль x, когерентный приёмник с осью вдоль x, WGP2
    в нуле своей шкалы). Поэтому калибровка v1 читается без изменений и даёт
    прежние числа.

    Соответствие офсетов: в v1 `theta0_calibration_deg` -- показание шкалы WGP1,
    при котором оси WGP1 и WGP2 совмещены, а WGP2 стоит в нуле своей шкалы.
    В v2 у каждого ротатора свой механический офсет, и
    ``theta0_calibration_deg == off1 - off2``.
    """

    def __init__(self, data: dict):
        self.device_id = data["device_id"]
        self.dataset = data["calibration_dataset"]
        self.generated = data.get("generated", "?")
        self.schema_version = int(data.get("schema_version", 1))
        self.P_um = float(data["P_um"])
        self.D_um = float(data["D_um"])
        self.loss_db = float(data["loss_db_per_thz_gamma"])
        self.gamma = float(data["gamma"])
        self.band_thz = tuple(data["band_thz"])
        self.at_bound = bool(data["at_bound"])
        self.freqs_ref = np.array(data["freqs_ref_thz"], dtype=float)
        self.power_ref = np.array(data["power_ref"], dtype=float)

        # --- офсеты ротаторов (v2), с приведением из v1 -------------------
        off = data.get("offsets") or {}
        if off:
            self.off1_deg = float(off.get("wgp1_deg", 0.0))
            self.off2_deg = float(off.get("wgp2_deg", 0.0))
        else:
            self.off1_deg = float(data["theta0_calibration_deg"])
            self.off2_deg = 0.0

        # --- источник и приёмник (v2), с умолчаниями v1 -------------------
        src = data.get("source") or {}
        self.source_kind = str(src.get("kind", "linear"))
        self.source_psi_deg = float(src.get("psi_deg", 0.0))
        self.source_dop = float(src.get("dop", 1.0))
        det = data.get("detector") or {}
        self.detector_kind = str(det.get("kind", "coherent"))
        self.detector_axis_deg = float(det.get("axis_deg", 0.0))

        # --- приборные пределы (v2, заполняются процедурами П0/П3) --------
        lim = data.get("limits") or {}
        self.dark_level = lim.get("dark_level")
        self.dark_sigma = lim.get("dark_sigma")
        self.saturation_level = lim.get("saturation_level")

    #: SET OFFSET -- показание, при котором оси WGP1 и WGP2 совмещены.
    #: НЕ рабочая точка отсчёта (это SET ZERO), см. докстринг модуля.
    @property
    def theta0_calibration_deg(self) -> float:
        return self.off1_deg - self.off2_deg

    def source_state(self) -> "sm.PolState":
        """Состояние поляризации источника как объект модели."""
        return sm.PolState.from_source(self.source_kind, self.source_psi_deg,
                                       self.source_dop)

    def analyzer(self) -> "sm.Analyzer":
        """Матрица чувствительности приёмника как объект модели."""
        return sm.Analyzer(self.detector_kind, self.detector_axis_deg)

    def describe_source(self) -> str:
        """Тип источника ПО-РУССКИ -- для сообщений оператору у стенда; голое
        `source_kind` (`linear`/`unpolarized`/`partial`) латиницей в русской
        фразе оператор читать не должен."""
        return {"linear": "источник линейный",
                "unpolarized": "источник деполяризованный",
                "partial": "источник частично поляризован"}.get(
                    self.source_kind, f"источник {self.source_kind}")

    def describe_setup(self) -> str:
        """Одна строка про источник и приёмник -- для CLI и заголовков."""
        s = {"linear": f"линейный, азимут {self.source_psi_deg:+.1f}°",
             "unpolarized": "деполяризованный (DOP = 0)",
             "partial": f"частично поляризованный, DOP {self.source_dop:.2f}, "
                        f"азимут {self.source_psi_deg:+.1f}°"}[self.source_kind]
        d = (f"когерентный, ось {self.detector_axis_deg:+.1f}°"
             if self.detector_kind == "coherent" else "мощностной (оси анализатора нет)")
        return f"источник: {s} | приёмник: {d}"


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> Calibration:
    with open(path, encoding="utf-8") as f:
        return Calibration(json.load(f))


# --- метрика: по какой полосе усредняем ------------------------------
@dataclass(frozen=True)
class Metric:
    """Спецификация полосы усреднения. `a`/`b` трактуются по `kind`:
    full -- не используются; single -- a=частота; band_cw -- a=центр, b=ширина;
    band_minmax -- a=f_min, b=f_max. Всё в ТГц."""

    kind: str = "full"
    a: float | None = None
    b: float | None = None

    def __post_init__(self):
        if self.kind not in METRIC_KINDS:
            raise ValueError(f"неизвестная метрика {self.kind!r}, ожидается одна из {METRIC_KINDS}")
        if self.kind == "single" and self.a is None:
            raise ValueError("для метрики 'одна частота' нужна частота")
        # частота <= 0 физически бессмысленна и даёт NaN, а не отказ: длина
        # волны обращается в бесконечность, `nu_eff ** gamma` от отрицательного
        # числа = nan. Окно тогда печатало «затухание = nan дБ» и рисовало
        # пустой график без единого слова оператору -- ловим здесь, чтобы
        # отказ был один и тот же в GUI и в CLI
        if self.kind == "single" and float(self.a) <= 0:
            raise ValueError("частота должна быть больше нуля")
        if self.kind in ("band_cw", "band_minmax") and (self.a is None or self.b is None):
            raise ValueError("для полосы нужны оба значения")
        if self.kind == "band_cw" and float(self.b) <= 0:
            raise ValueError("ширина полосы должна быть больше нуля")
        if self.kind == "band_minmax" and float(self.b) <= float(self.a):
            raise ValueError("f_max должна быть больше f_min")

    @property
    def limits(self) -> tuple[float, float] | None:
        """(lo, hi) для полосовых метрик, иначе None."""
        if self.kind == "band_cw":
            return (self.a - self.b / 2.0, self.a + self.b / 2.0)
        if self.kind == "band_minmax":
            return (float(self.a), float(self.b))
        return None

    @property
    def label(self) -> str:
        if self.kind == "full":
            return "полная мощность (вся записанная полоса)"
        if self.kind == "single":
            return f"на {self.a:.3f} ТГц"
        lo, hi = self.limits
        if self.kind == "band_cw":
            return f"полоса {self.a:.3f} +- {self.b / 2.0:.3f} ТГц ({lo:.3f}-{hi:.3f})"
        return f"полоса {lo:.3f}-{hi:.3f} ТГц"

    def resolve(self, cal: Calibration) -> tuple[np.ndarray, np.ndarray | None]:
        """(частоты, веса) для усреднения. Вес None = равномерное среднее."""
        if self.kind == "full":
            return cal.freqs_ref, cal.power_ref
        if self.kind == "single":
            return np.array([float(self.a)]), None
        lo, hi = self.limits
        m = (cal.freqs_ref >= lo) & (cal.freqs_ref <= hi)
        if not m.any():
            raise ValueError(
                f"в полосе {lo:.3f}-{hi:.3f} ТГц нет ни одной точки спектра "
                f"(сетка {cal.freqs_ref[0]:.3f}-{cal.freqs_ref[-1]:.3f} ТГц, "
                f"шаг {cal.freqs_ref[1] - cal.freqs_ref[0]:.4f} ТГц)")
        return cal.freqs_ref[m], cal.power_ref[m]

    def warning(self, cal: Calibration) -> str | None:
        """Предупреждение об экстраполяции за откалиброванную полосу."""
        lo_c, hi_c = cal.band_thz
        if self.kind == "single":
            if lo_c <= self.a <= hi_c:
                return None
            return (f"[!] {self.a:.3f} ТГц вне откалиброванной полосы "
                    f"{lo_c:.2f}-{hi_c:.2f} ТГц -- значение экстраполировано, не измерено")
        lim = self.limits
        if lim is None:
            return None
        lo, hi = lim
        if lo >= lo_c and hi <= hi_c:
            return None
        return (f"[!] полоса {lo:.3f}-{hi:.3f} ТГц частично вне откалиброванной "
                f"{lo_c:.2f}-{hi_c:.2f} ТГц -- край экстраполирован, не измерен")


FULL = Metric("full")


def power_field_ratios(att_db: float) -> tuple[float, float]:
    """(P/P_ref, E/E_ref) по затуханию в дБ ПО МОЩНОСТИ (отрицательному):
    P/P_ref = 10^(dB/10), E/E_ref = 10^(dB/20) = sqrt(P/P_ref)."""
    return 10.0 ** (att_db / 10.0), 10.0 ** (att_db / 20.0)


# --- физика ------------------------------------------------------------
def transmission_array(theta_deg, offset_deg: float, cal: Calibration,
                       metric: Metric = FULL, ref: str = "pmax",
                       zero_deg: float | None = None) -> np.ndarray:
    """Отношение МОЩНОСТЕЙ T(theta) для схемы S1 (два идентичных WGP), см.
    docstring модуля и `FINDINGS_measured_curve_2026-08-19.md` п.1 /
    `measured_curve.blanco_angular_curve` (тот же вывод, продублирован здесь в
    минимальном виде, чтобы не тянуть импорт `track_viewer` в рантайм).

        E1(theta,nu) = t_perp(nu)*cos^2(d) + t_par(nu)*sin^2(d),  d = theta - offset
        'p0':    T = <|t_perp|^2 * |E1(theta)|^2>            (доля P_0)
        'pmax':  T = <|E1(theta)|^2> / <|E1(offset)|^2>      (T(offset) == 1)
        'pzero': T = <|E1(theta)|^2> / <|E1(zero)|^2>        (T(zero)   == 1)

    `<x>` -- среднее по частоте с весом |E_ref(nu)|^2 по точкам, отобранным
    метрикой (для одной частоты -- само значение).

    `offset_deg` -- SET OFFSET (физика), `zero_deg` -- SET ZERO (рабочая точка
    отсчёта, по умолчанию = offset; используется только при ref='pzero').
    `theta_deg` -- массив любой формы, градусы; возвращает массив той же формы.
    """
    if ref not in REFS:
        raise ValueError(f"неизвестная опорная мощность {ref!r}, ожидается одна из {REFS}")
    if zero_deg is None:
        zero_deg = offset_deg
    freqs, weight = metric.resolve(cal)
    tp, ta, _ = dressed_t(freqs, cal.P_um, cal.D_um, loss_factor=cal.loss_db, gamma=cal.gamma)

    def field(th) -> np.ndarray:
        d = np.deg2rad(np.asarray(th, dtype=float) - offset_deg)
        c2, s2 = np.cos(d) ** 2, np.sin(d) ** 2
        return tp[None, :] * c2[..., None] + ta[None, :] * s2[..., None]

    def wavg(x):
        return np.mean(x, axis=-1) if weight is None else np.average(x, axis=-1, weights=weight)

    e1 = field(theta_deg)
    if ref == "p0":
        return wavg(np.abs(tp[None, :]) ** 2 * np.abs(e1) ** 2)
    norm_angle = offset_deg if ref == "pmax" else zero_deg
    p_norm = float(wavg(np.abs(field(np.array([norm_angle]))) ** 2)[0])
    return wavg(np.abs(e1) ** 2) / p_norm


def attenuation_db_array(theta_deg, offset_deg: float, cal: Calibration,
                         metric: Metric = FULL, ref: str = "pmax",
                         zero_deg: float | None = None) -> np.ndarray:
    """Затухание в ДЕЦИБЕЛАХ ПО МОЩНОСТИ, ОТРИЦАТЕЛЬНЫХ: 10*log10(T)."""
    T = transmission_array(theta_deg, offset_deg, cal, metric, ref, zero_deg)
    return 10.0 * np.log10(np.maximum(T, 1e-300))


# --- два ротатора ------------------------------------------------------
def pair_response(theta1_deg, theta2_deg, cal: Calibration,
                  metric: Metric = FULL) -> dict:
    """Отклик схемы при ДВУХ произвольных углах ротаторов.

    Возвращает `intensity` (показание приёмника, доля от единичного входа),
    `intensity_total`, `azimuth_deg`, `ellipticity_deg`, `dop` -- всё формы
    входных углов после усреднения по полосе метрики.

    Усреднение по частоте делается на уровне МАТРИЦЫ КОГЕРЕНТНОСТИ, а не над
    готовыми углами: параметры Стокса аддитивны, поэтому средняя матрица даёт
    правильные азимут и степень поляризации широкополосного пучка. Усреднять
    сами азимуты нельзя -- это углы по модулю 180 град.
    """
    freqs, weight = metric.resolve(cal)
    M = sm.chain(theta1_deg, theta2_deg, freqs, cal.P_um, cal.D_um,
                 loss_factor=cal.loss_db, gamma=cal.gamma,
                 off1_deg=cal.off1_deg, off2_deg=cal.off2_deg)
    J = sm.propagate(M, cal.source_state())          # (n_ang, n_f, 2, 2)
    if weight is None:
        J_avg = J.mean(axis=-3)
    else:
        w = np.asarray(weight, dtype=float)
        J_avg = np.einsum("...fij,f->...ij", J, w / w.sum())
    out = sm.polarization_of(J_avg)
    out["intensity_total"] = out.pop("intensity")
    out["intensity"] = sm.detected(J_avg, cal.analyzer())
    return out


def aligned_pair(cal: Calibration) -> tuple:
    """Показания обеих шкал в положении максимального пропускания.

    Оси обоих WGP выставлены по азимуту источника: `theta = off + psi`. Для
    деполяризованного источника азимут безразличен (пара со сцепленными осями
    вращательно инвариантна), берётся `psi = 0`.
    """
    psi = 0.0 if cal.source_kind == "unpolarized" else cal.source_psi_deg
    return cal.off1_deg + psi, cal.off2_deg + psi


def transmission_pair(theta1_deg, theta2_deg, cal: Calibration,
                      metric: Metric = FULL, ref: str = "pmax",
                      zero_pair: tuple | None = None) -> np.ndarray:
    """T(theta1, theta2) для трёх опор -- двухугловой аналог `transmission_array`.

    Отличие от одноуглового пути, сознательное: здесь `pmax`/`pzero` считаются
    как отношение ПОЛНЫХ интенсивностей, тогда как `transmission_array` в этих
    режимах выбрасывает общий множитель `|t_perp|^2` из числителя и знаменателя.
    При взвешенном усреднении по полосе это не тождественные операции.
    Расхождение измерено на канонической калибровке: ноль на одной частоте,
    до 0.032 дБ на самом дне (85 град) в полной полосе -- заметно ниже
    паспортной RMSE. Старый путь оставлен бит-в-бит, чтобы не двигать числа
    сданного приложения.
    """
    if ref not in REFS:
        raise ValueError(f"неизвестная опорная мощность {ref!r}, ожидается одна из {REFS}")
    num = pair_response(theta1_deg, theta2_deg, cal, metric)["intensity"]
    if ref == "p0":
        return num
    if ref == "pmax":
        n1, n2 = aligned_pair(cal)
    else:
        if zero_pair is None:
            n1, n2 = aligned_pair(cal)
        else:
            n1, n2 = zero_pair
    den = float(np.ravel(pair_response(np.array([n1]), np.array([n2]),
                                       cal, metric)["intensity"])[0])
    return num / den


def attenuation_db_pair(theta1_deg, theta2_deg, cal: Calibration,
                        metric: Metric = FULL, ref: str = "pmax",
                        zero_pair: tuple | None = None) -> np.ndarray:
    """Затухание в ОТРИЦАТЕЛЬНЫХ дБ по мощности при двух углах ротаторов."""
    T = transmission_pair(theta1_deg, theta2_deg, cal, metric, ref, zero_pair)
    return 10.0 * np.log10(np.maximum(T, 1e-300))


def transmission(theta_deg: float, offset_deg: float, cal: Calibration,
                 metric: Metric = FULL, ref: str = "pmax",
                 zero_deg: float | None = None) -> float:
    return float(transmission_array(np.array([theta_deg]), offset_deg, cal,
                                    metric, ref, zero_deg)[0])


def attenuation_db(theta_deg: float, offset_deg: float, cal: Calibration,
                   metric: Metric = FULL, ref: str = "pmax",
                   zero_deg: float | None = None) -> float:
    """Прямая задача: предсказанное затухание (отрицательные дБ по мощности)."""
    return float(attenuation_db_array(np.array([theta_deg]), offset_deg, cal,
                                      metric, ref, zero_deg)[0])


def relative_to_zero_db(theta_deg: float, offset_deg: float, zero_deg: float,
                        cal: Calibration, metric: Metric = FULL) -> float:
    """ДОБАВОЧНАЯ величина относительно рабочей точки SET ZERO, дБ по мощности.

    `att(theta) - att(zero)` -- от выбора опорной мощности `ref` НЕ зависит
    (общий знаменатель сокращается), поэтому считается один раз в 'pmax'.
    Положительна = усиление (идём к совмещению), отрицательна = затухание.
    """
    return (attenuation_db(theta_deg, offset_deg, cal, metric, "pmax") -
            attenuation_db(zero_deg, offset_deg, cal, metric, "pmax"))


def fmt_db_bound(value: float, lower: bool) -> str:
    """Граница достижимого диапазона, округлённая ВНУТРЬ него.

    Обычное `{:.2f}` округляет к ближайшему и печатает НЕДОСТИЖИМОЕ число:
    дно кривой -40.90804 дБ показывалось как «-40.91», оператор вводил ровно
    его -- то, что прибор ему же и назвал, -- и получал «недостижимо: минимум
    -40.91 дБ». У стенда это читается как противоречие в приборе. Нижнюю
    границу округляем вверх, верхнюю вниз: напечатанное всегда достижимо.
    """
    r = round(value, 2)
    if lower and r < value - 1e-9:
        r += 0.01
    elif not lower and r > value + 1e-9:
        r -= 0.01
    return f"{r:.2f}"


def angle_for_db(target_db: float, offset_deg: float, cal: Calibration,
                 metric: Metric = FULL, ref: str = "pmax",
                 zero_deg: float | None = None, n: int = 901) -> dict:
    """Обратная задача: угол(ы) WGP1 для желаемого затухания (отрицательные дБ).

    Кривая затухания(delta), delta=theta-offset in [0,90], монотонно УБЫВАЕТ от
    `db_max` (delta=0, совмещённое положение) до `db_min` (delta=90,
    скрещенное). Симметрична по знаку delta (cos^2/sin^2 -- чётные), поэтому
    решения ДВА: offset+delta и offset-delta, физически равнозначны -- какое
    ближе к текущему положению ротатора, решает оператор (моторизации нет,
    `attenuator_app` C4_motor -- todo).

    В режиме ref='pzero' со сдвинутой рабочей точкой `db_max` > 0: цель можно
    задать положительной, это запрос усиления относительно SET ZERO.
    """
    delta = np.linspace(0.0, 90.0, n)
    atten = attenuation_db_array(offset_deg + delta, offset_deg, cal, metric, ref, zero_deg)
    db_max, db_min = float(atten[0]), float(atten[-1])
    if target_db > db_max + 1e-6:
        hint = ""
        if target_db > 0 and db_min - 1e-6 <= -target_db <= db_max + 1e-6:
            hint = f"; затухание задаётся ОТРИЦАТЕЛЬНЫМ числом -- возможно, нужно {-target_db:.2f} дБ"
        raise ValueError(f"выше максимума на этой калибровке: {fmt_db_bound(db_max, False)} дБ "
                         f"(совмещённое положение WGP1||WGP2, опора={REF_SHORT[ref]}){hint}")
    if target_db < db_min - 1e-6:
        raise ValueError(f"недостижимо на этой калибровке: минимум {fmt_db_bound(db_min, True)} дБ "
                         f"(скрещенное положение, {offset_deg + 90.0:+.3f} град)")
    atten_mono = np.minimum.accumulate(atten)      # защита от численного шума
    delta_sol = float(np.interp(target_db, atten_mono[::-1], delta[::-1]))
    return {"theta_plus_deg": offset_deg + delta_sol,
            "theta_minus_deg": offset_deg - delta_sol,
            "delta_deg": delta_sol, "db_max": db_max, "db_min": db_min}


def _wrap180(a: float) -> float:
    """Свернуть разность азимутов в (-90, +90]: азимут задан по модулю 180."""
    return (float(a) + 90.0) % 180.0 - 90.0


def angles_for_db_and_azimuth(target_db: float, azimuth_deg: float,
                              cal: Calibration, metric: Metric = FULL,
                              ref: str = "pmax", zero_pair: tuple | None = None,
                              n: int = 901, iters: int = 8,
                              tol_deg: float = 0.01) -> dict:
    """Обратная задача по ДВУМ углам: заданные ослабление И азимут на выходе.

    «Дай -20 дБ и поляризацию на выходе под 30 градусов». Две неизвестные, два
    уравнения. Азимут задаёт второй поляризатор, ослабление -- взаимный угол,
    поэтому решение ищется так: `theta2` ставится по требуемому азимуту, при
    нём одномерно подбирается `theta1`, затем `theta2` поправляется на
    невязку азимута. Связь азимута с `theta2` почти тождественна, увод даёт
    только утечка, поэтому сходимость занимает единицы итераций.

    ДВА ИСТОЧНИКА ОТКАЗА, оба физические, оба называются явно:

    1. При ЛИНЕЙНОМ источнике задачи связаны: пропускание идёт как
       cos^2(theta1-psi) * cos^2(theta2-theta1), то есть `theta1` работает и на
       ослабление тоже. Развернув выход на азимут `chi`, оператор уже теряет
       часть мощности, и слабое ослабление при сильно повёрнутом выходе
       недостижимо в принципе. При ДЕПОЛЯРИЗОВАННОМ источнике этого нет:
       после первого WGP интенсивность от `theta1` не зависит, и задача
       расщепляется точно -- `theta2` задаёт азимут, взаимный угол ослабление.

    2. У самого дна азимутом управлять нельзя. Пара ОДИНАКОВЫХ WGP в скрещении
       поляризационно нейтральна, и на выходе воспроизводится состояние
       источника, а не ось WGP2 (см. `service_model`, проверка T7). Поэтому
       пара «очень глубокое ослабление + заданный азимут» отвергается с
       указанием достигнутого азимута.

    Возвращает словарь с `theta1_deg`, `theta2_deg`, `delta_deg`, зеркальным
    решением `theta1_mirror_deg`, достигнутыми `achieved_db` / `achieved_azimuth_deg`
    и числом итераций. При недостижимости поднимает ValueError с причиной.
    """
    delta = np.linspace(0.0, 90.0, n)
    th2 = cal.off2_deg + float(azimuth_deg)
    best = None

    for it in range(1, iters + 1):
        arr2 = np.full_like(delta, th2)
        db = attenuation_db_pair(th2 - delta, arr2, cal, metric, ref, zero_pair)
        db_max, db_min = float(db[0]), float(db[-1])
        if target_db > db_max + 1e-9:
            raise ValueError(
                f"при азимуте выхода {azimuth_deg:+.2f}° ослабление не может быть "
                f"слабее {fmt_db_bound(db_max, False)} дБ: сам разворот выхода уже забирает "
                f"мощность ({cal.describe_source()}). Ближайшее достижимое "
                f"{fmt_db_bound(db_max, False)} дБ -- либо уменьшите азимут, либо "
                f"согласитесь на это ослабление")
        if target_db < db_min - 1e-9:
            raise ValueError(
                f"недостижимо на этой калибровке: минимум {fmt_db_bound(db_min, True)} дБ "
                f"в скрещенном положении. Ближайшее достижимое "
                f"{fmt_db_bound(db_min, True)} дБ")

        mono = np.minimum.accumulate(db)                # защита от численного шума
        d_sol = float(np.interp(target_db, mono[::-1], delta[::-1]))
        th1 = th2 - d_sol
        r = pair_response(np.array([th1]), np.array([th2]), cal, metric)
        chi = float(np.ravel(r["azimuth_deg"])[0])
        err = _wrap180(float(azimuth_deg) - chi)
        best = {"theta1_deg": th1, "theta2_deg": th2, "delta_deg": d_sol,
                "theta1_mirror_deg": th2 + d_sol,
                "achieved_db": float(np.ravel(
                    attenuation_db_pair(np.array([th1]), np.array([th2]),
                                        cal, metric, ref, zero_pair))[0]),
                "achieved_azimuth_deg": chi, "azimuth_error_deg": err,
                "iterations": it, "db_max": db_max, "db_min": db_min}
        if abs(err) <= tol_deg:
            return best
        th2 += err

    if best is not None and abs(best["azimuth_error_deg"]) > max(1.0, 10.0 * tol_deg):
        raise ValueError(
            f"на глубине {best['achieved_db']:.2f} дБ азимут не удерживается: "
            f"заказан {azimuth_deg:+.2f}°, достигнут {best['achieved_azimuth_deg']:+.2f}°. "
            f"Скрещенная пара одинаковых WGP поляризационно нейтральна, у дна на "
            f"выходе воспроизводится состояние источника, а не ось WGP2. "
            f"Отступите от дна (азимут держится лучше 0.4° примерно до -28 дБ) "
            f"либо откажитесь от контроля азимута на этой глубине")
    return best


def describe_point(theta_deg: float, offset_deg: float, zero_deg: float,
                   cal: Calibration, metric: Metric = FULL, ref: str = "pmax") -> dict:
    """Полное описание точки: значения во ВСЕХ трёх опорах сразу + добавочная
    величина относительно SET ZERO. Нужно, чтобы окно результатов показывало
    работу со сдвинутой точкой, а не одно число в выбранной шкале."""
    out = {"theta_deg": theta_deg}
    for r in REFS:
        db = attenuation_db(theta_deg, offset_deg, cal, metric, r, zero_deg)
        out[f"db_{r}"] = db
        out[f"pct_{r}"] = 10.0 ** (db / 10.0) * 100.0
    out["db_sel"] = out[f"db_{ref}"]
    out["pct_sel"] = out[f"pct_{ref}"]
    out["delta_zero_db"] = relative_to_zero_db(theta_deg, offset_deg, zero_deg, cal, metric)
    p_r, f_r = power_field_ratios(out["delta_zero_db"])
    out["delta_power_ratio"], out["delta_field_ratio"] = p_r, f_r
    return out


# --- CLI --------------------------------------------------------------
def _print_zero_block(theta_deg: float, offset_deg: float, zero_deg: float,
                      cal: Calibration, metric: Metric, ref: str) -> None:
    """Показать работу со сдвинутой рабочей точкой: обе точки во всех опорах."""
    q = describe_point(theta_deg, offset_deg, zero_deg, cal, metric, ref)
    z = describe_point(zero_deg, offset_deg, zero_deg, cal, metric, ref)
    print(f"  {'точка':<10} {'угол':>10} {'T/P_0':>10} {'T/P_max':>10} "
          f"{'T/P_zero':>10} {'дБ (' + REF_SHORT[ref] + ')':>14}")
    for name, d in (("SET ZERO", z), ("запрос", q)):
        print(f"  {name:<10} {d['theta_deg']:>+9.3f}° {d['pct_p0']:>9.2f}% "
              f"{d['pct_pmax']:>9.2f}% {d['pct_pzero']:>9.2f}% {d['db_sel']:>+13.2f}")
    dz = q["delta_zero_db"]
    kind = "УСИЛЕНИЕ" if dz > 0 else "затухание"
    print(f"  добавочно к рабочей точке: {dz:+.2f} дБ -- {kind}, "
          f"мощность x{q['delta_power_ratio']:.3g}, поле x{q['delta_field_ratio']:.3g}")


def _print_forward(theta_deg: float, offset_deg: float, zero_deg: float,
                   cal: Calibration, metric: Metric, ref: str) -> None:
    w = metric.warning(cal)
    if w:
        print(w)
    q = describe_point(theta_deg, offset_deg, zero_deg, cal, metric, ref)
    print(f"угол WGP1 = {theta_deg:+.3f} град "
          f"(от SET OFFSET {theta_deg - offset_deg:+.3f}, от SET ZERO {theta_deg - zero_deg:+.3f})")
    print(f"  затухание = {q['db_sel']:+.2f} дБ по мощности, "
          f"T = P/{REF_SHORT[ref]} = {q['pct_sel']:.3f} %")
    print()
    _print_zero_block(theta_deg, offset_deg, zero_deg, cal, metric, ref)


def _print_inverse(target_db: float, offset_deg: float, zero_deg: float,
                   cal: Calibration, metric: Metric, ref: str) -> None:
    w = metric.warning(cal)
    if w:
        print(w)
    sol = angle_for_db(target_db, offset_deg, cal, metric, ref, zero_deg)
    print(f"желаемое затухание {target_db:+.2f} дБ по мощности (опора {REF_SHORT[ref]}, "
          f"{metric.label}), диапазон [{fmt_db_bound(sol['db_min'], True)}, "
          f"{fmt_db_bound(sol['db_max'], False)}] дБ")
    print(f"  угол WGP1 = {sol['theta_plus_deg']:+.3f} град  (delta={sol['delta_deg']:+.3f})")
    print(f"  или       = {sol['theta_minus_deg']:+.3f} град  (delta={-sol['delta_deg']:+.3f})")
    print("  -- выбрать вариант ближе к текущему положению ротатора")
    print()
    _print_zero_block(sol["theta_plus_deg"], offset_deg, zero_deg, cal, metric, ref)


def metric_from_args(args) -> Metric:
    given = [args.freq is not None, args.band is not None,
             args.band_center is not None or args.band_width is not None]
    if sum(given) > 1:
        raise ValueError("--freq, --band и --band-center/--band-width взаимоисключающи")
    if args.freq is not None:
        return Metric("single", args.freq)
    if args.band is not None:
        return Metric("band_minmax", args.band[0], args.band[1])
    if args.band_center is not None or args.band_width is not None:
        if args.band_center is None or args.band_width is None:
            raise ValueError("--band-center и --band-width задаются вместе")
        return Metric("band_cw", args.band_center, args.band_width)
    return FULL


def _apply_setup_overrides(cal: Calibration, args) -> Calibration:
    """Переопределить источник и приёмник из командной строки.

    Калибровка описывает стенд, на котором её снимали; сегодняшняя установка
    может отличаться -- у неё другой приёмник или повёрнутый источник. Поэтому
    тип источника и приёмника задаётся флагами, а калибровка даёт умолчание.
    """
    if args.source is not None:
        cal.source_kind = args.source
    if args.psi is not None:
        cal.source_psi_deg = args.psi
    if args.dop is not None:
        cal.source_dop = args.dop
    if args.detector is not None:
        cal.detector_kind = args.detector
    if args.det_axis is not None:
        cal.detector_axis_deg = args.det_axis
    return cal


def _print_pair_point(theta1: float, theta2: float, cal: Calibration,
                      metric: Metric, ref: str) -> None:
    """Точка при двух углах: затухание и СОСТОЯНИЕ ПОЛЯРИЗАЦИИ на выходе."""
    db = float(np.ravel(attenuation_db_pair(np.array([theta1]), np.array([theta2]),
                                            cal, metric, ref))[0])
    r = pair_response(np.array([theta1]), np.array([theta2]), cal, metric)
    p_r, f_r = power_field_ratios(db)
    print(f"  WGP1 = {theta1:+.3f}°, WGP2 = {theta2:+.3f}°, "
          f"взаимный угол {_wrap180(theta2 - theta1 - cal.theta0_calibration_deg):+.3f}°")
    print(f"  затухание {db:+.2f} дБ ({REF_SHORT[ref]}), "
          f"мощность x{p_r:.4g}, поле x{f_r:.4g}")
    print(f"  на выходе: азимут {float(np.ravel(r['azimuth_deg'])[0]):+.3f}°, "
          f"эллиптичность {float(np.ravel(r['ellipticity_deg'])[0]):+.3f}°, "
          f"степень поляризации {float(np.ravel(r['dop'])[0]):.4f}")
    if cal.detector_kind == "power":
        print("  (приёмник мощностной -- азимут ему безразличен, но важен "
              "образцу ниже по тракту)")


def _print_pair_inverse(target_db: float, azimuth: float, cal: Calibration,
                        metric: Metric, ref: str) -> None:
    """Обратная задача по двум углам: заданы и затухание, и азимут выхода."""
    s = angles_for_db_and_azimuth(target_db, azimuth, cal, metric, ref)
    print(f"  цель: {target_db:+.2f} дБ при азимуте выхода {azimuth:+.2f}°")
    print(f"  решение: WGP1 = {s['theta1_deg']:+.3f}°, WGP2 = {s['theta2_deg']:+.3f}° "
          f"(взаимный угол {s['delta_deg']:.3f}°, итераций {s['iterations']})")
    print(f"  зеркальное решение по WGP1: {s['theta1_mirror_deg']:+.3f}° "
          f"-- выбирает оператор по текущему положению ротатора")
    print(f"  получится: {s['achieved_db']:+.3f} дБ, азимут "
          f"{s['achieved_azimuth_deg']:+.3f}° (невязка "
          f"{s['azimuth_error_deg']:+.4f}°)")
    print(f"  на этом азимуте доступно {fmt_db_bound(s['db_min'], True)} … "
          f"{fmt_db_bound(s['db_max'], False)} дБ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offset", type=float, default=None,
                    help="SET OFFSET (theta0): показание шкалы WGP1 в СОВМЕЩЁННОМ "
                         "положении, град. Физический параметр модели, по умолчанию "
                         "берётся из зашитой калибровки прибора")
    ap.add_argument("--zero", type=float, default=None,
                    help="SET ZERO: рабочая точка отсчёта, град. Относительно неё "
                         "считается добавочное затухание/усиление; при --ref pzero "
                         "она же точка нормировки. По умолчанию = SET OFFSET")
    ap.add_argument("--ref", choices=REFS, default="pmax",
                    help="опорная мощность в знаменателе T: p0 -- абсолютная (доля "
                         "мощности на входе); pmax (по умолчанию) -- к максимуму "
                         "(совмещённое положение); pzero -- к рабочей точке SET ZERO")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--to-db", type=float,
                   help="желаемое затухание (ОТРИЦАТЕЛЬНЫЕ дБ по мощности) -> угол")
    g.add_argument("--from-angle", type=float, help="текущий угол WGP1 (град) -> затухание")
    ap.add_argument("--freq", type=float, default=None, help="метрика: одна частота, ТГц")
    ap.add_argument("--band", type=float, nargs=2, metavar=("FMIN", "FMAX"),
                    help="метрика: полоса по минимуму и максимуму, ТГц")
    ap.add_argument("--band-center", type=float, default=None,
                    help="метрика: центр полосы, ТГц (вместе с --band-width)")
    ap.add_argument("--band-width", type=float, default=None,
                    help="метрика: ширина полосы, ТГц (вместе с --band-center)")
    ap.add_argument("--calibration", default=None, help="путь к JSON калибровки устройства")
    ap.add_argument("--theta2", type=float, default=None,
                    help="показание шкалы WGP2, град. Включает режим ДВУХ УГЛОВ: "
                         "--from-angle тогда задаёт WGP1, и выводится ещё и "
                         "состояние поляризации на выходе")
    ap.add_argument("--azimuth", type=float, default=None,
                    help="желаемый азимут поляризации НА ВЫХОДЕ, град. Вместе с "
                         "--to-db включает обратную задачу по двум углам")
    ap.add_argument("--source", choices=tuple(sm.SOURCES), default=None,
                    help="тип источника (по умолчанию из калибровки)")
    ap.add_argument("--psi", type=float, default=None,
                    help="азимут поляризации источника, град")
    ap.add_argument("--dop", type=float, default=None,
                    help="степень поляризации источника для --source partial")
    ap.add_argument("--detector", choices=tuple(sm.DETECTORS), default=None,
                    help="тип приёмника: coherent -- проекция поля на ось анализатора; "
                         "power -- полная мощность, оси анализатора нет")
    ap.add_argument("--det-axis", type=float, default=None,
                    help="ось анализатора когерентного приёмника, град")
    args = ap.parse_args()

    cal = load_calibration(Path(args.calibration)) if args.calibration else load_calibration()
    cal = _apply_setup_overrides(cal, args)
    offset = args.offset if args.offset is not None else cal.theta0_calibration_deg
    zero = args.zero if args.zero is not None else offset

    try:
        metric = metric_from_args(args)
    except ValueError as e:
        print(f"ошибка: {e}")
        return 1

    print(f"устройство {cal.device_id}, калибровка {cal.dataset} ({cal.generated}), "
          f"P={cal.P_um:.2f} D={cal.D_um:.2f} мкм, "
          f"потери={cal.loss_db:.3f} дБ/ТГц^{cal.gamma:.2f}")
    print(f"SET OFFSET = {offset:+.3f} град "
          f"({'из калибровки' if args.offset is None else 'задан вручную'})")
    print(f"SET ZERO   = {zero:+.3f} град "
          f"({'= SET OFFSET' if args.zero is None else 'сдвинут вручную'})")
    print(f"опора: {REF_LABEL[args.ref]}; метрика: {metric.label}")
    print(f"{cal.describe_setup()}\n")

    try:
        if args.azimuth is not None:
            if args.to_db is None:
                print("ошибка: --azimuth задаёт цель по азимуту и требует --to-db")
                return 1
            _print_pair_inverse(args.to_db, args.azimuth, cal, metric, args.ref)
        elif args.theta2 is not None:
            if args.from_angle is None:
                print("ошибка: --theta2 задаёт второй угол и требует --from-angle "
                      "(угол WGP1); для обратной задачи по двум углам нужен --azimuth")
                return 1
            _print_pair_point(args.from_angle, args.theta2, cal, metric, args.ref)
        elif args.to_db is not None:
            _print_inverse(args.to_db, offset, zero, cal, metric, args.ref)
        else:
            _print_forward(args.from_angle, offset, zero, cal, metric, args.ref)
    except ValueError as e:
        print(f"ошибка: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
