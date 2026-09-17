# BOARD — one line per role, at a glance

Each role writes and maintains **only its own line**. This is a dashboard, not a journal —
detail belongs in `roles/<ID>.md` (live state) or `ACTIVITY.md` (history), not here. Keep every
line short enough to scan the whole table in one glance; if a line needs a paragraph, that's a
sign the detail belongs in the role's own file with a pointer from here instead.

| Role | Status (date) | One-line summary |
|---|---|---|
| \<ID\> | active (YYYY-MM-DD) | what it's doing right now, in one line |
| ORCH | active (YYYY-MM-DD) | coordination status |

**Status vocabulary:** `active` · `idle` · `stale` · `blocked`, written as
`<status> (YYYY-MM-DD)`. These are protocol tokens parsed by tooling and stay English even in a
project written in another language — the one-line summary is prose and does not
(the skill's `references/rationale.md`). A word outside this list is reported as unrecognised and counted in
neither the active nor the inactive total, rather than being guessed at.

A role that's gone quiet for a while doesn't need its line deleted — update the date and status
so it's visible at a glance that it's stale (`CHARTER.md §7` covers what the orchestrator does
about a role that's actually gone quiet, as opposed to one that's just between sessions).
