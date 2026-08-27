# -*- coding: utf-8 -*-
"""Главное окно CW-приложения. MVP: одно окно, без строки меню.

Единственное место, где панель параметров встречается с расчётным слоем.
Виджеты физику не зовут, модель про Qt не знает.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtWidgets

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.cwapp import __version__, theme        # noqa: E402
from attenuator_app.cwapp.model import CwModel             # noqa: E402
from attenuator_app.cwapp.state import CwParams            # noqa: E402
from attenuator_app.cwapp.widgets.params import ParamsPanel    # noqa: E402
from attenuator_app.cwapp.widgets.plotpanel import PlotPanel   # noqa: E402
from attenuator_app.cwapp.widgets.readout import ReadoutPanel  # noqa: E402

#: минимальный размер, при котором виден весь контент с учётом прокрутки
MIN_SIZE = (1000, 720)
DEFAULT_SIZE = (1160, 800)


class CwMainWindow(QtWidgets.QMainWindow):
    def __init__(self, calibration_path=None, parent=None):
        super().__init__(parent)
        self.model = CwModel(calibration_path)
        self.setWindowTitle("THz Attenuator — CW")
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MIN_SIZE)

        self.params = ParamsPanel(self.model.params)
        self.params.setFixedWidth(330)
        self.plots = PlotPanel()
        self.readout = ReadoutPanel()

        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.plots, 1)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet("color: %s;" % theme.LINE)
        rl.addWidget(line)
        rl.addWidget(self.readout)

        central = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.params)
        cl.addWidget(right, 1)
        self.setCentralWidget(central)

        self.status = self.statusBar()
        self.update_button = QtWidgets.QPushButton("Check for updates")
        self.update_button.setFlat(True)
        self.update_button.clicked.connect(self._check_updates)
        self.status.addPermanentWidget(self.update_button)

        self.params.changed.connect(self.recompute)
        self.recompute(self.params.value())

    # -- расчёт ---------------------------------------------------------
    @QtCore.Slot(object)
    def recompute(self, params: CwParams) -> None:
        """Единственная точка пересчёта. Отказ ядра -- в строку состояния."""
        try:
            result = self.model.compute(params)
        except ValueError as e:
            # негодный ввод -- обычное событие, а не сбой: окно живо,
            # прежний результат на экране, причина сказана словами
            self.status.showMessage(str(e))
            self.status.setStyleSheet("color: %s;" % theme.STATUS["critical"])
            return
        self.status.setStyleSheet("")
        self.plots.update_from(result, params.units)
        self.readout.update_from(result)
        self.params.set_band_hint(self.model.band_warning())
        self.status.showMessage("%s · v%s" % (self.model.device_line(), __version__))

    # -- обновления -----------------------------------------------------
    def _check_updates(self) -> None:
        """MVP: заглушка. Механизм описан в 13_CW_APP_RELEASES.md §5.

        Автообновления не будет никогда: приборная программа не должна менять
        себя между двумя измерениями одной серии.
        """
        QtWidgets.QMessageBox.information(
            self, "Check for updates",
            "Update checking is not wired up in this build.\n\n"
            "Version %s. Releases will be published in the application's own "
            "repository; see docs/attenuator_app/13_CW_APP_RELEASES.md."
            % __version__)
