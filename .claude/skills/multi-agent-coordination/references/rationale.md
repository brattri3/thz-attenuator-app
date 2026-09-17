# Rationale — what this scaffolding is answering, and how the lessons were learned

The templates and scripts in this skill aren't a first draft — they're a distillation of a
multi-role Claude Code project that ran this paradigm for weeks, hit specific failure modes, and
fixed them. This file records those failure modes so the fix doesn't get "simplified away" the
next time someone edits a template and reintroduces the problem it exists to prevent.

## Status-phrasing drift in `HANDOFFS.md`

The source project's `HANDOFFS.md` header originally said a closed entry needed "a status
(`open`/`taken`/`done`)" — describing the *values*, not mandating an exact line. Over roughly a
month and ~29 entries, that turned into eight different actual phrasings: `Статус:`, `Статус
записи:`, with and without backticks, status embedded mid-paragraph instead of on its own line,
one entry with no status at all. A parser written against "the status line" (for `INDEX.md`)
missed several of these silently — they looked closed to a human skimming, but the tool counted
them as open, or vice versa.

**Fix baked into the templates here:** `HANDOFFS.md`'s format block mandates the *exact* string
`- **Status:** open|taken|done` as the literal last line, no variants. Enforce this from the
first entry, not "once it starts causing problems" — by the time it's causing problems, you
already have months of entries to retroactively fix.

## Status keywords are protocol tokens, not prose

The section above is about *phrasing* drift. This one is about *language*, and until now the
scaffold only implied its own rule.

Write everything a human reads in whatever language the project uses: questions, answers,
summaries, handoff bodies, role descriptions, commit subjects. But these stay English, in every
project, because tooling parses them:

- statuses — `open`, `taken`, `done`, `resolved`, `closed`
- question types — `blocking`, `non-blocking`
- board statuses — `active`, `idle`, `stale`, `blocked`
- the table headers themselves — `#`, `Question`, `Owner's answer`, `Type`, `Status`, `Role`,
  `Status (date)`, `One-line summary`

The docs already argued this by example — `Статус:` is cited three times as *the* failure — but
never said it plainly, and a dashboard was then built that accepted Cyrillic *headers* while
classifying Cyrillic *values* as closed. That combination is worse than either choice alone: a
Russian board parsed into rows that were all silently counted inactive, and a Russian question
journal reported "Open Questions: 0" while showing red OPEN badges beside the rows it had just
excluded.

**The tools do not guess at a translation.** An unrecognised status is reported as
`unknown-status` and counted in neither the open nor the closed totals; an unrecognised header
set is reported as `unknown-table-schema` and its rows are not read at all. Both appear in
`INDEX.md` under "Unrecognised", on stderr from `build_index.py`, and in the dashboard above the
counts — and a file with an unreadable schema is refused for writing, because a tool that could
not read a file must not write to it.

If that feels strict, the alternative is the failure this file exists to record: numbers that are
quietly wrong get believed, and nobody's job is to notice.

## `LAUNCH_PROMPTS.md` duplication drift

The source project's launch-prompt file grew to duplicate each role's full zone description,
current task list, and guardrails inline, in addition to the role's own `roles/<ID>.md` file
saying the same things. The two copies inevitably diverged — a role's zone changed in
`roles/<ID>.md` and the launch-prompt copy didn't get updated, so a freshly launched session
started with stale zone information it had no reason to distrust (it's the *launch* prompt; there's
nothing yet to check it against). The fix wasn't a smarter sync mechanism — it was deleting the
duplicated content entirely and reducing the file to a launch-command table plus one universal
"read your role file, continue the first open item" nudge.

**Lesson generalized:** anywhere two files could describe the same fact, prefer one file being
the source of truth and the other pointing at it, over trying to keep copies in sync by
discipline. Discipline doesn't scale across weeks and multiple contributors; a missing second
copy does.

## The `ORCH_BRIEF.md` durable-vs-snapshot split

