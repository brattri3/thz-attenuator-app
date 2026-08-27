# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: поставка CW-приложения ТГц-аттенюатора.

**Не onefile.** Решение владельца П-1 от 2026-08-27: PySide6 идёт под LGPL, и у
получателя должна оставаться возможность заменить Qt своей сборкой. Одиночный
`.exe` этого не даёт -- распакованные Qt-DLL живут во временном каталоге и
стираются при выходе. Папка с отдельными DLL даёт: требование закрывается самой
формой поставки, а не обещанием. Отсюда пара `EXE(...) + COLLECT(...)`, где
`EXE` получает только `a.scripts`, а двоичные файлы и данные уходят в `COLLECT`.

⚠ Второе следствие формы поставки: «рядом с программой» для поиска паспорта --
это каталог `.exe`, то есть `Path(sys.executable).parent` (см. `cwapp/state.py`,
`program_dir`). Под onefile он указывал бы во временный `_MEIPASS`, и паспорт,
положенный оператором, не нашёлся бы никогда. Проверять это надо на собранной
папке: из исходников дефект не проявляется вовсе.

Собирается ТОЛЬКО `cwapp` -- продукт (решение В-36). tkinter-окна остаются
сервисной оснасткой наладчика; для них есть отдельная точка входа `gui_entry.py`.

Сборка из корня репозитория (пути ровно такие: `build/dist/` и `build/build/`
закрыты `.gitignore`, а корневой `dist/` -- нет, и собранные 144 МБ попали бы
в `git status`):
    python -m PyInstaller build/gui.spec --distpath build/dist --workpath build/build

Результат: `build/dist/THz-Attenuator/` -- каталог с `THz-Attenuator.exe`, Qt-DLL и
`LICENSES.txt` рядом. Наружу уходит zip этого каталога, SHA-256 считается на
архив (план релизов §6, решение П-1).
"""
from pathlib import Path

# SPECPATH -- каталог самого .spec, PyInstaller подставляет его глобально.
SPEC_DIR = Path(SPECPATH).resolve()          # <корень>/build
ROOT_DIR = SPEC_DIR.parent                   # корень репозитория
APP_DIR = ROOT_DIR / "attenuator_app"

a = Analysis(
    [str(APP_DIR / "cwapp_entry.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=[
        # Зашитый образец калибровки -- последний рубеж поиска паспорта. Без
        # него приложение не поднимется вовсе: `CwModel` читает его, когда
        # рядом с программой паспорта нет.
        (str(APP_DIR / "tools" / "calibration" / "SAMPLE.json"),
         "attenuator_app/tools/calibration"),
        # Обезличенный паспорт пакета -- на нём идёт приёмка tkinter-линии;
        # весит килобайты, а его отсутствие ломает `attenuator_app.api`.
        (str(APP_DIR / "passports" / "SAMPLE.json"), "attenuator_app/passports"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # matplotlib нужен только PNG-рендереру `core/plots.py`, который в
        # cwapp не зовётся: на экране рисует pyqtgraph, а палитра берётся из
        # модуля константами, без импорта matplotlib. Экономит десятки МБ.
        "matplotlib",
        # tkinter -- сервисная линия наладчика, в поставку не входит.
        "tkinter",
        # scipy тянется транзитивно через pyqtgraph (там он опционален) и
        # весит 68 МБ из 215. Проверено: при полном расчёте cwapp в
        # `sys.modules` нет ни одного модуля scipy, в `core/` и
        # `service_calc.py` он не упоминается вовсе.
        "scipy",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # двоичные файлы уходят в COLLECT, не в .exe
    name="THz-Attenuator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # чистое GUI: ошибки идут в окно, не в консоль
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="THz-Attenuator",
)

# LICENSES.txt кладётся РЯДОМ С .exe, а не в `_internal`: PyInstaller 6
# складывает всё из `datas` во внутренний каталог, а по решению П-1 условия
# лицензий должны попадаться получателю на глаза, а не прятаться. Спека -- это
# обычный скрипт, и код после COLLECT выполняется, когда каталог уже собран.
import shutil                                              # noqa: E402

_dist = Path(DISTPATH) / "THz-Attenuator"
shutil.copy2(str(ROOT_DIR / "LICENSES.txt"), str(_dist / "LICENSES.txt"))
print("spec: LICENSES.txt положен рядом с .exe -> %s" % (_dist / "LICENSES.txt"))
