# -*- coding: utf-8 -*-
"""Точка входа CW-приложения.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe -m attenuator_app.cwapp
    .venv\\Scripts\\python.exe -m attenuator_app.cwapp --selftest

Приложение собирается с `console=False`, поэтому необработанное исключение
иначе исчезло бы молча -- «двойной клик, ничего не произошло». Перехват ставится
ДО создания окна: трассировка уходит в лог и показывается диалогом.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import faulthandler
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def log_dir() -> Path:
    """Каталог логов. Рядом с .exe писать нельзя -- Program Files не пишется."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home()
    d = root / "THz-CW"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path.home()
    return d


def _install_excepthook(app) -> None:
    from PySide6 import QtWidgets

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = log_dir() / ("crash-%s.log" % stamp)
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            path = None
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical,
                                    "THz Attenuator — CW", "Something went wrong.")
        box.setInformativeText(
            "The calculation could not be completed.\n\n"
            + ("Details saved to:\n%s" % path if path else "Details below."))
        box.setDetailedText(text)
        box.exec()

    sys.excepthook = hook


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="attenuator_app.cwapp",
        description="CW attenuator: transmission for a pair of rotator angles")
    parser.add_argument("--selftest", action="store_true",
                        help="run the numeric self-check and exit (no window)")
    parser.add_argument("--calibration", default=None,
                        help="path to a calibration JSON")
    args = parser.parse_args(argv)

    if args.selftest:
        from attenuator_app.cwapp.selftest import selfcheck
        return selfcheck()

    faulthandler.enable(file=open(log_dir() / "faults.log", "a", encoding="utf-8"))

    from PySide6 import QtWidgets
    from attenuator_app.cwapp import theme
    from attenuator_app.cwapp.mainwindow import CwMainWindow

    theme.configure_locale()
    theme.configure_pyqtgraph()
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("THz Attenuator CW")
    app.setStyleSheet(theme.QSS)
    theme.configure_fonts(app)
    _install_excepthook(app)

    window = CwMainWindow(args.calibration)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
