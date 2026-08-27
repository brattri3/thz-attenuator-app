# -*- coding: utf-8 -*-
"""Проверка обновлений: разбор ответа, без сети и без Qt.

Разделение то же, что у расчётного слоя: здесь чистые функции, которые
проверяются приёмкой без окна и без интернета, а сам запрос делает окно через
`QtNetwork` (см. `mainwindow._check_updates`). Логика «что показать оператору»
разъезжается молча, если её нельзя прогнать числами.

**Автообновления не будет никогда** (решение владельца, план релизов §5):
приборная программа не должна менять себя между двумя измерениями одной серии.
Отсюда и роль этого модуля -- только сказать, что вышло; скачивает и ставит
человек.

Ошибка сети -- ОБЫЧНЫЙ ответ, а не сбой: у спектрометра машина без интернета --
норма, и окно обязано работать так же.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

#: откуда спрашиваем. Публичный API GitHub, без ключа: у неаутентифицированных
#: запросов лимит 60 в час на адрес, а кнопку жмут единицами раз за сеанс
RELEASES_URL = ("https://api.github.com/repos/brattri3/"
                "thz-attenuator-app/releases/latest")
#: куда отправляем человека за файлом
RELEASES_PAGE = "https://github.com/brattri3/thz-attenuator-app/releases"

#: сколько ждём ответа, мс -- дальше считаем, что сети нет
TIMEOUT_MS = 8000


@dataclass(frozen=True)
class UpdateAnswer:
    """Что показать оператору. `kind` -- один из четырёх исходов."""

    kind: str            # current | available | none | failed
    title: str
    text: str
    url: str = ""

    @property
    def is_failure(self) -> bool:
        return self.kind == "failed"


def parse_version(text: str) -> tuple[int, ...] | None:
    """`v0.2.0` или `0.2.0` -> (0, 2, 0). Мусор -> None.

    Хвост вида `0.2.0-rc1` отбрасывается вместе с суффиксом: предвыпуски
    здесь не различаются, а падать из-за них нельзя.
    """
    if not text:
        return None
    head = str(text).strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = head.split(".")
    out: list[int] = []
    for part in parts:
        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            return None
        out.append(int(digits))
    return tuple(out) if out else None


def is_newer(latest: str, current: str) -> bool:
    """Строго ли `latest` новее `current`. Неразборчивое -> False.

    Разная длина номера сравнивается по правилам semver: 0.2 и 0.2.0 -- одно
    и то же, а 0.2.1 новее обоих.
    """
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a > b


def interpret(status: int, body: bytes | str | None, current: str) -> UpdateAnswer:
    """Ответ сервера -> что сказать оператору.

    Четыре исхода, а не три: к трём из плана §5 добавлен случай «релизов ещё
    нет». До первого тега GitHub отвечает на `/releases/latest` кодом 404, и
    показать это как «проверить не удалось» значило бы напугать оператора
    поломкой там, где всё исправно.
    """
    if status == 404:
        return UpdateAnswer(
            "none", "No releases yet",
            "The repository has no published releases yet.\n\n"
            "You are running version %s." % current, RELEASES_PAGE)
    if status != 200:
        return UpdateAnswer(
            "failed", "Update check failed",
            "The release list could not be read (HTTP %s).\n\n"
            "This is not a malfunction: the application works offline, and a "
            "spectrometer machine usually has no internet access. Version %s "
            "is installed." % (status, current), RELEASES_PAGE)
    try:
        data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
        tag = str(data["tag_name"])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        return UpdateAnswer(
            "failed", "Update check failed",
            "The answer from the server could not be read (%s).\n\n"
            "Version %s is installed." % (type(e).__name__, current),
            RELEASES_PAGE)

    url = str(data.get("html_url") or RELEASES_PAGE)
    if not is_newer(tag, current):
        return UpdateAnswer(
            "current", "You are up to date",
            "Version %s is the latest published release." % current, url)

    published = str(data.get("published_at") or "")[:10]
    notes = str(data.get("body") or "").strip()
    if len(notes) > 1200:                    # диалог не должен уехать за экран
        notes = notes[:1200].rstrip() + "…"
    text = "Version %s is available%s.\n\nYou have %s." % (
        tag.lstrip("vV"), (" (published %s)" % published) if published else "",
        current)
    if notes:
        text += "\n\nWhat changed:\n%s" % notes
    text += ("\n\nDownload and installation are done by hand: the application "
             "never updates itself between two measurements of one series.")
    return UpdateAnswer("available", "Update available", text, url)


def network_failure(reason: str, current: str) -> UpdateAnswer:
    """Сеть не ответила вовсе -- отдельный вход, ответ тот же по смыслу."""
    return UpdateAnswer(
        "failed", "Update check failed",
        "The release list could not be reached (%s).\n\n"
        "This is not a malfunction: the application works offline, and a "
        "spectrometer machine usually has no internet access. Version %s is "
        "installed." % (reason, current), RELEASES_PAGE)
