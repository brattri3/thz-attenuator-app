# Setup — wiring the pieces into a target project

Read this when actually instantiating the templates into a project (SKILL.md points here for the
mechanical steps, so it doesn't have to carry them inline).

## 0. Before anything: read what the repository already knows

Run this first, in the target project, and read the output before asking the owner a single
question:

```bash
python3 <this-skill>/assets/coordination/tools/discover.py --root . --json
```

It writes nothing. It reports the candidate zones (top-level directories crossed with who
actually edits them, from git history), any existing `CODEOWNERS`, any instruction files
another agent tool has left behind, the verification commands already defined in
`package.json` / `Makefile` / CI, a guess at the documentation language with its evidence,
and whether this scaffold is already installed.

**Why this comes before the interview.** In a new project `CHARTER.md` is a statement of
intent. In a live one it is archaeological: the codebase already works some way, and the
scaffold has to describe that rather than overwrite it. Concretely — ask the owner what
directories exist and who owns them, when `git log` answers both, and you teach them that
this questionnaire is not worth reading. Then the questions that genuinely need them, the
ones in §4, get the same treatment.

So: everything `discover.py` found is presented as a **default to confirm**. Only these are
asked outright, because no amount of evidence settles them — the roles and what each owns,
whether there is an orchestrator, the project's hard guardrails, the enforcement level
(§6/§9), and whether work spans several machines.

Two findings change what you do rather than what you ask:

- **An existing `AGENTS.md`, `CLAUDE.md`, `.cursorrules` or `.github/copilot-instructions.md`
  is imported, never replaced.** Append a section; add `@AGENTS.md` to the top of an
  existing `CLAUDE.md`. Destroying a project's own agent instructions is the fastest way to
  make the scaffold unwelcome, and nobody notices until their rules stop applying.
- **An existing `CODEOWNERS` is already a zone map.** Seed `OWNERSHIP.md` from it rather
  than from an empty table, then keep the two in step with §6's generator.
- **An existing `coordination/OWNERSHIP.md` or `coordination/CHARTER.md` is read in full
  before either is touched, never assumed missing from a directory listing that happens not
  to show it.** `discover.py`'s `existing_coordination_files` reports both explicitly for
  this reason. On a mature project either file is likely to already be accurate and
  load-bearing — the "fill from discovery" instruction below is for the case where the file
  is absent or stale, not a license to regenerate one that already exists and is neither.

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
  prompts/
    REVIEW.md       (optional — periodic-review prompt, see §4 step 9 and
                     references/upstream-feedback.md; only once "is this still current"
                     is a real question for the project)
  tools/
    build_index.py
    kpi_git.py
    ownership.py     (renders .github/CODEOWNERS from OWNERSHIP.md — see §6)
    check_rules.py   (validates .claude/rules globs — see §3)
    discover.py      (read-only reconnaissance, run BEFORE the interview — see §0)
    upgrade.py       (drift report against a newer scaffold — see §10)
    kpi_config.json  (optional, from kpi_config.json.template — only if the project needs it)
    coordlib/        (shared, stdlib-only: vocabulary, table tokenizer, diagnostics,
                      ownership, install manifest)
  .scaffold-version  (written at install by `upgrade.py --adopt` — see §10)
    dashboard/       (OPTIONAL add-on, read-only — needs streamlit; see §7.
                      Not installed by default)
.claude/
  hooks/
    check-context-budget.py
    check-path-ownership.py   (optional but recommended — see §9)
    check-commit-trailers.py  (optional but recommended — see §9)
    budget.json      (from budget.json.template)
  rules/
    <topic>.md        (optional, path-scoped — see §3)
AGENTS.md             (from AGENTS.md.template, at repo root)
CLAUDE.md             (from CLAUDE.md.template, at repo root)
archive/
  README.md
```

### Why the instructions are split across two files

`AGENTS.md` holds everything that is true regardless of which agent tool is driving the
session; `CLAUDE.md` holds the Claude Code specifics and pulls the other in with a single
`@AGENTS.md` line on its first line.

That import is not decoration. **Claude Code reads `CLAUDE.md` and does not read
`AGENTS.md`** — delete the import and every vendor-neutral instruction silently stops
reaching the session, with no error anywhere. (`ln -s AGENTS.md CLAUDE.md` is the documented
alternative when you have nothing Claude-specific to add, but it needs Administrator
privileges or Developer Mode on Windows, so the import is the portable choice.)

The split is worth the second file because `AGENTS.md` is the one genuinely cross-vendor
convention in this area: since December 2025 it is governed by the Linux Foundation's
Agentic AI Foundation, alongside MCP. A project whose substance lives there can be driven by
another tool tomorrow without rewriting its coordination rules — which is the whole premise
of `docs/ru/CROSS_PLATFORM_BRIDGE.md`.

Keep the boundary clean in both directions: a `claude ...` command in `AGENTS.md` is an
instruction other agents cannot follow, and duplicating the shared rules into `CLAUDE.md`
recreates the drift the split exists to prevent.

## 2. Wiring the SessionStart hook

`check-context-budget.py` only does anything if it's actually registered. Add to
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
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/check-context-budget.py\""
          }
        ]
      }
    ]
  }
}
```

**`$CLAUDE_PROJECT_DIR` is load-bearing, not tidy quoting.** A relative command resolves
against the **tool call's** working directory, not the project root. The first time a session
runs something that begins `cd coordination/tools && …`, the hook's path no longer exists and
the hook stops running. For this one that means a missed warning. For the two *barrier* hooks
in §9 it means the barrier is not there — and the condition that removes it is a completely
ordinary `cd`, invisible in the transcript. Reported live in
[#56](https://github.com/DimaMuhannad/multi-agent-coordination-skill/issues/56), where a
project's production-write guard disappeared exactly this way; the failure there happened to
surface as an error, but nothing promises that a harness treats "hook crashed" as "stop".

Anchoring it is what makes `CHARTER.md §4`'s claim true — *a rule enforced by a hook stays
true* — for a hook whose presence would otherwise depend on the caller's current directory.

Verify it actually fires and warns correctly before trusting it — write a `roles/TEST.md` file
larger than the configured `limit_bytes`, then feed the hook synthetic stdin matching what
`SessionStart` sends:

```bash
echo '{"source":"startup"}' | python .claude/hooks/check-context-budget.py
```

You should see a `systemMessage` JSON line naming the oversized file. Delete the test file
afterward.

The same glob + `limit_bytes` mechanism isn't limited to markdown — a rule's `glob` is matched
against any path under the project root. A project whose roles capture screenshots or other
binary evidence into the coordination tree (Playwright output, annotated photos) can add a rule
like `{"glob": "coordination/**/*.{png,jpg,wav}", "limit_bytes": 512000}` to `budget.json` to get
a warning the next time one lands there, without writing a second tool. This only fires at
`SessionStart`, so treat it as a periodic hygiene signal, not a commit gate — pair it with a
pre-commit hook or CI step if the project needs binaries kept out of git entirely (object storage
or Git LFS is the usual answer for heavy media; see `CHARTER.md §4`).

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

### The three glob rules that fail silently

Every one of these makes the rule you wrote stop loading, with no error anywhere — which is
why `coordination/tools/check_rules.py` exists. Run it after editing any rule file, and in CI
with `--strict`:

```bash
python3 coordination/tools/check_rules.py --strict
```

1. **`[` starts a bracket expression.** A `[` that can't be read as one makes the pattern
   invalid: it matches nothing, while the rule's *other* patterns keep working — so a rule
   can be half-live and look fine. A literal bracket must be escaped: `photos \[2024/**`.
   Mind the quoting: a double-quoted YAML scalar processes escapes and needs `"photos
   \\[2024/**"`, a single-quoted one processes none and needs `'photos \[2024/**'`.
2. **Brace expansion has a budget.** A rule's whole `paths:` list shares 1,000 expanded
   patterns and 4 MiB, and each group multiplies: `{a,b}/{c,d}/*.{ts,tsx}` is eight. Over
   budget, the pattern is used *unexpanded* and its literal braces then match no files.
3. **`paths: []` is not the same as no `paths:` key.** An empty list matches nothing; a
   missing key loads the rule unconditionally. Opposite outcomes from a one-character edit.

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
9. **`upgrade.py --adopt` — the last step, once every file above is in place.** It records
   `coordination/.scaffold-version`: the hash of every file as installed and of the asset it
   came from, so a later `upgrade.py` can tell "you changed this" from "upstream changed
   this" without a network. Skip it and the project is cut off from every future fix.

   ```bash
   python3 coordination/tools/upgrade.py --adopt --from <this-skill>/assets
   ```

   Run it **after** the placeholders are filled, not before: the stamp records the filled
   content as the local baseline, which is what stops your own install showing up as drift
   forever.

10. `prompts/REVIEW.md` — optional, usable as-is, no placeholders to fill. Copy it in only once
   the project has been running long enough that upstream drift and local-patch reconciliation
   (`references/upstream-feedback.md`) are real questions, not before — same principle as
   `kpi_config.json` in §5: don't pre-install this speculatively.

## 5. `build_index.py` and `kpi_git.py`

Both are stdlib-only Python, run from the repo root:

```bash
python coordination/tools/build_index.py --out coordination/INDEX.md
python coordination/tools/kpi_git.py
python coordination/tools/kpi_git.py --json coordination/reports/kpi_git.json
```

Both print diagnostics to stderr when something in the journals could not be interpreted,
and list those rows under an **Unrecognised** heading inside `INDEX.md` itself. Neither
blocks: add `--strict` if you want `build_index.py` to exit 2 instead. See §8 on why the
tools refuse to guess at a translated status word.

To run the test suite (from the repo root):

```bash
python -m pytest -m "not streamlit"   # protocol suite; pytest is the only dependency
python -m pytest                       # everything, including the dashboard UI tests
```

Neither needs registering anywhere — run them manually, or wire either into a scheduled task if
your tooling supports one, once the journals are large enough that a stale index is actually
costing someone time. If you do schedule one, read the scheduling part of
`assets/coordination/LAUNCH_PROMPTS.md` first: a scheduled run that starts a *fresh* session
gets no checkout and no history, so "regenerate `INDEX.md` from the repo root" has nothing to run
against and the firing is a silent no-op. Binding the schedule to a session that already has the
checkout is the working default for anything repo-bound; a fresh session needs its bootstrap
written into the prompt, `kpi_git.py`'s `--all` walk included.

`kpi_git.py` reads `coordination/tools/kpi_config.json` if present (template:
`kpi_config.json.template`) — leave it absent until you actually hit the two problems it solves
(a bulk-import commit skewing stats, or bulk data commits inflating "lines changed"); don't
pre-populate it speculatively.

## 6. Optional: git/GitHub rails

Only do this once `references/git-github-rails.md` §"when this earns its place" actually applies
— it's an add-on, not part of the base setup in §1–5 above.

1. **CODEOWNERS.** Don't hand-copy the template — generate it, so the two files describing the
   same fact can't describe it differently (exactly the drift `references/rationale.md` warns
   about elsewhere):

   ```bash
   python3 coordination/tools/ownership.py --map ORCH=@alice --map qa=@bob -o .github/CODEOWNERS
   ```

   Roles you don't map still get a line, with the template's `@<ROLE_GITHUB_USER>` placeholder
   — a *missing* line would read as "this path has no owner", which is the opposite of true.
   For more than a couple of roles, put the mapping in a JSON file and pass `--map-file`.
   Add `python3 coordination/tools/ownership.py --map-file owners.json --check` to CI: it exits
   1 when `.github/CODEOWNERS` has drifted from `OWNERSHIP.md`.

   `assets/dot-github/CODEOWNERS.template` stays as the hand-written fallback and as
   documentation of what the output means.

2. **CI checks.** Copy `assets/dot-github/workflows/coordination-checks.yml.template` to
   `.github/workflows/coordination-checks.yml` (drop the `.template` suffix). No placeholders to
   fill — it reads `.claude/hooks/check-context-budget.py` and `coordination/roles/*.md` at their
   standard paths. Note the budget step **warns and does not fail the build**, matching the
   local hook and `README.md`; the test jobs are the ones that gate. Push it and confirm the workflow actually appears and runs (GitHub's Actions
   tab) — don't assume it's wired up correctly from the YAML alone; the real verification is
   watching it run once, the same way the local hook was verified with synthetic stdin in §2.

3. **Blocking-question check.** The workflow template ships a `blocking-questions` job that
   goes **red while any open question is marked `blocking`**. This is the notification
   mechanism, and it is worth understanding why it takes this shape.

   `PROJECT.md`'s question protocol says a `blocking` question means the role stops and makes
   no changes until it is answered. So an unanswered one is not a to-do item — it is a halted
   session, and the owner is the only person who can restart it. Until this check existed that
   state lived in a markdown table nobody had a reason to open, and looked identical to
   ordinary progress. (The `Type` column was not even parsed.)

   A red check needs no service, no webhook, and no state outside git — it satisfies
   `CONCEPT.md §6.5` exactly, and it works on any platform because it is GitHub doing the
   noticing, not an agent.

   Non-blocking questions deliberately do **not** fail the check: they have a documented
   default and the role kept working. Failing on those would train everyone to ignore the one
   signal that means "a person is required".

   Locally, the same thing:

   ```bash
   python3 coordination/tools/build_index.py --out coordination/INDEX.md --fail-on-blocking
   ```

   Open blockers are also listed in a section at the very top of `INDEX.md` — above every other
   table, because a section below three tables is a section nobody scrolls to.

   **The flag needs a `Type` column to have anything to gate on.** The questions table is
   recognised by `#`/`Question`/`Status` alone, so a journal without `Type` parses perfectly
   and every row classifies as neither blocking nor non-blocking. `--fail-on-blocking` then
   exits **2** and says so, rather than reporting zero blockers and going green forever. Exit
   1 still means what it always meant: a real blocker was found.

4. **Branch protection (needs repo admin rights).** In the GitHub UI: Settings → Branches → Add
   branch protection rule → target the default branch → enable "Require status checks to pass"
   and select the `checks` job from `coordination-checks.yml` → optionally also enable "Require
   review from Code Owners" (only meaningful once CODEOWNERS lists more than one real account —
   see the caveat in `references/git-github-rails.md`). If doing this programmatically via `gh api`
   or the REST API, the token needs admin-level access to the repo; if it doesn't, this is a
   30-second manual step, not a blocker for the rest of the setup.

