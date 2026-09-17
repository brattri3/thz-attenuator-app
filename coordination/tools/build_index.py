#!/usr/bin/env python3
"""Build coordination/INDEX.md — an open/closed summary of QUESTIONS.md and HANDOFFS.md.

Why this exists: once QUESTIONS.md and HANDOFFS.md grow past a few hundred lines, nobody should
read them in full just to answer "what's still open?" — that's what grep is for, except grep
doesn't give you the shape of the backlog either. This script builds a short index: number/date/
status/line-to-jump-to, open items first. It is NOT a replacement for the journals — the actual
question text and decision text stay there; this is a filter on top.

This version assumes the CANONICAL format the bundled templates define — no drift tolerance:
  - QUESTIONS.md: one or more markdown tables, each with a `Status` column.
  - HANDOFFS.md: entries start with `## [ISO-date] ...` and end with a line reading exactly
    `- **Status:** open|taken|done` (see the HANDOFFS.md template for why this is mandatory).

If your project's journals drift from this format over time (they will, eventually — see
the skill's references/rationale.md for the THz project's experience with 8 different status-phrasing
variants), extend the regexes below rather than special-casing every historical entry; keep this
script simple and let format drift be a signal that the templates need reinforcing, not a reason
to make the parser permissive.

Usage (from repo root):
    python coordination/tools/build_index.py --out coordination/INDEX.md
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordlib import diagnostics as diag  # noqa: E402
from coordlib import md_table, schema  # noqa: E402
from coordlib.md_table import split_table_row  # noqa: E402

#: Two directories up from this script, in both layouts there are: <project>/coordination
#: in an installed project, and <skill>/assets/coordination in the repository the scaffold is
#: authored in. A branch here used to special-case the second one by appending "assets" to a
#: root that already ended in it, so it could only ever have produced
#: <skill>/assets/assets/coordination -- unreachable, because the condition guarding it was
#: never true. Anything that is neither layout says so with --coordination-dir.
COORD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "coordination",
)

STATUS_RE = re.compile(r"\*\*Status:?\*\*:?\s*`?([^`\n().]*)", re.IGNORECASE)
HEADER_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*(.*)$")

#: Hoisted out of the f-strings below: an f-string expression part may not contain a
#: backslash before Python 3.12, and the project's floor is 3.9.
EM_DASH = "\u2014"
ELLIPSIS = "\u2026"
WARNING_SIGN = "\u26a0"


def parse_questions(path, diagnostics=None):
    """Read every canonical questions table in the file.

    A table qualifies by header signature (#, Question, Status), not by position, so an
    unrelated table -- measurements attached to a decision, say -- is reported rather than
    silently read as questions.
    """
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        lines = fh.readlines()

    rows = []
    # Ids are what `INDEX.md` exists to let a reader jump by, so one id meaning two rows
    # defeats the file's purpose. It happens for two ordinary reasons in a project like this:
    # a template's example rows left in place while the first real question takes the same
    # number, and two roles appending a batch in parallel without seeing each other's. The
    # dashboard's parser has always reported this; the dependency-free tool everyone actually
    # installs did not, which made the check an accident of which layer you had.
    seen_ids = {}
    for block in md_table.iter_table_blocks(lines):
        resolved = schema.resolve_headers(block.headers)
        if not schema.matches_signature(resolved, schema.QUESTIONS_TABLE_SIGNATURE):
            diag.record(
                diagnostics, diag.UNKNOWN_TABLE_SCHEMA, path, block.header_index + 1,
                f"not a questions table; skipped {len(block.row_indices)} row(s)",
                " | ".join(block.headers),
            )
            continue
        if "type" not in resolved:
            # Not a schema failure: {id, question, status} is the whole signature, so a table
            # without Type is read normally. It does mean `blocking` cannot be computed for
            # any row here, and --fail-on-blocking is the one gate this scaffold ships for a
            # session that has stopped. Silence would make that gate permanently green.
            diag.record(
                diagnostics, diag.MISSING_TYPE_COLUMN, path, block.header_index + 1,
                "no Type column; blocking/non-blocking cannot be determined for this table",
                " | ".join(block.headers),
            )

        for row_index in block.row_indices:
            cells = split_table_row(lines[row_index].strip())

            def cell(key):
                index = resolved.get(key)
                return cells[index] if index is not None and index < len(cells) else ""

            rid = schema.strip_decoration(cell("id"))
            if schema.is_placeholder_text(rid):
                continue
            if rid in seen_ids:
                diag.record(
                    diagnostics, diag.DUPLICATE_ID, path, row_index + 1,
                    f"id already used on line {seen_ids[rid]}", rid,
                )
            else:
                seen_ids[rid] = row_index + 1
            # Unescaped for the same reason dashboard/parser.py has always unescaped it: the
            # value a human wrote is `grep -E "a|b"`, and the backslash exists only so the row
            # survives the table. Reading it back verbatim made the two shipped readers return
            # different strings for one cell.
            question = md_table.unescape_pipe(cell("question")).replace("**", "")
            if len(question) > 110:
                question = question[:107] + ELLIPSIS
            raw_status = schema.strip_decoration(cell("status"))
            state = schema.classify_item_status(raw_status)
            if state is None:
                diag.record(
                    diagnostics, diag.UNKNOWN_STATUS, path, row_index + 1,
                    "status is outside the documented vocabulary "
                    f"({'|'.join(schema.QUESTION_STATUSES)})",
                    raw_status,
                )
            raw_type = schema.strip_decoration(cell("type"))
            kind = schema.classify_question_type(raw_type)
            if raw_type and kind is None:
                diag.record(
                    diagnostics, diag.UNKNOWN_TYPE, path, row_index + 1,
                    "type is outside the documented vocabulary (blocking|non-blocking)",
                    raw_type,
                )
            rows.append({
                "id": rid,
                "line": row_index + 1,
                "text": question,
                "status": raw_status,
                "state": state,
                "who": cell("role"),
                "type": kind,
                "raw_type": raw_type,
            })
    return rows


def parse_handoffs(path, diagnostics=None):
    """Read handoff entries, skipping the fenced format example the template documents."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        lines = fh.readlines()

    entries = []
    cur = None
    in_fence = False
    fence_marker = ""

    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_marker = stripped[:3]
            continue

        m = HEADER_RE.match(raw)
        if m:
            if cur:
                entries.append(cur)
            date = m.group(1).strip()
            cur = {
                "date": date,
                "text": m.group(2).strip(),
                "line": i,
                "status": None,
                "status_lines": [],
                "is_template": schema.is_placeholder_text(date) or "template" in date.lower(),
            }
            continue
        if cur is not None:
            sm = STATUS_RE.search(raw)
            if sm:
                # LAST match wins, matching the entry shape HANDOFFS.md documents, where the
                # status line is the final line of the entry. This used to take the FIRST and
                # dashboard/parser.py the last, so an entry carrying two of them was read
                # differently by the two shipped readers.
                cur["status"] = schema.normalise(sm.group(1))
                cur["status_lines"].append(i)
    if cur:
        entries.append(cur)

    for e in entries:
        if len(e["status_lines"]) > 1 and not e["is_template"]:
            # An entry has one status line. More than one is ambiguous, and which one a tool
            # believes was the difference between the two readers -- so say so instead of
            # resolving it quietly.
            diag.record(
                diagnostics, diag.MALFORMED_STATUS_LINE, path, e["status_lines"][-1],
                "entry has %d `**Status:**` lines; the last one was used"
                % len(e["status_lines"]),
                "lines %s" % ", ".join(str(n) for n in e["status_lines"]),
            )
        if e["status"] is None:
            e["status"] = schema.MISSING
            if not e["is_template"]:
                diag.record(
                    diagnostics, diag.MISSING_STATUS, path, e["line"],
                    "entry has no `- **Status:**` line",
                )
        e["state"] = schema.classify_item_status(e["status"])
        if e["state"] is None and not e["is_template"]:
            diag.record(
                diagnostics, diag.UNKNOWN_STATUS, path, e["line"],
                "status is outside the documented vocabulary "
                f"({'|'.join(schema.HANDOFF_STATUSES)})",
                e["status"],
            )
    return entries


def render_table(rows, id_key, extra_key=None, extra_label=None):
    """Render one INDEX.md table.

    Every cell goes through `md_table.format_row`, which escapes pipes and flattens newlines.
    These rows used to be built by string interpolation, so a question containing a `|` -- a
    shell pipeline, a regex alternation, a type union -- emitted a row with more columns than
    its header declared. Markdown renderers do not error on that; they just draw a broken
    table, and the row that breaks is the one whose text was unusual, which is
    disproportionately the interesting one (issue #42).
    """
    headers = ["#", "Status"] + ([extra_label] if extra_label else []) + ["Line", "Summary"]
    out = [md_table.format_row(headers), md_table.format_row(["---"] * len(headers))]
    for r in rows:
        cells = [f"`{r[id_key]}`", r["status"] or EM_DASH]
        if extra_label:
            cells.append(r.get(extra_key, "") or "")
        cells.extend([f"[line {r['line']}]", r["text"]])
        out.append(md_table.format_row(cells))
    return "".join(out)


def build_index_text(coord_dir=None, diagnostics=None):
    """Render INDEX.md as a string.

    Exposed as a function so the optional dashboard can call it instead of keeping a second
    generator: dashboard.py used to emit its own INDEX.md with a different column set and a
    different template rule, so the same filename meant two things depending on who wrote it.
    """
    coord_dir = coord_dir or COORD
    q_rows = parse_questions(os.path.join(coord_dir, "QUESTIONS.md"), diagnostics)
    h_rows = parse_handoffs(os.path.join(coord_dir, "HANDOFFS.md"), diagnostics)

    q_open = [r for r in q_rows if r["state"] == "open"]
    q_blocking = [r for r in q_open if r["type"] == "blocking"]
    q_closed = [r for r in q_rows if r["state"] == "closed"]
    q_unknown = [r for r in q_rows if r["state"] is None]
    h_live = [r for r in h_rows if not r["is_template"]]
    h_open = [r for r in h_live if r["state"] == "open"]
    h_closed = [r for r in h_live if r["state"] == "closed"]
    h_unknown = [r for r in h_live if r["state"] is None]

    out = []
    out.append("# INDEX " + EM_DASH + " open items in `QUESTIONS.md` and `HANDOFFS.md`\n")
    out.append(
        "Built by `coordination/tools/build_index.py` " + EM_DASH + " the question/decision text itself is "
        "NOT duplicated here, only number/status/line to jump to. Rebuild after editing the "
        "journals: `python coordination/tools/build_index.py --out coordination/INDEX.md`.\n"
    )
    # Blocking questions go FIRST, above everything, and say who is waiting on whom.
    # `PROJECT.md` tells a role that a blocking question means "stop, make no changes,
    # wait" -- so an unanswered one is not an item on a list, it is a halted session. Until
    # this section existed, that state was indistinguishable from ordinary progress: the row
    # sat in a markdown table nobody had a reason to open, and the type column was not even
    # parsed.
    if q_blocking:
        out.append(
            f"## {WARNING_SIGN} BLOCKING {EM_DASH} {len(q_blocking)} question(s) waiting on the owner\n"
            "\nA role is stopped on each of these and will make no further changes to that "
            "step until it is answered (`PROJECT.md`, question protocol). Answer in "
            "`QUESTIONS.md` and set the status to `resolved`.\n"
        )
        out.append(render_table(q_blocking, "id", "who", "To"))
        out.append("")

    out.append(f"## QUESTIONS.md {EM_DASH} open ({len(q_open)} of {len(q_rows)})\n")
    out.append(render_table(q_open, "id", "who", "To"))
    out.append(f"\n## HANDOFFS.md {EM_DASH} open or missing status ({len(h_open)} of {len(h_live)})\n")
    out.append(render_table(h_open, "date"))

    # Unrecognised rows get their own section rather than being folded into either side.
    # An operator reading INDEX.md must see that some rows could not be classified; a
    # warning printed to a terminal nobody watched is how "Open Questions: 0" got believed.
    if q_unknown or h_unknown:
        out.append(
            f"\n## {WARNING_SIGN} Unrecognised ({len(q_unknown) + len(h_unknown)})\n"
            "\nThese rows use a status outside the documented vocabulary, so they are counted "
            "in NEITHER the open nor the closed totals above. Fix the files; the tools "
            "deliberately do not guess at a translation.\n"
        )
        if q_unknown:
            out.append(render_table(q_unknown, "id", "who", "To"))
        if h_unknown:
            out.append(render_table(h_unknown, "date"))

    out.append(f"\n<details><summary>QUESTIONS.md {EM_DASH} closed ({len(q_closed)})</summary>\n\n")
    out.append(render_table(q_closed, "id", "who", "To"))
    out.append("\n</details>\n")
    out.append(f"\n<details><summary>HANDOFFS.md {EM_DASH} closed ({len(h_closed)})</summary>\n\n")
    out.append(render_table(h_closed, "date"))
    out.append("\n</details>\n")

    return "\n".join(out), len(q_rows), len(h_rows), len(q_blocking)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="where to write INDEX.md")
    ap.add_argument(
        "--coordination-dir", default=None,
        help="directory holding QUESTIONS.md and HANDOFFS.md "
             "(default: the coordination/ directory next to this script)",
    )
    ap.add_argument(
        "--strict", action="store_true",
        help="exit 2 if anything could not be interpreted (default: warn on stderr, exit 0)",
    )
    ap.add_argument(
        "--fail-on-blocking", action="store_true",
        help="exit 1 while any open question is marked blocking; for a CI check that turns "
             "a halted session into something the owner cannot miss",
    )
    args = ap.parse_args()

    coord_dir = args.coordination_dir or COORD
    if not os.path.isdir(coord_dir):
        # Without this the run "succeeds" and writes an index reporting nothing open, which
        # is the failure this scaffold treats as its worst: a journal believed to be empty.
        print(
            f"build_index: no coordination directory at {coord_dir}. "
            "Pass --coordination-dir when the scaffold is not at <project>/coordination/.",
            file=sys.stderr,
        )
        return 2

    diagnostics = []
    text, q_count, h_count, blocking = build_index_text(coord_dir, diagnostics)

    # newline="\n" for the same reason ownership.py and coordlib/manifest.py force it: the
    # generated tree should not change shape with the platform that generated it. Without
    # it this file alone gained CRLF on Windows while CODEOWNERS and .scaffold-version,
    # written beside it, stayed LF.
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"written: {args.out} ({q_count} questions, {h_count} handoffs)")

    if blocking:
        # stderr, and named: this is the one line in the output that means a human is
        # required. On a terminal it stands out; in CI it becomes the failure message.
        print(
            f"BLOCKING: {blocking} open question(s) are waiting on the owner. "
            "A role is stopped on each of them.",
            file=sys.stderr,
        )

    for d in diagnostics:
        print(f"WARN {d}", file=sys.stderr)
    if diagnostics:
        print(
            f"WARN {len(diagnostics)} item(s) need attention. Anything the tools could not "
            "interpret is listed under 'Unrecognised' in the index and counted in neither "
            "total; a duplicate id is read normally, it just no longer identifies one row.",
            file=sys.stderr,
        )
        if args.strict:
            return 2
    if args.fail_on_blocking:
        # A gate that cannot see the signal must not report the signal as absent. With no
        # Type column every row classifies as neither blocking nor non-blocking, so `0
        # blocking` here means "could not tell", not "nothing is stopped". Exit 2, the code
        # this tool already uses for "something could not be interpreted", so a build can
        # tell it apart from exit 1, which means a real blocker was found.
        blind = [d for d in diagnostics if d.code == diag.MISSING_TYPE_COLUMN]
        if blind:
            print(
                "CANNOT GATE: %d questions table(s) have no Type column, so --fail-on-blocking "
                "has nothing to test. Add the column, or drop the flag." % len(blind),
                file=sys.stderr,
            )
            return 2
        if blocking:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
