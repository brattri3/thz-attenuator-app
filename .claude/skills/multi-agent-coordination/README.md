# multi-agent-coordination-skill

A [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills) that sets up a
coordination scaffold for projects where several agent sessions — each holding a distinct,
continuing role/zone — share one repository over an extended period.

The scaffold is platform-agnostic: a role is held by whatever session reads its file and makes
commits, so Claude Code, Gemini via Antigravity, Cursor or Aider can each hold one. See
[`docs/ru/CROSS_PLATFORM_BRIDGE.md`](docs/ru/CROSS_PLATFORM_BRIDGE.md).

That is enforced by the file layout rather than left to good intentions: the project's rules
live in **`AGENTS.md`**, the cross-vendor convention governed since December 2025 by the Linux
Foundation's [Agentic AI Foundation](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation),
and `CLAUDE.md` is a four-line adapter that imports it and adds the Claude Code specifics
(`claude -n <name>`, `claude agents --json`, `.claude/rules/` globs). Claude Code reads
`CLAUDE.md` and not `AGENTS.md`, which is exactly why the adapter exists.

It does not compete with a tool's own multi-agent features. Claude Code's agent teams keep
their shared task list in `~/.claude/`, scoped to one session and deleted when it ends; this
scaffold is the durable half — in git, on every machine, readable by any tool.

It's not a framework or a running service: there's no server, no live process registry, no
database. What lands in your project is markdown templates plus **stdlib-only Python** — six
tools, the shared `coordlib/`, and two hooks: roughly 3,500 lines that import nothing outside the
standard library, so adopting the scaffold adds no dependency to install or track. The optional
Streamlit dashboard below is the single exception, and it is not installed by default.

The repository itself is bigger than what it installs — about 10,700 lines under
`coordination/tools/`, roughly half of it the test suite, which stays here rather than travelling
into your project. All of it is distilled from a real multi-role project that ran this paradigm
for weeks and fixed the specific problems it hit along the way. Those problems — and why the fix
looks the way it does — are written up in [`references/rationale.md`](references/rationale.md).

## When not to install it

The problem this solves is two sessions holding the same repository with no idea what the other
decided. Where that isn't the situation, the scaffold is overhead and the journals become files
nobody reads:

- **One session working through a task list.** Nothing here helps it.
- **A one-off fan-out** — several agents on independent files, finished within the hour. Reach
  for your tool's own subagent mechanism; state that dies with the run is the right state.
- **Work that ends before anyone forgets why.** What this buys is a decision outliving the chat
  it was made in, and that only pays across sittings.

The test is whether *"whose job is this edit?"* has a non-obvious answer in your repository. If
it has an obvious one, don't install this. (`SKILL.md` applies the same test before setting
anything up, and is meant to say so out loud rather than proceed.)

## What's in it

- **`coordination/` templates** — role zone files, an append-only decision journal
  (`QUESTIONS.md`), cross-role request log (`HANDOFFS.md`), project-wide activity journal
  (`ACTIVITY.md`), ownership map, charter of working rules, and a launch-prompt table.
- **`.claude/hooks/check-context-budget.py`** — a `SessionStart` hook that warns (never blocks)
  when a role's cold-start file grows past its byte budget, so "keep this file short" stays true
  without anyone having to remember to check.
- **`coordination/tools/discover.py`** — read-only reconnaissance run *before* the setup
  interview: candidate zones from who actually edits what in git history, existing
  `CODEOWNERS` and agent instruction files to import rather than overwrite, the verification
  commands already defined. So the questionnaire asks only what the repository cannot answer.
- **`coordination/tools/upgrade.py`** — the delivery channel a copied-in scaffold otherwise
  lacks. Compares what you installed, what you changed, and a newer version of the skill, and
  reports where a human is actually needed. It reports; it does not merge.
- **`coordination/tools/coordlib/`** — the shared, stdlib-only core: one status vocabulary, one
  markdown-table tokenizer, and the diagnostics channel the tools use to say "this file's schema
  was not recognised" instead of quietly reporting zero.
- **`.claude/rules/`** — an example of Claude Code's path-scoped `paths:` rule files, for pushing
  domain knowledge out of the always-loaded `CLAUDE.md` and into context only when a session
  actually touches the relevant paths.
