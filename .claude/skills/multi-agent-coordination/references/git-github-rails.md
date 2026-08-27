# Git/GitHub rails — optional server-side layer on top of the base scaffold

The base scaffold (`CHARTER.md`, `OWNERSHIP.md`, the local `SessionStart` hook) enforces its rules
client-side: a role follows a written convention, or a hook that happens to be wired into that
particular session's `.claude/settings.json` catches a mistake. That's enough for a project small
enough that everyone touching it shares the same setup. It stops being enough once you have
genuinely separate contributors, or a session/environment that skipped the hook, or a shared file
that keeps colliding despite the convention. This file covers what GitHub itself can enforce
instead — and, as importantly, what it's worth *not* reaching for.

## What's actually native to Claude Code, vs. what's a GitHub feature you add

Worth being precise about this, because it's easy to assume a platform feature exists just because
it would be convenient. Checked against Anthropic's own current documentation rather than assumed:

**Documented, native to Claude Code on the web:**
- A cloud session can push a branch and, on request, open a pull request ("select **Create PR** at
  the top of the diff view").
- **Auto-fix pull requests** — Claude *monitors* an existing PR (CI failures, review comments) and
  responds; it does not create the PR itself. Requires the Claude GitHub App and explicit
  enablement per PR.
- Worktree-based parallel session isolation (`--worktree`), with its own `worktree-<name>` branch
  naming.

**NOT documented as native platform behavior** (observed in practice, but not in the docs, so
don't design a paradigm assuming it's guaranteed or will keep behaving the same way):
- Per-cloud-session "designated branches" (patterns like `claude/<slug>`) and a UI PR-status chip
  tracking one.
- Automatic PR creation without an explicit request.
- Any environment-level configuration switch for "always push straight to a shared branch" vs.
  "always use a per-session branch + PR."

**Conclusion:** there is no single officially-recommended coordination policy. The platform gives
you branch push, on-request PR creation, and PR monitoring as building blocks; how a multi-role
project stitches them together is entirely a project-level decision. Neither "everyone shares one
checkout and pushes to `main` with owner sign-off" (this scaffold's default) nor "every session
gets its own branch and PR" is more "correct" — they fit different shapes of work. The default here
fits a small number of *trusted, continuing* roles; the per-branch-PR model fits contributors who
are more like one-off task-doers than zone-holders. Worktrees exist as the platform's own
isolation primitive if you want separation without going all the way to PR-per-change.

## What's in this optional layer, and why each piece

### `CODEOWNERS`

Machine-readable mirror of `OWNERSHIP.md`'s "exclusive zones" table. Once it exists, GitHub
auto-requests the right reviewer on a PR touching a given path, and (only if you also turn on
"Require review from Code Owners" in branch protection) can block a merge until that happens.

**The honest limit worth stating plainly, not glossing over:** this is a real *gate* only when the
accounts listed are actually different people/bots with real write access to the repo. In a
single-maintainer repo, a CODEOWNERS file mapping every zone to the same one account is still
useful — it's a precise, versioned statement of "who's responsible for this path," readable by
anyone browsing the repo — but it is not a review gate, because the one account can always approve
its own PR. Don't present it as enforcement it isn't providing.

### Server-side coordination checks (CI)

`assets/dot-github/workflows/coordination-checks.yml.template` re-runs the same two checks the
local hooks already do — commit trailer format, cold-start budget — but on GitHub's own runner,
independent of whether the pushing session had the local hook installed. It deliberately reuses
`check-context-budget.sh` verbatim rather than reimplementing the budget check in a different
language — one rule, one implementation, checked in two places.

**When this earns its place:** once you've actually had a commit land with broken trailers or an
oversized role file because a session (a different environment, someone's local checkout, a
one-off contributor) didn't have the hook wired in. Before that's happened even once, it's a
speculative addition — the base scaffold already tells you this in `SKILL.md` §3 for the templates
themselves, and the same logic applies here.

### Selective PR-for-hotspots

Not a blanket policy change. `OWNERSHIP.md`'s "conflict hot spots" section already names the
specific shared files most likely to collide — that's exactly the list of files worth routing
through an actual PR (real diff view, inline comments) instead of a `HANDOFFS.md` text entry,
while everything else keeps working in the shared checkout as before. Adopting PRs everywhere
would just recreate the "one branch per task" model this scaffold explicitly isn't — do it only
where a real, repeated conflict justifies the overhead.

## What NOT to move onto GitHub, and why

**Don't replace `QUESTIONS.md`/`HANDOFFS.md` with GitHub Issues or Projects**, even though Issues
give you labels, assignment, and a native closed state for free. The scaffold's core property —
one source of truth, readable identically from any environment via plain `git log`/`grep`, no
network call, no API token — is worth more than the convenience. A subagent with no network access
can read `HANDOFFS.md`; it cannot read an Issue. If you're tempted because `build_index.py` feels
fragile, that's a signal to reinforce the exact-string format `HANDOFFS.md` already mandates, not
a signal to leave git.

## A reusable pattern: three-tier fallback for GitHub actions from a session

Any Claude Code session automating something against GitHub beyond plain `git push` (opening a PR,
merging, configuring branch protection) is stateless about what's actually available in its
container — `gh` might or might not be installed, and the proxied git credential might or might not
double as a usable API token. Don't assume; degrade explicitly:

1. Try `gh <command>` if the binary exists.
2. Fall back to a raw GitHub REST API call (`curl`) if a usable token can be found (check
   `git config --get credential.https://github.com.helper` and the environment for one).
3. If neither works, stop at the last fully-automatable step (a pushed branch, a ready compare
   URL) and hand the one remaining click to a human — and say so plainly in the result, rather than
   implying the automation completed when it didn't.

## Setting this up

Mechanical steps (what to copy where, how to enable branch protection by hand if the programmatic
attempt doesn't have enough scope) are in `references/setup.md` §6.
