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