- **`coordination/tools/build_index.py`** — turns `QUESTIONS.md` + `HANDOFFS.md` into a short
  open/closed index, so nobody has to read either journal in full just to see what's outstanding.
- **`coordination/tools/kpi_git.py`** — per-role commit/line/active-day stats from `git log`
  alone (no external telemetry, no live process tracking) — with configurable exclusions for
  bulk-import commits and non-authored (data/generated) paths.

### Optional add-ons

Neither is part of the base scaffold; install one only when the project has actually hit the
problem it solves.

- **git/GitHub rails** (`assets/dot-github/`) — CODEOWNERS, CI checks. See
  [`references/git-github-rails.md`](references/git-github-rails.md).
- **`coordination/tools/dashboard/`** — a Streamlit **read-only** view of the journals, and the
  only piece here that requires a third-party dependency. It shows the roles board, the decision
  queue, handoffs and worktrees on one screen; editing stays in git, where every role already
  works. It used to write as well, behind a diff-and-confirm step and an opt-in environment
  variable; that half was removed once field data showed nobody had ever used it. For the same
  view with no dependency at all, `build_index.py` writes `INDEX.md`.

### Building something on top

Monitoring, effectiveness reports, project-health consoles — those belong in **their own
repositories**, not here and not in a fork of this one. A fork exists to converge back; an
extension that consumes the coordination layer never will.

[`references/extension-contract.md`](references/extension-contract.md) states what such a tool
may rely on: read at a committed revision rather than the working tree (no writer here is
atomic), display three states rather than two, which files are sources and which are
projections, and which of `coordlib`'s modules are promised. It is deliberately short and points
at the code instead of restating it.

## Using it

Install as a Claude Code Skill (see Claude Code's skill docs for how skills are discovered in
your setup), then in a project that needs this, ask Claude something like "set up multi-agent
coordination for this project" — the skill interviews you for the project name, roles, and
guardrails, then instantiates the templates. See [`SKILL.md`](SKILL.md) for exactly what it does,
and [`references/setup.md`](references/setup.md) for the manual/mechanical version of the same
steps if you'd rather do it by hand.

Русская версия концепции (обязательный и необязательный слой, границы, human-интерфейс):
[`docs/ru/CONCEPT.md`](docs/ru/CONCEPT.md).

### What it costs

Two costs, and only one of them is bounded.

The bounded one is cold start. Each role session re-reads `coordination/roles/<ID>.md`, which has
a **2,400-byte budget** and a hook that warns when it grows past it, plus whatever of
`CHARTER.md` (about 13 KB) it needs. That is a few thousand tokens once per session start —
noise against any current context window, and it is capped on purpose, which is the whole point
of budgeting a file that gets re-read forever.

The unbounded one is whoever coordinates. Every launch, verification and check accumulates in
that session and is re-read every turn. Measured on the project this scaffold came from: role
files held at 2,400 bytes each while the orchestrator's own context reached **508,093 tokens**,
so the coordination layer cost more per turn than the work it coordinated. `CHARTER.md §10`
makes handing over early a standing duty for exactly this reason — the handover costs one
journal entry, because everything the next session needs is already in files.

The one-time cost is human, not tokens: the setup interview, and writing one role file per role
honestly enough to be worth re-reading.

### Nothing leaves the machine

No tool installed by default makes a network call. Everything reads files and `git log` in the
local checkout, including `upgrade.py`, which compares your installation against a copy of the
skill already on disk and therefore works offline.

Both optional add-ons are worth naming, since neither is installed unless you ask. The
git/GitHub rails put CI templates in GitHub Actions — the one place the coordination files get
read somewhere other than your machine. The Streamlit dashboard serves a page, but a local one,
and it reads the same files everything else reads.

### Removing it

`rm -rf coordination/`, delete `.claude/hooks/` and the hook entries they added to
`.claude/settings.json`, drop the `.claude/rules/` files you took from here, and remove the
coordination paragraphs from `AGENTS.md` / `CLAUDE.md`.
Nothing in the project imports the tools, so nothing breaks; the journals were ordinary markdown
all along.

What was recorded stays recorded — the decisions in `QUESTIONS.md` remain in git history after
the file is gone, which is the reason for writing them into a file in the first place.

## License

MIT — see [`LICENSE`](LICENSE).
