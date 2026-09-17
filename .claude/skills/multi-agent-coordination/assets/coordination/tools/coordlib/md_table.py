"""
md_table.py - markdown table tokenizing and block scanning. No domain knowledge lives here.

Two implementations of this existed. build_index.py:42 had the buggier one:

    protected = line.strip("|").replace(r"\\|", "\\x00")

`str.strip("|")` removes *every* leading and trailing pipe, so `|| a || b ||` loses cells,
and it had no handling for pipes inside backtick code spans. dashboard/parser.py:16 had the
careful version. This module keeps the careful one and both callers now share it.

`iter_table_blocks` is the piece that makes safe insertion possible. The old
`append_question` scanned for "the last pipe-prefixed line in the whole file" with no notion
of which table it belonged to, so a new question appended to whatever table happened to come
last -- in the reporter's case a table of physical measurements, which it corrupted.

STABILITY: PARTIAL -- promised: split_table_row, unescape_pipe, iter_table_blocks

Those three are promised because a consumer cannot avoid them. The contract's §4 makes them
normative for reading a row, and there is no other tokenizer here -- so marking the whole module
INTERNAL, as this docstring used to, left an outside reader with no legal way to read a table at
all. That contradiction was found by the first external consumer (issue #50) and this is the
half of the fix that travels with a vendored copy.

Everything else in here -- SEP_RE, TableBlock's field layout, format_row, escape_pipe,
detect_line_ending, is_separator_row, scan_control_characters, and every private helper -- stays
INTERNAL and may change without notice. See the skill's references/extension-contract.md.
"""

import re
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence

#: A table separator cell: `---`, `:--`, `--:`, `:-:`.
SEP_RE = re.compile(r"^:?-+:?$")

