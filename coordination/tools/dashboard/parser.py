"""
parser.py - Safe, robust, tokenized parser for multi-agent coordination files and git worktrees.
Preserves markdown formatting, handles escaped pipes (\\|), code spans with pipes, unicode/Cyrillic, and CRLF/LF.
"""

from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

SEP_RE = re.compile(r"^:?-+:?$")
STATUS_RE = re.compile(r"\*\*Status:?\*\*:?\s*`?([^`\n().]*)", re.IGNORECASE)
HEADER_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*(?:FROM\s+(\S+)\s+TO\s+(\S+)\s*[-—–]\s*)?(.*)$", re.IGNORECASE)


def split_table_row(line: str) -> List[str]:
    """
    Splits a markdown table row into individual cell strings.
    Correctly handles:
      - Escaped pipes (`\\|`)
      - Pipes inside backtick code spans (e.g. `` `a | b` ``)
      - Strips outer table borders (`|`) and trims cell whitespace.
    """
    content = line.strip()
    if content.startswith("|"):
        content = content[1:]
    if content.endswith("|"):
        content = content[:-1]

    cells: List[str] = []
    current: List[str] = []
    in_code = False
    i = 0
    n = len(content)
    while i < n:
        c = content[i]
        if c == "\\" and i + 1 < n and content[i + 1] == "|":
            current.append(r"\|")
            i += 2
        elif c == "`":
            in_code = not in_code
            current.append(c)
            i += 1
        elif c == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(c)
            i += 1
    cells.append("".join(current).strip())
    return cells


def parse_board(path: Path) -> List[Dict[str, Any]]:
    """
    Parses BOARD.md into structured role status records.
    Extracts: role, status, date, status_date, summary, line number, and raw cells.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    rows: List[Dict[str, Any]] = []
    headers: Optional[List[str]] = None

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line.startswith("|"):
            headers = None
            continue
        cells = split_table_row(line)
        if all(SEP_RE.match(c) for c in cells):
            continue
        if headers is None:
            # Detect header row (supports Russian and English labels)
            if any(h.lower() in ("role", "роль", "id", "status", "статус") for h in cells):
                headers = cells
                continue
        else:
            row_dict = dict(zip(headers, cells))
            raw_role = row_dict.get("Role") or row_dict.get("роль") or row_dict.get("ID") or cells[0]
            clean_role = raw_role.strip("`* ")

            if not clean_role or clean_role.startswith("<"):
                # Skip template placeholders like <ID>
                continue
            
            status_date = row_dict.get("Status (date)") or row_dict.get("Status") or row_dict.get("Статус") or (cells[1] if len(cells) > 1 else "")
            summary = row_dict.get("One-line summary") or row_dict.get("Summary") or row_dict.get("Описание") or (cells[2] if len(cells) > 2 else "")

            # Parse status keyword and date from "status (YYYY-MM-DD)"
            status_match = re.match(r"^([A-Za-zА-Яа-я0-9_-]+)(?:\s*\(([^)]+)\))?", status_date.strip())
            status = status_match.group(1) if status_match else status_date.strip()
            date = status_match.group(2) if (status_match and status_match.group(2)) else ""

            rows.append({
                "role": clean_role,

                "status": status.strip().lower(),
                "date": date.strip(),
                "status_date": status_date.strip(),
                "summary": summary.strip(),
                "line": idx,
                "raw_cells": row_dict
            })
    return rows


def parse_questions(path: Path) -> List[Dict[str, Any]]:
    """
    Parses QUESTIONS.md across all batch tables in the file.
    Extracts: id, question, answer, type, status, who, line, is_open, is_blocking, raw_cells.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    questions: List[Dict[str, Any]] = []
    headers: Optional[List[str]] = None

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line.startswith("|"):
            headers = None
            continue
        cells = split_table_row(line)
        if all(SEP_RE.match(c) for c in cells):
            continue
        if headers is None:
            if cells and (cells[0] in ("#", "ID", "№") or any("question" in c.lower() or "вопрос" in c.lower() for c in cells)):
                headers = cells
                continue
        else:
            row_dict = dict(zip(headers, cells))
            qid = (row_dict.get("#") or row_dict.get("ID") or row_dict.get("№") or cells[0]).strip("`* ")
            if not qid or qid.startswith("<"):
                continue

            question = (row_dict.get("Question") or row_dict.get("Вопрос") or (cells[1] if len(cells) > 1 else "")).replace(r"\|", "|")
            answer = (row_dict.get("Owner's answer") or row_dict.get("Answer") or row_dict.get("Ответ") or (cells[2] if len(cells) > 2 else "")).replace(r"\|", "|")
            q_type = row_dict.get("Type") or row_dict.get("Тип") or (cells[3] if len(cells) > 3 else "blocking")
            status = row_dict.get("Status") or row_dict.get("Статус") or (cells[4] if len(cells) > 4 else "open")
            who = row_dict.get("Role") or row_dict.get("To") or ""

            clean_status = status.strip("`* ").lower()
            clean_type = q_type.strip("`* ").lower()
            is_open = "open" in clean_status or "taken" in clean_status
            is_blocking = "blocking" in clean_type and "non" not in clean_type

            questions.append({
                "id": qid,
                "question": question.strip(),
                "answer": answer.strip(),
                "type": clean_type,
                "status": clean_status,
                "who": who.strip(),
                "line": idx,
                "is_open": is_open,
                "is_blocking": is_blocking,
                "raw_cells": row_dict
            })
    return questions


def parse_handoffs(path: Path) -> List[Dict[str, Any]]:
    """
    Parses HANDOFFS.md into structured handoff entry blocks.
    Extracts: date, from_role, to_role, title, what, context, done_when, status, start_line, status_line, is_template, is_open.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    entries: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        m = HEADER_RE.match(line)
        if m:
            if cur:
                entries.append(cur)
            date_str = m.group(1).strip()
            from_role = m.group(2) or ""
            to_role = m.group(3) or ""
            title = m.group(4).strip() if m.group(4) else ""
            is_tmpl = "template" in date_str.lower() or "YYYY-MM-DD" in date_str or "<ID>" in line
            cur = {
                "date": date_str,
                "from_role": from_role,
                "to_role": to_role,
                "title": title,
                "what": "",
                "context": "",
                "done_when": "",
                "status": None,
                "start_line": idx,
                "status_line": None,
                "is_template": is_tmpl
            }
            continue

        if cur is not None:
            sm = STATUS_RE.search(line)
            if sm:
                cur["status"] = sm.group(1).strip("` ").lower()
                cur["status_line"] = idx
            elif line.strip().startswith("- What:"):
                cur["what"] = line.strip()[7:].strip()
            elif line.strip().startswith("- Context:"):
                cur["context"] = line.strip()[10:].strip()
            elif line.strip().startswith("- Done when:"):
                cur["done_when"] = line.strip()[12:].strip()

    if cur:
        entries.append(cur)

    for e in entries:
        if e["status"] is None:
            e["status"] = "missing"
        status_val = e["status"].lower()
        e["is_open"] = status_val in ("open", "taken", "missing", "in_progress")

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