## 7. Optional: the Streamlit dashboard

The only part of this scaffold with a third-party dependency, and the only part that is not
required. Everything in §1–6 is stdlib-only markdown and Python; the dashboard is an add-on in
the same sense as the git/GitHub rails, and like them it is **not installed by default** —
copy `coordination/tools/dashboard/` in when someone actually wants the screen.

```bash
pip install -r coordination/tools/dashboard/requirements.txt
streamlit run coordination/tools/dashboard/dashboard.py
```

**It reads and does not write.** There is no write mode to enable: `docs/ru/CONCEPT.md` §6.5's
invariant — the interface is a read-only projection over git — holds literally. Editing a
journal is git's job. The browser-side editor that used to live here, and the four conditions
that justified it, are recorded in §6.6 along with the measurement that retired it.

Skip the dashboard entirely if the project doesn't want a Python service; `build_index.py`
covers the same status question with no dependencies at all.

## 8. Protocol tokens stay English

The status and type keywords are parsed by tooling: `open` · `taken` · `done` · `resolved` ·
`closed` · `blocking` · `non-blocking` · `active` · `idle` · `stale` · `blocked`, plus the
table headers. They stay English even in a project written in another language. Questions,
answers, summaries and handoff prose go in the project's own language — that half is not
parsed by anything.

