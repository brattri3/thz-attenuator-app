# -*- coding: utf-8 -*-
"""Параметры CW-приложения: только данные, никакого Qt и никакой физики.

Отдельный модуль, потому что от него зависят две разные вещи -- расчётный слой
(`model.py`) и раскладка окна. Правило «какое поле сейчас имеет смысл»
(`enabled_fields`) живёт здесь, а не внутри слота виджета: иначе его нельзя
проверить, не подняв окно, а именно такие правила и разъезжаются молча.

MVP v0.1 (решение владельца 2026-08-27): один вопрос -- какое пропускание даёт
пара углов на выбранной частоте. Офсеты насадок приняты нулевыми, диапазон
углов -90..+90, шаг сетки фиксирован; всё это возвращается в поздних версиях,
см. `docs/attenuator_app/13_CW_APP_RELEASES.md`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

#: типы источника -- имена совпадают с `service_model.SOURCES`
SOURCES = ("linear", "unpolarized", "partial")
#: типы приёмника -- имена совпадают с `service_model.DETECTORS`
DETECTORS = ("coherent", "power")
#: единицы вертикальной оси
UNITS = ("dB", "percent")

#: границы свипа, MVP: жёсткие
THETA_MIN, THETA_MAX, THETA_STEP = -90.0, 90.0, 1.0
#: на сколько градусов оценивается цена ошибки установки угла
ANGLE_TOLERANCE_DEG = 1.0


@dataclass(frozen=True)
class CwParams:
    """Полный набор входных данных одного расчёта."""

    freq_thz: float = 0.200
    theta1_deg: float = 0.0
    theta2_deg: float = 0.0
    source: str = "linear"
    psi_deg: float = 0.0
    dop: float = 1.0
    detector: str = "coherent"
    analyzer_deg: float = 0.0
    units: str = "dB"

    def validate(self) -> None:
        """ValueError с текстом для оператора, а не для автора кода."""
        if self.source not in SOURCES:
            raise ValueError("unknown source %r, expected one of %s"
                             % (self.source, ", ".join(SOURCES)))
        if self.detector not in DETECTORS:
            raise ValueError("unknown detector %r, expected one of %s"
                             % (self.detector, ", ".join(DETECTORS)))
        if self.units not in UNITS:
            raise ValueError("unknown units %r, expected one of %s"
                             % (self.units, ", ".join(UNITS)))
        # частота <= 0 даёт nan, а не отказ: длина волны обращается в
        # бесконечность. Тот же дефект уже ловили в service_gui 2026-08-27
        if not self.freq_thz > 0.0:
            raise ValueError("frequency must be greater than zero")
        for name, value in (("theta1", self.theta1_deg), ("theta2", self.theta2_deg)):
            if not THETA_MIN <= value <= THETA_MAX:
                raise ValueError("%s must be within %+.0f...%+.0f deg"
                                 % (name, THETA_MIN, THETA_MAX))
        if not 0.0 <= self.dop <= 1.0:
            raise ValueError("degree of polarization must be within 0...1")

    def with_(self, **kw) -> "CwParams":
        """Копия с изменёнными полями -- параметры неизменяемы намеренно."""
        return replace(self, **kw)


def enabled_fields(p: CwParams) -> set[str]:
    """Какие поля сейчас влияют на результат.

    Остальные гасятся в окне, а не прячутся: оператор должен видеть, что
    параметр существует, но здесь не работает. Иначе он покрутит ось
    анализатора при болометре, ничего не изменится, и вывод будет «прибор
    сломан».
    """
    fields = {"freq_thz", "theta1_deg", "theta2_deg", "source", "detector", "units"}
    if p.source == "linear":
        fields.add("psi_deg")
    elif p.source == "partial":
        fields.add("psi_deg")
        fields.add("dop")
    # unpolarized: азимута нет вовсе, DOP = 0 по определению типа
    if p.detector == "coherent":
        fields.add("analyzer_deg")
    return fields


def disabled_reason(p: CwParams, field: str) -> str | None:
    """Почему поле погашено -- строкой под группой, в терминах физики."""
    if field in enabled_fields(p):
        return None
    if field == "analyzer_deg":
        return "power detector is polarization-insensitive — the analyzer axis has no effect"
    if field == "psi_deg":
        return "a depolarized source has no azimuth (DOP = 0)"
    if field == "dop":
        return "a fully polarized or fully depolarized source has DOP fixed at 1 or 0"
    return None


# --- где лежит паспорт прибора ------------------------------------------
#: подкаталог рядом с программой, куда оператор кладёт паспорт своего прибора
PASSPORT_SUBDIR = "passports"


def program_dir() -> Path:
    """Каталог, «рядом с которым» оператор кладёт паспорт.

    ⚠ Под PyInstaller это `Path(sys.executable).parent`, и никак иначе.
    `__file__` в собранном `.exe` указывает во временный распакованный
    `_MEIPASS`, который создаётся заново при каждом запуске и стирается при
    выходе: положенный оператором паспорт там не найдётся никогда, а
    приложение молча возьмёт зашитый образец и посчитает верной арифметикой
    неверные числа. Из исходников ошибка не проявляется вовсе -- отсюда и
    проверка `passport_candidates` на поддельном `sys.frozen` в приёмке.

    Из исходников «рядом с программой» -- корень репозитория, а не каталог
    интерпретатора: класть паспорт рядом с `python.exe` никто не станет.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def passport_candidates(explicit=None, base: Path | None = None) -> list[Path]:
    """Пути к паспорту в порядке предпочтения, без единого обращения к диску
    сверх перечисления каталога.

    Порядок задан владельцем (хэндофф 27.08): явный выбор в интерфейсе ->
    каталог рядом с исполняемым файлом -> зашитый образец последним рубежом.
    Сам образец сюда не входит: он подставляется расчётным слоем, когда ни
    один кандидат не подошёл, и в интерфейсе это видно отдельной пометкой.

    Функция чистая (кроме `glob`) и проверяется без запуска окна -- правило
    поиска файла из тех, что разъезжаются молча.
    """
    out: list[Path] = []
    if explicit:
        out.append(Path(explicit))
    root = Path(base) if base is not None else program_dir()
    for folder in (root / PASSPORT_SUBDIR, root):
        try:
            found = sorted(folder.glob("*.json"))
        except OSError:                    # каталога нет или он недоступен
            continue
        out.extend(f for f in found if f not in out)
    return out
