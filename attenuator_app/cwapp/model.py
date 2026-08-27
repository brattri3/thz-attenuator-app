# -*- coding: utf-8 -*-
"""Расчётный слой CW-приложения: состояние + вызовы сервисного ядра.

**Здесь нет ни одной формулы и ни одного импорта Qt.** Вся физика приходит из
`attenuator_app.tools.service_calc`; этот модуль только собирает параметры,
зовёт ядро и раскладывает ответ так, как его показывает окно. Разделение
сделано ради проверяемости: числа сверяются приёмкой без запуска окна
(`selftest.py`), а окно проверяется отдельно. Именно этого разделения не
хватало облачной сессии, чей мок-импорт не поймал разрыв метода в `service_gui`.

Ядро сервисное, а не клиентское (решение владельца 2026-08-27): отсюда
ОТРИЦАТЕЛЬНЫЕ децибелы, три опоры нормировки в ядре и два независимых угла
ротаторов. Подробности выбора -- `docs/attenuator_app/13_CW_APP_RELEASES.md`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.tools.service_calc import (           # noqa: E402
    DEFAULT_CALIBRATION_PATH, Calibration, Metric, attenuation_db_pair,
    load_calibration)
from attenuator_app.cwapp.state import (                  # noqa: E402
    ANGLE_TOLERANCE_DEG, THETA_MAX, THETA_MIN, THETA_STEP, CwParams,
    passport_candidates)


#: шаг уточнения максимума в окрестности лучшего узла грубой сетки
PEAK_FINE_STEP = 0.05


def theta_grid() -> np.ndarray:
    """Сетка свипа. Одна на оба сечения -- числа обязаны совпадать."""
    return np.arange(THETA_MIN, THETA_MAX + THETA_STEP / 2.0, THETA_STEP)


@dataclass
class CwResult:
    """Всё, что окно показывает по одному расчёту."""

    params: CwParams
    theta: np.ndarray
    #: сечение при бегущем theta1 и закреплённом theta2
    vs_theta1_db: np.ndarray
    #: сечение при бегущем theta2 и закреплённом theta1
    vs_theta2_db: np.ndarray
    #: значение в самой точке (theta1, theta2)
    value_db: float
    #: цена ошибки в 1 градус по каждому углу: (минус, плюс)
    err_theta1_db: tuple[float, float]
    err_theta2_db: tuple[float, float]
    #: где стоит максимум, к которому нормировано показание (theta1, theta2).
    #: Окно обязано это показывать: после решения П-2 опора уезжает вместе с
    #: азимутом источника, и молчать о её положении -- значит выдавать числа,
    #: которые не с чем сравнить
    reference_at: tuple[float, float] | None = None

    @property
    def reference_is_at_zero(self) -> bool:
        """Совпадает ли опора с нулём обеих шкал ротаторов."""
        if self.reference_at is None:
            return True
        return abs(self.reference_at[0]) < 1e-9 and abs(self.reference_at[1]) < 1e-9

    @staticmethod
    def to_percent(db):
        """Отрицательные дБ -> проценты пропускания. 0 дБ = 100 %."""
        return 10.0 ** (np.asarray(db, dtype=float) / 10.0) * 100.0

    @property
    def value_percent(self) -> float:
        return float(self.to_percent(self.value_db))

    @property
    def combined_error_db(self) -> float:
        """Совместная оценка при ошибке 1 градус по каждому углу.

        Квадратичное сложение: ошибки установки двух ротаторов независимы.
        Берётся худшая сторона по каждому углу -- оценка сознательно
        консервативная, как и весь бюджет неопределённости в этом проекте.
        """
        e1 = max(abs(self.err_theta1_db[0]), abs(self.err_theta1_db[1]))
        e2 = max(abs(self.err_theta2_db[0]), abs(self.err_theta2_db[1]))
        return float((e1 ** 2 + e2 ** 2) ** 0.5)

    def curve(self, which: int, units: str):
        """Сечение в запрошенных единицах. which = 1 или 2."""
        db = self.vs_theta1_db if which == 1 else self.vs_theta2_db
        return db if units == "dB" else self.to_percent(db)


class CwModel:
    """Состояние приложения. Один экземпляр на окно."""

    def __init__(self, calibration_path=None, params: CwParams | None = None):
        self.cal, self.passport_path, self.passport_note = self._open_passport(
            calibration_path)
        # MVP: офсеты насадок приняты нулевыми (решение владельца 2026-08-27).
        # Погрешность установки поляризатора в ротатор учитывается оценкой
        # цены ошибки в 1 градус, а не отдельным параметром модели.
        self.cal.off1_deg = 0.0
        self.cal.off2_deg = 0.0
        # умолчание частоты -- середина откалиброванной полосы: со старым
        # значением 0.200 ТГц приложение поднималось сразу с предупреждением
        # об экстраполяции, хотя оператор ещё ничего не ввёл
        lo, hi = self.cal.band_thz
        self.params = params or CwParams(freq_thz=round((lo + hi) / 2.0, 3))
        self._result: CwResult | None = None
        #: опора нормировки: {ключ конфигурации: (дБ, (theta1, theta2))}
        self._ref_cache: dict = {}

    # -- паспорт прибора -----------------------------------------------
    @staticmethod
    def _open_passport(explicit=None):
        """Первый годный паспорт из порядка поиска, иначе зашитый образец.

        Кандидат проверяется тем же чтением, каким потом пользуется расчёт:
        рядом с программой может лежать посторонний JSON (в том числе паспорт
        другого формата -- из tkinter-линии), и падать на старте из-за чужого
        файла приложение не должно. Негодный кандидат пропускается, причина
        доходит до интерфейса вместе с именем взятого файла.

        Возвращает (калибровка, путь, пометка для строки состояния).
        """
        skipped: list[str] = []
        for path in passport_candidates(explicit):
            try:
                cal = load_calibration(path)
            except (OSError, ValueError, KeyError, TypeError) as e:
                # ЯВНО выбранный файл отказывает громко. Тихо перейти к
                # следующему кандидату здесь нельзя: оператор указал файл
                # пальцем, а расчёт пошёл бы по образцу -- ровно та подмена,
                # ради которой правка и делалась
                if explicit is not None and Path(path) == Path(explicit):
                    raise ValueError("%s is not a valid passport file (%s)"
                                     % (path.name, type(e).__name__)) from e
                skipped.append("%s (%s)" % (path.name, type(e).__name__))
                continue
            note = "passport %s" % path.name
            if skipped:
                note += " · skipped %s" % ", ".join(skipped)
            return cal, path, note
        # последний рубеж: обезличенный образец внутри пакета. Молчать об этом
        # нельзя -- на образце считать можно, измерять нельзя
        cal = load_calibration(DEFAULT_CALIBRATION_PATH)
        note = "built-in SAMPLE — not your device"
        if skipped:
            note += " · skipped %s" % ", ".join(skipped)
        return cal, DEFAULT_CALIBRATION_PATH, note

    # -- служебное -----------------------------------------------------
    def _apply(self, p: CwParams) -> None:
        """Перенести схему тракта из параметров в калибровку ядра."""
        self.cal.source_kind = p.source
        self.cal.source_psi_deg = float(p.psi_deg)
        self.cal.source_dop = 1.0 if p.source == "linear" else (
            0.0 if p.source == "unpolarized" else float(p.dop))
        self.cal.detector_kind = p.detector
        self.cal.detector_axis_deg = float(p.analyzer_deg)

    def _db(self, th1, th2, metric: Metric) -> np.ndarray:
        return np.asarray(attenuation_db_pair(
            np.asarray(th1, dtype=float), np.asarray(th2, dtype=float),
            self.cal, metric, "pmax"), dtype=float)

    def _reference_db(self, metric: Metric) -> float:
        """Максимум пропускания по обоим углам -- к нему нормируется всё.

        Решение владельца П-2 от 2026-08-27: опора -- **максимум кривой**, а не
        отсчёт при theta1 = theta2 = 0. При повёрнутом источнике максимум
        уезжает с нуля шкал (при psi = 45° -- на theta1 = +30°, theta2 = +15°),
        и нормировка на нуль шкал давала «пропускание больше 100 %».

        Цена решения, о которой окно обязано сказать оператору: 0 дБ больше не
        отвечает нулю шкал и уезжает вместе с psi, поэтому два протокола с
        разным наклоном источника несравнимы по абсолютной величине.

        Максимум берётся по ПОВЕРХНОСТИ, а не по текущему сечению: опора,
        зависящая от закреплённого угла, прыгала бы при каждом движении
        второго ротатора, и кривая ездила бы вверх-вниз сама по себе.

        При psi = 0 максимум лежит ровно в нуле шкал, и новая опора совпадает
        со старой до последнего знака -- прежние числа и опорная точка сверки
        с CLI (-4.77 дБ при 40°/0°/0.8 ТГц) не тронуты.
        """
        key = (self.cal.source_kind, float(self.cal.source_psi_deg),
               float(self.cal.source_dop), self.cal.detector_kind,
               float(self.cal.detector_axis_deg), metric.kind, metric.a, metric.b)
        hit = self._ref_cache.get(key)
        if hit is not None:
            return hit[0]
        ref, at = self._find_peak(metric)
        # кэш держит одну запись: конфигурация меняется реже, чем углы, а
        # движение слайдера углов не должна сопровождать переоценка опоры
        self._ref_cache = {key: (ref, at)}
        return ref

    def _find_peak(self, metric: Metric) -> tuple[float, tuple[float, float]]:
        """Максимум по (theta1, theta2): грубая сетка, затем уточнение.

        Сетка шага свипа стоит около 65 мс на 181x181 -- дешевле, чем кажется,
        потому что ядро векторное. Уточнение в окрестности лучшего узла даёт
        меньше 0.001 дБ прибавки, но снимает зависимость опоры от того, попал
        ли максимум в узел сетки: систематический сдвиг опоры уехал бы во ВСЕ
        показания разом, и заметить его по одному числу было бы нечем.
        """
        th = theta_grid()
        t1, t2 = np.meshgrid(th, th, indexing="ij")
        grid = self._db(t1.ravel(), t2.ravel(), metric).reshape(t1.shape)
        i = np.unravel_index(int(np.argmax(grid)), grid.shape)
        c1, c2 = float(t1[i]), float(t2[i])

        step = THETA_STEP
        f1 = np.clip(np.arange(c1 - step, c1 + step + PEAK_FINE_STEP / 2,
                               PEAK_FINE_STEP), THETA_MIN, THETA_MAX)
        f2 = np.clip(np.arange(c2 - step, c2 + step + PEAK_FINE_STEP / 2,
                               PEAK_FINE_STEP), THETA_MIN, THETA_MAX)
        g1, g2 = np.meshgrid(f1, f2, indexing="ij")
        fine = self._db(g1.ravel(), g2.ravel(), metric).reshape(g1.shape)
        j = np.unravel_index(int(np.argmax(fine)), fine.shape)
        if float(fine[j]) < float(grid[i]):        # уточнение не ухудшает опору
            return float(grid[i]), (c1, c2)
        return float(fine[j]), (float(g1[j]), float(g2[j]))

    def reference_at(self) -> tuple[float, float] | None:
        """Где стоит максимум, к которому нормировано текущее показание."""
        for ref, at in self._ref_cache.values():
            return at
        return None

    # -- расчёт --------------------------------------------------------
    def compute(self, params: CwParams | None = None) -> CwResult:
        """Полный пересчёт. ValueError с текстом для оператора при мусоре."""
        p = params or self.params
        p.validate()
        self.params = p
        self._apply(p)

        metric = Metric("single", a=float(p.freq_thz))
        ref = self._reference_db(metric)
        th = theta_grid()

        vs1 = self._db(th, np.full_like(th, p.theta2_deg), metric) - ref
        vs2 = self._db(np.full_like(th, p.theta1_deg), th, metric) - ref
        here = float(self._db([p.theta1_deg], [p.theta2_deg], metric)[0]) - ref

        d = ANGLE_TOLERANCE_DEG
        e1 = tuple(float(self._db([p.theta1_deg + s * d], [p.theta2_deg], metric)[0])
                   - ref - here for s in (-1.0, +1.0))
        e2 = tuple(float(self._db([p.theta1_deg], [p.theta2_deg + s * d], metric)[0])
                   - ref - here for s in (-1.0, +1.0))

        self._result = CwResult(params=p, theta=th, vs_theta1_db=vs1,
                                vs_theta2_db=vs2, value_db=here,
                                err_theta1_db=e1, err_theta2_db=e2,
                                reference_at=self.reference_at())
        return self._result

    @property
    def result(self) -> CwResult | None:
        return self._result

    # -- сводки для окна -----------------------------------------------
    def device_line(self) -> str:
        """Строка состояния: прибор, набор калибровки и ОТКУДА он взят.

        Источник паспорта в интерфейсе обязателен (требование владельца,
        хэндофф 27.08): подмена паспорта зашитым образцом ничем себя не
        выдаёт -- окно исправно, числа правдоподобны, прибор чужой.
        """
        return "%s · calibration %s · %s" % (
            self.cal.device_id, self.cal.dataset, self.passport_note)

    def band_warning(self) -> str | None:
        """Предупреждение об экстраполяции за полосу калибровки.

        Модель посчитает и на 0.140 ТГц при полосе 0.30...1.50, но это
        экстраполяция вдвое ниже нижней границы, и молчать об этом нельзя.
        """
        lo, hi = self.cal.band_thz
        f = self.params.freq_thz
        if lo <= f <= hi:
            return None
        return ("%.3f THz is outside the calibrated band %.2f–%.2f THz — "
                "the value is extrapolated, not measured" % (f, lo, hi))