An orchestrator's "brief" file naturally accumulates two different kinds of content: durable
goals that stay true for the life of the project, and dated status snapshots ("as of this week,
here's what's blocked"). Left unsplit, the file just grows — old snapshots never get removed
because removing them feels like deleting history, so the file becomes mostly stale status
updates with the durable content buried somewhere inside.

**Fix:** treat these as different content from the start. Durable goals stay in the live file,
rewritten in place as they change. A snapshot that's no longer current moves *verbatim* to
`archive/<name>-<year-month>/`, with a short README explaining what it was and where its durable
parts now live. The live file, after the move, should read like it was written today — not like
a changelog of every previous state it went through.

## The `.claude/agents/` trap ("roles as subagents")

It's tempting to formalize each role as a `.claude/agents/<ID>.md` subagent definition — it looks
like it would give one-command launching with the role's context baked in. This is a real
mechanical trap, not just a style preference: **any file placed in a Claude Code agent-
definitions directory automatically becomes callable as a subagent by every session in the
project**, regardless of what the file's author intended it to represent. A subagent has no
memory between invocations, doesn't survive the call that spawned it, isn't listed by
`claude agents`, and has no transcript kept — none of which is compatible with a role that's
supposed to hold a zone and carry continuity across a project's lifetime. Putting a role there
doesn't create a lightweight launcher; it silently creates a second, incompatible notion of what
that role even is.

**Resolution used here:** role launch ergonomics live in `LAUNCH_PROMPTS.md` as plain prompt
templates a human (or an orchestrating session) reads and acts on. Nothing about a role goes into
an agent-definitions directory. `CHARTER.md §8` states the boundary explicitly so it doesn't get
re-litigated project by project.

## Git trailer parsing needs a blank line before, none inside

`git interpret-trailers` requires the trailer block to be its own paragraph — a blank line
separating it from the commit body — and will silently fail to recognize it as a trailer block if
a trailer's value wraps onto a second line. In the source project, roughly a third of a week's
commits had trailers that *looked* right to a human reading the commit message but that git
itself didn't parse as trailers, because the block wasn't separated by a blank line from the
preceding text. This is exactly the kind of rule worth enforcing with a `PostToolUse` hook that
asks git itself (`git interpret-trailers --parse`) rather than trusting visual inspection — a
rule that's checked automatically stays true; one that's only documented rots.

## Why `.claude/rules/*.md` with `paths:` earns its place here

Before reaching for it, the source project's `CLAUDE.md` had grown to include command references,
data-format specs, and domain background that only a subset of roles ever needed — every role
paid the cold-start cost of all of it anyway. Verify this mechanism actually exists and behaves
as expected in your version of the tooling before building an unload plan on top of it (it did,
as of this writing — see `references/setup.md §3` for the exact frontmatter and load semantics),
rather than assuming from a project's internal docs that a feature works a particular way.

## Why there is no hook watching the orchestrator's own context

The obvious companion to the cold-start budget hook is one that warns when the *orchestrator's*
context grows too large — same shape, same warn-never-block posture, aimed at the resource that
turns out to dominate per-turn cost (`CHARTER.md §10` carries the measurement: 2400-byte role
files next to a 508,093-token orchestrator session). It was considered and deliberately not built.

A hook is handed an event payload, and nothing in it reports the session's live context usage; no
file in the repository knows it either. The only thing that does is the harness's own local
transcript — which is exactly the dependency this scaffold already dropped once. The source
project's first KPI collector read `~/.claude/projects/**/*.jsonl` and was retired in favour of
`kpi_git.py` because transcripts are tied to one machine, invisible to every other environment
working on the same project, and blind to subagents. A context hook would rebuild that dependency
for a smaller payoff, and it would answer "what is this session doing right now" out of
machine-local state — precisely the class of mechanism `CHARTER.md §10`'s first standing duty
exists to catch growing back.

What *is* checkable becomes the rule instead: the handover leaves a dated entry in `ACTIVITY.md`.
That entry is either in git or it is not — visible from any machine, needing no new tool, and
readable by a session that has never seen the one that wrote it. It is also the thing that
actually matters. A token count is only a proxy for the risk that something is lost when a session
ends; the journal entry is that risk being absent.

## The general pattern underneath all of the above

Every one of these is the same shape: a rule that lives only in a human-readable document decays
under real multi-session use, because nobody's job is to notice the decay. The fixes that stuck
were the ones that either (a) made the rule mechanically checkable (the commit-trailer hook, the
cold-start budget hook, the exact-string status line a parser can rely on), or (b) removed the
opportunity for two copies to diverge in the first place (deleting duplicated content rather than
trying to keep it synced). When extending this scaffolding for your own project, prefer both of
those over adding another paragraph asking people to remember something.