The tools do **not** guess at a translation. A word outside the documented vocabulary is
reported as unrecognised and counted in neither total, and the dashboard shows it as
unclassified rather than as a documented state. The alternative — accepting a Russian `открыт` as "open" — was
tried and is exactly how a journal reported "Open Questions: 0" and was believed; see
`references/rationale.md`.

## 9. Optional: enforcing OWNERSHIP.md instead of just documenting it

"Work only in your own zone" is an instruction, and Claude Code's documentation is explicit
that instruction files are context rather than configuration: *"Claude treats them as context,
not enforced configuration. To block an action regardless of what Claude decides, use a
PreToolUse hook instead."* `check-path-ownership.py` is that hook.

Copy it to `.claude/hooks/` and register it:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/check-path-ownership.py\""
          }
        ]
      }
    ]
  }
}
```

Then give each session its role: `COORDINATION_ROLE=<ID> claude`.

**Without that variable the hook does nothing at all.** That is deliberate — a coordination
aid that halts real work when it is misconfigured gets deleted within a day — but it does mean
a silent no-op is the failure mode, so verify once with synthetic input the same way §2
verifies the budget hook:

```bash
echo '{"tool_name":"Edit","cwd":"'"$PWD"'","tool_input":{"file_path":"'"$PWD"'/coordination/BOARD.md"}}' \
  | COORDINATION_ROLE=not-the-owner python .claude/hooks/check-path-ownership.py
