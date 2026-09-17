"""
dashboard.py - Streamlit read-only view of the coordination journals.

Shows the Roles Board, Decision Queue, Cross-Role Handoffs, Git Worktrees and the Backlog
Index. It reads; it writes nothing, and it runs no git command that changes anything.

Editing the journals is git's job, and git is what every role already uses: the files are
append-only markdown, and `git log` is the record the whole scaffold calls its arbiter.
This module used to carry a browser-side editor for them -- surgical table mutators, a
write gate, a diff-and-confirm step and an isolated commit engine, about a thousand lines.
Field data retired it: across three projects with the scaffold installed, two with this
package on disk, 47 commits touched the journals and not one came from here. Both owners
said they had never launched it; one did not know it existed.

To regenerate INDEX.md, run the dependency-free generator:

    python coordination/tools/build_index.py --out coordination/INDEX.md
"""

from pathlib import Path
import sys
from typing import Any, List, Optional
import streamlit as st

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from coordlib.paths import find_repo_root  # noqa: E402

# Add parent directories to sys.path to allow running standalone or as package
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from .parser import (
        parse_board,
        parse_questions,
        parse_handoffs,
        parse_worktrees
    )
    from .components import render_kpi_bar
    from .badges import render_status_badge, render_type_badge, render_role_badge
except (ImportError, ValueError):
    from parser import (
        parse_board,
        parse_questions,
        parse_handoffs,
        parse_worktrees
    )
    from components import render_kpi_bar
    from badges import render_status_badge, render_type_badge, render_role_badge


def discover_coordination_dir(start_path: Optional[Path] = None) -> Path:
    """Discovers the coordination folder in the repository."""
    start = start_path or Path.cwd()
    repo_root = find_repo_root(start)
    if repo_root:
        candidate_assets = repo_root / "assets" / "coordination"
        if candidate_assets.exists() and (candidate_assets / "BOARD.md").exists():
            return candidate_assets
        candidate_coord = repo_root / "coordination"
        if candidate_coord.exists() and (candidate_coord / "BOARD.md").exists():
            return candidate_coord

    # Search local parents
    curr = (start if start.is_dir() else start.parent).resolve()
    for p in [curr] + list(curr.parents):
        if (p / "BOARD.md").exists():
            return p
        if (p / "assets" / "coordination" / "BOARD.md").exists():
            return p / "assets" / "coordination"
        if (p / "coordination" / "BOARD.md").exists():
            return p / "coordination"

    # Default fallback
    return curr


def render_diagnostics(diagnostics) -> None:
    """Surface everything the parsers could not interpret, above the numbers.

    A count that silently excludes rows the tool failed to read is worse than an error,
    because it gets believed.
    """
    if not diagnostics:
        return
    st.error(
        f"⚠ {len(diagnostics)} item(s) in the coordination files could not be interpreted. "
        "They are shown as unclassified, NOT as resolved. Fix them in the journal itself; "
        "the counts above stay wrong until you do."
    )
    with st.expander(f"Schema diagnostics ({len(diagnostics)})"):
        for item in diagnostics:
            st.text(str(item))


