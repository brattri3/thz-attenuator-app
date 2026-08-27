# Setup — wiring the pieces into a target project

Read this when actually instantiating the templates into a project (SKILL.md points here for the
mechanical steps, so it doesn't have to carry them inline).

## 1. Directory layout to create

```
coordination/
  CHARTER.md
  PROJECT.md
  OWNERSHIP.md
  ACTIVITY.md
  HANDOFFS.md
  QUESTIONS.md
  BOARD.md
  ORCH_BRIEF.md
  LAUNCH_PROMPTS.md
  roles/
    <ID>.md         (one per role, from roles/ROLE_ID.md)
  tools/
    build_index.py
    kpi_git.py
    kpi_config.json  (optional, from kpi_config.json.template — only if the project needs it)
.claude/
  hooks/
    check-context-budget.sh
    budget.json      (from budget.json.template)
  rules/
    <topic>.md        (optional, path-scoped — see references/setup.md §3)
CLAUDE.md             (from CLAUDE.md.template, at repo root)
archive/
  README.md
```

## 2. Wiring the SessionStart hook

`check-context-budget.sh` only does anything if it's actually registered. Add to
`.claude/settings.json` (create the file if the project doesn't have one yet — merge into it if
it does, don't overwrite existing hooks):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/check-context-budget.py"
          }
        ]
      }
    ]
  }
}
```

Verify it actually fires and warns correctly before trusting it — write a `roles/TEST.md` file
larger than the configured `limit_bytes`, then feed the hook synthetic stdin matching what
`SessionStart` sends:

```bash
echo '{"source":"startup"}' | python .claude/hooks/check-context-budget.py
```

You should see a `systemMessage` JSON line naming the oversized file. Delete the test file
afterward.

## 3. `.claude/rules/*.md` with `paths:` — when to reach for this

This is a real, current Claude Code mechanism, distinct from both `CLAUDE.md` (always loaded) and
Skills (never path-triggered — task-description match or explicit `/name` only). A file in
`.claude/rules/` with a `paths:` frontmatter list of globs loads into context only when a session
reads or edits a file matching one of those globs; a rules file with no `paths:` key loads
unconditionally, same as `CLAUDE.md`, just split into a separate named file.

Use it for: commands/conventions/domain background that's real and useful, but only to the
subset of roles whose work actually touches a specific subtree. Moving this kind of content out
of `CLAUDE.md` and into scoped rules is a legitimate way to bring cold-start cost down for roles
that never touch those paths, without losing the content for roles that do.

Don't use it for: anything every role needs regardless of what they touch (that's `CLAUDE.md`),
or a repeatable *procedure* you invoke by name or that should trigger on a task description
rather than a file path (that's a Skill).

## 4. Populating the templates for your project

Work through them roughly in this order, since later ones reference earlier ones:

1. `PROJECT.md` — the role roster and zone boundaries. Do this first; everything else names
   roles from here.
2. `OWNERSHIP.md` — the path-by-path map, seeded from `PROJECT.md`'s zones.
3. `CHARTER.md` — mostly usable as-is; fill in the "shared/core code" and "conflict hot spots"
   placeholders once §1–2 exist.
4. One `roles/<ID>.md` per role from `roles/ROLE_ID.md` — this is the file that actually gets
   read every cold start, so keep it within budget from the very first version, not just once it
   grows too large.
5. `LAUNCH_PROMPTS.md` — the launch table, once role session names are settled.
6. `CLAUDE.md` at the repo root — the index table and guardrails, once the above exist to point
   to.
7. `ACTIVITY.md`, `HANDOFFS.md`, `QUESTIONS.md`, `BOARD.md` — mostly usable as-is; they're
   append-only logs, not filled-in-once documents.
8. `ORCH_BRIEF.md` — only if the project has an orchestrator role and standing goals worth
   keeping separate from that role's own cold-start file.

## 5. `build_index.py` and `kpi_git.py`

Both are stdlib-only Python, run from the repo root:

```bash
python coordination/tools/build_index.py --out coordination/INDEX.md
python coordination/tools/kpi_git.py
python coordination/tools/kpi_git.py --json coordination/reports/kpi_git.json
```

If you are using the Streamlit dashboard, you will need to install its dependencies:

```bash
pip install -r assets/coordination/tools/dashboard/requirements.txt
```

Neither needs registering anywhere — run them manually, or wire either into a scheduled task if
your tooling supports one (e.g. a Claude Code Routine that clones the repo read-only, regenerates
`INDEX.md`, and commits it — only worth doing once the journals are large enough that a stale
index is actually costing someone time).

`kpi_git.py` reads `coordination/tools/kpi_config.json` if present (template:
`kpi_config.json.template`) — leave it absent until you actually hit the two problems it solves
(a bulk-import commit skewing stats, or bulk data commits inflating "lines changed"); don't
pre-populate it speculatively.

## 6. Optional: git/GitHub rails

Only do this once `references/git-github-rails.md` §"when this earns its place" actually applies
— it's an add-on, not part of the base setup in §1–5 above.

1. **CODEOWNERS.** Copy `assets/dot-github/CODEOWNERS.template` to `.github/CODEOWNERS`. Fill in
   every `<...>_GITHUB_USER>` placeholder with a real GitHub username or team, mirroring
   `OWNERSHIP.md`'s zones exactly (same paths, same owners) — the two files describing the same
   fact differently is exactly the kind of drift `references/rationale.md` warns about elsewhere.

2. **CI checks.** Copy `assets/dot-github/workflows/coordination-checks.yml.template` to
   `.github/workflows/coordination-checks.yml` (drop the `.template` suffix). No placeholders to
   fill — it reads `.claude/hooks/check-context-budget.sh` and `coordination/roles/*.md` at their
   standard paths. Push it and confirm the workflow actually appears and runs (GitHub's Actions
   tab) — don't assume it's wired up correctly from the YAML alone; the real verification is
   watching it run once, the same way the local hook was verified with synthetic stdin in §2.

3. **Branch protection (needs repo admin rights).** In the GitHub UI: Settings → Branches → Add
   branch protection rule → target the default branch → enable "Require status checks to pass"
   and select the `checks` job from `coordination-checks.yml` → optionally also enable "Require
   review from Code Owners" (only meaningful once CODEOWNERS lists more than one real account —
   see the caveat in `references/git-github-rails.md`). If doing this programmatically via `gh api`
   or the REST API, the token needs admin-level access to the repo; if it doesn't, this is a
   30-second manual step, not a blocker for the rest of the setup.
