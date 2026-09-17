# QUESTIONS — decision queue and recorded owner decisions

Protocol: `PROJECT.md`, "Question protocol". **Append-only**: new rows get added, existing rows
aren't rewritten (except closing the status once the owner/orchestrator has answered).

**Why this file matters more than it looks like it should.** A question that only lives in a
chat transcript is invisible to every other role and to the same role after `/clear`. This file
is the one place a role can find out what the owner already decided without having access to
someone else's conversation. Write both the question **and** the answer here — a queue of
unanswered questions is only half useful; the point is a durable decision record.

**Status vocabulary:** `open` · `resolved` · `closed`. **Type:** `blocking` · `non-blocking`.

`blocking` is not a severity label — it is a claim that a session has **stopped**. Mark it only
when that is true, and expect it to be visible: open blockers head `INDEX.md`, and the optional
`blocking-questions` CI check is red until they are answered (the skill's `references/setup.md §6`). Marking
a question blocking when a default existed is how that signal stops being believed.
Both are protocol tokens parsed by tooling and stay English even in a project written in another
language; the question and answer text is prose and does not (the skill's `references/rationale.md`). A word
outside these lists is reported as unrecognised and counted in neither total — the tools will not
guess at a translation.

Use one table per batch of related questions (e.g. all questions from one review session), with
a consistent schema — pick **one** column layout and stick to it project-wide, since
`coordination/tools/build_index.py` expects a `Status` column by name. If a table genuinely
doesn't fit that shape (e.g. it tracks execution progress rather than a yes/no decision), that's
a sign it belongs in `ACTIVITY.md` instead, not a reason to invent a new QUESTIONS.md schema.

---

## Example batch — replace with your project's first real batch

The example rows are numbered `EX-*` on purpose, so that your first real question can be `Q-1`
whether or not you delete this section first. Two rows sharing an id is not cosmetic: `INDEX.md`
exists so a reader can jump to an item by number, and an id resolving to two different rows
defeats that for the one number a new project reaches for soonest.

| # | Question | Owner's answer | Type | Status |
|---|---|---|---|---|
| EX-1 | *(example)* Should X or Y? | *(owner's actual answer, verbatim)* | blocking | resolved |
| EX-2 | *(example)* Non-blocking question with a default | Took default `<D>` because `<reason>` | non-blocking | resolved |

### Follow-ups a resolved question implies

If closing a question implies action other roles need to take (a rename, a changed default), say
so explicitly right below the table — don't make readers infer consequences from the raw answer.
