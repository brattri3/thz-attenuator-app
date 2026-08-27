# QUESTIONS — decision queue and recorded owner decisions

Protocol: `PROJECT.md`, "Question protocol". **Append-only**: new rows get added, existing rows
aren't rewritten (except closing the status once the owner/orchestrator has answered).

**Why this file matters more than it looks like it should.** A question that only lives in a
chat transcript is invisible to every other role and to the same role after `/clear`. This file
is the one place a role can find out what the owner already decided without having access to
someone else's conversation. Write both the question **and** the answer here — a queue of
unanswered questions is only half useful; the point is a durable decision record.

Use one table per batch of related questions (e.g. all questions from one review session), with
a consistent schema — pick **one** column layout and stick to it project-wide, since
`coordination/tools/build_index.py` expects a `Status` column by name. If a table genuinely
doesn't fit that shape (e.g. it tracks execution progress rather than a yes/no decision), that's
a sign it belongs in `ACTIVITY.md` instead, not a reason to invent a new QUESTIONS.md schema.

---

## Решения владельца, перенесённые из исследовательского репозитория (27.08)

Приняты до заведения этого репозитория, в `THz-Unified-Optimizer` числятся как В-35…В-42.
Здесь — те, что определяют продукт; формулировки сокращены до сути.

| # | Вопрос | Ответ владельца | Тип | Статус |
|---|---|---|---|---|
| В-36 | Два интерфейса на разных тулкитах: что считать продуктом, остаётся ли Windows 7 | **`cwapp` — продукт, Win7 снят.** tkinter-окна остаются сервисной оснасткой наладчика | блокирующий | решён |
| В-37 | Хостинг и публичность репозитория | **`brattri3`, публичный** | блокирующий | решён |
| В-39 | Лицензия | **Apache 2.0** | блокирующий | решён |
| В-40 | Паспорта реальных приборов в публичном репозитории | **В репозитории — обезличенный образец.** Реальные идут в поставке отдельно, рядом с `.exe` | блокирующий | решён |
| В-41 | Старый `attenuator_app/` в исследовательском репозитории | **Заморозить с пометкой**, не удалять | не блокирующий | решён |
| В-42 | Едет ли `track_viewer` | **Нет, остаётся в исследовательском.** Его Win7-обязательство В-36 не отменял | не блокирующий | решён |
| — | Бюджет файлов ролей | **Мягкий: выходить можно, если обосновано** | не блокирующий | решён |

## Открытые вопросы

| # | Вопрос | Ответ владельца | Тип | Статус |
|---|---|---|---|---|
| П-1 | LGPL и onefile: PySide6 требует, чтобы получатель мог подменить Qt. Либо не onefile, либо приложить достаточное для пересборки | — | **блокирующий первый внешний релиз** | открыт |
| П-2 | Нормировка при повёрнутом источнике: на максимум или на ось прибора. Варианты расходятся содержательно (скрещенная пара WGP поляризационно нейтральна) | — | блокирующий правку 3 | открыт |
| П-3 | Момент переезда/релиза `v0.1.0` — тег не поставлен | — | не блокирующий | открыт |
