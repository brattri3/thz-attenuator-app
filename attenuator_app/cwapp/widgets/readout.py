# -*- coding: utf-8 -*-
"""Текстовый блок: входные данные и результат рядом.

Показываются обе величины сразу -- децибелы и проценты, независимо от того,
что выбрано осью графика: перевод в уме между ними и есть источник ошибок в
протоколе.

Цена ошибки установки угла заменяет собой панель производной, убранную из MVP
(решение владельца 2026-08-27): вопрос «сколько стоит промах на градус» тот же,
а ответ числом читается точнее, чем по кривой.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class ReadoutPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.inputs = QtWidgets.QFormLayout()
        self.results = QtWidgets.QFormLayout()
        for form in (self.inputs, self.results):
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(3)
            form.setLabelAlignment(QtCore.Qt.AlignLeft)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(34)
        for title, form in (("Input", self.inputs), ("Result", self.results)):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(4)
            head = QtWidgets.QLabel(title.upper())
            head.setStyleSheet("font-size: 10px; font-weight: 600; "
                               "letter-spacing: 1px; color: #898781;")
            col.addWidget(head)
            col.addLayout(form)
            col.addStretch(1)
            lay.addLayout(col, 1)

        self._input_fields: list[QtWidgets.QLabel] = []
        self._result_fields: list[QtWidgets.QLabel] = []

    # -- построение строк -----------------------------------------------
    def _fill(self, form, cache, rows):
        """Строки создаются один раз, дальше только меняется текст."""
        if not cache:
            for label, _value in rows:
                lab = QtWidgets.QLabel(label)
                lab.setStyleSheet("color: #52514e;")
                val = QtWidgets.QLabel()
                val.setStyleSheet("font-family: 'Cascadia Mono', Consolas, monospace;")
                val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                form.addRow(lab, val)
                cache.append(val)
        for widget, (_label, value) in zip(cache, rows):
            widget.setText(value)

    def update_from(self, result) -> None:
        p = result.params
        analyzer = ("%+.2f°" % p.analyzer_deg if p.detector == "coherent"
                    else "— (no axis)")
        azimuth = ("%+.2f°" % p.psi_deg if p.source != "unpolarized"
                   else "— (depolarized)")
        dop = {"linear": "1.00", "unpolarized": "0.00"}.get(
            p.source, "%.2f" % p.dop)
        self._fill(self.inputs, self._input_fields, [
            ("Frequency", "%.3f THz" % p.freq_thz),
            ("Source", "%s · azimuth %s · DOP %s" % (p.source, azimuth, dop)),
            ("Detector", "%s · analyzer %s" % (p.detector, analyzer)),
            ("Angle θ₁", "%+.2f°" % p.theta1_deg),
            ("Angle θ₂", "%+.2f°" % p.theta2_deg),
            ("Mutual angle", "%+.2f°" % (p.theta2_deg - p.theta1_deg)),
        ])
        self._fill(self.results, self._result_fields, [
            ("Attenuation", "%+.3f dB" % result.value_db),
            ("Transmission", "%.3f %% of the maximum" % result.value_percent),
            ("Normalised to", "maximum at θ₁ = θ₂ = 0"
             if result.reference_is_at_zero else
             "maximum at θ₁ %+.2f°, θ₂ %+.2f°" % result.reference_at),
            ("If θ₁ off by 1°", "%+.3f / %+.3f dB" % result.err_theta1_db),
            ("If θ₂ off by 1°", "%+.3f / %+.3f dB" % result.err_theta2_db),
            ("Combined, ±1° each", "±%.3f dB" % result.combined_error_db),
        ])
