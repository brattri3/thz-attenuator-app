# OWNERSHIP — кто какие пути пишет

Одна строка — один путь. Спор о зоне решается здесь, а не в переписке.

| Путь | Владелец | Примечание |
|---|---|---|
| `attenuator_app/cwapp/**` | APP | основное CW-приложение (PySide6) |
| `attenuator_app/tools/**` | APP | сервисный контур наладчика |
| `attenuator_app/{api,cli,gui,gui_entry,cw_curve,selftest}.py` | APP | tkinter-линия и CLI |
| `attenuator_app/core/**` | **никто** | снимок физического ядра, см. ниже |
| `docs/**`, `build/**`, `tests/**` | APP | |
| `coordination/**`, `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `LICENSE*`, `NOTICE`, `.gitignore`, `.claude/**` | ORCH | |
| `passports/*.json` | **вне git** | паспорта конкретных приборов, репозиторий публичный |
| `tools/verify_core.py`, `tools/core_manifest.json` | ORCH | сверка снимка ядра |

## `attenuator_app/core/**` — снимок, а не исходник

Оригинал живёт в исследовательском репозитории `THz-Unified-Optimizer`. Поток вещества
односторонний: физика зреет там, сюда приезжает застывший результат. Правка ядра здесь заводит
вторую версию физики — ровно тот риск, ради которого заведена сверка:

```
python tools/verify_core.py                      # против манифеста
python tools/verify_core.py --against <путь>     # против оригинала
```

Обновление снимка — целиком из оригинала, затем `--update` для манифеста. Вызывать `--update`
без осознанного обновления нельзя: манифест начнёт подтверждать любое расхождение.