def main():
    st.set_page_config(
        page_title="Multi-Agent Coordination Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 1. Settings, in the MAIN column.
    #
    # These lived in st.sidebar, which does not render at all under some Streamlit versions
    # (verified by the issue reporter on 1.62). An unreachable control is strictly worse
    # than a visible one. Nothing here is navigation, so nothing is lost by moving it.
    st.title("🤖 Multi-Agent Coordination")
    st.caption("🔒 Read-only. Edit the journals with git; this view never writes.")

    default_coord_dir = discover_coordination_dir()
    with st.expander("⚙️ Settings", expanded=False):
        coord_path_str = st.text_input(
            "📁 Coordination directory",
            value=str(default_coord_dir),
            help="Path containing BOARD.md, QUESTIONS.md, HANDOFFS.md",
        )
        coord_dir = Path(coord_path_str).resolve()
        repo_root = find_repo_root(coord_dir)

        if repo_root:
            st.success(f"Git root: `{repo_root.name}`")
        else:
            st.warning("No git repository detected")

        if st.button("🔄 Refresh data"):
            st.rerun()

    # 2. File Paths
    board_file = coord_dir / "BOARD.md"
    questions_file = coord_dir / "QUESTIONS.md"
    handoffs_file = coord_dir / "HANDOFFS.md"
    index_file = coord_dir / "INDEX.md"

    # 3. Parse Active Coordination State
    diagnostics: List[Any] = []
    board_data = parse_board(board_file, diagnostics=diagnostics)
    questions_data = parse_questions(questions_file, diagnostics=diagnostics)
    handoffs_data = parse_handoffs(handoffs_file, diagnostics=diagnostics)
    render_diagnostics(diagnostics)
    worktrees_data = parse_worktrees(repo_root)

    # 4. Top Header & KPI Bar
    st.title("🎛️ Multi-Agent Coordination Dashboard")
    st.caption(f"Active Workspace: `{coord_dir}`")
    render_kpi_bar(board_data, questions_data, handoffs_data, worktrees_data)
    st.markdown("---")

    # 5. Main 5 Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Roles Board",
        "❓ Decision Queue",
        "🤝 Handoffs",
        "🌳 Git Worktrees",
        "📑 Backlog Index"
    ])

    # -------------------------------------------------------------------------
    # TAB 1: Roles Board
    # -------------------------------------------------------------------------
    with tab1:
        st.subheader("📋 Roles Board (`BOARD.md`)")
        st.write("Live operational status for each agent role in the project.")

        if not board_data:
            st.info(f"No active roles found in `{board_file.name}`.")
        else:
            cols_per_row = 3
            for i in range(0, len(board_data), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, role_info in enumerate(board_data[i : i + cols_per_row]):
                    with cols[j]:
                        with st.container(border=True):
                            badge = render_role_badge(role_info["status"])
                            st.markdown(f"### `{role_info['role']}` {badge}")
                            st.caption(f"📅 Last updated: **{role_info['date'] or 'N/A'}**")
                            st.markdown(f"**Summary:** {role_info['summary'] or '—'}")

    # -------------------------------------------------------------------------
    # TAB 2: Decision Queue / Questions
    # -------------------------------------------------------------------------
    with tab2:
        st.subheader("❓ Decision Queue & Owner Decisions (`QUESTIONS.md`)")
        st.write("Append-only durable decision record across all agent sessions.")

        # Filters
        f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
        with f_col1:
            status_filter = st.selectbox("Filter Status", options=["All", "Open / In Progress", "Resolved / Closed"])
        with f_col2:
            type_filter = st.selectbox("Filter Type", options=["All", "Blocking Only", "Non-blocking Only"])
        with f_col3:
            search_query = st.text_input("🔍 Search Questions", placeholder="Keywords in question or answer...")

        # Apply filtering
        filtered_q = []
        for q in questions_data:
            if status_filter == "Open / In Progress" and not q.get("is_open"):
                continue
            if status_filter == "Resolved / Closed" and q.get("is_open"):
                continue
            if type_filter == "Blocking Only" and not q.get("is_blocking"):
                continue
            if type_filter == "Non-blocking Only" and q.get("is_blocking"):
                continue
            if search_query:
                sq = search_query.lower()
                if sq not in q["question"].lower() and sq not in q["answer"].lower() and sq not in q["id"].lower():
                    continue
            filtered_q.append(q)

        st.caption(f"Showing **{len(filtered_q)}** of **{len(questions_data)}** questions")

        if not filtered_q:
            st.info("No questions matching the selected filter.")
        else:
            for q in filtered_q:
                with st.container(border=True):
                    q_header_col1, q_header_col2, q_header_col3 = st.columns([2, 1, 1])
                    with q_header_col1:
                        st.markdown(f"#### `{q['id']}`: {q['question']}")
                    with q_header_col2:
                        st.markdown(f"{render_type_badge(q['type'])}")
                    with q_header_col3:
                        st.markdown(f"{render_status_badge(q['status'])}")

                    if q["answer"] and q["answer"] != "—":
                        st.markdown(f"**Owner's Answer:** `{q['answer']}`")

    # -------------------------------------------------------------------------
    # TAB 3: Handoffs
    # -------------------------------------------------------------------------
    with tab3:
        st.subheader("🤝 Cross-Role Handoffs (`HANDOFFS.md`)")
        st.write("Cross-layer delegation requests across agent zone boundaries.")

        active_handoffs = [h for h in handoffs_data if h.get("is_open") and not h.get("is_template")]
        completed_handoffs = [h for h in handoffs_data if not h.get("is_open") and not h.get("is_template")]

        h_col1, h_col2 = st.columns(2)

        with h_col1:
            st.markdown(f"### 🚀 Active Requests ({len(active_handoffs)})")
            if not active_handoffs:
                st.info("No active handoff requests.")
            for h in active_handoffs:
                with st.container(border=True):
                    st.markdown(f"**[{h['date']}]** FROM `{h['from_role']}` ➔ TO `{h['to_role']}`")
                    st.markdown(f"#### {h['title']}")
                    st.markdown(f"**Status:** {render_status_badge(h['status'])}")
                    st.markdown(f"- **What:** {h['what']}")
                    st.markdown(f"- **Context:** {h['context']}")
                    st.markdown(f"- **Done when:** {h['done_when']}")

        with h_col2:
            st.markdown(f"### ✅ Completed Handoffs ({len(completed_handoffs)})")
            if not completed_handoffs:
                st.info("No completed handoffs yet.")
            for h in completed_handoffs:
                with st.container(border=True):
                    st.markdown(f"**[{h['date']}]** FROM `{h['from_role']}` ➔ TO `{h['to_role']}`")
                    st.markdown(f"#### {h['title']}")
                    st.markdown(f"**Status:** {render_status_badge(h['status'])}")
                    st.caption(f"Done criterion: {h['done_when']}")

    # -------------------------------------------------------------------------
    # TAB 4: Git Worktrees
    # -------------------------------------------------------------------------
    with tab4:
        st.subheader("🌳 Active Git Worktrees (`git worktree list`)")
        st.write("Isolated per-role git working trees enabling concurrent agent execution without file contention.")

        if not worktrees_data:
            st.info("No active git worktrees found.")
        else:
            for wt in worktrees_data:
                with st.container(border=True):
                    wt_c1, wt_c2, wt_c3 = st.columns([3, 2, 1])
                    with wt_c1:
                        st.markdown(f"**Path:** `{wt['path']}`")
                        if wt.get("is_main"):
                            st.caption("⭐️ **Primary Repository Root**")
                    with wt_c2:
                        # .get(): a bare worktree's porcelain block carries no branch or
                        # HEAD line, and subscripting raised KeyError on it.
                        st.markdown(f"**Branch:** `{wt.get('branch') or '(detached)'}`")
                        head = wt.get("head") or ""
                        st.caption(f"HEAD: `{head[:7] or '-'}`")
                    with wt_c3:
                        if wt.get("role"):
                            st.markdown(f"Role: `{wt['role']}`")
                        if wt.get("prunable"):
                            st.warning("Prunable")

        st.markdown("---")
        st.caption(
            "To add one: `git worktree add ../<repo>-<ID> session/<ID>` "
            "(`CHARTER.md §5`). One command, and it is the same one the charter documents."
        )

    # -------------------------------------------------------------------------
    # TAB 5: Backlog & Index
    # -------------------------------------------------------------------------
    with tab5:
        st.subheader("📑 Backlog & Index (`INDEX.md`)")
        st.write("Aggregated index of open and closed items across all journals.")

        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                index_content = f.read()
            st.markdown(index_content)
        else:
            st.info(
                "INDEX.md not generated yet. Run "
                "`python coordination/tools/build_index.py --out coordination/INDEX.md` "
                "— it needs no dependencies."
            )


if __name__ == "__main__":
    main()
