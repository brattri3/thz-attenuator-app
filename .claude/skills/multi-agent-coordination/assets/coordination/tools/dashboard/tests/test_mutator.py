"""
test_mutator.py - Comprehensive Unit Test Suite for mutator.py.
Tests escape_pipe, format_table_row, mutate_table_cell, mutate_handoff_status, append_question, append_handoff.
Asserts strict formatting preservation, CRLF/LF line endings, Cyrillic/emoji support, comments preservation,
and graceful error handling.
"""

from datetime import datetime
from pathlib import Path
import pytest

from mutator import (
    escape_pipe,
    format_table_row,
    mutate_table_cell,
    mutate_handoff_status,
    append_question,
    append_handoff,
)
from parser import parse_board, parse_questions, parse_handoffs


# ============================================================================
# 1. Tests for escape_pipe and format_table_row
# ============================================================================

def test_escape_pipe_basic():
    assert escape_pipe("normal text") == "normal text"
    assert escape_pipe(r"already \| escaped") == r"already \| escaped"
    assert escape_pipe("raw | pipe") == r"raw \| pipe"
    assert escape_pipe("multiple | raw | pipes") == r"multiple \| raw \| pipes"
    assert escape_pipe(r"mixed raw | and \| escaped") == r"mixed raw \| and \| escaped"


def test_format_table_row():
    row_lf = format_table_row(["col1", "col2 | with pipe", "col3"], line_ending="\n")
    assert row_lf == "| col1 | col2 \\| with pipe | col3 |\n"

    row_crlf = format_table_row(["A", "B"], line_ending="\r\n")
    assert row_crlf == "| A | B |\r\n"


# ============================================================================
# 2. Tests for mutate_table_cell
# ============================================================================

def test_mutate_table_cell_board_status(mock_git_repo):
    board_file = mock_git_repo["board_file"]

    # Initial state
    roles_before = parse_board(board_file)
    w2_before = next(r for r in roles_before if r["role"] == "worker_2")
    assert w2_before["status"] == "idle"

    # Mutate status of worker_2
    ok, msg = mutate_table_cell(
        file_path=board_file,
        key_col="Role",
        key_val="worker_2",
        target_col="Status (date)",
        new_val="active (2026-08-27)"
    )
    assert ok is True
    assert "Updated row" in msg

    # Verify parsed result
    roles_after = parse_board(board_file)
    w2_after = next(r for r in roles_after if r["role"] == "worker_2")
    assert w2_after["status"] == "active"
    assert w2_after["date"] == "2026-08-27"
    assert w2_after["status_date"] == "active (2026-08-27)"

    # Verify other roles remained untouched
    lead = next(r for r in roles_after if r["role"] == "lead")
    assert lead["status"] == "active"
    assert lead["summary"] == "Orchestrating multi-agent release"


def test_mutate_table_cell_questions_answer_and_status(mock_git_repo):
    q_file = mock_git_repo["questions_file"]

    # Update question Q-1 status to resolved and answer
    ok1, msg1 = mutate_table_cell(q_file, "#", "Q-1", "Status", "resolved")
    assert ok1 is True

    ok2, msg2 = mutate_table_cell(q_file, "#", "Q-1", "Owner's answer", "Implemented via binary byte preservation")
    assert ok2 is True

    questions = parse_questions(q_file)
    q1 = next(q for q in questions if q["id"] == "Q-1")
    assert q1["status"] == "resolved"
    assert q1["is_open"] is False
    assert q1["answer"] == "Implemented via binary byte preservation"


def test_mutate_table_cell_crlf_preservation(crlf_markdown_files):
    board_file = crlf_markdown_files["board_file"]

    # Verify input is CRLF
    initial_bytes = board_file.read_bytes()
    assert b"\r\n" in initial_bytes
    assert b"\n" not in initial_bytes.replace(b"\r\n", b"")

    ok, msg = mutate_table_cell(
        file_path=board_file,
        key_col="Role",
        key_val="worker_2",
        target_col="Status (date)",
        new_val="active (2026-08-27)"
    )
    assert ok is True

    # Strict byte-level assertion: all lines must end with \r\n
    after_bytes = board_file.read_bytes()
    assert b"\r\n" in after_bytes
    assert b"\n" not in after_bytes.replace(b"\r\n", b"")


def test_mutate_table_cell_lf_preservation(tmp_path):
    content = (
        "# Questions\n\n"
        "| # | Question | Status |\n"
        "|---|---|---|\n"
        "| Q-1 | Unix LF test | open |\n"
    )
    fpath = tmp_path / "LF_QUESTIONS.md"
    fpath.write_bytes(content.encode("utf-8"))

    ok, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", "resolved")
    assert ok is True

    raw_bytes = fpath.read_bytes()
    assert b"\r" not in raw_bytes
    assert b"\n" in raw_bytes


