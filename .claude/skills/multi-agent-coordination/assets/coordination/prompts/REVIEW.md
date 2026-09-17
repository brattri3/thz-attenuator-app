# Periodic Review

Run this prompt on an infrequent, deliberate schedule — not automated, not on every session.
It exists to catch the kind of staleness nobody's job is otherwise to notice: a scaffold that was
installed once and never checked against what changed since. Optional; only worth having once the
project has been running long enough that "is this still current" is a real question. See
the closing section of the skill's `references/rationale.md`, on why undocumented rules decay — this prompt is the
mechanical check that keeps the five items below from silently rotting the same way.

Whoever runs this (`ORCH`, or the owner) works through all five items in one sitting and records
the result — **every** item, including "checked, no changes" — as one dated entry in
`ACTIVITY.md`. A missing entry for an item is indistinguishable from "never reviewed"; write it
down even when nothing changed, or the next review can't tell the difference between "still true"
and "nobody looked."

This prompt only produces a written record and, where relevant, entries in `QUESTIONS.md` for the
owner to decide on. It does not itself update anything — a review that quietly applies its own
findings removes the human decision point this scaffold otherwise insists on everywhere else
(see the skill's `references/rationale.md`).

## 1. Upstream scaffold comparison and local patch reconciliation

Search the project for `LOCAL PATCH` markers. That is a marker put next to a patch working
around a defect in the scaffold itself, so the divergence is visible in the code rather than
only in someone's memory, and it looks like this (the language's own comment syntax for a
non-Markdown file):

```
<!-- LOCAL PATCH 2026-08-29: works around <short bug description>; reported upstream as
     <repo>#<issue-number>; remove this patch once that lands -->
```

For each one found: is the linked upstream issue/PR merged yet? If so, remove the patch
and its marker now — a merged fix left in place is exactly the kind of drift
the skill's `references/rationale.md` warns about. If not, does the marker still accurately describe what
it's working around? If the project's copy of this scaffold predates a since-added scaffold
feature that would replace something built locally, note it as a candidate to adopt.

## 2. New agent-system capabilities

Check the skill's `references/agent-tooling.md` against what the agentic system actually running roles'
sessions currently supports. Has a capability been added or changed since the file was last
touched? Has a role been reaching for something not covered there that's become common enough to
document? Update the file directly if the answer is a small factual correction; log a
`QUESTIONS.md` entry if it's a real behavior change worth the owner weighing in on first.

## 3. Multi-agent development practices and thematic resources

Freeform: has anything worth knowing changed in how multi-role/multi-session agentic development
is generally done — practices, write-ups, tools other projects in this space have converged on?
Not a mandate to chase every trend; a "checked, nothing worth adopting" verdict is a legitimate
and expected outcome most cycles.

## 4. Relevant GitHub tooling — strict selection only

Don't add a GitHub-side tool or integration on the strength of "it might help." Apply the same bar
the skill's `references/git-github-rails.md` already sets for that whole optional layer: only worth adopting
once it solves a problem this project has *actually hit*, not a hypothetical one, and only if it
doesn't reintroduce something that file explicitly warns against (e.g. moving `QUESTIONS.md` /
`HANDOFFS.md` onto GitHub Issues). Most cycles, the right verdict here is also "checked, nothing
adopted."

## 5. Feedback suitable for upstream contribution

Cross-check against item 1: any `LOCAL PATCH` marker whose issue field is still empty is a fix
that exists but hasn't been reported. Report each one rather than leaving it as a standing local
divergence indefinitely. The short version, so this step does not depend on a file that lives in
the skill rather than in this project:

- **Is it really a scaffold bug?** Only if it would reproduce in a different project built from
  the same scaffold. A zone boundary that is wrong for *this* project's layout is local
  configuration, not a defect.
- **Write it the way that gets fixes merged**: a summary, why it is worth fixing rather than
  tolerating, a minimal runnable reproduction, `Expected` vs `Actual`, a suggested fix, and the
  environment. The reproduction is what lets a maintainer confirm it without rebuilding your
  project.
- **Expect it to cost three steps, not one**, if the project and the skill sit under different
  accounts — a session normally cannot file against a repository it cannot attach. Draft here,
  hand the text to a session started *on* the skill's repository, and be present for one
  approval.

The skill's `references/upstream-feedback.md` has the full version, including how to mark the
patch while it is still local and when to remove it.
