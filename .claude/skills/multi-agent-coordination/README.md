# multi-agent-coordination-skill

A [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills) that sets up a
coordination scaffold for projects where several Claude Code sessions — each holding a distinct,
continuing role/zone — share one repository over an extended period.

It's not a framework or a running service: there's no server, no live process registry, no
database. It's a set of markdown templates and two small stdlib-only Python scripts, distilled
from a real multi-role project that ran this paradigm for weeks and fixed the specific problems
it hit along the way. Those problems — and why the fix looks the way it does — are written up in
[`references/rationale.md`](references/rationale.md).

## What's in it

- **`coordination/` templates** — role zone files, an append-only decision journal
  (`QUESTIONS.md`), cross-role request log (`HANDOFFS.md`), project-wide activity journal
  (`ACTIVITY.md`), ownership map, charter of working rules, and a launch-prompt table.
- **`.claude/hooks/check-context-budget.sh`** — a `SessionStart` hook that warns (never blocks)
  when a role's cold-start file grows past its byte budget, so "keep this file short" stays true
  without anyone having to remember to check.
- **`.claude/rules/`** — an example of Claude Code's path-scoped `paths:` rule files, for pushing
  domain knowledge out of the always-loaded `CLAUDE.md` and into context only when a session
  actually touches the relevant paths.
- **`coordination/tools/build_index.py`** — turns `QUESTIONS.md` + `HANDOFFS.md` into a short
  open/closed index, so nobody has to read either journal in full just to see what's outstanding.
- **`coordination/tools/kpi_git.py`** — per-role commit/line/active-day stats from `git log`
  alone (no external telemetry, no live process tracking) — with configurable exclusions for
  bulk-import commits and non-authored (data/generated) paths.

## Using it

Install as a Claude Code Skill (see Claude Code's skill docs for how skills are discovered in
your setup), then in a project that needs this, ask Claude something like "set up multi-agent
coordination for this project" — the skill interviews you for the project name, roles, and
guardrails, then instantiates the templates. See [`SKILL.md`](SKILL.md) for exactly what it does,
and [`references/setup.md`](references/setup.md) for the manual/mechanical version of the same
steps if you'd rather do it by hand.

## License

MIT — see [`LICENSE`](LICENSE).