```

You should get back a JSON object with `"permissionDecision": "deny"`. Nothing printed means
the hook is inert — usually a missing `OWNERSHIP.md`, a matrix that still has only template
rows, or `coordination/tools/coordlib/` not copied across.

**What it does not cover, stated plainly.** It inspects file-writing tools only. A `Bash`
command that writes is *not* caught: deciding whether `make build` lands in someone else's
zone means predicting a shell, and a check that is right most of the time invites exactly the
misplaced confidence the hook exists to remove. For paths that must never be touched at all,
use `permissions.deny`. And it governs the sessions that run it — a teammate on another
machine without the hook installed is unaffected, which is why the generated `CODEOWNERS` plus
branch protection (§6) is the rail that catches that case.

### The commit-trailer hook, same opt-in shape

`CHARTER.md §4` requires the trailer block to be the last paragraph with no blank line inside
it, because that is what `git interpret-trailers` requires. Sessions do not reliably comply
with it from reading alone — 10 of 29 commits in one week in the source project, and 1 of 7 in
a later controlled run where every session had just read the rule. Wire this one the same way,
on `PostToolUse`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/check-commit-trailers.py\"",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

Verify it the same way, against a commit you make on purpose with a blank line before a
signature:

```bash
echo '{"tool_name":"Bash","cwd":"'"$PWD"'","tool_input":{"command":"git commit"}}' \
  | python .claude/hooks/check-commit-trailers.py
