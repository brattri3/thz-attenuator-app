---
name: multi-agent-coordination
description: Sets up a battle-tested multi-session/multi-role Claude Code coordination scaffold — role zones, an append-only decision journal, cold-start budget checks, cross-role handoffs, and a KPI-from-git script — for a project where several Claude Code sessions (or a human plus several sessions) work the same repository in parallel roles. Use this whenever the user wants to run multiple Claude Code sessions/agents on one project, coordinate parallel roles or "subagents as team members," avoid sessions stepping on each other's files, set up a coordination directory, or asks for something like "multi-agent workflow," "team of Claude sessions," "role-based coordination," or "how do I keep several Claude Code sessions from conflicting." Also use it to review or fix an EXISTING coordination setup that's showing the specific failure modes this skill was built to prevent (see references/rationale.md) — status-line phrasing drift, duplicated launch prompts going stale, an ever-growing orchestrator brief, or someone about to turn a role into a `.claude/agents/` subagent definition.
---

# Multi-Agent Coordination

This skill instantiates a coordination scaffold that a real multi-role Claude Code project
(several sessions, each holding a distinct specialty/zone, sharing one repository) evolved over
weeks of actual use — including the specific mistakes it made and fixed. `references/rationale.md`
documents those mistakes; read it before deciding to simplify or skip a piece of the scaffold, in
case the piece you're about to drop is exactly the fix for a failure mode you haven't hit yet.

## When this fits, and when it doesn't

This is for a project where **multiple Claude Code sessions genuinely need to hold distinct,
continuing responsibilities** ("zones") in the same repository over an extended period — not a
single session doing one task, and not a one-off parallel fan-out you'd reach for the `Agent`
tool for instead. The giveaway questions: will more than one named, persistent session work this
repo over multiple sittings? Does each one own a distinct part of it well enough that "whose job
is this edit" is a real question? If the honest answer is "no, this is one session working
through a task list," this scaffold is overhead — say so and don't set it up.

## What to do

### 1. Interview the user

Don't guess these — they shape every template:

- **Project name and what it does** (a sentence or two — goes at the top of `CLAUDE.md`).
- **Documentation/commit language** — the source project used Russian throughout; yours might be
  English or something else. Every template here is written in English as the *scaffold*
  language, but the user's project content (zone descriptions, role names, actual entries) should
  be written in whatever language the user's project actually uses.
- **The roles** — how many, what each one's specialty and zone is, and a short session-name
  convention (the source project used `<letter>-<specialty>`, e.g. `a-model`, but that's a
  convention, not a requirement). Don't invent roles the user didn't ask for; a project with two
  roles doesn't need the same shape as one with seven.
- **Is there an orchestrator role** — a session that coordinates the others, merges branches,
  keeps `coordination/**` current? Many projects want one; some don't (a human filling that role
  directly is fine too — then skip `ORCH_BRIEF.md` and the orchestrator row in the templates).
- **Does work span multiple machines/environments** (a workstation, a laptop, an ephemeral cloud
  sandbox)? If so, `PROJECT.md`'s multi-environment section is worth filling in carefully — that's
  exactly where "which mechanism sees what" assumptions go wrong.
- **What are the actual hard guardrails** — read-only paths, a push-only-with-permission rule,
  domain-specific quality bars. These go in `CLAUDE.md`'s guardrails section; don't invent generic
  ones, ask what actually matters for this project.

### 2. Instantiate the templates

Read `references/setup.md` for the exact directory layout, file order, and hook-wiring steps —
follow it rather than improvising the layout, since later templates reference earlier ones by
exact path. In short: copy everything under this skill's `assets/` into the target project
(dropping the `.template` suffix where present, and `dot-claude/` becomes `.claude/`), then fill
in the placeholders (`<PROJECT NAME>`, `<ID>`, `<LANGUAGE>`, role tables, zone descriptions) from
the interview — one `roles/<ID>.md` per role the user named. Wire the `SessionStart` hook into
`.claude/settings.json` per `references/setup.md §2`, and verify it actually fires before calling
the setup done.

**Keep every `roles/<ID>.md` within its cold-start budget from the very first version.** It's
tempting to write a thorough first draft with lots of context — resist it. The budget hook will
catch growth later, but a file that starts oversized normalizes staying oversized.

### 3. Don't over-fill speculative content

Several templates (`QUESTIONS.md`, `ACTIVITY.md`, `HANDOFFS.md`, `kpi_config.json`) are meant to
start nearly empty and grow from real use, not be pre-populated with guessed content. Filling
`OWNERSHIP.md`'s "conflict hot spots" section with hypothetical conflicts nobody's hit yet, for
instance, produces noise a real conflict later will be buried under. Populate what the interview
actually established; leave placeholders as placeholders where the project doesn't have an answer
yet, and say so to the user rather than inventing one.

### 4. Explain what you set up, briefly

After instantiating, tell the user in a few sentences: where the role entry points are, how to
launch a session, and where the guardrails live — not a full walkthrough of every file, since the
templates themselves are meant to be self-explanatory reading. Point them at
`references/rationale.md` if they ask *why* something is shaped a particular way.

### 5. Optional: git/GitHub rails

Not part of the interview above, and not something to set up by default — only reach for it when
the user explicitly asks about GitHub-side enforcement (CI, required reviewers, branch protection)
or the project has actually hit a failure mode this addresses (a commit landed broken because a
session skipped the local hook; a shared "hot spot" file keeps colliding). Read
`references/git-github-rails.md` first — it covers what's genuinely documented as native Claude
Code behavior versus a GitHub feature the project adds, which of `assets/dot-github/*` to copy in,
and an explicit warning against moving `QUESTIONS.md`/`HANDOFFS.md` onto GitHub Issues. Same
principle as step 3: don't pre-install this speculatively.

## Reviewing or fixing an existing setup

If the user already has a coordination directory (theirs or one this skill set up before) and
wants it reviewed or fixed, check specifically for the failure modes in `references/rationale.md`
— status-line phrasing that's drifted from one exact string, a launch-prompts file that's grown
to duplicate role files, an orchestrator brief mixing durable goals with dated snapshots, or a
role that's been turned into (or is about to be turned into) a `.claude/agents/*.md` subagent
definition. Fix the specific thing found rather than replacing their whole setup with this
skill's templates — their setup has presumably diverged for reasons specific to their project.

## Reference files

- `references/setup.md` — the mechanical instantiation steps: directory layout, hook wiring, fill
  order, how to run `build_index.py` / `kpi_git.py`.
- `references/rationale.md` — the failure modes this scaffold's specific shapes were built to
  prevent, and why the fix looks the way it does. Read before removing or simplifying a piece of
  the scaffold.
- `references/git-github-rails.md` — optional server-side layer (CODEOWNERS, CI checks, when to
  use a real PR instead of a `HANDOFFS.md` entry) for a project that's outgrown pure client-side
  enforcement. Read only when step 5 above applies.
- `docs/ru/CROSS_PLATFORM_BRIDGE.md` - details on LLM agnosticism, Git Worktrees (`worktree_launcher.py`), and soft context limits.

Also check `coordination/tools/status.py` as a useful CLI dashboard for human orchestrators to see the overall state of the project.
