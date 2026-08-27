# ACTIVITY — append-only project journal

Every role appends here on a significant change: a finding, a decision, a paradigm-level
observation, a completed piece of work worth other roles knowing about. **Append-only** — past
entries are never rewritten, even when later work supersedes them; if something is superseded,
say so in a *new* entry, don't edit the old one.

This file will grow large. That's fine — it's meant to be searched by date and tag, never read
in full. Once it's grown past a size where a fresh session shouldn't read it at cold start, say
so explicitly in `CLAUDE.md`'s index table (see that file's "what to read and when" section) so
sessions don't accidentally pay for reading the whole thing.

Format: one entry per change, dated, tagged with the acting role's `[<ID>]`. A loose shape that
works:

```
## [YYYY-MM-DD] [<ID>] short title
What happened / what was decided / what was found. Link to the relevant file+line rather than
pasting large excerpts. If this closes out detail that used to live in a role's
`roles/<ID>.md`, that's a good reason for an entry — the detail moves here, the role file keeps
only the live summary (see `roles/ROLE_ID.md` template for why that split matters).
```

Tag proposals about the coordination process itself with `[proposal]` (see `CHARTER.md §10`) so
the orchestrator can find them without reading every entry.

## [2026-08-27] [APP] Три правки интерфейса из четырёх сделаны, третья остановлена на П-2

Работа шла в песочнице `.worktrees/app` (ветка `role/app`), три коммита.

**Правка 1 — кнопки вверх у `QDoubleSpinBox`.** Гипотеза владельца про верхнюю границу не
подтвердилась: щелчок по верхней стрелке исправно шагал значение и до правки. Причина в
`theme.py` -- правило `QDoubleSpinBox { background/border/padding }` переводило виджет в разбор
таблицей стилей целиком, и стрелки вырождались в закорючку 4 px при кнопке 20 px. Задать
`::up-button` явно нельзя: без `image:` Qt не рисует стрелки вовсе (проверено снимком). Спинбокс
отдан нативному стилю -- стрелка стала 10 px при кнопке 16 px, и стиль сам красит её серым при
упоре в границу диапазона.

**Правка 2 — слайдеры к `θ₁` и `θ₂`**, цена деления 1°, синхронно с полем в обе стороны. Флаг
`_syncing` не даёт целочисленному слайдеру округлить введённые с клавиатуры 30.25° обратно до 30.

**Правка 3 — нормировка при повёрнутом источнике: ОСТАНОВЛЕНА.** Условие хэндоффа «опора при
фактическом ψ» оказалось уже выполненным в коде (`compute` зовёт `_apply` до `_reference_db`).
Осталась ровно развилка П-2: опора приколочена к оси прибора (θ₁ = θ₂ = 0), и при ψ = 45°
максимум уезжает на +23° и превышает 0 дБ на 1.64 дБ. Числа и цена каждого варианта -- в
`QUESTIONS.md`, подраздел «П-2 — уточнение от APP». Работа ждёт ответа владельца.

**Правка 4 — поиск паспорта рядом с программой**, ловушка PyInstaller закрыта: под сборкой
каталог берётся от `sys.executable`. Явно выбранный негодный файл отказывает громко и оставляет
прежний паспорт; посторонний JSON рядом лишь пропускается с пометкой. Источник паспорта виден в
строке состояния.

**Проверки.** Каждая правка проверена живым запуском окна и снимком, не импортом. На каждый
дефект заведена машинная проверка, и каждая проверена откатом -- краснеет на дефекте:
`cwapp.selftest` вырос с 12 до 17 (M13…M17: порядок поиска, поддельный `sys.frozen`, громкий
отказ явного файла, имя файла в строке состояния, образец последним рубежом), дымовой прогон --
до 70 проверок и 15 снимков. Первая редакция пиксельной проверки стрелок считала чернила вместе
с рамкой кнопки и давала одинаковые числа до и после правки -- переписана на ширину стрелки в
долях ширины кнопки.

⚠ **Ожидаемое число приёмки в `CLAUDE.md` устарело:** там `cwapp.selftest # 12/12`, фактически
17/17. Файл в зоне ORCH -- запись заведена в `HANDOFFS.md`.

Приёмка после каждой правки: cwapp 17/17, база 13/13, сервисное (модель OK, пределы OK,
калибровка 8/8, приложение 7/7, A7 пропущена штатно), CW-кривая 5/5, сверка ядра 9 файлов без
расхождений. Опорная точка CLI сходится: −4.77 дБ, азимут +0.023°, эллиптичность +0.630°.
