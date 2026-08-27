# Role \<ID\> — \<one-line specialty\>

**Session name:** `<id>-<specialty>` · **Commit prefix:** `[<ID>]`

## Writes
The specific paths this role owns (see `OWNERSHIP.md` for the canonical list; repeating the
short version here saves a lookup for the common case).

## Does not touch
Paths owned by other roles that this role commonly brushes up against — name them explicitly so
it's obvious at a glance, not just "everything not listed above."

## What's open, what's next

This section is the **only** part of this file that should change often, and it's the reason
this file exists: a role reads *only* this file at cold start (`CHARTER.md §6`), so whatever's
here has to be enough to resume work without reading anything else. Keep it to a live summary of
current state — a numbered list of open items, each with just enough detail (a file+line
reference, a key number, a one-line "why") to pick the thread back up.

**Keep this file under your project's cold-start budget** (a few hundred words / ~2400 bytes is
a reasonable target for most projects — see `.claude/hooks/` in this skill for a hook that
checks this automatically). When an item here gets fully resolved, don't let its detailed
history accumulate in this file — write the detail into `ACTIVITY.md` (which is meant to be
searched, not read cold) and shrink this file's line down to a one-sentence "closed, see
ACTIVITY.md `<date>`" pointer, or drop it once it's no longer actionable.

1. *(example)* Open item — one line: what's the state, what's the next concrete step.
2. *(example)* Blocked item — what it's blocked on (a `QUESTIONS.md` row, another role's
   deliverable), and what to do meanwhile.

## Mine
Any per-role state file, log, or reference doc this role maintains and might want to jump to
directly (a progress/state file, a key results summary). Not for content that belongs above —
only for pointers to *other* files.

## Remember
Optional: a standing methodological caution specific to this role's work — the kind of thing
that's easy to forget between sessions and expensive to relearn by making the mistake again.
