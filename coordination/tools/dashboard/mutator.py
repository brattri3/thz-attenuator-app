"""
mutator.py - Line-preserving, non-destructive mutator for Markdown tables and handoff entries.
Preserves exact file structure, comments, headers, blank lines, escaped pipes, CRLF/LF endings, and UTF-8 encoding.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional, Tuple

try:
    from .parser import SEP_RE, split_table_row, HEADER_RE, STATUS_RE
except (ImportError, ValueError):
    from parser import SEP_RE, split_table_row, HEADER_RE, STATUS_RE


def escape_pipe(text: str) -> str:
    """
    Ensures unescaped pipe characters in table cells are properly escaped as \\|.
    Leaves already escaped pipes (\\|) intact.
    """
    return re.sub(r"(?<!\\)\|", r"\|", text)


def format_table_row(cells: List[str], line_ending: str = "\n") -> str:
    """
    Formats a list of cell values into a standard markdown table row with trailing line ending.
    """
    escaped_cells = [escape_pipe(c.strip()) for c in cells]
    return f"| {' | '.join(escaped_cells)} |{line_ending}"


def mutate_table_cell(
    file_path: Path,
    key_col: str,
    key_val: str,
    target_col: str,
    new_val: str
) -> Tuple[bool, str]:
    """
    Line-preserving table cell mutator.
    Finds the table row where cell under `key_col` equals `key_val`,
    and updates `target_col` to `new_val`.
    Preserves all surrounding markdown, comments, untouched lines, and line endings.
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    with open(file_path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    headers: Optional[List[str]] = None
    target_line_idx: Optional[int] = None
    target_col_idx: Optional[int] = None
    matched_cells: Optional[List[str]] = None
    key_col_idx: Optional[int] = None

    key_col_clean = key_col.strip().lower()
    target_col_clean = target_col.strip().lower()
    key_val_clean = key_val.strip().lower()

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("|"):
            headers = None
            continue
        cells = split_table_row(line)
        if all(SEP_RE.match(c) for c in cells):
            continue

        if headers is None:
            # Check if this row is a header containing the target columns
            header_map = {h.strip().lower(): i for i, h in enumerate(cells)}
            # Find key column match
            matched_key_idx = None
            for k, i in header_map.items():
                if k == key_col_clean or key_col_clean in k or k in key_col_clean:
                    matched_key_idx = i
                    break
            
            # Find target column match
            matched_target_idx = None
            for k, i in header_map.items():
                if k == target_col_clean or target_col_clean in k or k in target_col_clean:
                    matched_target_idx = i
                    break

            if matched_key_idx is not None and matched_target_idx is not None:
                headers = cells
                key_col_idx = matched_key_idx
                target_col_idx = matched_target_idx
            else:
                continue
        else:
            if key_col_idx is None or target_col_idx is None:
                continue
            if len(cells) <= max(key_col_idx, target_col_idx):
                continue

            row_key_val = cells[key_col_idx].strip("`* ").lower()
            if row_key_val == key_val_clean:
                target_line_idx = idx
                matched_cells = cells
                break

    if target_line_idx is None or target_col_idx is None or matched_cells is None:
        return False, f"Row with {key_col}='{key_val}' and column '{target_col}' not found in {file_path.name}"

    orig_line = lines[target_line_idx]
    line_ending = "\r\n" if orig_line.endswith("\r\n") else "\n"

    # Update cell with new value
    matched_cells[target_col_idx] = new_val.strip()

    # Reconstruct only the modified line
    new_line = format_table_row(matched_cells, line_ending=line_ending)
    lines[target_line_idx] = new_line

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)

    return True, f"Updated row '{key_val}' column '{target_col}' in {file_path.name}"


def mutate_handoff_status(
    file_path: Path,
    date: str,
    title: str,
    new_status: str
) -> Tuple[bool, str]:
    """
    Line-preserving status mutator for HANDOFFS.md.
    Locates entry by date + title and updates the - **Status:** line in place.
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    with open(file_path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    entry_start: Optional[int] = None
    target_status_line: Optional[int] = None

    date_clean = date.strip().lower()
    title_clean = title.strip().lower()

    for idx, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        m = HEADER_RE.match(line)
        if m:
            if entry_start is not None and target_status_line is not None:
                # Found and completed previous matched entry
                break
            entry_date = m.group(1).strip().lower()
            entry_title = (m.group(4) or "").strip().lower()
            # Match date and title (supports partial match for resilience)
            if entry_date == date_clean and (not title_clean or title_clean in entry_title or entry_title in title_clean):
                entry_start = idx
                target_status_line = None
            else:
                entry_start = None
            continue

        if entry_start is not None:
            sm = STATUS_RE.search(line)
            if sm:
                target_status_line = idx
                break

    if target_status_line is None:
        return False, f"Handoff entry '{date}' - '{title}' status line not found in {file_path.name}"

    orig_line = lines[target_status_line]
    line_ending = "\r\n" if orig_line.endswith("\r\n") else "\n"

    # Preserve any leading indentation
    leading_ws = len(orig_line) - len(orig_line.lstrip())
    indent = orig_line[:leading_ws]

    new_line = f"{indent}- **Status:** {new_status.strip().lower()}{line_ending}"
    lines[target_status_line] = new_line

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)

    return True, f"Updated handoff '{title}' status to '{new_status}' in {file_path.name}"


def append_question(
    file_path: Path,
    question: str,
    q_type: str = "blocking",
    status: str = "open",
    qid: Optional[str] = None,
    answer: str = "—"
) -> Tuple[bool, str]:
    """
    Appends a new question to QUESTIONS.md with an auto-generated or specified Q-ID.
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    with open(file_path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    line_ending = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"

    # Find highest Q-number among existing rows to generate next ID
    max_id_num = 0
    last_table_row_idx: Optional[int] = None

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("|"):
            cells = split_table_row(line)
            if cells and not all(SEP_RE.match(c) for c in cells) and cells[0] not in ("#", "ID", "№"):
                last_table_row_idx = idx
                m = re.search(r"Q-(\d+)", cells[0])
                if m:
                    max_id_num = max(max_id_num, int(m.group(1)))

    assigned_id = qid if qid else f"Q-{max_id_num + 1}"
    row_cells = [assigned_id, question, answer, q_type, status]
    new_row_str = format_table_row(row_cells, line_ending=line_ending)

    if last_table_row_idx is not None:
        lines.insert(last_table_row_idx + 1, new_row_str)
    else:
        table_header = f"{line_ending}| # | Question | Owner's answer | Type | Status |{line_ending}|---|---|---|---|---|{line_ending}"
        lines.append(table_header)
        lines.append(new_row_str)

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)

    return True, f"Appended question {assigned_id} in {file_path.name}"


def append_handoff(
    file_path: Path,
    from_role: str,
    to_role: str,
    title: str,
    what: str,
    context: str,
    done_when: str,
    status: str = "open",
    date: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Appends a new handoff entry to HANDOFFS.md in strict CHARTER format.
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    with open(file_path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()

    line_ending = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"
    date_str = date if date else datetime.now().strftime("%Y-%m-%d")

    block = [
        f"{line_ending}## [{date_str}] FROM {from_role.strip()} TO {to_role.strip()} — {title.strip()}{line_ending}",
        f"- What: {what.strip()}{line_ending}",
        f"- Context: {context.strip()}{line_ending}",
        f"- Done when: {done_when.strip()}{line_ending}",
        f"- **Status:** {status.strip().lower()}{line_ending}"
    ]

    lines.extend(block)

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)

    return True, f"Appended handoff [{date_str}] FROM {from_role} TO {to_role} in {file_path.name}"
