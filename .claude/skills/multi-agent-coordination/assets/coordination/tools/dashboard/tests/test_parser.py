"""
test_parser.py - Comprehensive Unit Test Suite for parser.py.
Tests split_table_row, parse_board, parse_questions, parse_handoffs, parse_index, and parse_worktrees.
Covers escaped pipes, backticks with raw pipes, Cyrillic headers, emojis, templates, and edge cases.
"""

from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

from parser import (
    split_table_row,
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_index,
    parse_worktrees,
)


# ============================================================================
# 1. Tests for split_table_row
# ============================================================================

def test_split_table_row_standard():
    line = "| col1 | col2 | col3 |"
    cells = split_table_row(line)
    assert cells == ["col1", "col2", "col3"]


def test_split_table_row_without_outer_borders():
    line = "col1 | col2 | col3"
    cells = split_table_row(line)
    assert cells == ["col1", "col2", "col3"]


def test_split_table_row_with_escaped_pipes():
    line = r"| regex `a\|b` | math $\|x\| + \|y\|$ | normal text |"
    cells = split_table_row(line)
    assert len(cells) == 3
    assert cells[0] == r"regex `a\|b`"
    assert cells[1] == r"math $\|x\| + \|y\|$"
    assert cells[2] == "normal text"


def test_split_table_row_with_raw_pipes_in_backticks():
    line = r"| ID | `cat file | grep pattern | awk '{print $1}'` | execute pipeline |"
    cells = split_table_row(line)
    assert len(cells) == 3
    assert cells[0] == "ID"
    assert cells[1] == "`cat file | grep pattern | awk '{print $1}'`"
    assert cells[2] == "execute pipeline"


def test_split_table_row_multiple_backticks_and_escapes():
    line = r"| `cmd1 | cmd2` | normal | `cmd3 | cmd4` | val \| with \| pipes |"
    cells = split_table_row(line)
    assert len(cells) == 4
    assert cells[0] == "`cmd1 | cmd2`"
    assert cells[1] == "normal"
    assert cells[2] == "`cmd3 | cmd4`"
    assert cells[3] == r"val \| with \| pipes"


def test_split_table_row_empty_cells():
    line = "| col1 | | col3 |   | col5 |"
    cells = split_table_row(line)
    assert cells == ["col1", "", "col3", "", "col5"]


def test_split_table_row_single_cell():
    line = "| only_cell |"
    cells = split_table_row(line)
    assert cells == ["only_cell"]


def test_split_table_row_whitespace_trimming():
    line = "  |   leading spaces   |   trailing spaces   |   middle   |  "
    cells = split_table_row(line)
    assert cells == ["leading spaces", "trailing spaces", "middle"]


# ============================================================================
# 2. Tests for parse_board
# ============================================================================

