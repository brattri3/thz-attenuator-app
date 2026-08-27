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
references/rationale.md for the THz project's experience with 8 different status-phrasing
variants), extend the regexes below rather than special-casing every historical entry; keep this
script simple and let format drift be a signal that the templates need reinforcing, not a reason
to make the parser permissive.

Usage (from repo root):
    python coordination/tools/build_index.py --out coordination/INDEX.md
"""

import argparse
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COORD = os.path.join(ROOT, "coordination")

SEP_RE = re.compile(r"^:?-+:?$")
STATUS_RE = re.compile(r"\*\*Status:?\*\*:?\s*`?([^`\n().]*)", re.IGNORECASE)
HEADER_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\]\s*(.*)$")


def is_open(status):
    s = status.lower()
    return "open" in s or "taken" in s


def split_row(line):
    # `\|` inside inline code (e.g. an escaped pipe in a formula) is not a column separator.
    protected = line.strip("|").replace(r"\|", "\x00")
    return [c.replace("\x00", "|").strip() for c in protected.split("|")]


def parse_questions(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    rows = []
    headers = None
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if not line.startswith("|"):
            headers = None
            continue
        cells = split_row(line)
        if all(SEP_RE.match(c) for c in cells):
            continue
        if cells and cells[0] == "#":
            headers = cells
            continue
        if headers is None:
            continue
        row = dict(zip(headers, cells))
        rid = row.get("#", "").strip().strip("*").strip()
        if not rid:
            continue
        question = (row.get("Question") or "").replace("**", "")
        if len(question) > 110:
            question = question[:107] + "…"
        status = row.get("Status", "").strip("` ")
        who = row.get("Role") or row.get("To") or ""
        rows.append({"id": rid, "line": i, "text": question, "status": status, "who": who})
    return rows


def parse_handoffs(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    entries = []
    cur = None
    for i, raw in enumerate(lines, start=1):
        m = HEADER_RE.match(raw)
        if m:
            if cur:
                entries.append(cur)
            cur = {"date": m.group(1), "text": m.group(2).strip(), "line": i, "status": None}
            continue
        if cur is not None and cur["status"] is None:
            sm = STATUS_RE.search(raw)
            if sm:
                cur["status"] = sm.group(1).strip()
    if cur:
        entries.append(cur)
    for e in entries:
        if e["status"] is None:
            e["status"] = "missing"
    return entries


def render_table(rows, id_key, extra_key=None, extra_label=None):
    head = f"| # | Status | {extra_label + ' | ' if extra_label else ''}Line | Summary |\n"
    head += f"|---|---|{'---|' if extra_label else ''}---|---|\n"
    body = []
    for r in rows:
        extra = f"{r.get(extra_key, '')} | " if extra_label else ""
        body.append(f"| `{r[id_key]}` | {r['status'] or '—'} | {extra}[line {r['line']}] | {r['text']} |")
    return head + "\n".join(body) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="where to write INDEX.md")
    args = parser.parse_args()

    q_rows = parse_questions(os.path.join(COORD, "QUESTIONS.md"))
    h_rows = parse_handoffs(os.path.join(COORD, "HANDOFFS.md"))

    q_open = [r for r in q_rows if is_open(r["status"])]
    q_closed = [r for r in q_rows if not is_open(r["status"])]
    h_open = [r for r in h_rows if is_open(r["status"]) or r["status"] == "missing"]
    h_closed = [r for r in h_rows if not is_open(r["status"]) and r["status"] != "missing"]

    out = []
    out.append("# INDEX — open items in `QUESTIONS.md` and `HANDOFFS.md`\n")
    out.append(
        "Built by `coordination/tools/build_index.py` — the question/decision text itself is "
        "NOT duplicated here, only number/status/line to jump to. Rebuild after editing the "
        "journals: `python coordination/tools/build_index.py --out coordination/INDEX.md`.\n"
    )
    out.append(f"## QUESTIONS.md — open ({len(q_open)} of {len(q_rows)})\n")
    out.append(render_table(q_open, "id", "who", "To"))
    out.append(f"\n## HANDOFFS.md — open or missing status ({len(h_open)} of {len(h_rows)})\n")
    out.append(render_table(h_open, "date"))
    out.append(f"\n<details><summary>QUESTIONS.md — closed ({len(q_closed)})</summary>\n\n")
    out.append(render_table(q_closed, "id", "who", "To"))
    out.append("\n</details>\n")
    out.append(f"\n<details><summary>HANDOFFS.md — closed ({len(h_closed)})</summary>\n\n")
    out.append(render_table(h_closed, "date"))
    out.append("\n</details>\n")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"written: {args.out} ({len(q_rows)} questions, {len(h_rows)} handoffs)")


if __name__ == "__main__":
    main()
