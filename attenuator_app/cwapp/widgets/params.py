# -*- coding: utf-8 -*-
"""Панель ввода параметров.

Виджеты не считают физику и не решают, что имеет смысл: правило гашения полей
приходит готовым из `state.enabled_fields()` -- чистой функции, которая
проверяется приёмкой без запуска окна.

Поля гасятся, а не прячутся: оператор должен видеть, что параметр существует,
но здесь не работает. Иначе он покрутит ось анализатора при болометре, ничего
не изменится, и вывод будет «прибор сломан».
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.cwapp.state import (                  # noqa: E402
    THETA_MAX, THETA_MIN, CwParams, disabled_reason, enabled_fields)

#: пауза перед пересчётом: клики по стрелке спинбокса не должны давать
#: пересчёт на каждый шаг
DEBOUNCE_MS = 120


def _spin(value, lo, hi, step, decimals, suffix=""):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)      # пересчёт по завершении ввода, не на символ
    s.setMinimumWidth(96)
    f = QtGui.QFont("Cascadia Mono", 9)
    f.setStyleHint(QtGui.QFont.Monospace)
    s.setFont(f)
    return s


class ParamsPanel(QtWidgets.QScrollArea):
    """Слева от графиков. Сигнал `changed` несёт готовые параметры."""

    changed = QtCore.Signal(object)

    def __init__(self, params: CwParams, parent=None):
        super().__init__(parent)
        self._loading = True          # защита от рекурсии сигналов
        self._syncing = False         # поле <-> слайдер, чтобы не зациклиться
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        lay.addWidget(self._build_source(params))
        lay.addWidget(self._build_detector(params))
        lay.addWidget(self._build_angles(params))
        lay.addWidget(self._build_frequency(params))
        lay.addWidget(self._build_units(params))
        lay.addStretch(1)
        self.setWidget(body)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)

        self._loading = False
        self._sync_enabled()

    # -- группы ---------------------------------------------------------
    def _group(self, title):
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QVBoxLayout(box)
        form.setContentsMargins(8, 4, 8, 6)
        form.setSpacing(4)
        return box, form

    def _row(self, label, widget):
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = QtWidgets.QLabel(label)
        lab.setMinimumWidth(78)
        h.addWidget(lab)
        h.addWidget(widget, 1)
        return row, lab

    def _build_source(self, p):
        box, form = self._group("Source")
        self.src_buttons = {}
        group = QtWidgets.QButtonGroup(self)
        for kind, label in (("linear", "linear"),
                            ("unpolarized", "unpolarized"),
                            ("partial", "partial")):
            b = QtWidgets.QRadioButton(label)
            b.setChecked(p.source == kind)
            b.toggled.connect(self._touch)
            group.addButton(b)
            self.src_buttons[kind] = b
            form.addWidget(b)
        self.psi = _spin(p.psi_deg, -180.0, 180.0, 1.0, 2, " °")
        self.psi.valueChanged.connect(self._touch)
        row, self.psi_label = self._row("Azimuth ψ", self.psi)
        form.addWidget(row)
        self.dop = _spin(p.dop, 0.0, 1.0, 0.05, 2)
        self.dop.valueChanged.connect(self._touch)
        row, self.dop_label = self._row("DOP", self.dop)
        form.addWidget(row)
        self.src_hint = QtWidgets.QLabel()
        self.src_hint.setObjectName("hint")
        self.src_hint.setWordWrap(True)
        form.addWidget(self.src_hint)
        return box

    def _build_detector(self, p):
        box, form = self._group("Detector")
        self.det_buttons = {}
        group = QtWidgets.QButtonGroup(self)
        for kind in ("coherent", "power"):
            b = QtWidgets.QRadioButton(kind)
            b.setChecked(p.detector == kind)
            b.toggled.connect(self._touch)
            group.addButton(b)
            self.det_buttons[kind] = b
            form.addWidget(b)
        self.analyzer = _spin(p.analyzer_deg, -180.0, 180.0, 1.0, 2, " °")
        self.analyzer.valueChanged.connect(self._touch)
        row, self.analyzer_label = self._row("Analyzer", self.analyzer)
        form.addWidget(row)
        self.det_hint = QtWidgets.QLabel()
        self.det_hint.setObjectName("hint")
        self.det_hint.setWordWrap(True)
        form.addWidget(self.det_hint)
        return box

    def _build_angles(self, p):
        box, form = self._group("Angles")
        self.theta1 = _spin(p.theta1_deg, THETA_MIN, THETA_MAX, 1.0, 2, " °")
        self.theta2 = _spin(p.theta2_deg, THETA_MIN, THETA_MAX, 1.0, 2, " °")
        for s in (self.theta1, self.theta2):
            s.valueChanged.connect(self._touch)
        r1, _ = self._row("θ₁  first grid", self.theta1)
        r2, _ = self._row("θ₂  second grid", self.theta2)
        form.addWidget(r1)
        self.theta1_slider = self._slider(self.theta1)
        form.addWidget(self.theta1_slider.holder)
        form.addWidget(r2)
        self.theta2_slider = self._slider(self.theta2)
        form.addWidget(self.theta2_slider.holder)
        return box

    def _slider(self, spin):
        """Слайдер-дублёр поля угла ротатора, шаг 1° -- как у поля.

        Только углам ротаторов (решение владельца 27.08): крутить мышью
        осмысленно то, что оператор и правда крутит руками, а частоту или
        степень поляризации задают числом.

        Слайдер целочисленный: 1° -- цена деления и на нём, и на поле. Поле
        при этом остаётся точнее слайдера, и дробное значение, введённое с
        клавиатуры, обратной синхронизацией не затирается -- слайдер лишь
        встаёт на ближайший градус. Отсюда `_syncing`: без него округление
        поехало бы обратно в поле и 30.25° превратились бы в 30.00°.
        """
        sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        sl.setRange(int(round(spin.minimum())), int(round(spin.maximum())))
        sl.setSingleStep(1)
        sl.setPageStep(10)
        sl.setTickPosition(QtWidgets.QSlider.TicksBelow)
        sl.setTickInterval(15)
        sl.setValue(int(round(spin.value())))

        def from_slider(v):
            if self._syncing:
                return
            self._syncing = True
            try:
                spin.setValue(float(v))
            finally:
                self._syncing = False

        def to_slider(v):
            if self._syncing:
                return
            self._syncing = True
            try:
                sl.setValue(int(round(v)))
            finally:
                self._syncing = False

        sl.valueChanged.connect(from_slider)
        spin.valueChanged.connect(to_slider)

        # отступ слева ровно на ширину метки строки: иначе слайдер висит между
        # двумя полями и непонятно, к какому из них он относится
        holder = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(holder)
        h.setContentsMargins(86, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(sl)
        sl.holder = holder
        return sl

    def _build_frequency(self, p):
        box, form = self._group("Frequency")
        self.freq = _spin(p.freq_thz, 0.001, 10.0, 0.01, 3, " THz")
        self.freq.valueChanged.connect(self._touch)
        row, _ = self._row("Frequency", self.freq)
        form.addWidget(row)
        self.freq_hint = QtWidgets.QLabel()
        self.freq_hint.setObjectName("hint")
        self.freq_hint.setWordWrap(True)
        form.addWidget(self.freq_hint)
        return box

    def _build_units(self, p):
        box, form = self._group("Axis units")
        self.units = QtWidgets.QComboBox()
        self.units.addItem("dB", "dB")
        self.units.addItem("%", "percent")
        self.units.setCurrentIndex(0 if p.units == "dB" else 1)
        self.units.currentIndexChanged.connect(self._touch)
        row, _ = self._row("Units", self.units)
        form.addWidget(row)
        return box

    # -- состояние ------------------------------------------------------
    def value(self) -> CwParams:
        source = next(k for k, b in self.src_buttons.items() if b.isChecked())
        detector = next(k for k, b in self.det_buttons.items() if b.isChecked())
        return CwParams(
            freq_thz=self.freq.value(),
            theta1_deg=self.theta1.value(),
            theta2_deg=self.theta2.value(),
            source=source,
            psi_deg=self.psi.value(),
            dop=self.dop.value(),
            detector=detector,
            analyzer_deg=self.analyzer.value(),
            units=self.units.currentData())

    def set_band_hint(self, text: str | None) -> None:
        """Предупреждение об экстраполяции за полосу калибровки."""
        self.freq_hint.setText(text or "")
        self.freq_hint.setObjectName("warn" if text else "hint")
        self.freq_hint.style().unpolish(self.freq_hint)
        self.freq_hint.style().polish(self.freq_hint)

    def _sync_enabled(self) -> None:
        p = self.value()
        allowed = enabled_fields(p)
        for field, widget, label in (("psi_deg", self.psi, self.psi_label),
                                     ("dop", self.dop, self.dop_label),
                                     ("analyzer_deg", self.analyzer,
                                      self.analyzer_label)):
            on = field in allowed
            widget.setEnabled(on)
            label.setEnabled(on)
        # подсказка только про азимут: погашенный DOP при полностью
        # поляризованном источнике самоочевиден, и объяснять его -- шум
        self.src_hint.setText(disabled_reason(p, "psi_deg") or "")
        self.det_hint.setText(disabled_reason(p, "analyzer_deg") or "")

    def _touch(self, *_a) -> None:
        if self._loading:
            return
        self._sync_enabled()
        self._timer.start()

    def _emit(self) -> None:
        self.changed.emit(self.value())
