"""
components.py - Reusable Streamlit UI components and widget helpers for the Multi-Agent Coordination Dashboard.
Includes KPI metric bars, badge formatters, card renderers, and interactive action forms.
"""

from typing import Any, Callable, Dict, List, Optional
import streamlit as st


def render_kpi_bar(
    board_data: List[Dict[str, Any]],
    questions_data: List[Dict[str, Any]],
    handoffs_data: List[Dict[str, Any]],
    worktrees_data: List[Dict[str, Any]]
) -> None:
    """
    Renders top-level KPI metric cards:
      1. Roles Active / Total
      2. Open Questions (highlighting blocking)
      3. Active Handoffs (open & taken)
      4. Active Git Worktrees
    """
    total_roles = len(board_data)
    active_roles = sum(1 for r in board_data if r.get("status") == "active")

    open_questions = [q for q in questions_data if q.get("is_open", False)]
    blocking_questions = [q for q in open_questions if q.get("is_blocking", False)]

    active_handoffs = [h for h in handoffs_data if h.get("is_open", False) and not h.get("is_template", False)]
    taken_handoffs = [h for h in active_handoffs if h.get("status") == "taken"]

    active_worktrees = len(worktrees_data)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="🧑‍💻 Roles Active",
            value=f"{active_roles} / {total_roles}",
            delta=f"{total_roles - active_roles} idle/stale" if total_roles > active_roles else "All active",
            delta_color="normal" if active_roles > 0 else "off"
        )

    with col2:
        st.metric(
            label="❓ Open Questions",
            value=len(open_questions),
            delta=f"{len(blocking_questions)} blocking 🚨" if blocking_questions else "0 blocking",
            delta_color="inverse" if blocking_questions else "off"
        )

    with col3:
        st.metric(
            label="🤝 Active Handoffs",
            value=len(active_handoffs),
            delta=f"{len(taken_handoffs)} in progress" if taken_handoffs else "None taken",
            delta_color="normal" if taken_handoffs else "off"
        )

    with col4:
        st.metric(
            label="🌳 Git Worktrees",
            value=active_worktrees,
            delta="Isolated branches",
            delta_color="off"
        )


def render_status_badge(status: str) -> str:
    """Returns a visual badge emoji & formatted string for question/handoff statuses."""
    s = (status or "").strip().lower()
    if s in ("open", "открыт"):
        return "🔴 **OPEN**"
    elif s in ("taken", "in_progress", "in progress", "в работе"):
        return "🟡 **TAKEN**"
    elif s in ("done", "resolved", "решен", "готов"):
        return "🟢 **DONE**"
    elif s in ("closed", "закрыт"):
        return "⚪ **CLOSED**"
    elif s in ("missing",):
        return "⚠️ **MISSING**"
    return f"🔹 **{status.upper()}**"


def render_type_badge(q_type: str) -> str:
    """Returns a formatted badge for question urgency type."""
    t = (q_type or "").strip().lower()
    if "blocking" in t and "non" not in t:
        return "🚨 **Blocking**"
    return "ℹ️ **Non-blocking**"


def render_role_badge(status: str) -> str:
    """Returns a formatted badge for role activity status."""
    s = (status or "").strip().lower()
    if s == "active":
        return "🟢 Active"
    elif s == "idle":
        return "⚪ Idle"
    elif s == "stale":
        return "🟠 Stale"
    elif s == "blocked":
        return "🟣 Blocked"
    return f"🔹 {status}"
