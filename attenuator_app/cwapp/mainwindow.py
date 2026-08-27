# -*- coding: utf-8 -*-
"""Главное окно CW-приложения. MVP: одно окно, без строки меню.

Единственное место, где панель параметров встречается с расчётным слоем.
Виджеты физику не зовут, модель про Qt не знает.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtCore, QtNetwork, QtWidgets

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.cwapp import __version__, theme, updates  # noqa: E402
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
        self.passport_button = QtWidgets.QPushButton("Passport…")
        self.passport_button.setFlat(True)
        self.passport_button.setToolTip(
            "Choose the passport file of your device. Without an explicit choice "
            "the application looks next to the executable and falls back to the "
            "built-in sample.")
        self.passport_button.clicked.connect(self._choose_passport)
        self.status.addPermanentWidget(self.passport_button)
        self.update_button = QtWidgets.QPushButton("Check for updates")
        self.update_button.setFlat(True)
        self.update_button.clicked.connect(self._check_updates)
        self.status.addPermanentWidget(self.update_button)

        #: один менеджер на окно: создавать его на каждый запрос значит терять
        #: соединение и системные настройки прокси
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._reply = None
        #: последний ответ проверки обновлений -- читает дымовой прогон
        self.last_update_answer = None

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

    # -- паспорт прибора -----------------------------------------------
    def _choose_passport(self) -> None:
        """Явный выбор файла -- первая ступень порядка поиска.

        Негодный файл не роняет окно и не заменяет собой рабочую модель:
        прежний паспорт остаётся на месте, причина уходит в строку состояния.
        Иначе один промах в диалоге оставил бы оператора без расчёта посреди
        серии измерений.
        """
        start = str(self.model.passport_path.parent)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose device passport", start, "Passport files (*.json)")
        if not path:
            return
        self.load_passport(path)

    def load_passport(self, path) -> bool:
        """Перечитать паспорт, сохранив введённые оператором параметры."""
        try:
            model = CwModel(path, params=self.model.params)
        except Exception as e:                             # noqa: BLE001
            self.status.setStyleSheet("color: %s;" % theme.STATUS["critical"])
            self.status.showMessage("passport %s rejected: %s"
                                    % (Path(path).name, e))
            return False
        self.model = model
        self.recompute(self.params.value())
        return True

    # -- обновления -----------------------------------------------------
    def _check_updates(self) -> None:
        """Спросить GitHub, вышло ли что-то новее. Окно при этом живёт.

        Запрос идёт через `QtNetwork` -- он уже в PySide6-Essentials, так что
        ради одного HTTP-запроса не тянется ни одной новой зависимости (план
        релизов §5). Ответ приходит сигналом, а не ожиданием внутри слота: окно
        не должно замирать, и у спектрометра это не теория -- машина там часто
        без интернета, и таймаут отрабатывает целиком.

        Автообновления нет и не будет: приборная программа не должна менять
        себя между двумя измерениями одной серии. Скачивает и ставит человек.
        """
        if self._reply is not None:
            return                                   # запрос уже в пути
        self.update_button.setEnabled(False)
        self.status.showMessage("checking for updates…")

        request = QtNetwork.QNetworkRequest(QtCore.QUrl(updates.RELEASES_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(updates.TIMEOUT_MS)
        self._reply = self._network.get(request)
        self._reply.finished.connect(self._updates_answered)

    def _updates_answered(self) -> None:
        """Ответ (или его отсутствие) -> диалог. Весь разбор -- в `updates`."""
        reply, self._reply = self._reply, None
        self.update_button.setEnabled(True)
        try:
            status = reply.attribute(
                QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
            if reply.error() != QtNetwork.QNetworkReply.NoError and not status:
                answer = updates.network_failure(reply.errorString(), __version__)
            else:
                answer = updates.interpret(int(status or 0),
                                           bytes(reply.readAll()), __version__)
        finally:
            reply.deleteLater()
        self.show_update_answer(answer)

    def show_update_answer(self, answer) -> None:
        """Показать готовый ответ. Отдельным методом -- чтобы дымовой прогон
        проверял все четыре исхода, не выходя в сеть."""
        self.last_update_answer = answer
        self.status.showMessage("%s · v%s"
                                % (self.model.device_line(), __version__))
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Check for updates")
        box.setIcon(QtWidgets.QMessageBox.Warning if answer.is_failure
                    else QtWidgets.QMessageBox.Information)
        box.setText(answer.title)
        box.setInformativeText(answer.text)
        if answer.url:
            box.setDetailedText("Releases page:\n%s" % answer.url)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        # `open`, а не `exec`: модально, но без собственного цикла событий --
        # окно продолжает перерисовываться, а дымовой прогон не встаёт намертво
        # на диалоге, которого некому нажать
        box.open()
        return box
