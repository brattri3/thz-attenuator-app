# -*- coding: utf-8 -*-
"""Два ортогональных сечения поверхности T(theta1, theta2).

Пропускание зависит от двух углов, поэтому одной кривой мало: сверху бежит
`theta1` при закреплённом `theta2`, снизу наоборот. Точка на обоих графиках
одна и та же и подписана тремя числами -- оба угла и значение (решение
владельца 2026-08-27).

Оси X НЕ связаны между собой: это разные переменные, и зум одного сечения не
должен двигать другое. Кривые не пересоздаются -- обновляются `setData`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.cwapp import theme                    # noqa: E402
from attenuator_app.cwapp.state import THETA_MAX, THETA_MIN   # noqa: E402


class SectionPlot(QtWidgets.QWidget):
    """Одно сечение: кривая, вертикаль в точке, точка с подписью."""

    def __init__(self, which: int, parent=None):
        super().__init__(parent)
        self.which = which                     # 1 или 2 -- какой угол по оси X
        pens = theme.pens()

        self.caption = QtWidgets.QLabel()
        self.caption.setObjectName("hint")

        self.plot = pg.PlotWidget()
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setXRange(THETA_MIN, THETA_MAX, padding=0.01)
        self.plot.setLabel("bottom", "θ%d, deg" % which)
        self.plot.setMenuEnabled(False)

        self.curve = self.plot.plot([], [], pen=pens["model"])
        self.vline = pg.InfiniteLine(angle=90, pen=pens["cursor"], movable=False)
        self.plot.addItem(self.vline)
        self.dot = pg.ScatterPlotItem(size=9, brush=pens["mark"],
                                      pen=pg.mkPen(theme.SURFACE, width=1.6))
        self.plot.addItem(self.dot)
        self.text = pg.TextItem(color=theme.INK, anchor=(0, 1))
        self.text.setFont(QtCore.QCoreApplication.instance().font())
        self.plot.addItem(self.text)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.caption)
        lay.addWidget(self.plot, 1)

    # -- отрисовка ------------------------------------------------------
    def update_from(self, result, units: str) -> None:
        """Перерисовать по готовому CwResult. Своей физики здесь нет."""
        p = result.params
        y = result.curve(self.which, units)
        x = result.theta

        self.plot.setLabel("left", theme.axis_label(units))
        lo, hi = theme.limits(units)
        self.plot.setYRange(lo, hi, padding=0.0)
        self.curve.setData(x, y)

        point_th = p.theta1_deg if self.which == 1 else p.theta2_deg
        value = result.value_db if units == "dB" else result.value_percent
        self.vline.setPos(point_th)
        self.dot.setData([point_th], [value])

        shown = ("%+.2f dB" % value) if units == "dB" else ("%.2f %%" % value)
        self.text.setText("θ₁ %+.1f°, θ₂ %+.1f° → %s"
                          % (p.theta1_deg, p.theta2_deg, shown))
        # подпись уводится влево у правого края и вниз от точки, если та стоит у верхней границы
        # поля: иначе текст срезается рамкой (поймано на снимке)
        lo, hi = theme.limits(units)
        near_top = value > lo + 0.86 * (hi - lo)
        near_right = point_th > (THETA_MIN + THETA_MAX) / 2.0 + 25.0
        self.text.setAnchor((1 if near_right else 0, 0 if near_top else 1))
        self.text.setPos(point_th + (-2.0 if near_right else 2.0), value)

        fixed = p.theta2_deg if self.which == 1 else p.theta1_deg
        other = 2 if self.which == 1 else 1
        self.caption.setText("θ%d varies, θ%d held at %+.1f°"
                             % (self.which, other, fixed))


class PlotPanel(QtWidgets.QWidget):
    """Оба сечения одно под другим."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.top = SectionPlot(1)
        self.bottom = SectionPlot(2)

        title = QtWidgets.QLabel("Attenuation vs rotator angles")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        subtitle = QtWidgets.QLabel()
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        self.subtitle = subtitle
        self._set_subtitle(None)

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.addWidget(self.top)
        split.addWidget(self.bottom)
        split.setSizes([1, 1])
        split.setChildrenCollapsible(False)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 6)
        lay.setSpacing(3)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addWidget(split, 1)

    def _set_subtitle(self, result) -> None:
        """Подпись под заголовком: где стоит опора и чем это грозит.

        Опора -- максимум по обоим углам (решение владельца П-2 от 27.08). При
        неповёрнутом источнике максимум лежит в нуле шкал, и подпись читается
        так же, как раньше. Как только источник наклонён, опора уезжает, и
        сказать об этом обязательно: 0 дБ перестаёт отвечать нулю шкал, и два
        протокола с разным азимутом источника несравнимы по абсолютной
        величине. Молча выдать такие числа -- значит дать оператору сравнить
        их и получить расхождение из ниоткуда.
        """
        head = "two orthogonal sections through the same surface · "
        if result is None or result.reference_is_at_zero:
            self.subtitle.setText(head + "0 dB = maximum transmission, "
                                         "here at θ₁ = θ₂ = 0")
            self.subtitle.setObjectName("hint")
        else:
            t1, t2 = result.reference_at
            self.subtitle.setText(
                head + "0 dB = maximum transmission, which the tilted source "
                "moves to θ₁ %+.2f°, θ₂ %+.2f° — readings are not comparable "
                "with runs at a different source azimuth" % (t1, t2))
            self.subtitle.setObjectName("warn")
        self.subtitle.style().unpolish(self.subtitle)
        self.subtitle.style().polish(self.subtitle)

    def update_from(self, result, units: str) -> None:
        self.top.update_from(result, units)
        self.bottom.update_from(result, units)
        self._set_subtitle(result)
