"""
Multi-Agent Coordination Interactive Dashboard Package.
Provides line-preserving markdown parsers, surgical table/block mutators, git isolation service, and Streamlit components.
"""

from .parser import (
    split_table_row,
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_index,
    parse_worktrees
)
from .mutator import (
    escape_pipe,
    format_table_row,
    mutate_table_cell,
    mutate_handoff_status,
    append_question,
    append_handoff
)
from .git_service import GitService
from .components import (
    render_kpi_bar,
    render_status_badge,
    render_type_badge,
    render_role_badge
)

__all__ = [
    "split_table_row",
    "parse_board",
    "parse_questions",
    "parse_handoffs",
    "parse_index",
    "parse_worktrees",
    "escape_pipe",
    "format_table_row",
    "mutate_table_cell",
    "mutate_handoff_status",
    "append_question",
    "append_handoff",
    "GitService",
    "render_kpi_bar",
    "render_status_badge",
    "render_type_badge",
    "render_role_badge"
]
