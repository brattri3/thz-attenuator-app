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
