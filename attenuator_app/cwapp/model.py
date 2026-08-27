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
        """Отсчёт при theta1 = theta2 = 0 -- к нему нормируется всё.

        Опора выбирается не оператором (в MVP её нет в интерфейсе): в нуле
        обоих шкал ровно 0 дБ и 100 %. При наклонённом источнике максимум
        уезжает с нуля, и кривая может слегка превысить 100 % -- это верное
        поведение, а не ошибка, шкала окна оставляет запас сверху.
        """
        return float(self._db([0.0], [0.0], metric)[0])

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
                                err_theta1_db=e1, err_theta2_db=e2)
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
