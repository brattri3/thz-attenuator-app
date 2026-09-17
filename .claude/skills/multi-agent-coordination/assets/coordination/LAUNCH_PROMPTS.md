# LAUNCH_PROMPTS — how to start each role's session

Keep this file **short**. Its only two jobs are: (1) the launch-command table, and (2) one
universal nudge-to-start template. Resist the urge to duplicate each role's zone, task list, or
guardrails here — that content already lives in `coordination/roles/<ID>.md`, which every role
reads at cold start anyway. A prompt block per role that repeats that content is pure
duplication, and duplication drifts: the day someone updates a role's zone in `roles/<ID>.md`
and forgets this file has a stale copy, a session launched from here starts with wrong
information it has no reason to distrust. If you want richer per-role launch ergonomics later,
put them in the prompt text itself (below), not in a separate file per role — see
`CHARTER.md §8` for why a `.claude/agents/*.md` file is the wrong tool for this even though it
looks tempting (it silently turns a role into a callable subagent for every session in the
project, which conflicts with a role needing continuity/state ownership).

## Launch table

| Role | Session name | Launch |
|---|---|---|
| \<ID\> | `<id>-<specialty>` | `claude -n <id>-<specialty>` |
| ORCH | `orch` | `claude -n orch` |

## Universal start nudge

Once a session is named and running, send:

```
Start: read coordination/roles/<ID>.md, then continue the first open item there.
```

If you want the session to keep working autonomously across multiple steps rather than stopping
after one, wrap it with your tool's looping mechanism (e.g. Claude Code's `/loop`) instead of
writing a separate always-keep-going prompt variant here.

### What to keep OUT of the nudge

**Don't tell the session to `git clone` the project.** When the repository is already attached to
the session — the normal case for a cloud or container session started against a repo — a clone
just re-downloads what is already on disk. Measured: **+157 MB, +3.4 s**, and no information the
checkout did not already have. An explicit clone earns its place only when a from-scratch
checkout is the thing being tested (timing a cold provision, verifying container setup), not as a
default "to be safe".

If the session needs to know whether work is pushed, `git fetch origin <branch>` on the checkout
it already has answers that — and it was the only thing the clone was really providing.
`CHARTER.md §4` has the rule, and the measured failure that makes it worth stating.

## Launching a session you will not be able to talk to

A session started from another session — cloud, remote, or on a schedule — is not a subagent:
nothing you send afterwards reaches it, and you cannot read its transcript (`CHARTER.md §8` has
the measurements). Its opening prompt is the entire briefing, so write it as one:

```
The repository is already checked out; do not clone it. Read coordination/roles/<ID>.md.

Task: <the complete task, including every decision already taken — this session cannot ask>

When done: <commit to branch <X> / publish the result and report its URL>. If something is
genuinely undecidable, write the question into coordination/QUESTIONS.md, commit it, and
carry on with the rest rather than stopping.

This work will be checked against git and the published result, not against your summary.
```

The last line is not decoration: a launched session's self-report is the one thing that cannot be
verified from outside it (`CHARTER.md §8`). Say the check runs on primary sources — and run it.

**Outward-facing actions cost one human approval, not a dead session.** Opening issues or pull
requests, pushing, publishing, sending — a harness may hold these for confirmation even in a
session that was told to expect it. Observed: the gate fires on the class of action, not on the
wording, so a prompt that politely anticipates it buys nothing; the session parks before doing
anything, and its status is indistinguishable from ordinary idleness. One human opening it
releases the whole queue in a single turn. So either the launching session performs the
outward-facing step itself, where it holds the credentials, or the human is told upfront that
they will need to open the session once. What does not work is scheduling such a session
unattended and assuming it ran.

### On a schedule: bind to a session, or bootstrap the fresh one

A scheduled run is a launched session with a clock instead of a caller, and the mode matters more
than the cadence. Two exist:

- **Bound to an existing session** — the firing lands in a session that is already running, with
  the checkout, the URLs and the history it has accumulated. **This is the default for anything
  repo-bound**: regenerating `INDEX.md`, refreshing KPI output, updating a published page.
- **A fresh session per firing** — starts empty. No checkout, no artifact URL, nothing. A prompt
  like "run `coordination/tools/kpi_git.py` from the repo root and republish" then has nothing to
  run against, and the firing is a silent no-op: it reports no error, it simply does nothing.
  This was the first configuration tried in the field report behind this section, and it produced
  nothing until it was noticed by hand.

Binding to a session is not free either — the run inherits that session's context and cost, and
stops working the day that session ends. Take that trade knowingly rather than by default.

If a fresh session per firing is genuinely what you want, its opening prompt must do the bootstrap
itself: get the repository (`git fetch origin main && git reset --hard origin/main`, or clone if
there is nothing to fetch into), then — if the tooling needs real history, as `kpi_git.py` does
walking `--all` — check `git rev-parse --is-shallow-repository` and `git fetch --unshallow`, and
only then read any published page by its URL.

**Check what "leave it unchanged" actually does before writing it into a scheduled prompt.**
Omitting a field is not the same as preserving it. A daily republish here told the session to omit
the page's title "so as not to change manually-set metadata"; omitting it made the publisher
re-derive the title from a temporary filename instead, and the page quietly renamed itself on
eight consecutive days before anyone connected the two. A scheduled prompt repeats its mistake
every firing, which is exactly what makes a small wrong assumption expensive.

## If your project also uses a different tool/agent (no session names, no `/loop`, etc.)

Note the genuinely different mechanics briefly rather than duplicating the whole table — e.g. "no
persistent named sessions, so paste the same cold-start nudge above at the start of each new
conversation."