#: Bytes that must never appear in a coordination file. Excludes tab, LF and CR, which are
#: legitimate. A bare CR *inside* a line is caught separately by scan_control_characters:
#: it splits the line for every reader and shifts every subsequent line number by one, which
#: is what corrupted HANDOFFS.md and misdirected the mutator's write target.
_CONTROL_BYTES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def split_table_row(line: str) -> List[str]:
    """Split a markdown table row into cell strings.

    Handles escaped pipes (`\\|`), pipes inside backtick code spans, strips the outer
    borders, and trims each cell. An escaped pipe is preserved as `\\|` in the output so a
    round-trip through format_row does not double-escape it.
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
        char = content[i]
        if char == "\\" and i + 1 < n and content[i + 1] == "|":
            current.append(r"\|")
            i += 2
        elif char == "`":
            in_code = not in_code
            current.append(char)
            i += 1
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    cells.append("".join(current).strip())
    return cells


def escape_pipe(text: str) -> str:
    """Escape unescaped pipes so a value cannot break out of its cell. Idempotent."""
    return re.sub(r"(?<!\\)\|", r"\|", text or "")


def unescape_pipe(text: str) -> str:
    """Turn `\\|` back into a bare pipe: the inverse of `escape_pipe`, for display.

    The tokenizer deliberately hands back `\\|` verbatim -- it is reading bytes and must not
    guess at intent. But the VALUE a human wrote is `grep -E "a|b"`, and the backslash exists
    only so the row survives the table. Anything showing that value to a person, or comparing
    it to something a person typed, wants this.

    Both shipped readers needed it and only one had it: `dashboard/parser.py` unescaped the
    question and answer columns while `build_index.py` did not, so the same cell arrived as
    two different strings depending on which module you imported.
    """
    return (text or "").replace(r"\|", "|")


def format_row(cells: Sequence[str], line_ending: str = "\n") -> str:
    """Render cells as a markdown table row, escaping pipes and flattening newlines.

    Newlines are flattened rather than escaped: a multi-line value written verbatim into a
    table shatters it, and there is no markdown escape for a newline inside a cell.
    """
    safe = [escape_pipe(str(cell)).replace("\r\n", " ").replace("\n", " ") for cell in cells]
    return f"| {' | '.join(safe)} |{line_ending}"


def is_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(SEP_RE.match(cell) for cell in cells)


def detect_line_ending(lines: Sequence[str]) -> str:
    """Return the dominant line ending, defaulting to LF for an empty or single-line file."""
    crlf = sum(1 for line in lines if line.endswith("\r\n"))
    lf = sum(1 for line in lines if line.endswith("\n") and not line.endswith("\r\n"))
    return "\r\n" if crlf > lf else "\n"


@dataclass
class TableBlock:
    """One contiguous markdown table, located by line index (0-based, into `lines`).

    `preceding_heading` is the nearest `#`-heading above the table, which is what lets the
    UI tell the operator *which* table a write is about to land in.
    """

    header_index: int
    separator_index: Optional[int]
    first_row_index: Optional[int]
    last_row_index: Optional[int]
    headers: List[str]
    preceding_heading: str = ""
    line_ending: str = "\n"
    row_indices: List[int] = field(default_factory=list)

    @property
    def insert_after_index(self) -> int:
        """Line index to insert a new row after: the last data row, else the separator."""
        if self.last_row_index is not None:
            return self.last_row_index
        if self.separator_index is not None:
            return self.separator_index
        return self.header_index


def iter_table_blocks(lines: Sequence[str]) -> Iterator[TableBlock]:
    """Yield every markdown table in `lines`, in document order.

    A table starts at the first pipe row, and its header is that row; the separator row is
    recognised but not required (some hand-written tables omit it). The table ends at the
    first line that is not a pipe row.

    Fenced code blocks are skipped entirely. The templates document their own format inside
    a ``` fence, and without this every reader treats the *example* as real data -- which is
    exactly what parse_handoffs still does with the HANDOFFS.md format block.
    """
    line_ending = detect_line_ending(lines)
    heading = ""
    in_fence = False
    fence_marker = ""
    index = 0
    total = len(lines)

    while index < total:
        stripped = lines[index].strip()

        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
            index += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_marker = stripped[:3]
            index += 1
            continue

        if stripped.startswith("#"):
            heading = stripped
            index += 1
            continue

        if not stripped.startswith("|"):
            index += 1
            continue

        # A table starts here.
        header_index = index
        headers = split_table_row(stripped)
        separator_index = None
        row_indices: List[int] = []
        index += 1

        while index < total:
            row_stripped = lines[index].strip()
            if not row_stripped.startswith("|"):
                break
            cells = split_table_row(row_stripped)
            if is_separator_row(cells):
                # Only the row immediately following the header is the separator; a later
                # one is a malformed data row, not a new table.
                if separator_index is None and not row_indices:
                    separator_index = index
                index += 1
                continue
            row_indices.append(index)
            index += 1

        yield TableBlock(
            header_index=header_index,
            separator_index=separator_index,
            first_row_index=row_indices[0] if row_indices else None,
            last_row_index=row_indices[-1] if row_indices else None,
            headers=headers,
            preceding_heading=heading,
            line_ending=line_ending,
            row_indices=row_indices,
        )


def scan_control_characters(text: str):
    """Yield (line_number, description) for control bytes that corrupt a coordination file.

    Two kinds, both seen in HANDOFFS.md after a Windows path was passed through an
    escape-interpreting writer:
      - a C0 control byte such as the 0x07 that `\\a` in `\\assets` became;
      - a bare CR inside a line, which `\\r` in `\\references` became. That one splits the
        line for every reader, shifting every following line number by one -- so every
        diagnostic and every INDEX.md jump target after it points at the wrong row.
    """
    for number, line in enumerate(text.split("\n"), start=1):
        body = line[:-1] if line.endswith("\r") else line
        if "\r" in body:
            yield number, "bare carriage return inside a line (shifts every later line number)"
        for match in _CONTROL_BYTES.finditer(body):
            yield number, f"control byte 0x{ord(match.group()):02x}"
