# -*- coding: utf-8 -*-
"""Точка входа для сборки `.exe` с CW-приложением (PyInstaller).

Обычный запуск из исходников -- `python -m attenuator_app.cwapp`. Этот файл
существует только ради сборки: PyInstaller анализирует ОДИН файл-скрипт, а
`cwapp/__main__.py` запускается как часть пакета. Здесь узкая обёртка с
абсолютным импортом -- ровно по образцу `gui_entry.py` для tkinter-линии.

Продукт -- `cwapp` (решение владельца В-36); tkinter-окна остаются сервисной
оснасткой наладчика и в поставку не входят.
"""
import sys

from attenuator_app.cwapp.app import main

if __name__ == "__main__":
    sys.exit(main())