def test_mutate_table_cell_unicode_cyrillic(unicode_markdown_files):
    q_file = unicode_markdown_files["questions_file"]

    ok, msg = mutate_table_cell(
        file_path=q_file,
        key_col="№",
        key_val="Q-1",
        target_col="Статус",
        new_val="resolved"
    )
    assert ok is True

    questions = parse_questions(q_file)
    q1 = next(q for q in questions if q["id"] == "Q-1")
    assert q1["status"] == "resolved"
    assert "UTF-8 и эмодзи 🚀" in q1["question"]


def test_mutate_table_cell_preserves_comments_and_surroundings(tmp_path):
    content = (
        "<!-- Header comment banner -->\n\n"
        "# Custom Title\n\n"
        "Introductory description paragraph.\n\n"
        "| ID | Task | Status |\n"
        "|---|---|---|\n"
        "| T-1 | First task | pending |\n"
        "| T-2 | Second task | open |\n\n"
        "<!-- Trailing footer note -->\n"
    )
    fpath = tmp_path / "COMMENTED.md"
    fpath.write_text(content, encoding="utf-8")

    ok, msg = mutate_table_cell(fpath, "ID", "T-1", "Status", "completed")
    assert ok is True

    updated_text = fpath.read_text(encoding="utf-8")
    assert "<!-- Header comment banner -->" in updated_text
    assert "# Custom Title" in updated_text
    assert "Introductory description paragraph." in updated_text
    assert "| T-1 | First task | completed |" in updated_text
    assert "| T-2 | Second task | open |" in updated_text
    assert "<!-- Trailing footer note -->" in updated_text


def test_mutate_table_cell_multi_batch_tables(mock_git_repo):
    q_file = mock_git_repo["questions_file"]

    # Mutate Q-4 in Batch 2 table
    ok, msg = mutate_table_cell(q_file, "#", "Q-4", "Status", "resolved")
    assert ok is True

    questions = parse_questions(q_file)
    q4 = next(q for q in questions if q["id"] == "Q-4")
    assert q4["status"] == "resolved"

    # Batch 1 questions remain untouched
    q1 = next(q for q in questions if q["id"] == "Q-1")
    assert q1["status"] == "open"


def test_mutate_table_cell_nonexistent_targets_fail_gracefully(tmp_path):
    fpath = tmp_path / "TEST.md"
    fpath.write_text("| Role | Status |\n|---|---|\n| lead | active |\n", encoding="utf-8")

    # Nonexistent row key
    ok, msg = mutate_table_cell(fpath, "Role", "ghost_role", "Status", "idle")
    assert ok is False
    assert "not found" in msg

    # Nonexistent target column
    ok, msg = mutate_table_cell(fpath, "Role", "lead", "NonexistentColumn", "val")
    assert ok is False
    assert "not found" in msg

    # Nonexistent file
    ok, msg = mutate_table_cell(tmp_path / "NO_FILE.md", "Role", "lead", "Status", "val")
    assert ok is False
    assert "File not found" in msg


# ============================================================================
# 3. Tests for mutate_handoff_status
# ============================================================================

def test_mutate_handoff_status_lifecycle(mock_git_repo):
    h_file = mock_git_repo["handoffs_file"]

    # 1. Transition 'Implement dashboard core' from taken -> done
    ok, msg = mutate_handoff_status(h_file, "2026-08-27", "Implement dashboard core", "done")
    assert ok is True
    handoffs = parse_handoffs(h_file)
    h1 = next(h for h in handoffs if "Implement dashboard core" in h["title"])
    assert h1["status"] == "done"
    assert h1["is_open"] is False

    # 2. Transition back from done -> open
    ok, msg = mutate_handoff_status(h_file, "2026-08-27", "Implement dashboard core", "open")
    assert ok is True
    handoffs = parse_handoffs(h_file)
    h1 = next(h for h in handoffs if "Implement dashboard core" in h["title"])
    assert h1["status"] == "open"
    assert h1["is_open"] is True

    # 3. Transition from open -> taken
    ok, msg = mutate_handoff_status(h_file, "2026-08-27", "Implement dashboard core", "taken")
    assert ok is True
    handoffs = parse_handoffs(h_file)
    h1 = next(h for h in handoffs if "Implement dashboard core" in h["title"])
    assert h1["status"] == "taken"


