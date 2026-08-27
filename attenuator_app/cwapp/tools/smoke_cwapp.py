# -*- coding: utf-8 -*-
"""Дымовой прогон окна без участия человека.

Поднимает НАСТОЯЩЕЕ окно на настоящем Qt (offscreen), проходит все органы
управления, вводит мусор, снимает изображение каждой конфигурации. Ловит то,
чего не видят числа: развалившуюся раскладку, падение при переключении режима,
поле, оставшееся активным, разорванный метод.

**Ни одного `unittest.mock`.** Мок не ловит разрыв метода, потому что мок и
есть заглушка вместо того, что должно было сломаться -- этот урок стоил
облачной сессии реальной ошибки в `service_gui`.

По умолчанию платформа offscreen: окно не всплывает на экране, но в ней
НЕТ системных шрифтов, и текст на снимках выходит квадратиками -- снимки
годятся для проверки раскладки, а не читаемости. Для читаемых снимков
задайте QT_QPA_PLATFORM=windows.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe attenuator_app/cwapp/tools/smoke_cwapp.py
    .venv\\Scripts\\python.exe attenuator_app/cwapp/tools/smoke_cwapp.py --out <каталог>
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from PySide6 import QtCore, QtGui, QtWidgets               # noqa: E402

from attenuator_app.cwapp import theme                     # noqa: E402
from attenuator_app.cwapp.mainwindow import CwMainWindow   # noqa: E402

#: методы, которые обязаны существовать: дешёвая страховка от разрыва класса
REQUIRED = ("recompute", "_check_updates")

FAILURES: list[str] = []


def check(name: str, ok: bool, note: str = "") -> None:
    print(("  [OK] " if ok else "  [FAIL] ") + name + (("   " + note) if note else ""))
    if not ok:
        FAILURES.append(name)


def _spin_buttons(sb):
    """Прямоугольники стрелок вверх/вниз так, как их считает сам стиль."""
    opt = QtWidgets.QStyleOptionSpinBox()
    opt.initFrom(sb)
    opt.rect = sb.rect()
    opt.subControls = QtWidgets.QStyle.SC_All
    opt.buttonSymbols = sb.buttonSymbols()
    opt.frame = True
    style = sb.style()
    return (style.subControlRect(QtWidgets.QStyle.CC_SpinBox, opt,
                                 QtWidgets.QStyle.SC_SpinBoxUp, sb),
            style.subControlRect(QtWidgets.QStyle.CC_SpinBox, opt,
                                 QtWidgets.QStyle.SC_SpinBoxDown, sb))


def _click(app, widget, point) -> None:
    """Настоящий щелчок мышью, а не вызов stepBy: проверяется попадание."""
    pos = QtCore.QPointF(point)
    for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
        QtWidgets.QApplication.sendEvent(widget, QtGui.QMouseEvent(
            kind, pos, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier))
    app.processEvents()


def _arrow_width(img, rect, pad: int = 3) -> int:
    """Ширина нарисованной стрелки в пикселях.

    Отступ `pad` отрезает рамку самой кнопки: она есть в обоих случаях и
    считать её как «стрелка нарисована» нельзя -- на этом первая редакция
    проверки и промахнулась, дав одинаковые числа до и после правки.
    """
    xs = [x
          for y in range(rect.top() + pad, min(rect.bottom() + 1 - pad, img.height()))
          for x in range(rect.left() + pad, min(rect.right() + 1 - pad, img.width()))
          if img.pixelColor(x, y).lightness() < 160]
    return (max(xs) - min(xs) + 1) if xs else 0


def shot(window, out: Path, tag: str) -> None:
    img = window.grab()
    img.save(str(out / ("cwapp_%s.png" % tag)))


def run(out: Path) -> int:                                 # noqa: C901
    theme.configure_locale()
    theme.configure_pyqtgraph()
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setStyleSheet(theme.QSS)
    theme.configure_fonts(app)
    w = CwMainWindow()
    w.show()
    app.processEvents()

    check("окно построено", w.isVisible() and w.width() > 0,
          "%d x %d" % (w.width(), w.height()))

    # В offscreen-платформе системных шрифтов нет вообще (проверено: 0 против
    # 300 на реальной Windows), и весь текст на снимках выходит квадратиками.
    # Это артефакт среды, а не дефект окна -- но снимки тогда годятся только
    # для проверки РАСКЛАДКИ, и молчать об этом нельзя.
    n_fonts = len(QtGui.QFontDatabase.families())
    if n_fonts == 0:
        print("  [!] в этой платформе нет системных шрифтов: текст на снимках")
        print("      будет квадратиками. Для читаемых снимков запустите с")
        print("      переменной окружения QT_QPA_PLATFORM=windows")
    check("шрифты для снимков", True,
          "%d семейств" % n_fonts if n_fonts else "0 — снимки только про раскладку")
    missing = [n for n in REQUIRED if not callable(getattr(w, n, None))]
    check("методы окна на месте", not missing, str(missing) if missing else str(REQUIRED))
    check("первый расчёт выполнен", w.model.result is not None,
          "%+.4f dB" % w.model.result.value_db if w.model.result else "нет")

    def apply(**kw):
        """Правка параметров через настоящие виджеты, без обхода сигналов."""
        p = w.params
        if "theta1" in kw:
            p.theta1.setValue(kw["theta1"])
        if "theta2" in kw:
            p.theta2.setValue(kw["theta2"])
        if "freq" in kw:
            p.freq.setValue(kw["freq"])
        if "source" in kw:
            p.src_buttons[kw["source"]].setChecked(True)
        if "detector" in kw:
            p.det_buttons[kw["detector"]].setChecked(True)
        if "units" in kw:
            p.units.setCurrentIndex(0 if kw["units"] == "dB" else 1)
        p._emit()                       # дебаунс в прогоне не ждём
        app.processEvents()

    print("\n--- комбинации источник x приёмник x единицы ---")
    n = 0
    for source in ("linear", "unpolarized", "partial"):
        for detector in ("coherent", "power"):
            for units in ("dB", "percent"):
                tag = "%s_%s_%s" % (source, detector, units)
                try:
                    apply(source=source, detector=detector, units=units,
                          theta1=25.0, theta2=-10.0)
                    r = w.model.result
                    ok = r is not None and r.params.source == source \
                        and r.params.detector == detector
                    # погашенные поля обязаны быть погашены на живых виджетах
                    if detector == "power" and w.params.analyzer.isEnabled():
                        ok, tag_note = False, "ось анализатора осталась активной"
                    elif source == "unpolarized" and w.params.psi.isEnabled():
                        ok, tag_note = False, "азимут остался активным"
                    else:
                        tag_note = "%+.3f dB" % r.value_db
                    check(tag, ok, tag_note)
                    shot(w, out, tag)
                    n += 1
                except Exception as e:                     # noqa: BLE001
                    check(tag, False, "%s: %s" % (type(e).__name__, e))
                    traceback.print_exc()

    print("\n--- углы, включая края и глубокое гашение ---")
    for t1, t2 in ((0.0, 0.0), (90.0, 90.0), (-90.0, 90.0), (0.0, 90.0),
                   (45.0, -45.0), (89.0, -1.0)):
        try:
            apply(theta1=t1, theta2=t2, source="linear", detector="coherent")
            r = w.model.result
            check("θ₁ %+.0f, θ₂ %+.0f" % (t1, t2), r is not None,
                  "%+.3f dB" % r.value_db)
        except Exception as e:                             # noqa: BLE001
            check("θ₁ %+.0f, θ₂ %+.0f" % (t1, t2), False, str(e))
            traceback.print_exc()
    shot(w, out, "angles_edge")

    print("\n--- негодный ввод: окно обязано выжить ---")
    try:
        w.params.freq.setValue(0.0)     # спинбокс не пустит ниже минимума
        w.params._emit()
        app.processEvents()
        check("частота у нижнего предела не роняет окно", w.isVisible(),
              "статус: %s" % w.status.currentMessage()[:52])
    except Exception as e:                                 # noqa: BLE001
        check("частота у нижнего предела", False, str(e))
    # прямой вызов пересчёта с заведомо негодными параметрами
    from attenuator_app.cwapp.state import CwParams
    try:
        w.recompute(CwParams(freq_thz=-1.0))
        check("отрицательная частота -> отказ, а не падение", w.isVisible(),
              "статус: %s" % w.status.currentMessage()[:52])
    except Exception as e:                                 # noqa: BLE001
        check("отрицательная частота", False, "%s: %s" % (type(e).__name__, e))
        traceback.print_exc()
    try:
        w.recompute(CwParams(source="magic"))
        check("неизвестный источник -> отказ, а не падение", w.isVisible())
    except Exception as e:                                 # noqa: BLE001
        check("неизвестный источник", False, "%s: %s" % (type(e).__name__, e))
    # восстановление сверяется с прямым расчётом ТЕХ ЖЕ параметров, а не с
    # величиной, снятой в другой конфигурации: первая редакция сравнивала точку
    # (30, 0) со значением при (89, -1) и расходилась на 46 дБ
    apply(freq=0.200, theta1=30.0, theta2=0.0, source="linear", detector="coherent")
    from attenuator_app.cwapp.model import CwModel
    want = CwModel().compute(w.model.result.params).value_db
    check("окно восстановилось после отказов",
          w.model.result is not None and abs(w.model.result.value_db - want) < 1e-12,
          "%+.4f dB, эталон %+.4f dB" % (w.model.result.value_db, want))

    print("\n--- частота вне полосы калибровки ---")
    apply(freq=0.140)
    check("подсказка об экстраполяции появилась",
          "outside the calibrated band" in w.params.freq_hint.text(),
          w.params.freq_hint.text()[:56])
    shot(w, out, "out_of_band")
    apply(freq=0.800)
    check("подсказка снялась в полосе", w.params.freq_hint.text() == "")

    print("\n--- согласованность экрана и модели ---")
    apply(theta1=30.0, theta2=0.0, units="dB")
    r = w.model.result
    x, y = w.plots.top.curve.getData()
    i = list(r.theta).index(30.0)
    check("кривая на экране == массив модели",
          abs(float(y[i]) - float(r.vs_theta1_db[i])) < 1e-9,
          "%.6f dB" % float(y[i]))
    check("подпись точки несёт оба угла и значение",
          all(s in w.plots.top.text.toPlainText() for s in ("θ₁", "θ₂", "dB")),
          w.plots.top.text.toPlainText())
    check("палитра экрана взята из core.plots",
          theme.pens()["model"].color().name() == theme.MODEL, theme.MODEL)
    # десятичный разделитель: русская локаль Windows превращала «0.200 THz» в
    # «0,200 THz», и скопированное в протокол число переставало разбираться
    shown = w.params.freq.text()
    check("числа с десятичной точкой, а не с запятой", "," not in shown, shown)
    # умолчание не должно поднимать окно сразу с предупреждением
    fresh = CwMainWindow()
    check("стартовая частота лежит в полосе калибровки",
          fresh.model.band_warning() is None,
          "%.3f THz" % fresh.model.params.freq_thz)
    fresh.close()

    # Выбранная радиокнопка обязана ОТЛИЧАТЬСЯ от невыбранной на пикселях.
    # Проверка появилась после реального дефекта: правило `QWidget {...}` в
    # таблице стилей отключало нативную отрисовку индикатора, и выбранный
    # пункт становился неотличим от невыбранного. Числа этого не видят.
    w.params.det_buttons["coherent"].setChecked(True)
    app.processEvents()
    off = w.params.det_buttons["power"].grab().toImage()
    w.params.det_buttons["power"].setChecked(True)
    app.processEvents()
    on = w.params.det_buttons["power"].grab().toImage()
    check("выбранная радиокнопка видна на пикселях", off != on,
          "одинаковы — индикатор не рисуется" if off == on else "отличается")

    # Стрелки спинбокса. Дефект владельца «не работают кнопки вверх» (правка 1
    # хэндоффа 27.08) был не в диапазоне и не в обработчике: щелчок исправно
    # шагал значение, но правило таблицы стилей на QDoubleSpinBox переводило
    # виджет в разбор QSS целиком, и стрелка ВВЕРХ срезалась по высоте до
    # чёрточки. Числа этого не видят -- поэтому проверок две: шаг и пиксели.
    print("\n--- стрелки спинбокса ---")
    for name in ("theta1", "theta2", "freq", "psi", "analyzer"):
        sb = getattr(w.params, name)
        if not sb.isEnabled():
            continue
        up, down = _spin_buttons(sb)
        before = sb.value()
        _click(app, sb, up.center())
        stepped_up = sb.value() > before
        mid = sb.value()
        _click(app, sb, down.center())
        stepped_down = sb.value() < mid
        check("%s: щелчок по стрелке шагает в обе стороны" % name,
              stepped_up and stepped_down,
              "вверх %+.3f -> %+.3f, вниз -> %+.3f" % (before, mid, sb.value()))
        img = sb.grab().toImage()
        # Стрелка обязана быть РАЗЛИЧИМОЙ, а не просто присутствовать. Нативная
        # занимает около 2/3 ширины кнопки (10 px из 16), при разборе таблицей
        # стилей вырождается в 4 px из 20 -- четырёхпиксельная закорючка и
        # читается оператором как «кнопки нет». Порог в долях ширины кнопки, а
        # не в пикселях: абсолютный размер зависит от масштаба экрана.
        for label, r in (("вверх", up), ("вниз", down)):
            wid = _arrow_width(img, r)
            check("%s: стрелка %s различима" % (name, label),
                  wid >= 0.4 * r.width(),
                  "%d px при кнопке %d px" % (wid, r.width()))

    # Прямая страховка от возврата причины: правило QSS, задающее спинбоксу
    # фон, рамку или отступы, снова отключит нативную отрисовку подконтролей.
    styled = [ln for ln in theme.QSS.splitlines()
              if "QDoubleSpinBox" in ln and "::" not in ln
              and any(k in ln for k in ("background:", "border:", "padding:"))]
    check("таблица стилей не забирает отрисовку спинбокса", not styled,
          styled[0].strip() if styled else "правил нет")

    print("\n########## ИТОГ ##########")
    print("  снимков: %d, каталог %s" % (n + 2, out))
    if FAILURES:
        print("  ОТКАЗОВ: %d" % len(FAILURES))
        for f in FAILURES:
            print("   - " + f)
    else:
        print("  всё зелёное")
    w.close()
    return 1 if FAILURES else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="smoke test for the CW app window")
    parser.add_argument("--out", default=None, help="где сохранять снимки")
    args = parser.parse_args(argv)
    out = Path(args.out) if args.out else Path(REPO) / "runs" / "cwapp_smoke"
    out.mkdir(parents=True, exist_ok=True)
    return run(out)


if __name__ == "__main__":
    sys.exit(main())
