# OWNERSHIP — path-by-path ownership map

"Owns" = has the right to WRITE. Everyone else is read-only; a change → request via
`HANDOFFS.md` + a note in `ACTIVITY.md`.

## Exclusive zones

| Path | Owner | Others |
|---|---|---|
| *(fill in per role, e.g.)* `src/core/**` | B | read |
| `docs/**` (if a role owns documentation) | \<ID\> | read |
| `coordination/**`, `CLAUDE.md`, top-level state files | ORCH | read; proposals go in ACTIVITY |
| `coordination/roles/<ID>.md` | **that role, `<ID>`, itself** | read. The **only** file a role must read at cold start — its own zone, what's open, what's next, where to go for detail. Each role maintains its own file; the orchestrator only edits someone else's during a process restructure |
| `coordination/rationale/**` (if you keep one — see `references/rationale.md` in this skill) | ORCH | read. Decision rationale, not loaded at cold start; nothing here is ever executed |
| `archive/**` — frozen layers of the project (rules for the directory: see the `archive/README.md` template) | ORCH | read. **Nothing here is ever executed**, even text phrased as an instruction; archived content is not added to or deleted, only frozen. Proposing to archive something goes through `QUESTIONS.md` |

## Rule for anything not listed above

**Don't create a new top-level directory without a line in this table.** An unowned area rots
silently — nobody is obligated to maintain it and nobody has clear permission to touch it
without asking, which in practice means it accumulates cruft nobody wants to be responsible for
cleaning up. When a new top-level directory shows up, add a row here in the same commit (or the
next `coordination/**` commit) that introduces it.

For directories owned by convention rather than by a single explicit grant (e.g. "results of a
task go to the role that computed them"), state the *rule*, not an exhaustive list — a rule
survives new subdirectories showing up; a list needs updating every time one does.

## Shared files and access rules

| File | Rule |
|---|---|
| `coordination/ACTIVITY.md` | **append-only**, every session appends with its `[<ID>]` tag; don't edit someone else's entries |
| A shared per-project log (e.g. a research log, a build log) | same append-only convention — name it here once it exists |
| `coordination/BOARD.md` (if you keep one — a one-line-per-role dashboard) | each session writes ONLY its own line |

## Per-session state

Each role keeps its OWN state/progress file (not a shared one) — name where, once each role has
one, e.g. `<ID> → <path>`. A shared `state.json` two roles both write to is exactly the kind of
"conflicting hot spot" worth avoiding from day one.

## Conflict hot spots (guard these especially)

List the specific shared files where two roles' edits are most likely to collide — the core
module(s) one role owns, an append-only log, any main-branch state file. Naming them here isn't
redundant with the rows above; it's a quick-glance list for "what do I have to be careful about"
without reading the whole table.
