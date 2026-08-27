"""
test_adversarial_stress.py - Deep Adversarial Stress, Invariants, and Fuzzing Suite
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from parser import (
    split_table_row,
    parse_board,
    parse_questions,
    parse_handoffs,
    parse_index,
    parse_worktrees,
)
from mutator import (
    escape_pipe,
    format_table_row,
    mutate_table_cell,
    mutate_handoff_status,
    append_question,
    append_handoff,
)


class TestAdversarialInvariantsAndStress(unittest.TestCase):
    """Stress testing invariants, idempotency, and boundary conditions."""

    def test_100_sequential_mutations_idempotency(self):
        """Mutating the same cell 100 times should not drift line count, duplicate lines, or corrupt structure."""
        content = (
            "# QUESTIONS\n\n"
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-1 | Loop test question | Initial answer | blocking | open |\n"
            "| Q-2 | Sibling question | Sibling answer | non-blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")
            initial_line_count = len(fpath.read_text(encoding="utf-8").splitlines())

            for i in range(100):
                new_status = "resolved" if i % 2 == 0 else "open"
                ok, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", new_status)
                self.assertTrue(ok, msg)

            final_text = fpath.read_text(encoding="utf-8")
            final_lines = final_text.splitlines()
            self.assertEqual(len(final_lines), initial_line_count)

            # Q-2 should be completely unchanged
            self.assertIn("| Q-2 | Sibling question | Sibling answer | non-blocking | open |", final_text)

            # Q-1 should have last status "open" (since 99 % 2 == 1 -> "open")
            q_list = parse_questions(fpath)
            self.assertEqual(len(q_list), 2)
            self.assertEqual(q_list[0]["status"], "open")
            self.assertEqual(q_list[1]["status"], "open")

    def test_multi_column_wide_table_with_empty_cells(self):
        """Tables with empty cells, whitespace cells, and many columns."""
        content = (
            "| C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| K1 |   | val3 | | val5 |   val6   | | val8 |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "TABLE.md"
            fpath.write_text(content, encoding="utf-8")

            # Mutate empty C4 to new value
            ok, msg = mutate_table_cell(fpath, "C1", "K1", "C4", "new_c4_val")
            self.assertTrue(ok, msg)

            lines = fpath.read_text(encoding="utf-8").splitlines()
            cells = split_table_row(lines[2])
            self.assertEqual(len(cells), 8)
            self.assertEqual(cells[0], "K1")
            self.assertEqual(cells[1], "")
            self.assertEqual(cells[2], "val3")
            self.assertEqual(cells[3], "new_c4_val")
            self.assertEqual(cells[4], "val5")
            self.assertEqual(cells[5], "val6")
            self.assertEqual(cells[6], "")
            self.assertEqual(cells[7], "val8")

    def test_mutate_nonexistent_targets_fails_safely(self):
        """Mutations of non-existent rows, columns, or files must fail gracefully without file corruption."""
        content = (
            "| # | Question | Status |\n"
            "|---|---|---|\n"
            "| Q-1 | Test question | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # 1. Non-existent file
            ok, msg = mutate_table_cell(Path(tmpdir) / "NONEXISTENT.md", "#", "Q-1", "Status", "done")
            self.assertFalse(ok)
            self.assertIn("File not found", msg)

            # 2. Non-existent key value
            ok, msg = mutate_table_cell(fpath, "#", "Q-999", "Status", "done")
            self.assertFalse(ok)
            self.assertIn("not found", msg)

            # 3. Non-existent column
            ok, msg = mutate_table_cell(fpath, "#", "Q-1", "NonExistentColumn", "done")
            self.assertFalse(ok)
            self.assertIn("not found", msg)

            # Assert file content remained unmodified
            self.assertEqual(fpath.read_text(encoding="utf-8"), content)

    def test_append_question_auto_id_increment(self):
        """append_question should auto-detect highest Q-id and assign Q-(max+1)."""
        content = (
            "# QUESTIONS\n\n"
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-3 | Question 3 | ans | blocking | open |\n"
            "| Q-15 | Question 15 | ans | non-blocking | resolved |\n"
            "| Q-7 | Question 7 | ans | blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # Append question without explicit ID
            ok, msg = append_question(fpath, "Newly added question", q_type="blocking", status="open")
            self.assertTrue(ok, msg)
            self.assertIn("Q-16", msg)

            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 4)
            self.assertEqual(questions[3]["id"], "Q-16")
            self.assertEqual(questions[3]["question"], "Newly added question")

    def test_append_question_to_file_without_table(self):
        """append_question to a file without existing table creates standard header and first row."""
        content = "# QUESTIONS\n\nNo tables yet.\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            ok, msg = append_question(fpath, "First question ever", qid="Q-1")
            self.assertTrue(ok, msg)

            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["id"], "Q-1")
            self.assertEqual(questions[0]["question"], "First question ever")

    def test_append_handoff_and_parse(self):
        """append_handoff appends a valid block conforming to CHARTER.md."""
        content = "# HANDOFFS\n\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "HANDOFFS.md"
            fpath.write_text(content, encoding="utf-8")

            ok, msg = append_handoff(
                fpath,
                from_role="Frontend",
                to_role="Backend",
                title="Integrate Auth Token API",
                what="Expose /api/v1/auth/token endpoint with JWT refresh.",
                context="Needed for session persistence across browser reloads.",
                done_when="Unit tests for refresh token return 200 OK.",
                status="open",
                date="2026-08-27"
            )
            self.assertTrue(ok, msg)

            handoffs = parse_handoffs(fpath)
            self.assertEqual(len(handoffs), 1)
            self.assertEqual(handoffs[0]["from_role"], "Frontend")
            self.assertEqual(handoffs[0]["to_role"], "Backend")
            self.assertEqual(handoffs[0]["title"], "Integrate Auth Token API")
            self.assertEqual(handoffs[0]["status"], "open")
            self.assertTrue(handoffs[0]["is_open"])

    def test_emoji_as_id_key_search_and_mutate(self):
        """Test searching and mutating with emoji keys."""
        content = (
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| 🚀-1 | Rocket question | Ans | blocking | open |\n"
            "| ⚡-2 | Spark question | Ans | non-blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            ok, msg = mutate_table_cell(fpath, "#", "🚀-1", "Status", "resolved")
            self.assertTrue(ok, msg)

            q_list = parse_questions(fpath)
            self.assertEqual(len(q_list), 2)
            self.assertEqual(q_list[0]["id"], "🚀-1")
            self.assertEqual(q_list[0]["status"], "resolved")
            self.assertEqual(q_list[1]["id"], "⚡-2")
            self.assertEqual(q_list[1]["status"], "open")

    def test_canonical_and_case_insensitive_mutation(self):
        """Table mutation handles column matching case-insensitively and updates target cell."""
        content = (
            "| Role | Status (date) | One-line summary |\n"
            "|---|---|---|\n"
            "| ARCHITECT | active (2026-08-27) | Designing schemas |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "BOARD.md"
            fpath.write_text(content, encoding="utf-8")

            # Mutate with lowercase column names and lowercase key value
            ok, msg = mutate_table_cell(fpath, "role", "architect", "status", "idle (2026-08-28)")
            self.assertTrue(ok, msg)

            boards = parse_board(fpath)
            self.assertEqual(len(boards), 1)
            self.assertEqual(boards[0]["role"], "ARCHITECT")
            self.assertEqual(boards[0]["status"], "idle")
            self.assertEqual(boards[0]["date"], "2026-08-28")



if __name__ == "__main__":
    unittest.main(verbosity=2)
