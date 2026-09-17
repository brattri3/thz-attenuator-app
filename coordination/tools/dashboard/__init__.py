"""
Multi-Agent Coordination Dashboard package: line-preserving markdown parsers for a
read-only view of the journals.

It reads; it does not write. The write path this package used to carry -- surgical table
mutators, a write gate, and a git commit service -- was removed once field data showed it
had never been used: across three projects with the scaffold installed, two of them with
this package on disk, 47 journal commits were made and none of them through the browser.
The journals are append-only markdown in git, which every editor and `git commit` already
handle, and this was the only component that mutated the record the whole scaffold calls
its arbiter. See `docs/ru/CONCEPT.md` §6.5.

Deliberately does NOT re-export .components or .dashboard: both import streamlit at module
scope, so re-exporting them here would make `import dashboard.anything` require streamlit --
including the parsers, which are pure stdlib. Import the UI explicitly instead:

    from dashboard.components import render_kpi_bar
"""

from .parser import (
    split_table_row,
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_index,
    parse_worktrees
)

__all__ = [
    "split_table_row",
    "parse_board",
    "parse_questions",
    "parse_handoffs",
    "parse_index",
    "parse_worktrees",
]