def test_mutate_handoff_status_preserves_indentation(tmp_path):
    content = (
        "## [2026-08-27] FROM lead TO worker_1 — Indented handoff\n"
        "  - What: Indented bullets test\n"
        "  - Context: Testing spaces preservation\n"
        "  - Done when: Verified\n"
        "  - **Status:** open\n"
    )
    fpath = tmp_path / "INDENTED_HANDOFF.md"
    fpath.write_text(content, encoding="utf-8")

    ok, msg = mutate_handoff_status(fpath, "2026-08-27", "Indented handoff", "done")
    assert ok is True

    lines = fpath.read_text(encoding="utf-8").splitlines()
    assert lines[4] == "  - **Status:** done"


def test_mutate_handoff_status_crlf_preservation(crlf_markdown_files):
    h_file = crlf_markdown_files["handoffs_file"]

    initial_bytes = h_file.read_bytes()
    assert b"\r\n" in initial_bytes
    assert b"\n" not in initial_bytes.replace(b"\r\n", b"")

    ok, msg = mutate_handoff_status(h_file, "2026-08-27", "Build comprehensive test suite", "taken")
    assert ok is True

    after_bytes = h_file.read_bytes()
    assert b"\r\n" in after_bytes
    assert b"\n" not in after_bytes.replace(b"\r\n", b"")


def test_mutate_handoff_nonexistent_entry_fails_gracefully(mock_git_repo):
    h_file = mock_git_repo["handoffs_file"]

    ok, msg = mutate_handoff_status(h_file, "2020-01-01", "Ghost handoff", "done")
    assert ok is False
    assert "not found" in msg

    ok_nofile, msg_nofile = mutate_handoff_status(Path("nonexistent.md"), "2026-08-27", "Title", "done")
    assert ok_nofile is False


# ============================================================================
# 4. Tests for append_question and append_handoff
# ============================================================================

def test_append_question_auto_id(mock_git_repo):
    q_file = mock_git_repo["questions_file"]

    # Initial highest question is Q-4
    ok, msg = append_question(
        file_path=q_file,
        question="What is the test coverage target?",
        q_type="blocking",
        status="open"
    )
    assert ok is True
    assert "Q-5" in msg

    questions = parse_questions(q_file)
    assert len(questions) == 5
    q5 = next(q for q in questions if q["id"] == "Q-5")
    assert q5["question"] == "What is the test coverage target?"
    assert q5["type"] == "blocking"
    assert q5["status"] == "open"
    assert q5["is_open"] is True


def test_append_question_to_empty_file(tmp_path):
    fpath = tmp_path / "NEW_QUESTIONS.md"
    fpath.write_text("# New Questions File\n\n", encoding="utf-8")

    ok, msg = append_question(fpath, "Initial question?", qid="Q-100")
    assert ok is True

    questions = parse_questions(fpath)
    assert len(questions) == 1
    assert questions[0]["id"] == "Q-100"
    assert questions[0]["question"] == "Initial question?"


def test_append_handoff_strict_charter_format(mock_git_repo):
    h_file = mock_git_repo["handoffs_file"]

    ok, msg = append_handoff(
        file_path=h_file,
        from_role="worker_2",
        to_role="lead",
        title="Comprehensive test suite complete",
        what="Implemented all pytest suites",
        context="Milestone 2 deliverable",
        done_when="Auditor passes all tests",
        status="open",
        date="2026-08-27"
    )
    assert ok is True

    handoffs = parse_handoffs(h_file)
    new_h = next(h for h in handoffs if "Comprehensive test suite complete" in h["title"])
    assert new_h["date"] == "2026-08-27"
    assert new_h["from_role"] == "worker_2"
    assert new_h["to_role"] == "lead"
    assert new_h["what"] == "Implemented all pytest suites"
    assert new_h["context"] == "Milestone 2 deliverable"
    assert new_h["done_when"] == "Auditor passes all tests"
    assert new_h["status"] == "open"
    assert new_h["is_open"] is True


def test_append_handoff_auto_date(tmp_path):
    fpath = tmp_path / "HANDOFFS.md"
    fpath.write_text("# Handoffs\n", encoding="utf-8")

    ok, msg = append_handoff(
        file_path=fpath,
        from_role="roleA",
        to_role="roleB",
        title="Auto date handoff",
        what="Test auto date",
        context="Context",
        done_when="Verified",
        status="open"
    )
    assert ok is True

    today_str = datetime.now().strftime("%Y-%m-%d")
    handoffs = parse_handoffs(fpath)
    assert len(handoffs) == 1
    assert handoffs[0]["date"] == today_str


def test_append_nonexistent_files_fail_gracefully(tmp_path):
    nofile = tmp_path / "NO_FILE.md"
    ok1, _ = append_question(nofile, "Question")
    assert ok1 is False

    ok2, _ = append_handoff(nofile, "A", "B", "Title", "What", "Ctx", "Done")
    assert ok2 is False
