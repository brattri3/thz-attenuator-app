# PROJECT — roles, zones, question protocol

> **Not cold-start reading.** A role's entry point is `coordination/roles/<ID>.md`. Come here
> for the whole-picture table: a zone dispute, launching a new role, handing off work.
>
> The full path-by-path map is `OWNERSHIP.md`.

## Roles and zones

| Role | Session name | Specialty | Writes |
|---|---|---|---|
| **\<ID\>** | `<id>-<specialty>` | one line: what this role is for | the paths it owns |
| **ORCH** | `orch` | coordination, merges, process | `coordination/**`, `CLAUDE.md`, `archive/**` |

Fill in one row per role. Naming convention suggestion: `<role-letter>-<specialty>` (e.g.
`a-model`, `b-core`) — a letter prefix keeps `claude agents` sorted by role and matches the
commit-prefix convention in `CHARTER.md §4`. Pick IDs that won't need renaming later; treat them
as protocol identifiers, not descriptive labels.

## Zone boundaries worth spelling out explicitly

Whenever two roles' work could plausibly overlap, write the boundary down here **before** it
causes a conflict, not after. State the boundary by layer/responsibility, not by directory list
alone — a layer boundary ("role B owns the core computation, role A owns experiments built on
top of it") survives directory reorganizations; a directory list doesn't. Two examples of the
kind of boundary worth a paragraph:

- **Core vs. experiments** — one role owns shared/core logic others depend on; other roles build
  on top of it without needing a handoff for every use, but never fork a second copy of core
  logic — that's the invariant a boundary like this protects.
- **Adjacent specialties that could both plausibly "own" the same kind of output** (e.g. two
  roles that both touch "documentation" or "review") — state which one does primary work and
  which one consumes/synthesizes it, and the hand-off mechanism between them.

## Question protocol (`QUESTIONS.md`)

Hit a decision that isn't yours to make — don't decide it yourself and don't let it go quiet: a
row in `QUESTIONS.md`.

- **`blocking`** — the step is impossible without an answer. Stop, make no changes, wait.
- **`non-blocking`** — there's a reasonable default. Take it, **write down in the same row what
  you assumed and why**, keep working.
- Only the owner or the orchestrator closes a row (`status → resolved`, answer appended).
- The file is **append-only**: the text of a question already asked, and a decision already
  recorded, is never rewritten to match a new reality — otherwise the decision log stops being
  evidence of what was actually decided and when.

## Multiple environments (if your project spans more than one machine/sandbox)

If work happens across more than one machine or ephemeral cloud environment, say so here
explicitly, and note per-environment quirks (what each one can and can't see, what's ephemeral
vs. persistent). The important invariant: **coordination between environments happens through
git** — pull before working, push after the owner clears it. No live-process mechanism sees
across environments; don't assume one exists just because it exists within one environment.
