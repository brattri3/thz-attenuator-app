"""
parser.py - Safe, robust, tokenized parser for multi-agent coordination files and git worktrees.
Preserves markdown formatting, handles escaped pipes (\\|), code spans with pipes, unicode/Cyrillic, and CRLF/LF.
"""

from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

# coordlib lives one level up, beside build_index.py. It ships with the core scaffold and is
# stdlib-only; this package is the optional add-on that also uses it.
_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coordlib import diagnostics as diag  # noqa: E402
from coordlib import md_table, schema  # noqa: E402
from coordlib.md_table import split_table_row  # noqa: E402,F401

STATUS_RE = re.compile(r"\*\*Status:?\*\*:?\s*`?([^`\n().]*)", re.IGNORECASE)
HEADER_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*(?:FROM\s+(\S+)\s+TO\s+(\S+)\s*[-—–]\s*)?(.*)$", re.IGNORECASE)


def parse_board(path: Path, *, diagnostics=None) -> List[Dict[str, Any]]:
    """
    Parses BOARD.md into structured role status records.
    Extracts: role, status, date, status_date, summary, line number, and raw cells.

    `status` is the raw keyword as written; `status_known` is its canonical form, or None
    when the word is outside the documented vocabulary (BOARD.md documents
    active|idle|stale|blocked). Callers must not treat None as "inactive" -- an
    unrecognised status is a reporting failure, not a state.

    Pass `diagnostics=[]` to collect what could not be interpreted.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    rows: List[Dict[str, Any]] = []
    saw_table = False

    for block in md_table.iter_table_blocks(lines):
        saw_table = True
        resolved = schema.resolve_headers(block.headers)
        if not schema.matches_signature(resolved, schema.BOARD_TABLE_SIGNATURE):
            diag.record(
                diagnostics, diag.UNKNOWN_TABLE_SCHEMA, path, block.header_index + 1,
                "expected a table with Role and Status columns; skipped "
                f"{len(block.row_indices)} row(s)",
                " | ".join(block.headers),
            )
            continue

        for row_index in block.row_indices:
            cells = md_table.split_table_row(lines[row_index].strip())
            line_no = row_index + 1
            if len(cells) != len(block.headers):
                diag.record(
                    diagnostics, diag.COLUMN_COUNT_MISMATCH, path, line_no,
                    f"row has {len(cells)} cells, header has {len(block.headers)}",
                )

            def cell(key: str) -> str:
                index = resolved.get(key)
                return cells[index] if index is not None and index < len(cells) else ""

            raw_role = cell("role")
            if schema.is_placeholder_text(raw_role):
                continue

            status_date = cell("status")
            keyword, date = schema.split_role_status_date(status_date)
            status_known = schema.classify_role_status(status_date)
            if status_known is None and keyword:
                diag.record(
                    diagnostics, diag.UNKNOWN_STATUS, path, line_no,
                    "role status is outside the documented vocabulary "
                    f"({'|'.join(schema.BOARD_STATUSES)})",
                    keyword,
                )

            rows.append({
                "role": schema.strip_decoration(raw_role),
                "status": keyword.lower(),
                "status_known": status_known,
                "date": date,
                "status_date": status_date.strip(),
                "summary": cell("summary").strip(),
                "line": line_no,
                "raw_cells": dict(zip(block.headers, cells)),
            })

    if not saw_table:
        diag.record(diagnostics, diag.NO_HEADER_ROW, path, None, "no markdown table found")
    return rows


def parse_questions(path: Path, *, diagnostics=None) -> List[Dict[str, Any]]:
    """
    Parses QUESTIONS.md across all batch tables in the file.
    Extracts: id, question, answer, type, status, who, line, is_open, is_blocking, raw_cells.

    `is_open` and `is_blocking` are Optional[bool]: None means the value was outside the
    documented vocabulary, NOT that the answer is no. Truthy checks behave as before;
    negative checks must test `is not False` so unrecognised rows are not filed as resolved.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    questions: List[Dict[str, Any]] = []
    seen_ids: Dict[str, int] = {}
    saw_table = False

    for block in md_table.iter_table_blocks(lines):
        saw_table = True
        resolved = schema.resolve_headers(block.headers)
        if not schema.matches_signature(resolved, schema.QUESTIONS_TABLE_SIGNATURE):
            diag.record(
                diagnostics, diag.UNKNOWN_TABLE_SCHEMA, path, block.header_index + 1,
                "expected a questions table (#, Question, Status); skipped "
                f"{len(block.row_indices)} row(s)",
                " | ".join(block.headers),
            )
            continue

        for row_index in block.row_indices:
            cells = md_table.split_table_row(lines[row_index].strip())
            line_no = row_index + 1
            if len(cells) != len(block.headers):
                diag.record(
                    diagnostics, diag.COLUMN_COUNT_MISMATCH, path, line_no,
                    f"row has {len(cells)} cells, header has {len(block.headers)}",
                )

            def cell(key: str) -> str:
                index = resolved.get(key)
                return cells[index] if index is not None and index < len(cells) else ""

            qid = schema.strip_decoration(cell("id"))
            if schema.is_placeholder_text(qid):
                continue
            if qid in seen_ids:
                diag.record(
                    diagnostics, diag.DUPLICATE_ID, path, line_no,
                    f"id already used on line {seen_ids[qid]}", qid,
                )
            else:
                seen_ids[qid] = line_no

            raw_status = cell("status")
            raw_type = cell("type")
            open_state = schema.classify_item_status(raw_status)
            type_state = schema.classify_question_type(raw_type)

            if open_state is None:
                diag.record(
                    diagnostics, diag.UNKNOWN_STATUS, path, line_no,
                    "question status is outside the documented vocabulary "
                    f"({'|'.join(schema.QUESTION_STATUSES)}); counted as unclassified, "
                    "not as resolved",
                    schema.strip_decoration(raw_status),
                )
            if type_state is None and raw_type.strip():
                diag.record(
                    diagnostics, diag.UNKNOWN_TYPE, path, line_no,
                    "question type is outside the documented vocabulary "
                    f"({'|'.join(schema.QUESTION_TYPES)})",
                    schema.strip_decoration(raw_type),
                )

            questions.append({
                "id": qid,
                "question": md_table.unescape_pipe(cell("question")).strip(),
                "answer": md_table.unescape_pipe(cell("answer")).strip(),
                "type": schema.normalise(raw_type),
                "status": schema.normalise(raw_status),
                "who": cell("role").strip(),
                "line": line_no,
                "is_open": None if open_state is None else (open_state == "open"),
                "is_blocking": None if type_state is None else (type_state == "blocking"),
                "raw_cells": dict(zip(block.headers, cells)),
            })

    if not saw_table:
        diag.record(diagnostics, diag.NO_HEADER_ROW, path, None, "no markdown table found")
    return questions


