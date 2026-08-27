"""
test_dashboard_e2e.py - End-to-End Integration Test Suite for Dashboard Workflows.
Tests programmatic question resolution, handoff state transitions, role status updates,
INDEX.md rebuilding, coordination directory discovery, and UI component helpers.
Verifies table integrity, git commit execution, trailers, and line endings across all workflows.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

try:
    from dashboard.dashboard import (
        discover_coordination_dir,
        rebuild_index_file,
        handle_mutation_and_commit,
    )
except ImportError:
    from dashboard import (
        discover_coordination_dir,
        rebuild_index_file,
        handle_mutation_and_commit,
    )

from git_service import GitService
from mutator import (
    mutate_table_cell,
    mutate_handoff_status,
    append_question,
    append_handoff,
)
from parser import (
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_index,
    parse_worktrees,
)
from components import (
    render_kpi_bar,
    render_status_badge,
    render_type_badge,
    render_role_badge,
)


# ============================================================================
# 1. E2E Workflow: Resolve Question & Auto-Commit & Rebuild Index
# ============================================================================

def test_e2e_resolve_question_workflow(mock_git_repo):
    coord_dir = mock_git_repo["coord_dir"]
    repo_dir = mock_git_repo["repo_dir"]
    q_file = mock_git_repo["questions_file"]
    index_file = mock_git_repo["index_file"]

    # Initial state: 3 open questions
    initial_index = parse_index(index_file)
    assert initial_index["questions_open_count"] == 3

    # Step 1: Update answer and status in QUESTIONS.md
    ok_ans, msg_ans = mutate_table_cell(
        file_path=q_file,
        key_col="#",
        key_val="Q-1",
        target_col="Owner's answer",
        new_val="Supported via strict CRLF binary byte preservation"
    )
    assert ok_ans is True

    ok_stat, msg_stat = mutate_table_cell(
        file_path=q_file,
        key_col="#",
        key_val="Q-1",
        target_col="Status",
        new_val="resolved"
    )
    assert ok_stat is True

    # Step 2: Execute isolated git auto-commit with Role trailer
    commit_res = GitService.auto_commit_file(
        file_path=q_file,
        message="decision: resolve Q-1 regarding CRLF support",
        author_role="lead",
        trailers={"Decision-ID": "Q-1"},
        repo_root=repo_dir
    )
    assert commit_res["status"] == "success"

    # Step 3: Rebuild INDEX.md
    rebuilt_idx_path = rebuild_index_file(coord_dir)
    assert rebuilt_idx_path == index_file

    # Step 4: Verify markdown table integrity and parsed state
    questions = parse_questions(q_file)
    q1 = next(q for q in questions if q["id"] == "Q-1")
    assert q1["status"] == "resolved"
    assert q1["is_open"] is False
    assert "strict CRLF binary byte preservation" in q1["answer"]

    # Step 5: Verify INDEX.md open count decremented to 2
    updated_index = parse_index(index_file)
    assert updated_index["questions_open_count"] == 2
    assert updated_index["questions_total_count"] == 4

    # Step 6: Verify git log contains commit and trailers
    log_out = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True
    ).stdout

    assert "decision: resolve Q-1 regarding CRLF support" in log_out
    assert "Role: lead" in log_out
    assert "Decision-ID: Q-1" in log_out


# ============================================================================
# 2. E2E Workflow: Handoff Lifecycle & Auto-Commit Transitions
# ============================================================================

def test_e2e_handoff_lifecycle_workflow(mock_git_repo):
    coord_dir = mock_git_repo["coord_dir"]
    repo_dir = mock_git_repo["repo_dir"]
    h_file = mock_git_repo["handoffs_file"]
    index_file = mock_git_repo["index_file"]

    # Initial state: 2 open/taken handoffs
    initial_index = parse_index(index_file)
    assert initial_index["handoffs_open_count"] == 2

    # --- Phase 1: Transition 'Build comprehensive test suite' from open -> taken ---
    ok1, msg1 = mutate_handoff_status(
        file_path=h_file,
        date="2026-08-27",
        title="Build comprehensive test suite",
        new_status="taken"
    )
    assert ok1 is True

    commit1 = GitService.auto_commit_file(
        file_path=h_file,
        message="handoff: take 'Build comprehensive test suite'",
        author_role="worker_2",
        repo_root=repo_dir
    )
    assert commit1["status"] == "success"

    handoffs_phase1 = parse_handoffs(h_file)
    h_target1 = next(h for h in handoffs_phase1 if "Build comprehensive test suite" in h["title"])
    assert h_target1["status"] == "taken"
    assert h_target1["is_open"] is True

    # --- Phase 2: Transition from taken -> done ---
    ok2, msg2 = mutate_handoff_status(
        file_path=h_file,
        date="2026-08-27",
        title="Build comprehensive test suite",
        new_status="done"
    )
    assert ok2 is True

    commit2 = GitService.auto_commit_file(
        file_path=h_file,
        message="handoff: complete 'Build comprehensive test suite'",
        author_role="worker_2",
        repo_root=repo_dir
    )
    assert commit2["status"] == "success"

    handoffs_phase2 = parse_handoffs(h_file)
    h_target2 = next(h for h in handoffs_phase2 if "Build comprehensive test suite" in h["title"])
    assert h_target2["status"] == "done"
    assert h_target2["is_open"] is False

    # --- Phase 3: Rebuild INDEX.md and verify ---
    rebuild_index_file(coord_dir)
    updated_index = parse_index(index_file)
    # Open handoffs count decreased from 2 to 1 (only 'Implement dashboard core' remains taken)
    assert updated_index["handoffs_open_count"] == 1
    assert updated_index["handoffs_total_count"] == 4


# ============================================================================
# 3. E2E Workflow: Update Role Status on Board
# ============================================================================

def test_e2e_update_role_status_workflow(mock_git_repo):
    coord_dir = mock_git_repo["coord_dir"]
    repo_dir = mock_git_repo["repo_dir"]
    board_file = mock_git_repo["board_file"]

    # Step 1: Update status of worker_2 to active
    ok_stat, _ = mutate_table_cell(
        file_path=board_file,
        key_col="Role",
        key_val="worker_2",
        target_col="Status (date)",
        new_val="active (2026-08-27)"
    )
    assert ok_stat is True

    # Step 2: Update summary of worker_2
    ok_sum, _ = mutate_table_cell(
        file_path=board_file,
        key_col="Role",
        key_val="worker_2",
        target_col="One-line summary",
        new_val="Building Milestone 2 pytest harness"
    )
    assert ok_sum is True

    # Step 3: Git auto-commit
    commit_res = GitService.auto_commit_file(
        file_path=board_file,
        message="coord: update worker_2 status to active",
        author_role="worker_2",
        repo_root=repo_dir
    )
    assert commit_res["status"] == "success"

    # Step 4: Verify BOARD.md parsed data
    roles = parse_board(board_file)
    w2 = next(r for r in roles if r["role"] == "worker_2")
    assert w2["status"] == "active"
    assert w2["date"] == "2026-08-27"
    assert w2["summary"] == "Building Milestone 2 pytest harness"


# ============================================================================
# 4. E2E Discovery: discover_coordination_dir
# ============================================================================

def test_discover_coordination_dir_in_repo(mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]
    coord_dir = mock_git_repo["coord_dir"]

    # Discovers assets/coordination when pointed at repo root or subfolder
    assert discover_coordination_dir(repo_dir) == coord_dir.resolve()
    assert discover_coordination_dir(coord_dir) == coord_dir.resolve()


def test_discover_coordination_dir_standalone(tmp_path):
    standalone_dir = tmp_path / "custom_coord"
    standalone_dir.mkdir()
    (standalone_dir / "BOARD.md").write_text("# Board\n", encoding="utf-8")

    assert discover_coordination_dir(standalone_dir) == standalone_dir.resolve()


# ============================================================================
# 5. UI Component & Badge Formatters
# ============================================================================

def test_render_status_badge():
    assert "OPEN" in render_status_badge("open")
    assert "TAKEN" in render_status_badge("taken")
    assert "DONE" in render_status_badge("done")
    assert "CLOSED" in render_status_badge("closed")
    assert "MISSING" in render_status_badge("missing")
    assert "CUSTOM" in render_status_badge("custom")


def test_render_type_badge():
    assert "Blocking" in render_type_badge("blocking")
    assert "Non-blocking" in render_type_badge("non-blocking")


def test_render_role_badge():
    assert "Active" in render_role_badge("active")
    assert "Idle" in render_role_badge("idle")
    assert "Stale" in render_role_badge("stale")
    assert "Blocked" in render_role_badge("blocked")
    assert "custom_status" in render_role_badge("custom_status")


def test_render_kpi_bar_headless(mock_git_repo):
    board_data = parse_board(mock_git_repo["board_file"])
    questions_data = parse_questions(mock_git_repo["questions_file"])
    handoffs_data = parse_handoffs(mock_git_repo["handoffs_file"])
    worktrees_data = GitService.list_worktrees(mock_git_repo["repo_dir"])

    with patch("streamlit.columns") as mock_cols, patch("streamlit.metric") as mock_metric:
        col_mock = MagicMock()
        mock_cols.return_value = (col_mock, col_mock, col_mock, col_mock)
        # Should render 4 metrics without raising exceptions
        render_kpi_bar(board_data, questions_data, handoffs_data, worktrees_data)
        assert mock_cols.called


def test_handle_mutation_and_commit_success_and_failure(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]

    # 1. Failure branch
    with patch("streamlit.error") as mock_err, patch("streamlit.rerun") as mock_rerun:
        handle_mutation_and_commit(
            success=False,
            msg="Target column missing",
            target_file=board_file,
            commit_msg="test",
            trailers={},
            author_role="lead",
            enable_git=True,
            repo_root=repo_dir
        )
        mock_err.assert_called_once()
        assert not mock_rerun.called

    # 2. Success branch
    board_file.write_text(board_file.read_text(encoding="utf-8") + "\n<!-- ui update -->\n", encoding="utf-8")
    with patch("streamlit.success") as mock_succ, \
         patch("streamlit.toast") as mock_toast, \
         patch("streamlit.rerun") as mock_rerun:
        handle_mutation_and_commit(
            success=True,
            msg="Updated role",
            target_file=board_file,
            commit_msg="coord: ui update",
            trailers={"Role": "lead"},
            author_role="lead",
            enable_git=True,
            repo_root=repo_dir
        )
        mock_succ.assert_called_once()
        mock_toast.assert_called_once()
        mock_rerun.assert_called_once()