```

A well-formed commit prints nothing; a broken one gives back `"decision": "block"` with the
reason, which the session sees and fixes with `git commit --amend`. The commit is not undone —
`PostToolUse` runs after the fact, so this is feedback, not a barrier.

Note that this hook *does* key on `Bash`, which the ownership hook above refuses to do. The
difference is prediction: the ownership hook would have to guess, beforehand, where a shell
command writes. This one guesses nothing — it runs afterwards and asks git what git parsed on
a commit that already exists. Being wrong costs a line of output rather than a blocked write.

If your project renamed the trailer keys in its own `CHARTER.md`, say so rather than living
with a report on every commit: `COORDINATION_TRAILER_KEYS=Ticket,Why`. Renaming points the
check elsewhere; it does not switch it off.

## 10. Receiving upstream fixes

`references/upstream-feedback.md` covers sending findings up. This is the other direction,
which the scaffold had no answer for at all: the files were copied in and the link was cut,
so a fix made upstream reached no project already running it.

```bash
python3 coordination/tools/upgrade.py --from <newer-skill-checkout>/assets
```

It works offline — `.scaffold-version` records the pristine hashes, and the newer skill is
already a directory on disk, since that is how skills are used. It compares three states and
sorts every file into one bucket:

| Bucket | What it means |
|---|---|
| `both` | upstream changed it **and** so did you — **the only rows needing a decision** |
| `upstream-only-but-customized` | untouched *since* the baseline, but it was already your own content when the baseline was frozen — never the shipped seed. Review by hand; copying upstream across discards the customisation |
| `upstream-only` | your copy is untouched; copy the new one across |
| `new-upstream` | did not exist when you installed |
| `upstream-deleted` | upstream removed it; your copy is all that is left. Keep, archive or delete deliberately — and check what still imports it before taking anything else |
| `deleted-locally` | reinstall, or confirm the removal was deliberate |
| `seed-changed` | a template you filled in has moved upstream; compare and port what applies |
| `local-only` | yours alone. Listed so you can see your customisations, never a problem |
| `already-current` | you took this one already and it matches upstream byte for byte. Never a problem |

Exit 0 when nothing needs a person, 1 when a row needs one — usable as a CI gate. One rule,
the same in every project: **red means a `both` row.** Adding `--strict` also fails on
`upstream-only-but-customized`.

**Taking a file is how you finish a row, and the next report will say so.** This tool reports
and does not merge, so applying an update means copying the files across by hand; on the next
run those rows read `already-current` and stop affecting the exit code. Two buckets are worth
reading even though neither gates: `already-current` is how you confirm an update actually
landed, and `upstream-deleted` is the one that can break a tree — a file upstream retired is
often the module other files you are about to take were written against.

That second category carries the same risk as a `both` row — a hand-written file that
upstream has also moved — so a project that wants its build to stop on those should pass
`--strict`, in the CI step, where the next person to read the workflow can see it. The report
says which way it went whenever a customised row is present, so a red build can explain
itself. `--strict` cannot hide a `both` row; nothing can.

The flag briefly worked differently here than on the scaffold's other tools: it was
three-state, and its default was read out of the stamp's `format` version, so the same drift
could exit 0 in one project and 1 in another. That bought backward compatibility for
baselines written before the category existed, at the price of an exit code decided by a JSON
field nobody reads. Passing `--strict` in the CI file is backward compatible for every
project and visible to anyone.

**It reports; it does not merge.** A three-way auto-merge of markdown that people have
edited cannot be done without lying about the result, and a wrong merge of `CHARTER.md` is
worse than having no upgrade channel. What a human needs is the short list of places a
decision is actually required.

Two things it deliberately never reports as drift, because getting these wrong makes the
whole report noise and noise gets ignored:

- **The journals.** `ACTIVITY.md` grows every day by design; so do `HANDOFFS.md`,
  `QUESTIONS.md` and `BOARD.md`, and `OWNERSHIP.md` changes whenever a zone does.
- **Line endings.** A checkout with `core.autocrlf=true` changes every byte of every file
  and none of its content, so hashing normalises CRLF to LF first.

### Adopting a project that predates the stamp

```bash
python3 coordination/tools/upgrade.py --adopt --from <newer-skill-checkout>/assets
```

Be clear-eyed about the trade: adoption records **today's** files as the baseline, so *what*
any edit made before now changed is gone and no tool can recover it. That much is unavoidable
offline. *That* an edit happened is kept, though, because the stamp records both hashes — the
content adopted and the source it was compared against — so a file that already differed is
marked `upstream-only-but-customized` rather than `upstream-only` on every later report. Read
the already-diverged list the command prints to stderr anyway: it names those files while you
still have the context to say why each one differs.

## 11. Keeping the generated and the written in step

Three checks worth putting in CI once the scaffold is installed, all read-only, all exiting
non-zero only on a real disagreement:

```bash
python3 coordination/tools/ownership.py --map-file owners.json --check   # CODEOWNERS vs OWNERSHIP.md
python3 coordination/tools/check_rules.py --strict                       # .claude/rules globs
python3 coordination/tools/upgrade.py --from <skill>/assets              # upstream drift
```

The first two catch a file and its source of truth drifting apart. The third catches the
project drifting from upstream. None of them writes anything.

If you *want* an `upstream-only-but-customized` row to fail the build too — a file that was
already the project's own when the baseline was frozen, and that upstream has since moved —
add `--strict` to the third line. See §10.
