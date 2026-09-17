"""
diagnostics.py - the channel through which the coordination tools say "I did not understand
this", instead of silently reporting zero.

The failure this exists to prevent is documented in the skill's references/rationale.md: a parser that
matches English status words returns is_open=False for a Russian `открыт` and the operator
sees "Open Questions: 0" with no indication anything went wrong. Numbers that are quietly
wrong are worse than an error, because they get believed.

Nothing here translates anything. A Diagnostic means "this file used a schema or a vocabulary
the tools do not recognise" -- the fix is to correct the file, not for the tool to guess.

STABILITY: PROMISED. The code strings, `Diagnostic`'s five fields and `UNSAFE_TO_WRITE_CODES`
are what an external consumer keys on -- breaking them is a breaking change. See the skill's
references/extension-contract.md.
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Diagnostic codes. Grouped by what a reader would do about them.
#
# Schema-level: the tool could not locate the data at all.
UNKNOWN_TABLE_SCHEMA = "unknown-table-schema"
NO_HEADER_ROW = "no-header-row"
COLUMN_COUNT_MISMATCH = "column-count-mismatch"
# Value-level: the data was found, but a field used a word outside the documented vocabulary.
UNKNOWN_STATUS = "unknown-status"
UNKNOWN_TYPE = "unknown-type"
#: The questions table parsed fine and simply has no Type column. Harmless on its own -- the
#: table signature deliberately requires only {id, question, status} -- but it means the
#: blocking/non-blocking distinction cannot be computed for any row in that table, and the
#: one CI gate this scaffold ships for a halted session reads it.
MISSING_TYPE_COLUMN = "missing-type-column"
MISSING_STATUS = "missing-status"
MALFORMED_STATUS_LINE = "malformed-status-line"
# File-level: the bytes themselves are damaged.
CONTROL_CHARACTER = "control-character"
DUPLICATE_ID = "duplicate-id"

#: Codes that mean the tool could not reliably locate rows in a file. A file carrying any of
#: these must be treated as read-only by anything that writes: a tool that cannot read a file
#: must not write to it.
#:
#: Nothing in this repository calls it. The only caller was the dashboard's write path,
#: deleted in #40 once field data showed it had never been used, and that leaves this looking
#: exactly like the dead code the deconstruction has been removing all week. It is kept for
#: one reason that is not a promise about the future: this rule is the fourth of the four
#: conditions `docs/ru/CONCEPT.md` §6.6 set for writing into the journals, and #43 specifies
#: it as an obligation on external writers, which is where the caller now lives. If #43 is
#: closed without adopting it, delete this and `blocks_writes` with it.
UNSAFE_TO_WRITE_CODES = frozenset({UNKNOWN_TABLE_SCHEMA, NO_HEADER_ROW, CONTROL_CHARACTER})


@dataclass(frozen=True)
class Diagnostic:
    """One thing the tools could not interpret.

    `observed` carries the raw text that was not recognised, so the message can name it
    verbatim rather than making the reader guess which cell was meant.
    """

    code: str
    path: str
    line: Optional[int] = None
    detail: str = ""
    observed: str = ""

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line is not None else self.path
        seen = f" (found: {self.observed!r})" if self.observed else ""
        return f"{where} {self.code}: {self.detail}{seen}"


@dataclass
class DiagnosticList:
    """A collecting sink, so callers can pass `diagnostics=` without pre-building a list.

    A plain list works everywhere this is accepted; this only adds the query helpers.
    """

    items: List[Diagnostic] = field(default_factory=list)

    def append(self, diagnostic: Diagnostic) -> None:
        self.items.append(diagnostic)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def codes(self):
        return {d.code for d in self.items}

    def blocks_writes(self) -> bool:
        """True when any diagnostic means this file's rows could not be located."""
        return bool(self.codes() & UNSAFE_TO_WRITE_CODES)


def record(
    diagnostics,
    code: str,
    path,
    line: Optional[int] = None,
    detail: str = "",
    observed: str = "",
) -> None:
    """Append a Diagnostic if a sink was supplied; a no-op otherwise.

    Every parser takes `diagnostics=None` by default so existing callers keep working
    unchanged, which is why this tolerates None rather than requiring a sink.
    """
    if diagnostics is None:
        return
    diagnostics.append(
        Diagnostic(code=code, path=str(path), line=line, detail=detail, observed=observed)
    )
