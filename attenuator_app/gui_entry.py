"""Точка входа для сборки автономного .exe (PyInstaller).

Обычный способ запуска из исходников - `python -m attenuator_app.gui` (см.
README.md). Этот файл существует только для сборки: PyInstaller анализирует
один файл-скрипт как точку входа, а относительные импорты внутри пакета
(`from .api import Attenuator` и т.п. в gui.py) работают только когда модуль
запущен КАК ЧАСТЬ ПАКЕТА, а не напрямую. Поэтому здесь узкая обёртка с
абсолютным импортом - см. attenuator_app/gui.spec.
"""
from attenuator_app.gui import main

if __name__ == "__main__":
    main()
