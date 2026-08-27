# ORCH_BRIEF — durable goals, for the orchestrator only

> Not cold-start reading for role sessions — this is the orchestrator's own reference, kept
> separate from `coordination/roles/ORCH.md` (the orchestrator's own cold-start file, held to the
> same size budget as every other role's).

## Why this file is split the way it is

Keep **durable, standing content** here — the project's actual goals, the things that stay true
across weeks — and keep **dated, point-in-time state** (what's happening this week, current
blockers, a status snapshot) out of it. When this file accumulates enough dated snapshot content
that it stops being a quick read, don't let it keep growing — move the old snapshot verbatim to
`archive/<snapshot-name>-<year-month>/`, with a short `README.md` in that directory explaining
what it is and where the durable version of anything in it now lives (this file, a role's file,
or wherever). This file rewritten from scratch afterward should contain **only** what's still
true, not a changelog of how it got there.

This split is worth doing from the start, not retrofitting later — a file that mixes "what we're
trying to achieve" with "what happened this week" grows without bound and nobody notices when
the two kinds of content start pulling in different directions.

## Goal hierarchy

Fill this in with the project's actual standing goals, ordered by how foundational they are (a
later goal typically depends on an earlier one being basically settled). Revisit and re-verify
this section periodically — "still current as of `<date>`" is worth writing explicitly so a
future reader knows this wasn't just inherited unchanged from months ago.

1. *(e.g.)* Core capability / model / mechanism the project is built on.
2. *(e.g.)* The user-facing application or output built on top of it.
3. *(e.g.)* Novelty and validation — what's actually new here, and how it's checked.
4. *(e.g.)* The externally-facing deliverable (a paper, a release, a report).
