"""
components.py - Streamlit KPI bar for the Multi-Agent Coordination Dashboard.

Badge rendering moved to badges.py, which is stdlib-only. This file keeps its own copy of
the status vocabulary and disagreed with parser.py about what it meant; there is now one
rule, in coordlib.schema, that both go through.
"""

from typing import Any, Dict, List
import streamlit as st

try:
    from .badges import partition_questions, partition_roles
    from .badges import render_role_badge, render_status_badge, render_type_badge  # noqa: F401
except (ImportError, ValueError):
    from badges import partition_questions, partition_roles
    from badges import render_role_badge, render_status_badge, render_type_badge  # noqa: F401


def render_kpi_bar(
    board_data: List[Dict[str, Any]],
    questions_data: List[Dict[str, Any]],
    handoffs_data: List[Dict[str, Any]],
    worktrees_data: List[Dict[str, Any]]
) -> None:
    """
    Renders top-level KPI metric cards:
      1. Roles Active / Total
      2. Open Questions (highlighting blocking, and unclassified separately)
      3. Active Handoffs (open & taken)
      4. Active Git Worktrees

    Unclassified items get their own count rather than being folded into either side. On a
    journal the tools could not read, "Open Questions: 0" was true of what they understood
    and false about the project - which is the failure issue #6 reported.
    """
    total_roles = len(board_data)
    active_list, _other_roles, unclassified_roles = partition_roles(board_data)
    active_roles = len(active_list)

    open_questions, _closed, unclassified_questions = partition_questions(questions_data)
    blocking_questions = [q for q in open_questions if q.get("is_blocking") is True]

    live_handoffs = [h for h in handoffs_data if not h.get("is_template", False)]
    active_handoffs = [h for h in live_handoffs if h.get("is_open") is True]
    unclassified_handoffs = [h for h in live_handoffs if h.get("is_open") is None]
    taken_handoffs = [h for h in active_handoffs if h.get("status") == "taken"]

    active_worktrees = len(worktrees_data)
    unclassified_total = len(unclassified_questions) + len(unclassified_handoffs) + len(unclassified_roles)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="🧑‍💻 Roles Active",
            value=f"{active_roles} / {total_roles}",
            delta=(
                f"{len(unclassified_roles)} unclassified" if unclassified_roles
                else (f"{total_roles - active_roles} idle/stale" if total_roles > active_roles
                      else "All active")
            ),
            delta_color="inverse" if unclassified_roles else "off",
        )

    with col2:
        st.metric(
            label="❓ Open Questions",
            value=len(open_questions),
            delta=(
                f"{len(blocking_questions)} blocking 🚨" if blocking_questions
                else (f"{len(unclassified_questions)} unclassified" if unclassified_questions
                      else "0 blocking")
            ),
            delta_color="inverse" if (blocking_questions or unclassified_questions) else "off",
        )

    with col3:
        st.metric(
            label="🤝 Active Handoffs",
            value=len(active_handoffs),
            delta=(
                f"{len(taken_handoffs)} taken" if taken_handoffs
                else (f"{len(unclassified_handoffs)} unclassified" if unclassified_handoffs
                      else "None taken")
            ),
            delta_color="inverse" if unclassified_handoffs else "off",
        )

    with col4:
        st.metric(
            label="🌳 Git Worktrees",
            value=active_worktrees,
            delta="Isolated branches",
            delta_color="off",
        )

    if unclassified_total:
        st.warning(
            f"⚠ {unclassified_total} item(s) use a status outside the documented vocabulary "
            "and are counted in NEITHER the open nor the closed totals above. See the "
            "diagnostics panel; the tools do not guess at a translation."
        )
