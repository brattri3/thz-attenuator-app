# Черновик issue в апстрим скилла (DimaMuhannad/multi-agent-coordination-skill)

**Статус: публикация разрешена владельцем 27.08, но не выполнена** — в системе нет `gh` и
токена. Опубликовать можно так:

```
winget install --id GitHub.cli
gh auth login
gh issue create --repo DimaMuhannad/multi-agent-coordination-skill   --title "Dashboard silently misreads non-English journals and commits mutations without confirmation"   --body-file coordination/upstream/issue-dashboard.md
```

Перед отправкой убрать из тела эту шапку — она внутренняя. Второй путь: вставить текст ниже в
веб-форму `https://github.com/DimaMuhannad/multi-agent-coordination-skill/issues/new`.
Заголовок: `Dashboard silently misreads non-English journals and commits mutations without confirmation`

---

The Streamlit dashboard (`assets/coordination/tools/dashboard/**`, upstream `2e37500`) was
reviewed read-only on a project whose journals are written in Russian. Two classes of problem,
the second is the serious one.

## 1. Silent misreads on non-English journals

The parser matches English status words. No parse error is shown, so the operator sees numbers
and believes them.

| Screen | Files | Cause |
|---|---|---|
| `Open Questions: 0` | two questions open (`открыт`) | `parser.py:150` — `"open" in status` |
| question shown `Non-blocking` | marked blocking (`блокирующий`) | `parser.py:151` — `"blocking" in type` |
| `Roles Active: 0 / 2`, both idle/stale | both roles active | same dictionaries |
| role status shows the first word of prose; names keep `**` | — | `parser.py:94` expects the `Role / Status (date) / Summary` schema; `parser.py:84` does not strip inline `**` |
| handoff entries render empty, `FROM ➔ TO` blank | the file's richest entries | `parser.py:12-13` knows only `**Status:**` and `FROM x TO y`; fields are read from `- What:` bullets |

`ACTIVITY.md` and `roles/*.md` are not read at all, though `BOARD.md` points readers there.

Suggested: a single source of status/type vocabularies shared with `components.py`, and an
explicit "schema not recognised" banner instead of substituting the first word of prose.

## 2. Mutations are unconfirmed and one of them corrupts a table

- `append_question` (`mutator.py:217`) inserts the new row after the **last table row in the
  whole file**. In our `QUESTIONS.md` the last table holds physical measurements attached to a
  decision — a new question lands inside it and corrupts it. Insert by table heading instead.
- "Register New Role" (`dashboard.py:333`) appends to the end of `BOARD.md` — outside the table,
  below a trailing blockquote, and with the wrong column count.
- No confirmation on any destructive action: Update Role & Commit, Submit Question & Commit,
  Mark Done, Reopen, Rebuild INDEX.md, Create Worktree — one click writes and commits.
- The Git Auto-Commit toggle is in the sidebar, which does not render at all under Streamlit
  1.62 (verified with a minimal app, so it is the version, not this code). Its default is ON.
  Worth moving the toggle into the main area and defaulting it to `False`.
- Fuzzy column matching (`mutator.py:77`): an empty header matches any query; with non-English
  headers the Update Role / Resolve forms silently return "not found".
- `GitService.create_worktree` (`git_service.py:226`) hardcodes `assets/.worktrees/<role>`; the
  hint "cd assets/.worktrees/…" is wrong for projects that install the skill without the
  `assets/` prefix.

The commit isolation itself (`git commit --only <path>` with `index.lock` retries) is careful —
the objection is to *what* gets committed, not how.

## 3. Cosmetics (lowest priority)

KPI deltas are all grey `rgba(49,51,63,0.6)` on white (≈4.0:1 at 14 px, below WCAG AA 4.5:1);
the red "N blocking" highlight never triggers because of the type bug above; statuses are encoded
by emoji only (no difference in monochrome or for colour-blind readers); question text uses 24 px
heading size and the role card (28 px) competes with the section heading; the Roles Board grid is
hardcoded to three columns; at 375 px the tab strip scrolls horizontally with no visible affordance.

Related: the same repository still carries 22 `__pycache__/*.pyc` and `.coverage`, whose paths
exceed the Windows limit and break `git clone` without `core.longpaths`.
