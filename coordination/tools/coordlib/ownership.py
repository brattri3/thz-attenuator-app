"""ownership.py - read OWNERSHIP.md's zone table into matchable rules.

Two very different consumers need the same answer to "who owns this path":

  * `tools/ownership.py` renders `.github/CODEOWNERS` from it, so the review routing and
    the written matrix cannot drift apart.
  * `.claude/hooks/check-path-ownership.py` turns it into an actual write barrier.

They must agree exactly. A hook that blocks a write the CODEOWNERS file says is fine -- or
the reverse -- is worse than either alone, so the matching lives here once.

Template rows are skipped rather than obeyed. `OWNERSHIP.md` ships with example rows whose
owner is `\\<ID\\>`; treating those as real would hand every path to a role that does not
exist.

STABILITY: INTERNAL. Read the matrix through this module, not around it. Nothing outside this package should depend on the
names or shapes here; they may change without notice. See the skill's
references/extension-contract.md for what IS promised.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from . import diagnostics as diag
from . import schema
from .md_table import iter_table_blocks, scan_control_characters, split_table_row

#: Italic parenthetical commentary, e.g. ``*(fill in per role, e.g.)*``. Stripped before
#: anything else so a leading aside does not hide the globs behind it.
_ITALIC_ASIDE = re.compile(r"\*\([^)]*\)\*")

#: The LEADING run of backticked code spans, separated only by commas or whitespace.
#: Anything after the first prose word is commentary, and commentary contains backticks of
#: its own: the shipped matrix (in the skill) writes
#: ``(if you keep one -- see `references/rationale.md` in this skill)``
#: and ``(rules for the directory: see the `archive/README.md` template)``. Collecting every
#: code span in the cell turns both of those cross-references into owned zones.
_LEADING_SPANS = re.compile(r"^(?:\s*`[^`]+`\s*(?:,|and\b)?\s*)+")
_CODE_SPAN = re.compile(r"`([^`]+)`")

#: A `<...>` placeholder anywhere in a cell, escaped or not.
_INLINE_PLACEHOLDER = re.compile(r"\\?<[^>]*\\?>")


@dataclass(frozen=True)
class Zone:
    """One `| Path | Owner | Others |` row, reduced to something matchable."""

    pattern: str
    owner: str
    others: str = ""
    line: Optional[int] = None

    @property
    def specificity(self):
        """Sort key for "most specific rule wins".

        A pattern with more concrete (non-wildcard) segments beats one with fewer, so
        `coordination/roles/**` wins over `coordination/**`. Length breaks ties.
        """
        segments = [s for s in self.pattern.split("/") if s not in ("**", "*")]
        return (len(segments), len(self.pattern))


def _glob_to_regex(pattern: str) -> "re.Pattern":
    """Translate a path glob to a regex with real `**` semantics.

    `fnmatch` is not usable here: its `*` matches `/` too, so `coordination/*` would claim
    `coordination/roles/ORCH.md` and every nested file with it. Python 3.13 has
    `glob.translate`, but the declared floor for this scaffold is 3.9.
    """
    if pattern.endswith("/"):
        pattern = pattern + "**"
    out = ["^"]
    i = 0
    length = len(pattern)
    while i < length:
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                i += 2
                # `foo/**` matches foo itself as well as everything under it.
                if pattern.startswith("/", i):
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "/":
            # A trailing `/**` claims the directory itself as well as its contents, so the
            # separator is part of the optional tail: `src/core/**` must match `src/core`.
            if pattern[i:] == "/**":
                out.append("(?:/.*)?")
                i = length
                continue
            out.append("/")
        else:
            out.append(re.escape(char))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def strip_leading_dot_slash(path: str) -> str:
    """Remove a leading `./`, and nothing else.

    NOT `lstrip("./")`, which strips leading `.` and `/` CHARACTERS rather than the prefix
    and so turns `.github/workflows/ci.yml` into `github/workflows/ci.yml`. A zone written
    `.github/**` then matched nothing at all: the ownership hook silently permitted writes
    to it and the generated CODEOWNERS carried a rule covering no files. Dotted top-level
    directories are ordinary things to own, so this is not an exotic case.
    """
    while path.startswith("./"):
        path = path[2:]
    return path


def matches(pattern: str, rel_path: str) -> bool:
    """True when `rel_path` (repo-relative, `/`-separated) falls under `pattern`."""
    rel_path = strip_leading_dot_slash(rel_path.replace("\\", "/"))
    pattern = strip_leading_dot_slash(pattern.replace("\\", "/")).lstrip("/")
    if _glob_to_regex(pattern).match(rel_path):
        return True
    # A bare directory name owns its contents even when written without a trailing glob.
    if "*" not in pattern and "?" not in pattern:
        return rel_path == pattern or rel_path.startswith(pattern.rstrip("/") + "/")
    return False


def _clean_owner(cell: str) -> str:
    """Reduce an Owner cell to a bare role id, or "" when it is not one.

    The shipped matrix writes owners as `ORCH`, as `B`, and as prose
    (``**that role, `<ID>`, itself**``). Only the bare-id form is actionable; the rest is
    documentation and must not be turned into an enforceable rule.
    """
    text = schema.strip_decoration(cell).strip()
    if not text or _INLINE_PLACEHOLDER.search(text):
        return ""
    if schema.is_placeholder_text(text):
        return ""
    # Anything with punctuation or spaces is prose, not an id.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", text):
        return ""
    return text


def _patterns_in(cell: str) -> List[str]:
    """The globs a Path cell actually claims, placeholders and commentary dropped."""
    text = _ITALIC_ASIDE.sub(" ", cell).strip()
    head = _LEADING_SPANS.match(text)
    if head is None:
        return []
    found = []
    for span in _CODE_SPAN.findall(head.group(0)):
        candidate = span.strip()
        if not candidate or _INLINE_PLACEHOLDER.search(candidate):
            continue
        found.append(candidate.replace("\\", "/").lstrip("/"))
    return found


def parse_ownership(file_path, *, diagnostics=None) -> List[Zone]:
    """Read every actionable zone from an OWNERSHIP.md.

    Rows whose owner or path is still a template placeholder are skipped silently -- the
    shipped template is meant to ship with them, so reporting each one as a defect would
    make a clean scaffold look broken.
    """
    path = Path(file_path)
    if not path.is_file():
        return []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        text = handle.read()

    # The scanner yields (line number, description). This loop used to destructure that as
    # (offset, char) and then recompute the line by counting newlines up to the "offset" --
    # so a control byte on line 40 was reported at roughly line 2, and `observed`, which the
    # Diagnostic docstring defines as "the raw text that was not recognised", carried the
    # description string instead of anything from the file. There is no raw text to name for
    # a control byte, so `observed` is left empty and the description carries the meaning.
    for line_number, description in scan_control_characters(text):
        diag.record(
            diagnostics,
            diag.CONTROL_CHARACTER,
            path,
            line=line_number,
            detail=description,
        )

    lines = text.splitlines()
    zones: List[Zone] = []
    seen_table = False

    for block in iter_table_blocks(lines):
        resolved = schema.resolve_headers(block.headers)
        if not schema.matches_signature(resolved, schema.OWNERSHIP_TABLE_SIGNATURE):
            continue
        seen_table = True
        path_col = resolved["path"]
        owner_col = resolved["owner"]
        others_col = resolved.get("others")

        for index in block.row_indices:
            cells = split_table_row(lines[index])
            if len(cells) <= max(path_col, owner_col):
                diag.record(
                    diagnostics,
                    diag.COLUMN_COUNT_MISMATCH,
                    path,
                    line=index + 1,
                    detail="ownership row has fewer cells than its header",
                    observed=lines[index].strip(),
                )
                continue
            owner = _clean_owner(cells[owner_col])
            if not owner:
                continue
            others = cells[others_col] if others_col is not None and others_col < len(cells) else ""
            for pattern in _patterns_in(cells[path_col]):
                zones.append(
                    Zone(pattern=pattern, owner=owner, others=others.strip(), line=index + 1)
                )

    if not seen_table:
        diag.record(
            diagnostics,
            diag.UNKNOWN_TABLE_SCHEMA,
            path,
            detail="no table with both a Path and an Owner column",
            observed="",
        )
    return zones


def owner_of(rel_path: str, zones: Sequence[Zone]) -> Optional[Zone]:
    """The most specific zone claiming `rel_path`, or None when nothing claims it.

    Unclaimed is not the same as forbidden: OWNERSHIP.md's own rule for unlisted paths is
    "add a row", not "nobody may write here". Callers decide what to do with None.
    """
    candidates = [z for z in zones if matches(z.pattern, rel_path)]
    if not candidates:
        return None
    return max(candidates, key=lambda z: z.specificity)
