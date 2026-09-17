# Upstream feedback — returning scaffold-level findings, not just fixing them locally

A project using this scaffold will eventually hit a real defect in the scaffold itself — not a
project-specific customization gone wrong, but a bug in a template, hook, or tool this skill
ships. Left alone, the natural path is a quiet local patch: fast, unblocks the project, and
easy to forget about. Two things go wrong from there. Either the patch gets silently lost the
next time someone re-copies the scaffold's templates into the project, or it never leaves the
project at all, so every other project built from this scaffold keeps re-discovering and
re-fixing the same bug independently. This file is the pathway that avoids both.

## 0. The other direction

This file is about sending findings **up**. Receiving fixes back **down** used to have no
mechanism at all — files were copied into a project and the link was cut, so a fix merged
upstream reached no project already running the scaffold, including the one that reported it.

`coordination/tools/upgrade.py` is that channel now (`references/setup.md §10`). It matters
here for a specific reason: §2 below tells you to mark a local patch so it can be
reconciled later, and §5 tells you to remove it once upstream has the fix. `upgrade.py` is
how you find out that upstream *has* it — a `both` row on the file you patched is exactly
the signal that §5 is now due.

## 1. Is this actually a scaffold bug?

Only worth reporting upstream if it would reproduce in a different project built from the same
scaffold — not something specific to this project's own zone content, role names, or domain data.
A parser that mishandles a status word regardless of project, a hook that measures file size
wrong on a given OS, a template whose placeholder the instantiation steps don't actually fill in
— these are scaffold bugs. A role's zone boundary being wrong for *this* project's directory
layout is not; that's a local configuration fact, not a defect in the scaffold.

## 2. Mark the local patch while it's still local

Until a fix is accepted upstream, the project is carrying a real, live divergence from the
scaffold — make that visible in the code itself, not just in memory or a chat transcript. Put a
one-line marker next to the patch:

```
<!-- LOCAL PATCH 2026-08-29: works around <short bug description>; reported upstream as
     <repo>#<issue-number>; remove this patch once that lands -->
```

(or the language's own comment syntax for non-Markdown files). The marker needs a date, what
it's working around, and where the upstream report lives — without the issue reference, a future
reviewer can't tell whether the patch is still needed or already superseded. This is what
`coordination/prompts/REVIEW.md`'s upstream-comparison pass (see `references/setup.md`'s
templates) greps for when reconciling local patches against upstream.

## 3. Write the report the way that has actually gotten fixes merged

This scaffold's own upstream already has one worked example of the shape that works: a bug
report with a `Summary`, a short paragraph on *why it's worth fixing rather than tolerating*
(not just that it's technically wrong), a minimal, runnable reproduction, explicit `Expected` vs.
`Actual`, a concrete suggested fix, and the environment it was observed in. That's not a
convention invented for this file — it's the format that got a real fix reviewed and merged
promptly upstream. Reuse it rather than improvising a shorter report; the reproduction step in
particular is what lets the maintainer confirm the bug without first reconstructing your project.

## 4. Test both sides before calling the fix done

A fix for a false positive that's confirmed only by no longer seeing the false positive isn't
fully tested — confirm the *true* case still fires too. For a check that's supposed to catch real
problems (a budget hook, a validator, a parser), verify both that the case which shouldn't fire
now stays silent, and that a case which should still fire still does. A fix that only silences
the check has just moved the failure mode from "too noisy" to "misses real problems," which is
worse.

## 5. Remove the local patch once upstream has it

Once the upstream fix is merged, delete the local patch and its marker entirely rather than
leaving it in "just in case" — a merged upstream fix arriving via the scaffold's own update path
makes the local one redundant, and a dead patch left in place is exactly the kind of drift
`references/rationale.md` warns about: two things describing the same fact, only one of which is
still true. If the local patch predates the marker convention above, add the marker first so its
removal is a deliberate, greppable step rather than something that has to be remembered.

## 6. When the project and the skill live under different accounts

§3 reads as though the session that found the defect can file the report. Often it cannot, and
the reason is structural rather than a permission someone can grant — worth knowing before you
plan the work, because it is the most likely arrangement: the project belongs to whoever adopted
the scaffold, the skill belongs to whoever wrote it.

Reading and writing come from different places on a hosted harness. A public repository is
readable with no attachment at all — the session's git proxy serves an anonymous clone or fetch,
which is enough to survey the code, the issues and the PRs. Writing anything goes through the
platform API instead, and that needs the repository genuinely attached to the session. Attaching
it is what fails:

```
add_repo: cross-tier adds are not supported in v1: requested
"<owner-b>/<skill-repo>" but session already has repos from owner(s) [<owner-a>]. Start a
new session with the requested repo as the initial source, or add a repo from the same
owner as the existing sources
```

So a session working on a project under one account can read the skill's repository in full and
still be unable to file a single Issue against it. The channel is not broken; it costs three
steps that "just open an Issue" does not suggest:

1. **Draft the report where the evidence is** — in the session that hit the defect. It is the
   only one that can quote the actual error, the actual numbers, and the actual sequence, and §3
   is mostly a demand for exactly those.
2. **Launch a relay session whose *initial source* is the skill's repository.** Initial, not
   added afterwards: attaching later is precisely what does not work, so this cannot be
   retrofitted onto the session already running. Hand it the finished text in its opening
   prompt, because that prompt is the only input it will ever get (`CHARTER.md §8`).
3. **Be present for one approval.** Filing an Issue is an outward-facing action, so the relay
   session parks until a human opens it once — see the launched-session rules in
   `assets/coordination/LAUNCH_PROMPTS.md`. One approval releases the whole batch.

None of that is a reason to skip reporting; it is a reason to **batch**. The cost is per relay
session, not per finding, so collect several findings, then spend one relay session and one
approval on all of them together.