def test_parse_board_canonical(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    roles = parse_board(board_file)

    # 4 valid roles, template role (<ID>) skipped
    assert len(roles) == 4
    role_names = [r["role"] for r in roles]
    assert role_names == ["lead", "worker_1", "worker_2", "auditor"]

    lead = roles[0]
    assert lead["role"] == "lead"
    assert lead["status"] == "active"
    assert lead["date"] == "2026-08-27"
    assert lead["status_date"] == "active (2026-08-27)"
    assert lead["summary"] == "Orchestrating multi-agent release"
    assert lead["line"] == 5

    auditor = roles[3]
    assert auditor["role"] == "auditor"
    assert auditor["status"] == "stale"
    assert auditor["date"] == "2026-08-20"


def test_parse_board_unicode_cyrillic(unicode_markdown_files):
    board_file = unicode_markdown_files["board_file"]
    roles = parse_board(board_file)

    assert len(roles) == 3
    assert roles[0]["role"] == "архитектор"
    assert roles[0]["status"] == "active"
    assert roles[0]["date"] == "2026-08-27"
    assert "Разработка архитектуры" in roles[0]["summary"]
    assert "📐" in roles[0]["summary"]

    assert roles[1]["role"] == "разработчик"
    assert "🚀" in roles[1]["summary"]

    assert roles[2]["role"] == "тестировщик"
    assert roles[2]["status"] == "idle"


def test_parse_board_status_without_date(tmp_path):
    board_content = (
        "| Role | Status | Summary |\n"
        "|---|---|---|\n"
        "| `solo_agent` | active | Running without date stamp |\n"
        "| `standby` | idle | On standby |\n"
    )
    b_file = tmp_path / "BOARD.md"
    b_file.write_text(board_content, encoding="utf-8")

    roles = parse_board(b_file)
    assert len(roles) == 2
    assert roles[0]["role"] == "solo_agent"
    assert roles[0]["status"] == "active"
    assert roles[0]["date"] == ""


def test_parse_board_nonexistent_file(tmp_path):
    nonexistent = tmp_path / "NONEXISTENT_BOARD.md"
    roles = parse_board(nonexistent)
    assert roles == []


def test_parse_board_empty_and_no_tables(tmp_path):
    f_empty = tmp_path / "EMPTY.md"
    f_empty.write_text("# Just a heading\n\nNo table here.\n", encoding="utf-8")
    assert parse_board(f_empty) == []


# ============================================================================
# 3. Tests for parse_questions
# ============================================================================

def test_parse_questions_canonical(mock_git_repo):
    q_file = mock_git_repo["questions_file"]
    questions = parse_questions(q_file)

    # 4 valid questions (Q-1, Q-2, Q-3, Q-4), <ID> skipped
    assert len(questions) == 4
    q_ids = [q["id"] for q in questions]
    assert q_ids == ["Q-1", "Q-2", "Q-3", "Q-4"]

    # Q-1: blocking, open
    q1 = questions[0]
    assert q1["id"] == "Q-1"
    assert q1["type"] == "blocking"
    assert q1["status"] == "open"
    assert q1["is_open"] is True
    assert q1["is_blocking"] is True

    # Q-2: non-blocking, resolved
    q2 = questions[1]
    assert q2["id"] == "Q-2"
    assert q2["type"] == "non-blocking"
    assert q2["status"] == "resolved"
    assert q2["is_open"] is False
    assert q2["is_blocking"] is False

    # Q-4: escaped pipe unescaped in text
    q4 = questions[3]
    assert q4["id"] == "Q-4"
    assert "cat | grep" in q4["question"]


def test_parse_questions_unicode_cyrillic(unicode_markdown_files):
    q_file = unicode_markdown_files["questions_file"]
    questions = parse_questions(q_file)

    assert len(questions) == 3
    assert questions[0]["id"] == "Q-1"
    assert "UTF-8 и эмодзи 🚀" in questions[0]["question"]
    assert questions[0]["is_open"] is True
    assert questions[0]["is_blocking"] is True

    assert questions[1]["id"] == "Q-2"
    assert r"$\int_0^1 x^2 dx = \frac{1}{3}$" in questions[1]["question"]
    assert questions[1]["status"] == "resolved"
    assert questions[1]["is_open"] is False

    assert questions[2]["id"] == "Q-3"
    assert "cat | grep" in questions[2]["question"]


def test_parse_questions_nonexistent_file(tmp_path):
    nonexistent = tmp_path / "NONEXISTENT_QUESTIONS.md"
    assert parse_questions(nonexistent) == []


# ============================================================================
# 4. Tests for parse_handoffs
# ============================================================================

def test_parse_handoffs_canonical(mock_git_repo):
    h_file = mock_git_repo["handoffs_file"]
    handoffs = parse_handoffs(h_file)

    assert len(handoffs) == 4

    h1 = handoffs[0]
    assert h1["date"] == "2026-08-27"
    assert h1["from_role"] == "lead"
    assert h1["to_role"] == "worker_1"
    assert h1["title"] == "Implement dashboard core"
    assert h1["what"] == "Implement parser.py and mutator.py"
    assert h1["context"] == "User requested visual coordination tool"
    assert h1["done_when"] == "Parsers and mutators handle all edge cases"
    assert h1["status"] == "taken"
    assert h1["is_open"] is True
    assert h1["is_template"] is False

    h3 = handoffs[2]
    assert h3["date"] == "2026-08-26"
    assert h3["status"] == "done"
    assert h3["is_open"] is False

    # Template detection
    h4 = handoffs[3]
    assert h4["is_template"] is True


def test_parse_handoffs_missing_status(tmp_path):
    content = (
        "## [2026-08-27] FROM worker_1 TO worker_2 — Incomplete handoff\n"
        "- What: Missing status line test\n"
        "- Context: Testing parser robustness\n"
        "- Done when: Parser assigns 'missing'\n"
    )
    h_file = tmp_path / "HANDOFFS_MISSING.md"
    h_file.write_text(content, encoding="utf-8")

    entries = parse_handoffs(h_file)
    assert len(entries) == 1
    assert entries[0]["status"] == "missing"
    assert entries[0]["is_open"] is True
    assert entries[0]["status_line"] is None


def test_parse_handoffs_en_dash_and_hyphen(tmp_path):
    content = (
        "## [2026-08-27] FROM roleA TO roleB - Hyphen title\n"
        "- **Status:** open\n\n"
        "## [2026-08-28] FROM roleC TO roleD – En-dash title\n"
        "- **Status:** taken\n"
    )
    h_file = tmp_path / "HANDOFFS_DASHES.md"
    h_file.write_text(content, encoding="utf-8")

    entries = parse_handoffs(h_file)
    assert len(entries) == 2
    assert entries[0]["title"] == "Hyphen title"
    assert entries[1]["title"] == "En-dash title"


def test_parse_handoffs_nonexistent_file(tmp_path):
    nonexistent = tmp_path / "NONEXISTENT_HANDOFFS.md"
    assert parse_handoffs(nonexistent) == []


# ============================================================================
# 5. Tests for parse_index
# ============================================================================

def test_parse_index_canonical(mock_git_repo):
    idx_file = mock_git_repo["index_file"]
    res = parse_index(idx_file)

    assert res["questions_open_count"] == 3
    assert res["questions_total_count"] == 4
    assert res["handoffs_open_count"] == 2
    assert res["handoffs_total_count"] == 4
    assert len(res["raw_content"]) > 0


def test_parse_index_nonexistent_file(tmp_path):
    nonexistent = tmp_path / "NONEXISTENT_INDEX.md"
    res = parse_index(nonexistent)

    assert res["questions_open_count"] == 0
    assert res["questions_total_count"] == 0
    assert res["handoffs_open_count"] == 0
    assert res["handoffs_total_count"] == 0
    assert res["raw_content"] == ""


# ============================================================================
# 6. Tests for parse_worktrees
# ============================================================================

def test_parse_worktrees_with_mock_git(mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]
    worktrees = parse_worktrees(repo_dir)

    # Initially 1 main worktree
    assert len(worktrees) == 1
    assert worktrees[0]["branch"] == "main"
    assert worktrees[0]["bare"] is False


def test_parse_worktrees_porcelain_parsing():
    porcelain_output = (
        "worktree /path/to/main\n"
        "HEAD 1234567890abcdef\n"
        "branch refs/heads/main\n\n"
        "worktree /path/to/.worktrees/worker_1\n"
        "HEAD fedcba0987654321\n"
        "branch refs/heads/role/worker_1\n\n"
        "worktree /path/to/detached\n"
        "HEAD 1111222233334444\n"
        "detached\n\n"
        "worktree /path/to/bare\n"
        "bare\n\n"
        "worktree /path/to/locked_wt\n"
        "HEAD 5555666677778888\n"
        "branch refs/heads/feature\n"
        "locked locked by user\n"
        "prunable gitdir file missing\n"
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = porcelain_output
        worktrees = parse_worktrees(Path("/fake/repo"))

    assert len(worktrees) == 5
    assert worktrees[0]["branch"] == "main"
    assert worktrees[1]["branch"] == "role/worker_1"
    assert worktrees[1]["role"] == "worker_1"
    assert worktrees[2]["branch"] == "(detached)"
    assert worktrees[3]["bare"] is True
    assert worktrees[4]["locked"] == "locked by user"
    assert worktrees[4]["prunable"] == "gitdir file missing"


def test_parse_worktrees_subprocess_error():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(128, ["git"])):
        worktrees = parse_worktrees(Path("/nonexistent/repo"))
        assert worktrees == []

    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        worktrees = parse_worktrees(Path("/nonexistent/repo"))
        assert worktrees == []

