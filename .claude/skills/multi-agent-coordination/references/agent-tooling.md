# Agent tooling — which platform capabilities a role is expected to use, and when

The rest of this scaffold describes coordination **through files**: zones, journals, handoffs,
cold-start budgets. It says nothing about which capabilities of the agentic system itself (Claude
Code, or whatever runs a role's session) a role is expected to reach for, and when. Left
unstated, that stays a personal habit of whichever session happens to have picked it up — one
role plans before editing, another doesn't, and the difference only shows up in the quality of
the result, not in anything the scaffold enforces.

This is the same shape of problem `references/rationale.md` describes for `HANDOFFS.md`'s status
line: "a rule that lives only in a human-readable document decays under real multi-session use,
because nobody's job is to notice the decay." The fix there was an exact string a parser could
check. There's no equivalent mechanical check for most of what follows — so treat this file as
the next-best thing: a short, concrete list of situations and the capability that situation
calls for, stated plainly enough that a role reading it at cold start knows what's expected
without having to infer it from experience.

**Not prescribed here:** which specific platform or mode name to use. The situations below are
real regardless of which agentic system is running a role's session; name your own system's
equivalent where one exists, and say so in `roles/<ID>.md` or `CLAUDE.md` if it's worth being
explicit about.

## 1. Plan before multi-file edits

A task that touches more than one file, or whose shape isn't obvious from the request alone,
starts with a plan — not with the first edit. This catches wrong assumptions about scope while
they're still cheap to correct, instead of after three files are already half-changed. A
single-file, mechanically obvious change doesn't need this ceremony; use judgment rather than
planning by rote.

## 2. Structured questions, logged to `QUESTIONS.md`

`QUESTIONS.md` already exists in this scaffold as the append-only record of things a role needed
the owner to decide. What it doesn't currently say is *how* to ask: a question logged there
should present the real options, not just describe a fork in the road, and should carry the
asking role's own recommendation rather than leaving the owner to reconstruct the trade-offs from
scratch. "What should I do about X?" costs the owner more attention than "X can go A or B; I'd
pick A because \<reason\>, unless \<condition\>." The owner can still say no — the point is giving
them a decision to react to, not a blank page.

## 3. Subagent tasks: self-contained, and scoped to your own zone

When a role's own agentic system supports spawning subagents for parallel or delegated work
(Claude Code's `Agent` tool, or an equivalent), two things matter here specifically, beyond the
general practice of writing a subagent a complete brief because it starts with none of the
parent's context:

- A subagent task should stay inside the launching role's own zone as defined in
  `OWNERSHIP.md`/`PROJECT.md`. A subagent has no notion of this scaffold's zone boundaries unless
  the prompt states them — it will happily edit outside the zone if asked to, which reintroduces
  exactly the cross-zone stepping-on-files problem the rest of this scaffold exists to prevent.
- Findings or state a subagent produces that matter beyond the single task (a discovered defect,
  a decision that affects other roles) still belong in `HANDOFFS.md`/`QUESTIONS.md` afterward —
  spawning a subagent doesn't create a second channel for that; the launching role stays
  responsible for getting it into the shared record.

## 4. Heterogeneous verification

Confirm a change through more than one independent method before calling it done, especially for
anything with a visible or interactive surface: a numeric/automated check alone is not enough
evidence that the feature itself works, only that the specific thing it measures does. This
scaffold's own dashboard is the concrete example: a review that ran only the parser's numeric
output against expected values would have missed all four of the interface defects a role
actually reading the rendered screens found (see the dashboard issue this scaffold tracks
upstream). Numeric plus visual, interface plus CLI, or automated tests plus a manual pass through
the golden path — pick a second method that would fail differently than the first, not one that
would fail alongside it for the same reason.

## 5. Isolation for irreversible or parallel work

Work that can't be undone with a single command, or that will run alongside another role's work
on overlapping ground, belongs in an isolated checkout rather than the shared one. This scaffold
doesn't need a new mechanism for that — `git worktree add` covers it directly, and Claude Code
adds session isolation on top (`--worktree`); see `CHARTER.md §5` for when a role's work warrants
its own checkout, and `references/git-github-rails.md`'s note on worktrees. The rule worth stating
here is just *when* to reach for it: before the irreversible step, not after it turns out to have
been a mistake.
