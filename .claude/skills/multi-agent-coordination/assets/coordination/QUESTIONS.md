# QUESTIONS — decision queue and recorded owner decisions

Protocol: `PROJECT.md`, "Question protocol". **Append-only**: new rows get added, existing rows
aren't rewritten (except closing the status once the owner/orchestrator has answered).

**Why this file matters more than it looks like it should.** A question that only lives in a
chat transcript is invisible to every other role and to the same role after `/clear`. This file
is the one place a role can find out what the owner already decided without having access to
someone else's conversation. Write both the question **and** the answer here — a queue of
unanswered questions is only half useful; the point is a durable decision record.

Use one table per batch of related questions (e.g. all questions from one review session), with
a consistent schema — pick **one** column layout and stick to it project-wide, since
`coordination/tools/build_index.py` expects a `Status` column by name. If a table genuinely
doesn't fit that shape (e.g. it tracks execution progress rather than a yes/no decision), that's
a sign it belongs in `ACTIVITY.md` instead, not a reason to invent a new QUESTIONS.md schema.

---

## Example batch — replace with your project's first real batch

| # | Question | Owner's answer | Type | Status |
|---|---|---|---|---|
| Q-1 | *(example)* Should X or Y? | *(owner's actual answer, verbatim)* | blocking | resolved |
| Q-2 | *(example)* Non-blocking question with a default | Took default `<D>` because `<reason>` | non-blocking | resolved |

### Follow-ups a resolved question implies

If closing a question implies action other roles need to take (a rename, a changed default), say
so explicitly right below the table — don't make readers infer consequences from the raw answer.
