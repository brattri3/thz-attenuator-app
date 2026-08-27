"""
dashboard.py - Interactive Streamlit Dashboard for Multi-Agent Coordination.
Visualizes and manages Roles Board, Decision Queue, Cross-Role Handoffs, Git Worktrees, and Backlog Index.
Safely mutates markdown journals preserving exact formatting and executes isolated git commits with trailers.
"""

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional
import streamlit as st

# Add parent directories to sys.path to allow running standalone or as package
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from .parser import (
        parse_board,
        parse_questions,
        parse_handoffs,
        parse_index,
        parse_worktrees
    )
    from .mutator import (
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
except (ImportError, ValueError):
    from parser import (
        parse_board,
        parse_questions,
        parse_handoffs,
        parse_index,
        parse_worktrees
    )
    from mutator import (
        mutate_table_cell,
        mutate_handoff_status,
        append_question,
        append_handoff
    )
    from git_service import GitService
    from components import (
        render_kpi_bar,
        render_status_badge,
        render_type_badge,
        render_role_badge
    )


def discover_coordination_dir(start_path: Optional[Path] = None) -> Path:
    """Discovers the coordination folder in the repository."""
    start = start_path or Path.cwd()
    repo_root = GitService.get_repo_root(start)
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


def rebuild_index_file(coord_dir: Path) -> Path:
    """Builds or rebuilds INDEX.md summarizing QUESTIONS.md and HANDOFFS.md."""
    q_file = coord_dir / "QUESTIONS.md"
    h_file = coord_dir / "HANDOFFS.md"
    index_file = coord_dir / "INDEX.md"

    q_rows = parse_questions(q_file)
    h_rows = parse_handoffs(h_file)

    q_open = [r for r in q_rows if r.get("is_open", False)]
    q_closed = [r for r in q_rows if not r.get("is_open", False)]
    h_open = [r for r in h_rows if r.get("is_open", False) and not r.get("is_template", False)]
    h_closed = [r for r in h_rows if not r.get("is_open", False) and not r.get("is_template", False)]

    lines: List[str] = [
        "# INDEX — open items in `QUESTIONS.md` and `HANDOFFS.md`\n",
        "Built by coordination dashboard — summarizes number/status/line to jump to.\n",
        f"## QUESTIONS.md — open ({len(q_open)} of {len(q_rows)})\n",
        "| # | Status | Role | Line | Summary |",
        "|---|---|---|---|---|"
    ]
    for q in q_open:
        text_summary = q["question"][:80] + "…" if len(q["question"]) > 80 else q["question"]
        lines.append(f"| `{q['id']}` | {q['status']} | {q.get('who', '')} | [line {q['line']}] | {text_summary} |")

    lines.append(f"\n## HANDOFFS.md — open or missing status ({len(h_open)} of {len(h_rows)})\n")
    lines.append("| # | Status | Line | Summary |")
    lines.append("|---|---|---|---|")
    for h in h_open:
        title_summary = h["title"][:80] + "…" if len(h["title"]) > 80 else h["title"]
        lines.append(f"| `{h['date']}` | {h['status']} | [line {h['start_line']}] | {title_summary} |")

    lines.append(f"\n<details><summary>QUESTIONS.md — closed ({len(q_closed)})</summary>\n")
    lines.append("| # | Status | Role | Line | Summary |")
    lines.append("|---|---|---|---|---|")
    for q in q_closed:
        text_summary = q["question"][:80] + "…" if len(q["question"]) > 80 else q["question"]
        lines.append(f"| `{q['id']}` | {q['status']} | {q.get('who', '')} | [line {q['line']}] | {text_summary} |")
    lines.append("\n</details>\n")

    lines.append(f"\n<details><summary>HANDOFFS.md — closed ({len(h_closed)})</summary>\n")
    lines.append("| # | Status | Line | Summary |")
    lines.append("|---|---|---|---|")
    for h in h_closed:
        title_summary = h["title"][:80] + "…" if len(h["title"]) > 80 else h["title"]
        lines.append(f"| `{h['date']}` | {h['status']} | [line {h['start_line']}] | {title_summary} |")
    lines.append("\n</details>\n")

    with open(index_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    return index_file


def handle_mutation_and_commit(
    success: bool,
    msg: str,
    target_file: Path,
    commit_msg: str,
    trailers: Dict[str, str],
    author_role: str,
    enable_git: bool,
    repo_root: Optional[Path]
) -> None:
    """Performs feedback notification, auto-commit, and UI rerun upon data mutation."""
    if not success:
        st.error(f"Mutation Failed: {msg}")
        return

    st.success(msg)

    if enable_git and repo_root:
        res = GitService.auto_commit_file(
            file_path=target_file,
            message=commit_msg,
            trailers=trailers,
            author_role=author_role,
            repo_root=repo_root
        )
        if res["status"] == "success":
            st.toast(f"Git Auto-Committed `{res['sha']}`: {commit_msg}", icon="✅")
        elif res["status"] == "noop":
            st.toast("No file diff detected for git commit.", icon="ℹ️")
        else:
            st.warning(f"Git Auto-Commit warning: {res.get('message') or res.get('stderr')}")

    st.rerun()


def main():
    st.set_page_config(
        page_title="Multi-Agent Coordination Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 1. Sidebar Configuration
    st.sidebar.title("🤖 Multi-Agent Coordination")
    st.sidebar.markdown("---")

    default_coord_dir = discover_coordination_dir()
    coord_path_str = st.sidebar.text_input(
        "📁 Coordination Directory",
        value=str(default_coord_dir),
        help="Path containing BOARD.md, QUESTIONS.md, HANDOFFS.md"
    )
    coord_dir = Path(coord_path_str).resolve()

    repo_root = GitService.get_repo_root(coord_dir)

    # Committer Role & Auto-Commit Options
    author_role = st.sidebar.selectbox(
        "🎭 Committer Role",
        options=["ORCH", "frontend", "physics", "qa_tester", "architect", "owner"],
        index=0,
        help="The active agent role recording the change"
    )

    enable_git = st.sidebar.checkbox(
        "⚡ Enable Git Auto-Commit",
        value=True,
        help="Automatically create isolated git commits with CHARTER trailers on state mutation"
    )

    if repo_root:
        st.sidebar.success(f"Git Root: `{repo_root.name}`")
    else:
        st.sidebar.warning("No Git repository detected")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption("Multi-Agent Coordination Tooling • Antigravity Ecosystem")

    # 2. File Paths
    board_file = coord_dir / "BOARD.md"
    questions_file = coord_dir / "QUESTIONS.md"
    handoffs_file = coord_dir / "HANDOFFS.md"
    index_file = coord_dir / "INDEX.md"

    # 3. Parse Active Coordination State
    board_data = parse_board(board_file)
    questions_data = parse_questions(questions_file)
    handoffs_data = parse_handoffs(handoffs_file)
    index_data = parse_index(index_file)
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
            # Display Roles Cards / Table
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

        st.markdown("---")
        with st.expander("✏️ Update Role Status & Summary", expanded=False):
            existing_roles = [r["role"] for r in board_data] if board_data else ["ORCH", "frontend", "physics", "qa_tester"]
            target_role = st.selectbox("Select Role to Update", options=existing_roles)
            new_role_status = st.selectbox("Status", options=["active", "idle", "stale", "blocked"], index=0)
            today_str = datetime.now().strftime("%Y-%m-%d")
            status_date_input = st.text_input("Status Date", value=today_str)
            new_summary = st.text_input("One-line Summary", placeholder="What this role is doing right now...")

            if st.button("💾 Update Role & Commit", key="btn_update_role"):
                combined_status = f"{new_role_status} ({status_date_input})"
                ok, msg = mutate_table_cell(
                    file_path=board_file,
                    key_col="Role",
                    key_val=target_role,
                    target_col="Status (date)",
                    new_val=combined_status
                )
                if ok and new_summary.strip():
                    mutate_table_cell(
                        file_path=board_file,
                        key_col="Role",
                        key_val=target_role,
                        target_col="One-line summary",
                        new_val=new_summary.strip()
                    )

                commit_subject = f"[{target_role}] update status: {new_role_status}"
                trailers = {
                    "Session": "dashboard",
                    "Reason": f"Updated role status in BOARD.md via dashboard"
                }
                handle_mutation_and_commit(
                    success=ok,
                    msg=msg,
                    target_file=board_file,
                    commit_msg=commit_subject,
                    trailers=trailers,
                    author_role=author_role,
                    enable_git=enable_git,
                    repo_root=repo_root
                )

        with st.expander("➕ Register New Role in BOARD.md", expanded=False):
            new_role_id = st.text_input("New Role ID (e.g. documentation, devops)")
            new_role_initial_status = st.selectbox("Initial Status", options=["active", "idle"], key="new_role_status")
            new_role_summary = st.text_input("Initial Summary", key="new_role_summary")
            if st.button("➕ Add Role to Board", key="btn_add_role"):
                if new_role_id.strip():
                    # Format new line and append to table
                    combined_status = f"{new_role_initial_status} ({datetime.now().strftime('%Y-%m-%d')})"
                    with open(board_file, "r", encoding="utf-8", newline="") as bf:
                        b_lines = bf.readlines()
                    b_ending = "\r\n" if any(l.endswith("\r\n") for l in b_lines) else "\n"
                    new_row = f"| {new_role_id.strip()} | {combined_status} | {new_role_summary.strip() or 'Initial registration'} |{b_ending}"
                    
                    # Insert before empty lines at bottom or append
                    b_lines.append(new_row)
                    with open(board_file, "w", encoding="utf-8", newline="") as bf:
                        bf.writelines(b_lines)
                    
                    commit_subject = f"[{author_role}] Register new role {new_role_id.strip()}"
                    trailers = {"Session": "dashboard", "Reason": "Registered role in BOARD.md"}
                    handle_mutation_and_commit(
                        success=True,
                        msg=f"Registered role {new_role_id.strip()}",
                        target_file=board_file,
                        commit_msg=commit_subject,
                        trailers=trailers,
                        author_role=author_role,
                        enable_git=enable_git,
                        repo_root=repo_root
                    )

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

                    # If open, provide resolution form
                    if q.get("is_open"):
                        with st.expander(f"💡 Resolve `{q['id']}`", expanded=False):
                            ans_text = st.text_area(f"Owner's Answer for {q['id']}", value=q["answer"] if q["answer"] != "—" else "")
                            q_new_status = st.selectbox(
                                f"Update Status for {q['id']}",
                                options=["resolved", "closed", "open"],
                                index=0
                            )
                            if st.button(f"💾 Record Decision for {q['id']}", key=f"btn_res_{q['id']}"):
                                ok1, m1 = mutate_table_cell(
                                    file_path=questions_file,
                                    key_col="#",
                                    key_val=q["id"],
                                    target_col="Status",
                                    new_val=q_new_status
                                )
                                if ans_text.strip():
                                    mutate_table_cell(
                                        file_path=questions_file,
                                        key_col="#",
                                        key_val=q["id"],
                                        target_col="Owner's answer",
                                        new_val=ans_text.strip()
                                    )
                                commit_subject = f"[{author_role}] Resolve {q['id']}: {q['question'][:50]}"
                                trailers = {
                                    "Session": "dashboard",
                                    "Reason": f"Recorded owner decision for {q['id']}"
                                }
                                handle_mutation_and_commit(
                                    success=ok1,
                                    msg=m1,
                                    target_file=questions_file,
                                    commit_msg=commit_subject,
                                    trailers=trailers,
                                    author_role=author_role,
                                    enable_git=enable_git,
                                    repo_root=repo_root
                                )

        st.markdown("---")
        with st.expander("➕ Post New Question to QUESTIONS.md", expanded=False):
            new_q_text = st.text_area("Question Text", placeholder="What decision is needed from the owner/orchestrator?")
            new_q_type = st.radio("Question Type", options=["blocking", "non-blocking"], horizontal=True)
            new_q_default = st.text_input("Default / Recommendation (if non-blocking)", placeholder="e.g. Default to Canvas2D")

            if st.button("➕ Submit Question & Commit", key="btn_post_q"):
                if new_q_text.strip():
                    ans_initial = f"Took default: {new_q_default.strip()}" if (new_q_type == "non-blocking" and new_q_default.strip()) else "—"
                    ok, msg = append_question(
                        file_path=questions_file,
                        question=new_q_text.strip(),
                        q_type=new_q_type,
                        status="open",
                        answer=ans_initial
                    )
                    commit_subject = f"[{author_role}] Post question: {new_q_text[:50]}"
                    trailers = {
                        "Session": "dashboard",
                        "Reason": "Submitted new coordination question via dashboard"
                    }
                    handle_mutation_and_commit(
                        success=ok,
                        msg=msg,
                        target_file=questions_file,
                        commit_msg=commit_subject,
                        trailers=trailers,
                        author_role=author_role,
                        enable_git=enable_git,
                        repo_root=repo_root
                    )

    # -------------------------------------------------------------------------
    # TAB 3: Handoffs
    # -------------------------------------------------------------------------
    with tab3:
        st.subheader("🤝 Cross-Role Handoffs (`HANDOFFS.md`)")
        st.write("Manage cross-layer delegation requests across agent zone boundaries.")

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

                    act_col1, act_col2 = st.columns(2)
                    with act_col1:
                        if h["status"] == "open":
                            if st.button("🚀 Take Handoff", key=f"btn_take_{h['start_line']}"):
                                ok, msg = mutate_handoff_status(
                                    file_path=handoffs_file,
                                    date=h["date"],
                                    title=h["title"],
                                    new_status="taken"
                                )
                                commit_subject = f"[{author_role}] Take handoff: {h['title'][:50]}"
                                trailers = {"Session": "dashboard", "Reason": "Marked handoff taken"}
                                handle_mutation_and_commit(
                                    success=ok,
                                    msg=msg,
                                    target_file=handoffs_file,
                                    commit_msg=commit_subject,
                                    trailers=trailers,
                                    author_role=author_role,
                                    enable_git=enable_git,
                                    repo_root=repo_root
                                )
                    with act_col2:
                        if st.button("✅ Mark Done", key=f"btn_done_{h['start_line']}"):
                            ok, msg = mutate_handoff_status(
                                file_path=handoffs_file,
                                date=h["date"],
                                title=h["title"],
                                new_status="done"
                            )
                            commit_subject = f"[{author_role}] Done handoff: {h['title'][:50]}"
                            trailers = {"Session": "dashboard", "Reason": "Marked handoff completed"}
                            handle_mutation_and_commit(
                                success=ok,
                                msg=msg,
                                target_file=handoffs_file,
                                commit_msg=commit_subject,
                                trailers=trailers,
                                author_role=author_role,
                                enable_git=enable_git,
                                repo_root=repo_root
                            )

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

                    if st.button("↩️ Reopen", key=f"btn_reopen_{h['start_line']}"):
                        ok, msg = mutate_handoff_status(
                            file_path=handoffs_file,
                            date=h["date"],
                            title=h["title"],
                            new_status="open"
                        )
                        commit_subject = f"[{author_role}] Reopen handoff: {h['title'][:50]}"
                        trailers = {"Session": "dashboard", "Reason": "Reopened handoff"}
                        handle_mutation_and_commit(
                            success=ok,
                            msg=msg,
                            target_file=handoffs_file,
                            commit_msg=commit_subject,
                            trailers=trailers,
                            author_role=author_role,
                            enable_git=enable_git,
                            repo_root=repo_root
                        )

        st.markdown("---")
        with st.expander("➕ Create New Cross-Role Handoff", expanded=False):
            h_fcol1, h_fcol2 = st.columns(2)
            with h_fcol1:
                new_h_from = st.text_input("From Role", value=author_role)
            with h_fcol2:
                new_h_to = st.text_input("To Role", placeholder="e.g. frontend, physics, qa_tester")
            new_h_title = st.text_input("Handoff Title", placeholder="Short descriptive title of the change needed")
            new_h_what = st.text_area("What", placeholder="Describe the specific change needed in the other role's zone")
            new_h_context = st.text_area("Context", placeholder="Why this role can't do it (zone boundary), relevant links")
            new_h_done_when = st.text_input("Done When", placeholder="Concrete, checkable criterion (e.g. test passes)")

            if st.button("➕ Submit Handoff & Commit", key="btn_create_handoff"):
                if new_h_title.strip() and new_h_to.strip():
                    ok, msg = append_handoff(
                        file_path=handoffs_file,
                        from_role=new_h_from.strip(),
                        to_role=new_h_to.strip(),
                        title=new_h_title.strip(),
                        what=new_h_what.strip(),
                        context=new_h_context.strip(),
                        done_when=new_h_done_when.strip(),
                        status="open"
                    )
                    commit_subject = f"[{new_h_from.strip()}] Handoff to {new_h_to.strip()}: {new_h_title.strip()[:50]}"
                    trailers = {
                        "Session": "dashboard",
                        "Reason": f"Delegated task to {new_h_to.strip()}"
                    }
                    handle_mutation_and_commit(
                        success=ok,
                        msg=msg,
                        target_file=handoffs_file,
                        commit_msg=commit_subject,
                        trailers=trailers,
                        author_role=author_role,
                        enable_git=enable_git,
                        repo_root=repo_root
                    )

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
                        st.markdown(f"**Branch:** `{wt['branch']}`")
                        st.caption(f"HEAD: `{wt['head'][:7]}`")
                    with wt_c3:
                        if wt.get("role"):
                            st.markdown(f"Role: `{wt['role']}`")
                        if wt.get("prunable"):
                            st.warning("Prunable")

        st.markdown("---")
        with st.expander("🚀 Launch Worktree for Agent Role", expanded=False):
            wt_role_input = st.text_input("Role to launch (e.g. qa_tester, physics, frontend)")
            if st.button("🚀 Create Worktree", key="btn_create_wt"):
                if wt_role_input.strip():
                    res = GitService.create_worktree(wt_role_input.strip(), repo_root=repo_root)
                    if res["status"] == "success":
                        st.success(f"Worktree created at `{res['path']}` for branch `{res['branch']}`")
                        st.info(f"Terminal Command: `cd assets/.worktrees/{wt_role_input.strip()} && claude`")
                    elif res["status"] == "noop":
                        st.info(res["message"])
                    else:
                        st.error(res["message"])
                    st.rerun()

    # -------------------------------------------------------------------------
    # TAB 5: Backlog & Index
    # -------------------------------------------------------------------------
    with tab5:
        st.subheader("📑 Backlog & Index (`INDEX.md`)")
        st.write("Aggregated index of open and closed items across all journals.")

        i_col1, i_col2 = st.columns([3, 1])
        with i_col2:
            if st.button("⚡ Rebuild INDEX.md", key="btn_rebuild_index", use_container_width=True):
                rebuilt_file = rebuild_index_file(coord_dir)
                commit_subject = f"[{author_role}] Rebuild INDEX.md"
                trailers = {"Session": "dashboard", "Reason": "Rebuilt backlog index"}
                handle_mutation_and_commit(
                    success=True,
                    msg=f"Rebuilt {rebuilt_file.name}",
                    target_file=rebuilt_file,
                    commit_msg=commit_subject,
                    trailers=trailers,
                    author_role=author_role,
                    enable_git=enable_git,
                    repo_root=repo_root
                )

        with i_col1:
            if index_file.exists():
                with open(index_file, "r", encoding="utf-8") as f:
                    index_content = f.read()
                st.markdown(index_content)
            else:
                st.info("INDEX.md not generated yet. Click '⚡ Rebuild INDEX.md' to generate.")


if __name__ == "__main__":
    main()
