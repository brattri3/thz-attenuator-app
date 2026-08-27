# HANDOFFS — cross-role requests (work outside your own zone)

If the owner or you hit a task outside your specialty — don't do it yourself (`CHARTER.md §3`).
Write the request here, offer to switch the owner into the right session or launch it
(`LAUNCH_PROMPTS.md`).

**Format is not optional — a tool depends on it.** Each entry:

```
## [ISO-date] FROM <ID> TO <ID> — title
- What: the specific ask.
- Context: links, why this is needed.
- Done when: a checkable completion criterion.
- **Status:** open|taken|done
```

That **exact** last line — `- **Status:** open|taken|done` with no variant phrasing — is what
`coordination/tools/build_index.py` parses to build `INDEX.md`. This is the single biggest
lesson worth taking from projects that didn't enforce this from day one: a status line whose
exact wording isn't specified drifts into half a dozen different phrasings over months (`Status:`
vs `Статус:` vs `done (resolved)` vs a status buried mid-paragraph), and an index tool built
against "the status line" quietly stops finding some of them. Enforce the literal string from the
first entry, not just when it starts hurting.

Closing an entry means editing that one line in place (`open` → `done`) — that's not a violation
of append-only, since the surrounding decision text above it isn't touched.

> If your project renames or moves paths referenced in old entries, this file being append-only
> means those old entries will reference stale paths forever. A short translation-table note at
> the top of the file (old path → new path, with the date/reason) costs one paragraph and saves
> every future reader from being misled by a path that no longer exists.

---

## [template]
## [YYYY-MM-DD] FROM A TO B — example: need a shared cache added to the core module
- What: describe the specific change needed in the other role's zone.
- Context: why this role can't just do it itself (zone boundary), links to relevant code.
- Done when: a concrete, checkable criterion — not "looks right."
- **Status:** open
## [2026-08-27] FROM ORCH TO toolsmith — Create requirements.txt for dashboard
- What: Create ssets/coordination/tools/dashboard/requirements.txt containing dependencies for the new Streamlit dashboard (streamlit, pytest, etc.). Also update eferences/setup.md to mention running pip install -r assets/coordination/tools/dashboard/requirements.txt.
- Context: We just built the dashboard but haven't formally documented its Python dependencies in a standard format.
- Done when: requirements.txt exists and setup.md is updated.
- **Status:** done

---

## [2026-08-27] ОТ ВЛАДЕЛЬЦА К APP — четыре правки интерфейса `cwapp`

Переданы владельцем 27.08 по итогу работы с приложением руками. Порядок — как ниже.

### 1. Кнопки вверх не работают, только вниз

`cwapp/widgets/params.py:33` — `QDoubleSpinBox` с `setRange(lo, hi)` и `setSingleStep(step)`.
Начинать с `setRange`: похоже на верхнюю границу, упирающуюся в текущее значение.

Дословно владелец: «НЕ работают кнопки вверх только кнопки вниз. Вообще кнопками не очень
удобно задаваться» — отсюда же пункт 2.

### 2. Слайдеры к полям углов ротаторов

Слайдеры, дублирующие поля ввода и синхронные с ними в обе стороны, шаг 1° — как у поля.
**Только полям углов ротаторов**; остальным достаточно ввода с клавиатуры.

### 3. Нормировка с учётом азимута поляризации источника

`cwapp/model.py`. Если правка сводится к тому, чтобы опора считалась при фактическом ψ, а не при
ψ=0 — делать. **Если упрётесь в выбор «нормировать на максимум или на ось прибора» — остановиться
и спросить владельца:** при повёрнутом источнике эти варианты расходятся содержательно, потому
что скрещенная пара одинаковых WGP поляризационно нейтральна и у дна воспроизводит состояние
источника, а не ось второй решётки. Это вопрос физической конвенции, а не техники.

### 4. Паспорт прибора — отдельным файлом рядом с программой

`cwapp/state.py`. Порядок поиска: явный выбор в интерфейсе → каталог рядом с исполняемым файлом
→ зашитый `SAMPLE` как последний рубеж; в интерфейсе видно, какой файл в итоге взят.

⚠ **Ловушка PyInstaller, из-за которой это ломается молча.** «Рядом с `.exe`» — это
`Path(sys.executable).parent`, а **не** `Path(__file__).parent`: под PyInstaller `__file__`
указывает во временный распакованный `_MEIPASS`. Из исходников ошибка не проявляется вовсе, а в
собранном `.exe` даёт подхват зашитого образца вместо паспорта, положенного оператором — то есть
неверные числа при внешне исправной работе.

- **Статус записи:** open