def parse_handoffs(path: Path, *, diagnostics=None) -> List[Dict[str, Any]]:
    """
    Parses HANDOFFS.md into structured handoff entry blocks.
    Extracts: date, from_role, to_role, title, what, context, done_when, status, start_line,
    status_line, is_template, is_open.

    Fenced code blocks are skipped. HANDOFFS.md documents its own entry format inside a ```
    fence, and without this the *example* is read as a live handoff dated "ISO-date".

    `is_open` is Optional[bool]: None means the status word was outside the documented
    vocabulary (open|taken|done), not that the entry is closed.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    entries: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    in_fence = False
    fence_marker = ""

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        # Fence tracking has to come first: a ``` block may contain anything, including
        # lines that look exactly like a handoff header or a status line.
        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_marker = stripped[:3]
            continue

        m = HEADER_RE.match(line)
        if m:
            if cur:
                entries.append(cur)
            date_str = m.group(1).strip()
            cur = {
                "date": date_str,
                "from_role": m.group(2) or "",
                "to_role": m.group(3) or "",
                "title": m.group(4).strip() if m.group(4) else "",
                "what": "",
                "context": "",
                "done_when": "",
                "status": None,
                "start_line": idx,
                "status_line": None,
                "status_lines": [],
                "is_template": schema.is_placeholder_text(date_str) or "template" in date_str.lower(),
            }
            continue

        if cur is not None:
            sm = STATUS_RE.search(line)
            if sm:
                # Last match wins, matching the entry shape HANDOFFS.md documents. This
                # reader already behaved that way; build_index.py took the first, so the two
                # disagreed on any entry carrying more than one status line.
                cur["status"] = schema.normalise(sm.group(1))
                cur["status_line"] = idx
                cur["status_lines"].append(idx)
            elif stripped.startswith("- What:"):
                cur["what"] = stripped[7:].strip()
            elif stripped.startswith("- Context:"):
                cur["context"] = stripped[10:].strip()
            elif stripped.startswith("- Done when:"):
                cur["done_when"] = stripped[12:].strip()

    if cur:
        entries.append(cur)

    for entry in entries:
        if len(entry["status_lines"]) > 1 and not entry["is_template"]:
            diag.record(
                diagnostics, diag.MALFORMED_STATUS_LINE, path, entry["status_lines"][-1],
                "entry has %d `**Status:**` lines; the last one was used"
                % len(entry["status_lines"]),
                "lines %s" % ", ".join(str(n) for n in entry["status_lines"]),
            )
        if entry["status"] is None:
            entry["status"] = schema.MISSING
            if not entry["is_template"]:
                diag.record(
                    diagnostics, diag.MISSING_STATUS, path, entry["start_line"],
                    "entry has no `- **Status:** open|taken|done` line; "
                    "treated as open so it stays visible",
                )
        open_state = schema.classify_item_status(entry["status"])
        if open_state is None and not entry["is_template"]:
            diag.record(
                diagnostics, diag.UNKNOWN_STATUS, path, entry["status_line"] or entry["start_line"],
                "handoff status is outside the documented vocabulary "
                f"({'|'.join(schema.HANDOFF_STATUSES)}); counted as unclassified, not as done",
                entry["status"],
            )
        entry["is_open"] = None if open_state is None else (open_state == "open")

    return entries


def parse_index(path: Path) -> Dict[str, Any]:
    """
    Parses INDEX.md summary counts and metadata.
    """
    if not path.exists():
        return {
            "questions_open_count": 0,
            "questions_total_count": 0,
            "handoffs_open_count": 0,
            "handoffs_total_count": 0,
            "raw_content": ""
        }
    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()

    q_match = re.search(r"## QUESTIONS\.md\s*[-—–]\s*open\s*\((\d+)\s+of\s+(\d+)\)", content, re.IGNORECASE)
    h_match = re.search(r"## HANDOFFS\.md\s*[-—–]\s*(?:open|missing)[^(]*\((\d+)\s+of\s+(\d+)\)", content, re.IGNORECASE)

    q_open_cnt = int(q_match.group(1)) if q_match else 0
    q_tot_cnt = int(q_match.group(2)) if q_match else 0
    h_open_cnt = int(h_match.group(1)) if h_match else 0
    h_tot_cnt = int(h_match.group(2)) if h_match else 0

    return {
        "questions_open_count": q_open_cnt,
        "questions_total_count": q_tot_cnt,
        "handoffs_open_count": h_open_cnt,
        "handoffs_total_count": h_tot_cnt,
        "raw_content": content
    }


def parse_worktrees(repo_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Runs git worktree list --porcelain and returns structured worktree records.
    """
    cwd = str(repo_path) if repo_path else "."
    try:
        res = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        output = res.stdout
    except Exception:
        return []

    worktrees: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        parts = line.split(" ", 1)
        key = parts[0]
        val = parts[1] if len(parts) > 1 else ""
        if key == "worktree":
            wt_path = Path(val).resolve()
            current["worktree"] = str(wt_path)
            current["path"] = str(wt_path)
            current["bare"] = False
            current["locked"] = False
            current["prunable"] = False
            current["role"] = None
        elif key == "HEAD":
            current["head"] = val
        elif key == "branch":
            b = val.replace("refs/heads/", "")
            current["branch"] = b
            if b.startswith("role/"):
                current["role"] = b[len("role/"):]
        elif key == "detached":
            current["branch"] = "(detached)"
        elif key == "bare":
            current["bare"] = True
            current["branch"] = "(bare)"
        elif key == "locked":
            current["locked"] = val or True
        elif key == "prunable":
            current["prunable"] = val or True

    if current:
        if current.get("path") and ".worktrees" in current["path"] and not current.get("role"):
            current["role"] = Path(current["path"]).name
        worktrees.append(current)

    return worktrees
