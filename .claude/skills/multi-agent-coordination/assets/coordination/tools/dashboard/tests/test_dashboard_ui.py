"""
test_dashboard_ui.py - the Streamlit layer: coordination-directory discovery and the
badge/KPI formatters.

Everything here reads. The workflow tests this file used to open with drove the browser
editor -- resolve a question, move a handoff, update a role, each followed by an isolated
git commit -- and went with it when that editor was removed; what they covered has no
code behind it any more.
"""

from unittest.mock import MagicMock, patch
import pytest

# This module exercises the Streamlit UI layer (dashboard.py, components.py), both of which
# import streamlit at module scope. Skip the whole file rather than failing collection, so the
# stdlib-only parser suites still run with pytest alone.
pytest.importorskip("streamlit", reason="dashboard UI layer requires streamlit")
pytestmark = pytest.mark.streamlit

try:
    from dashboard.dashboard import discover_coordination_dir
except ImportError:
    from dashboard import discover_coordination_dir

from parser import (
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_worktrees,
)
from components import (
    render_kpi_bar,
    render_status_badge,
    render_type_badge,
    render_role_badge,
)


# ============================================================================
# 1. Discovery: discover_coordination_dir
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
# 2. UI Component & Badge Formatters
# ============================================================================

def test_render_status_badge():
    assert "OPEN" in render_status_badge("open")
    assert "TAKEN" in render_status_badge("taken")
    assert "DONE" in render_status_badge("done")
    assert "CLOSED" in render_status_badge("closed")
    assert "MISSING" in render_status_badge("missing")

    # Deliberate change. An unrecognised word used to be echoed back as `🔹 **CUSTOM**`,
    # which reads exactly like a documented state and is how a Russian `открыт` rendered a
    # red OPEN badge beside a row the parser had already filed as closed. It is now labelled
    # UNCLASSIFIED - the word itself is still shown, so nothing is hidden.
    rendered = render_status_badge("custom")
    assert "UNCLASSIFIED" in rendered
    assert "custom" in rendered


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
    worktrees_data = parse_worktrees(mock_git_repo["repo_dir"])

    with patch("streamlit.columns") as mock_cols, patch("streamlit.metric") as mock_metric:
        col_mock = MagicMock()
        mock_cols.return_value = (col_mock, col_mock, col_mock, col_mock)
        # Should render 4 metrics without raising exceptions
        render_kpi_bar(board_data, questions_data, handoffs_data, worktrees_data)
        assert mock_cols.called
