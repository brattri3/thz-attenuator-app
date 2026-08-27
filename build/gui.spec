# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: автономный .exe GUI ТГц-аттенюатора.

Onefile, без консоли (console=False - чистое GUI-приложение, ошибки уходят в
messagebox, а не в невидимое окно консоли). Собирает пакет attenuator_app
целиком (core/ - физика, passports/ - паспорта приборов) через узкую точку
входа gui_entry.py (см. её докстринг - почему нельзя указать сам gui.py).

Сборка (из корня репозитория, тем же venv, где стоит numpy/matplotlib/pyinstaller):
    .venv\\Scripts\\python.exe -m PyInstaller attenuator_app\\gui.spec ^
        --distpath attenuator_app\\dist --workpath attenuator_app\\build

Результат: attenuator_app/dist/THz-Attenuator.exe (~60-80 МБ, matplotlib внутри).
matplotlib опционален для приложения (см. core/plots.py), но раз он есть в venv
сборки - PyInstaller включит его в exe, и графики будут "настоящими" (PNG через
core/plots.py), а не ручным Canvas-фолбэком. Это сознательный выбор для
поставочной сборки: у покупателя должен быть лучший вариант "из коробки".
"""
from pathlib import Path

block_cipher = None

# SPECPATH — каталог, где лежит сам .spec (PyInstaller подставляет глобально).
APP_DIR = Path(SPECPATH).resolve()          # .../attenuator_app
ROOT_DIR = APP_DIR.parent                    # корень репозитория

a = Analysis(
    [str(APP_DIR / "gui_entry.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=[
        (str(APP_DIR / "passports"), "attenuator_app/passports"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="THz-Attenuator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
