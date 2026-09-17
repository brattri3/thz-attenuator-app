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

That last line — `- **Status:** open|taken|done` — is what
`coordination/tools/build_index.py` parses to build `INDEX.md`. Write it exactly. The parser is
in fact a little more forgiving than that (the colon is optional, the case is ignored, and the
marker is found mid-line), but **do not rely on it**: the leniency is an implementation detail
nobody promised, the three keywords are not lenient at all, and a project that drifts toward
"whatever the tool happens to accept" is the one this section exists to warn about.

This is the single biggest lesson worth taking from projects that didn't enforce this from day one: a status line whose
exact wording isn't specified drifts into half a dozen different phrasings over months (`Status:`
vs `Статус:` vs `done (resolved)` vs a status buried mid-paragraph), and an index tool built
against "the status line" quietly stops finding some of them. Enforce the literal string from the
first entry, not just when it starts hurting.

The three keywords stay English even in a project written in another language — they are
parsed by tooling, while the What/Context/Done-when text is prose and is not
(the skill's `references/rationale.md`).

Closing an entry means editing that one line in place (`open` → `done`) — that's not a violation
of append-only, since the surrounding decision text above it isn't touched.

**A fourth word you may see but must never write: `missing`.** An entry with no status line at
all is reported as `missing` by the tools and counted as **open**, so a request nobody has
answered stays visible instead of disappearing into the closed pile. It is produced by the
readers, never by a person, and it is not a status you can set — writing it into an entry
yourself makes that entry indistinguishable from a broken one. If two `**Status:**` lines end up
in one entry, the last is used and the duplication is reported; that is ambiguity, not a
vocabulary word.

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
