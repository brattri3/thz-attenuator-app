# -*- coding: utf-8 -*-
"""Палитра и оформление окна.

Цвета берутся из `attenuator_app.core.plots` -- того же модуля, которым
рисуются PNG в остальном проекте. Один источник на два рендерера: иначе экран
и печатная картинка разъедутся молча при первой же правке палитры.

Импорт `core.plots` НЕ тянет matplotlib: там он подгружается лениво, а сами
цвета лежат обычными строками на уровне модуля.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.core import plots                     # noqa: E402

SERIES = plots.SERIES          # синий / оранжевый / бирюзовый
SURFACE = plots.SURFACE        # фон поля графика
INK = plots.INK                # основной текст
INK2 = plots.INK2              # вторичный текст
MUTED = plots.MUTED            # подписи осей
GRID = plots.GRID              # сетка
AXIS = plots.AXIS              # рамки и линии осей
STATUS = plots.STATUS          # good / warning / critical

MODEL = SERIES[0]              # кривая прибора
MARK = SERIES[1]               # точка запроса
PANEL = "#f4f3ef"              # фон панелей окна
LINE = "#dcdbd4"               # разделители

#: запас над 100 % и над 0 дБ. При наклонённом источнике максимум уезжает с
#: нуля шкал, и кривая слегка превышает опорный отсчёт -- это верно физически,
#: и обрезать макушку нельзя (решение владельца 2026-08-27)
DB_LIMITS = (-55.0, 1.0)
PCT_LIMITS = (0.0, 105.0)

FONT_UI = "Segoe UI"
FONT_MONO = "Cascadia Mono"

# ВАЖНО: общего правила `QWidget { ... }` здесь нет и быть не должно. Любое
# правило таблицы стилей, задевающее QRadioButton (в том числе через QWidget),
# отключает нативную отрисовку индикатора, и ВЫБРАННЫЙ пункт становится
# неотличим от невыбранного -- кружок просто пропадает. Поймано на снимке
# дымового прогона 2026-08-27. Шрифт задаётся объектом приложения
# (`configure_fonts`), а фон -- поимённо тем контейнерам, которым он нужен.
QSS = """
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget, QStatusBar {
    background: %(panel)s; }
QGroupBox { border: 1px solid %(line)s; border-radius: 3px; margin-top: 14px;
            padding: 6px 6px 8px 6px; background: %(surface)s; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px;
                   color: %(ink2)s; font-size: 11px; font-weight: 600; }
QLabel#hint { color: %(muted)s; font-size: 11px; }
QLabel#warn { color: %(warn)s; font-size: 11px; }
QLabel:disabled { color: %(muted)s; }
QDoubleSpinBox, QLineEdit, QComboBox { background: #ffffff; border: 1px solid %(axis)s;
                                       border-radius: 2px; padding: 3px 4px; }
QDoubleSpinBox:disabled { color: %(muted)s; background: %(panel)s; }
QPushButton { background: %(panel)s; border: 1px solid %(axis)s; border-radius: 2px;
              padding: 5px 12px; }
QPushButton:hover { background: #ecebe6; }
QScrollArea { border: none; }
QStatusBar { border-top: 1px solid %(line)s; color: %(ink2)s; }
""" % {"panel": PANEL, "ink2": INK2, "muted": MUTED, "line": LINE,
       "surface": SURFACE, "axis": AXIS, "warn": STATUS["warning"]}


def configure_fonts(app) -> None:
    """Шрифт приложения. Через QFont, а не через таблицу стилей -- см. QSS."""
    from PySide6.QtGui import QFont

    font = QFont(FONT_UI, 9)
    app.setFont(font)
    mono = QFont(FONT_MONO, 9)
    mono.setStyleHint(QFont.Monospace)
    return mono


def configure_locale() -> None:
    """Числа с точкой, а не с запятой.

    Windows с русской локалью отдаёт QLocale по системе, и спинбоксы начинают
    показывать «0,200 THz». В английском интерфейсе это неверно, а скопированное
    в протокол число ещё и перестаёт разбираться обратно.
    """
    from PySide6.QtCore import QLocale

    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))


def configure_pyqtgraph() -> None:
    """Глобальные настройки pyqtgraph под палитру проекта."""
    import pyqtgraph as pg

    pg.setConfigOption("background", SURFACE)
    pg.setConfigOption("foreground", INK2)
    pg.setConfigOption("antialias", True)


def pens():
    """Перья графика. Отдельной функцией -- Qt должен быть уже поднят."""
    import pyqtgraph as pg
    from PySide6.QtCore import Qt

    return {
        "model": pg.mkPen(MODEL, width=2),
        "grid": pg.mkPen(GRID, width=1),
        "cursor": pg.mkPen(INK2, width=1, style=Qt.DashLine),
        "mark": pg.mkBrush(MARK),
    }


def limits(units: str) -> tuple[float, float]:
    return DB_LIMITS if units == "dB" else PCT_LIMITS


def axis_label(units: str) -> str:
    return "attenuation, dB" if units == "dB" else "transmission, %"
