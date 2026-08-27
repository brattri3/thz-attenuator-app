"""THz Attenuator App — расчёт затухания ТГц аттенюатора на проволочных поляризаторах.

Публичная точка входа — attenuator_app.api.Attenuator.
CLI — python -m attenuator_app.cli
"""
__version__ = "0.1.0"

import sys as _sys


def _safe_console():
    """Windows-консоль часто в cp1251/cp866 и роняет вывод на греческих буквах.

    Переводим stdout/stderr в UTF-8; если не выходит — хотя бы не падаем.
    Греческие символы в пользовательском выводе всё равно не используем:
    theta / nu / sigma пишем латиницей.
    """
    for stream in (_sys.stdout, _sys.stderr):
        rec = getattr(stream, "reconfigure", None)
        if rec is None:
            continue
        try:
            rec(encoding="utf-8", errors="replace")
        except Exception:
            try:
                rec(errors="replace")
            except Exception:
                pass


_safe_console()
