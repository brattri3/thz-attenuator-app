"""
coordlib - shared, stdlib-only core for the coordination tools.

Ships with the CORE scaffold. build_index.py and kpi_git.py depend on it; the optional
Streamlit dashboard depends on it too. The dependency runs one way only:

    coordlib  <--  build_index.py, kpi_git.py         (core, stdlib only)
    coordlib  <--  dashboard/parser.py                 (optional add-on, still stdlib)
    coordlib  <--  dashboard/badges.py  <--  components.py, dashboard.py   (needs streamlit)

coordlib must never import from dashboard/, and nothing outside dashboard/ may import
streamlit. That is enforced by test_core_tools_do_not_import_dashboard_or_streamlit, not
merely documented -- a rule nobody checks is the failure mode the skill's references/rationale.md is
about.

**This namespace carries the promised surface only.** It used to re-export every name from all
four modules into one flat namespace, which meant `from coordlib import split_table_row` and
`from coordlib import classify_item_status` looked identical at the call site while only one of
them was promised -- an outside reader had no way to tell which of their imports were
load-bearing without opening each module. The first external consumer reported that (issue #50).

So what is re-exported here is exactly what an extension may rely on. Everything else is reached
through its module -- `from coordlib import md_table`, `coordlib.paths.find_repo_root` -- which
is how the tools in this repository already import it, and which makes reliance on an internal
visible in a diff.
"""

# Promised: the code strings, Diagnostic's five fields, and UNSAFE_TO_WRITE_CODES.
from .diagnostics import (
    CONTROL_CHARACTER,
    COLUMN_COUNT_MISMATCH,
    DUPLICATE_ID,
    Diagnostic,
    DiagnosticList,
    MALFORMED_STATUS_LINE,
    MISSING_STATUS,
    MISSING_TYPE_COLUMN,
    NO_HEADER_ROW,
    UNKNOWN_STATUS,
    UNKNOWN_TABLE_SCHEMA,
    UNKNOWN_TYPE,
    UNSAFE_TO_WRITE_CODES,
    record,
)

# Promised: the three functions a consumer cannot read a table without. The rest of md_table --
# SEP_RE, TableBlock's field layout, format_row, escape_pipe, detect_line_ending,
# is_separator_row, scan_control_characters -- is internal and is NOT re-exported here.
from .md_table import (
    iter_table_blocks,
    split_table_row,
    unescape_pipe,
)

# Promised: the vocabularies, the classifiers, and header/signature resolution.
from .schema import (
    BOARD_STATUSES,
    BOARD_TABLE_SIGNATURE,
    HANDOFF_STATUSES,
    MISSING,
    QUESTION_STATUSES,
    QUESTION_TYPES,
    QUESTIONS_TABLE_SIGNATURE,
    classify_item_status,
    classify_question_type,
    classify_role_status,
    is_placeholder_text,
    matches_signature,
    normalise,
    resolve_column,
    resolve_headers,
    split_role_status_date,
    strip_decoration,
)

# Deliberately NOT re-exported: coordlib.paths, coordlib.ownership, coordlib.manifest, and
# md_table's internals. They are reached as `coordlib.<module>.<name>`, and this repository's
# own tools already import them that way.

__all__ = [
    # diagnostics -- promised
    "Diagnostic",
    "DiagnosticList",
    "record",
    "UNSAFE_TO_WRITE_CODES",
    "UNKNOWN_TABLE_SCHEMA",
    "NO_HEADER_ROW",
    "UNKNOWN_STATUS",
    "UNKNOWN_TYPE",
    "MISSING_STATUS",
    "MISSING_TYPE_COLUMN",
    "MALFORMED_STATUS_LINE",
    "COLUMN_COUNT_MISMATCH",
    "CONTROL_CHARACTER",
    "DUPLICATE_ID",
    # md_table -- promised (three of them; the module itself is PARTIAL)
    "split_table_row",
    "unescape_pipe",
    "iter_table_blocks",
    # schema -- promised
    "HANDOFF_STATUSES",
    "QUESTION_STATUSES",
    "QUESTION_TYPES",
    "BOARD_STATUSES",
    "MISSING",
    "normalise",
    "strip_decoration",
    "is_placeholder_text",
    "classify_item_status",
    "classify_role_status",
    "classify_question_type",
    "split_role_status_date",
    "resolve_column",
    "resolve_headers",
    "matches_signature",
    "QUESTIONS_TABLE_SIGNATURE",
    "BOARD_TABLE_SIGNATURE",
]
