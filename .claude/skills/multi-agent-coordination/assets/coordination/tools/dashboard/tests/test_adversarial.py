"""
test_adversarial.py - Adversarial Stress & Correctness Suite for parser.py, mutator.py, and build_index.py

Covers:
1. Escaped pipes (\\|) in table cells (math formulas, regex, backtick spans, raw pipes)
2. Cyrillic characters, emojis, and multibyte unicode symbols
3. Strict byte-level line preservation across Windows CRLF (\\r\\n) and Unix LF (\\n)
4. Multi-table files and HANDOFFS.md full status lifecycle (open -> taken -> done -> open)
5. build_index.py compatibility and end-to-end index rebuilding on mutated journals
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

# Ensure dashboard package is in sys.path
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

BUILD_INDEX_PATH = DASHBOARD_DIR.parent / "build_index.py"


class TestAdversarialEscapedPipes(unittest.TestCase):
    """Stress testing escaped pipes, backticks, regex, and formulas in table cells."""

    def test_split_table_row_escaped_pipes(self):
        line = r"| ID | Formula $f(x) = \|x\| + \|y\|$ | `a\|b` regex | normal text |"
        cells = split_table_row(line)
        self.assertEqual(len(cells), 4)
        self.assertEqual(cells[0], "ID")
        self.assertEqual(cells[1], r"Formula $f(x) = \|x\| + \|y\|$")
        self.assertEqual(cells[2], r"`a\|b` regex")
        self.assertEqual(cells[3], "normal text")

    def test_split_table_row_backtick_with_raw_pipe(self):
        line = r'| C1 | `grep -E "a|b" file` | `cat x | grep y` | description |'
        cells = split_table_row(line)
        self.assertEqual(len(cells), 4)
        self.assertEqual(cells[0], "C1")
        self.assertEqual(cells[1], '`grep -E "a|b" file`')
        self.assertEqual(cells[2], "`cat x | grep y`")
        self.assertEqual(cells[3], "description")

    def test_split_table_row_edge_pipes(self):
        # Leading escaped pipe, trailing escaped pipe inside cell
        line = r"| P1 | \|leading pipe | trailing pipe\| | \|double\| |"
        cells = split_table_row(line)
        self.assertEqual(len(cells), 4)
        self.assertEqual(cells[0], "P1")
        self.assertEqual(cells[1], r"\|leading pipe")
        self.assertEqual(cells[2], r"trailing pipe\|")
        self.assertEqual(cells[3], r"\|double\|")

    def test_mutate_preserves_escaped_pipes_in_sibling_cells(self):
        content = (
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            r"| Q-1 | Is $\|x\| + \|y\| \le \|x+y\|$ valid? | Use `a\|b` pattern | blocking | open |" "\n"
            "| Q-2 | Normal question | Normal answer | non-blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # Mutate Q-1 status to resolved
            success, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", "resolved")
            self.assertTrue(success, msg)

            # Re-read raw lines
            raw_lines = fpath.read_text(encoding="utf-8").splitlines()
            q1_line = raw_lines[2]
            self.assertIn(r"$\|x\| + \|y\| \le \|x+y\|$", q1_line)
            self.assertIn(r"`a\|b` pattern", q1_line)
            self.assertIn("resolved", q1_line)

            # Parse with parse_questions
            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 2)
            self.assertEqual(questions[0]["id"], "Q-1")
            self.assertEqual(questions[0]["status"], "resolved")
            self.assertIn("$|x| + |y| <= |x+y|$".replace("<=", r"\le"), questions[0]["question"])

    def test_mutate_cell_value_with_unescaped_pipe_auto_escapes(self):
        content = (
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-1 | Choose branch | Pending | blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # User inputs answer containing raw unescaped pipes
            new_ans = "Use option A | option B | option C"
            success, msg = mutate_table_cell(fpath, "#", "Q-1", "Owner's answer", new_ans)
            self.assertTrue(success, msg)

            raw_text = fpath.read_text(encoding="utf-8")
            # Must be escaped in file
            self.assertIn(r"Use option A \| option B \| option C", raw_text)

            # Must parse back cleanly as 5 columns, with unescaped text in question/answer dict
            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["answer"], "Use option A | option B | option C")
            self.assertEqual(questions[0]["status"], "open")


class TestAdversarialUnicodeCyrillicEmoji(unittest.TestCase):
    """Stress testing Cyrillic, emojis, and multibyte unicode symbols."""

    def test_cyrillic_board_parsing_and_mutation(self):
        content = (
            "# BOARD — роли проекта\n\n"
            "| Роль | Статус (дата) | Описание |\n"
            "|---|---|---|\n"
            "| Архитектор | активен (2026-08-27) | Разработка архитектуры и контрактов |\n"
            "| Тестировщик | в_процессе (2026-08-27) | Написание стресс-тестов |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "BOARD.md"
            fpath.write_text(content, encoding="utf-8")

            records = parse_board(fpath)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["role"], "Архитектор")
            self.assertEqual(records[0]["status"], "активен")
            self.assertEqual(records[0]["date"], "2026-08-27")

            # Mutate Russian role status
            success, msg = mutate_table_cell(
                fpath,
                key_col="роль",
                key_val="Архитектор",
                target_col="статус (дата)",
                new_val="завершено (2026-08-28)"
            )
            self.assertTrue(success, msg)

            updated = parse_board(fpath)
            self.assertEqual(updated[0]["status"], "завершено")
            self.assertEqual(updated[0]["date"], "2026-08-28")

    def test_emoji_and_multibyte_math_symbols(self):
        content = (
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-1 | 🚀 Launch probe? | ⏳ Waiting on 📡 telemetry | ⚡ high-priority | open |\n"
            "| Q-2 | Compute 𝒳 = ∫ 𝒟ϕ e^{iS}? | Use λ-calculus α/β/γ ⚛️ | 🔬 physics | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # Mutate with emojis
            success, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", "✅ approved (🚀 launched)")
            self.assertTrue(success, msg)

            success2, msg2 = mutate_table_cell(fpath, "#", "Q-2", "Owner's answer", "Resolved via 𝒵 = ∫ 𝒟ψ 🌟")
            self.assertTrue(success2, msg2)

            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 2)
            self.assertEqual(questions[0]["status"], "✅ approved (🚀 launched)")
            self.assertEqual(questions[1]["answer"], "Resolved via 𝒵 = ∫ 𝒟ψ 🌟")


class TestAdversarialLineEndings(unittest.TestCase):
    """Stress testing byte-level line ending preservation (CRLF vs LF)."""

    def test_crlf_byte_preservation_table_mutation(self):
        lines = [
            "# QUESTIONS Header\r\n",
            "\r\n",
            "| # | Question | Owner's answer | Type | Status |\r\n",
            "|---|---|---|---|---|\r\n",
            "| Q-1 | First question | Pending | blocking | open |\r\n",
            "| Q-2 | Second question | Fixed | non-blocking | resolved |\r\n",
            "\r\n",
            "End note paragraph.\r\n"
        ]
        raw_bytes_orig = "".join(lines).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_bytes(raw_bytes_orig)

            # Mutate Q-1 in place
            success, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", "resolved")
            self.assertTrue(success, msg)

            raw_bytes_mutated = fpath.read_bytes()
            # Verify no bare \n without \r
            self.assertNotIn(b"\r\r\n", raw_bytes_mutated)
            text = raw_bytes_mutated.decode("utf-8")
            for idx, line in enumerate(text.splitlines(keepends=True)):
                self.assertTrue(line.endswith("\r\n"), f"Line {idx} does not end with CRLF: {repr(line)}")

            # Verify line 0, 1, 3, 5, 6, 7 are byte-for-byte identical to original
            mutated_lines = text.splitlines(keepends=True)
            self.assertEqual(mutated_lines[0], lines[0])
            self.assertEqual(mutated_lines[1], lines[1])
            self.assertEqual(mutated_lines[2], lines[2])
            self.assertEqual(mutated_lines[3], lines[3])
            self.assertEqual(mutated_lines[5], lines[5])
            self.assertEqual(mutated_lines[6], lines[6])
            self.assertEqual(mutated_lines[7], lines[7])

    def test_lf_byte_preservation_table_mutation(self):
        lines = [
            "# QUESTIONS Header\n",
            "\n",
            "| # | Question | Owner's answer | Type | Status |\n",
            "|---|---|---|---|---|\n",
            "| Q-1 | First question | Pending | blocking | open |\n",
            "| Q-2 | Second question | Fixed | non-blocking | resolved |\n",
            "\n",
            "End note paragraph.\n"
        ]
        raw_bytes_orig = "".join(lines).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_bytes(raw_bytes_orig)

            success, msg = mutate_table_cell(fpath, "#", "Q-1", "Status", "resolved")
            self.assertTrue(success, msg)

            raw_bytes_mutated = fpath.read_bytes()
            self.assertNotIn(b"\r", raw_bytes_mutated, "CR introduced into LF file!")

            text = raw_bytes_mutated.decode("utf-8")
            mutated_lines = text.splitlines(keepends=True)
            self.assertEqual(mutated_lines[0], lines[0])
            self.assertEqual(mutated_lines[1], lines[1])
            self.assertEqual(mutated_lines[2], lines[2])
            self.assertEqual(mutated_lines[3], lines[3])
            self.assertEqual(mutated_lines[5], lines[5])
            self.assertEqual(mutated_lines[6], lines[6])
            self.assertEqual(mutated_lines[7], lines[7])

    def test_crlf_preservation_handoff_mutation(self):
        content = (
            "# HANDOFFS\r\n\r\n"
            "## [2026-08-27] FROM RoleA TO RoleB — Setup database\r\n"
            "- What: Configure Postgres instance.\r\n"
            "- Context: Needed for backend API.\r\n"
            "- Done when: Connection pool passes health check.\r\n"
            "- **Status:** open\r\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "HANDOFFS.md"
            fpath.write_bytes(content.encode("utf-8"))

            success, msg = mutate_handoff_status(fpath, "2026-08-27", "Setup database", "taken")
            self.assertTrue(success, msg)

            raw_bytes = fpath.read_bytes()
            self.assertNotIn(b"\r\r\n", raw_bytes)
            text = raw_bytes.decode("utf-8")
            for idx, line in enumerate(text.splitlines(keepends=True)):
                self.assertTrue(line.endswith("\r\n"), f"Line {idx} not CRLF: {repr(line)}")
            self.assertIn("- **Status:** taken\r\n", text)

    def test_append_preserves_dominant_line_endings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # CRLF file
            q_crlf = Path(tmpdir) / "Q_CRLF.md"
            q_crlf.write_bytes(b"# Questions\r\n\r\n| # | Question | Owner's answer | Type | Status |\r\n|---|---|---|---|---|\r\n| Q-1 | Existing | ans | blocking | open |\r\n")
            append_question(q_crlf, "New CRLF question")
            raw_crlf = q_crlf.read_bytes()
            self.assertNotIn(b"\r\r\n", raw_crlf)
            for line in raw_crlf.decode("utf-8").splitlines(keepends=True):
                self.assertTrue(line.endswith("\r\n"), f"Not CRLF: {repr(line)}")

            # LF file
            q_lf = Path(tmpdir) / "Q_LF.md"
            q_lf.write_bytes(b"# Questions\n\n| # | Question | Owner's answer | Type | Status |\n|---|---|---|---|---|\n| Q-1 | Existing | ans | blocking | open |\n")
            append_question(q_lf, "New LF question")
            raw_lf = q_lf.read_bytes()
            self.assertNotIn(b"\r", raw_lf)


class TestAdversarialMultiTableAndLifecycle(unittest.TestCase):
    """Stress testing multi-table batch files and full status lifecycle transitions."""

    def test_multi_table_questions_file(self):
        content = (
            "# QUESTIONS\n\n"
            "## Batch 1: Initial Planning\n\n"
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-1 | Architecture pattern? | Event-driven | blocking | resolved |\n"
            "| Q-2 | Database choice? | PostgreSQL | blocking | open |\n\n"
            "Some narrative discussion text between tables.\n\n"
            "## Batch 2: Implementation Review\n\n"
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-3 | Cache strategy? | Redis LRU | non-blocking | open |\n"
            "| Q-4 | Rate limiter threshold? | 100 req/min | non-blocking | open |\n\n"
            "Another section with notes.\n\n"
            "## Batch 3: Deployment\n\n"
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-5 | Cluster topology? | 3 nodes | blocking | open |\n"
            "| Q-6 | Monitoring stack? | Prometheus/Grafana | non-blocking | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            # Parse initial 6 questions
            q_initial = parse_questions(fpath)
            self.assertEqual(len(q_initial), 6)
            self.assertEqual([q["id"] for q in q_initial], ["Q-1", "Q-2", "Q-3", "Q-4", "Q-5", "Q-6"])

            # Mutate Q-2 in Table 1
            ok, msg = mutate_table_cell(fpath, "#", "Q-2", "Status", "resolved")
            self.assertTrue(ok, msg)

            # Mutate Q-4 in Table 2
            ok, msg = mutate_table_cell(fpath, "#", "Q-4", "Status", "resolved")
            self.assertTrue(ok, msg)

            # Mutate Q-5 in Table 3
            ok, msg = mutate_table_cell(fpath, "#", "Q-5", "Status", "resolved")
            self.assertTrue(ok, msg)

            # Verify all mutations
            q_updated = parse_questions(fpath)
            self.assertEqual(len(q_updated), 6)
            status_map = {q["id"]: q["status"] for q in q_updated}
            self.assertEqual(status_map["Q-1"], "resolved")
            self.assertEqual(status_map["Q-2"], "resolved")
            self.assertEqual(status_map["Q-3"], "open")
            self.assertEqual(status_map["Q-4"], "resolved")
            self.assertEqual(status_map["Q-5"], "resolved")
            self.assertEqual(status_map["Q-6"], "open")

    def test_handoffs_status_lifecycle_transitions(self):
        content = (
            "# HANDOFFS\n\n"
            "## [template]\n"
            "## [YYYY-MM-DD] FROM A TO B — template entry\n"
            "- What: template\n"
            "- Context: template\n"
            "- Done when: template\n"
            "- **Status:** open\n\n"
            "## [2026-08-27] FROM Architect TO Backend — API Schema design\n"
            "- What: Implement OpenAPI 3.0 spec for auth routes.\n"
            "- Context: Frontend needs schema to mock endpoints.\n"
            "- Done when: Spec validates in swagger-cli.\n"
            "- **Status:** open\n\n"
            "## [2026-08-27] FROM QA TO DevOps — CI Test Matrix\n"
            "- What: Add Python 3.12 and 3.14 to GitHub Actions.\n"
            "- Context: Ensure compatibility across versions.\n"
            "- Done when: Matrix runs green on all runners.\n"
            "- **Status:** open\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "HANDOFFS.md"
            fpath.write_text(content, encoding="utf-8")

            # 1. Check initial state
            h_init = parse_handoffs(fpath)
            # Filter non-templates
            real_init = [h for h in h_init if not h["is_template"]]
            self.assertEqual(len(real_init), 2)
            self.assertEqual(real_init[0]["status"], "open")
            self.assertTrue(real_init[0]["is_open"])

            # 2. Transition: open -> taken
            ok, msg = mutate_handoff_status(fpath, "2026-08-27", "API Schema design", "taken")
            self.assertTrue(ok, msg)
            h_taken = [h for h in parse_handoffs(fpath) if not h["is_template"]]
            self.assertEqual(h_taken[0]["status"], "taken")
            self.assertTrue(h_taken[0]["is_open"])

            # 3. Transition: taken -> done
            ok, msg = mutate_handoff_status(fpath, "2026-08-27", "API Schema design", "done")
            self.assertTrue(ok, msg)
            h_done = [h for h in parse_handoffs(fpath) if not h["is_template"]]
            self.assertEqual(h_done[0]["status"], "done")
            self.assertFalse(h_done[0]["is_open"])

            # 4. Transition: done -> open (re-opening handoff)
            ok, msg = mutate_handoff_status(fpath, "2026-08-27", "API Schema design", "open")
            self.assertTrue(ok, msg)
            h_reopen = [h for h in parse_handoffs(fpath) if not h["is_template"]]
            self.assertEqual(h_reopen[0]["status"], "open")
            self.assertTrue(h_reopen[0]["is_open"])

            # Verify the second handoff was NOT affected
            self.assertEqual(h_reopen[1]["title"], "CI Test Matrix")
            self.assertEqual(h_reopen[1]["status"], "open")


class TestAdversarialBuildIndexCompatibility(unittest.TestCase):
    """Stress testing build_index.py execution against files modified by mutator."""

    def test_build_index_compatibility_with_mutated_files(self):
        """Tests that build_index.py parser functions correctly parse files mutated by mutator.py."""
        self.assertTrue(BUILD_INDEX_PATH.exists(), f"build_index.py not found at {BUILD_INDEX_PATH}")
        sys.path.insert(0, str(BUILD_INDEX_PATH.parent))
        import build_index as bi

        with tempfile.TemporaryDirectory() as tmpdir:
            coord_dir = Path(tmpdir) / "coordination"
            coord_dir.mkdir()

            q_file = coord_dir / "QUESTIONS.md"
            h_file = coord_dir / "HANDOFFS.md"
            idx_file = coord_dir / "INDEX.md"

            q_content = (
                "# QUESTIONS\n\n"
                "| # | Question | Owner's answer | Type | Status |\n"
                "|---|---|---|---|---|\n"
                r"| Q-1 | Formula check $\|a\| + \|b\|$? | Yes | blocking | open |" "\n"
                "| Q-2 | Cyrillic вопрос? | Да, проверено 🌟 | non-blocking | resolved |\n"
                "| Q-3 | Another item | Pending | blocking | open |\n"
            )
            q_file.write_text(q_content, encoding="utf-8")

            h_content = (
                "# HANDOFFS\n\n"
                "## [2026-08-27] FROM Alice TO Bob — First handoff\n"
                "- What: Do something.\n"
                "- Context: Reason.\n"
                "- Done when: Done.\n"
                "- **Status:** taken\n\n"
                "## [2026-08-27] FROM Bob TO Charlie — Second handoff\n"
                "- What: Do other thing.\n"
                "- Context: Other reason.\n"
                "- Done when: Complete.\n"
                "- **Status:** done\n"
            )
            h_file.write_text(h_content, encoding="utf-8")

            # Mutate Q-1 to resolved via mutator
            ok, msg = mutate_table_cell(q_file, "#", "Q-1", "Status", "resolved")
            self.assertTrue(ok, msg)

            # Mutate First handoff to done via mutator
            ok, msg = mutate_handoff_status(h_file, "2026-08-27", "First handoff", "done")
            self.assertTrue(ok, msg)

            # Mutate Second handoff to open via mutator
            ok, msg = mutate_handoff_status(h_file, "2026-08-27", "Second handoff", "open")
            self.assertTrue(ok, msg)

            # Test build_index parsing functions on mutated files
            q_rows = bi.parse_questions(str(q_file))
            h_rows = bi.parse_handoffs(str(h_file))

            self.assertEqual(len(q_rows), 3)
            self.assertEqual(len(h_rows), 2)

            q_open = [r for r in q_rows if bi.is_open(r["status"])]
            q_closed = [r for r in q_rows if not bi.is_open(r["status"])]
            h_open = [r for r in h_rows if bi.is_open(r["status"]) or r["status"] == "missing"]
            h_closed = [r for r in h_rows if not bi.is_open(r["status"]) and r["status"] != "missing"]

            self.assertEqual(len(q_open), 1)  # Only Q-3 is open
            self.assertEqual(q_open[0]["id"], "Q-3")
            self.assertEqual(len(q_closed), 2)

            self.assertEqual(len(h_open), 1)  # Second handoff is open
            self.assertEqual(len(h_closed), 1)

            # Render index content using build_index template
            out = []
            out.append("# INDEX — open items in `QUESTIONS.md` and `HANDOFFS.md`\n")
            out.append(f"## QUESTIONS.md — open ({len(q_open)} of {len(q_rows)})\n")
            out.append(bi.render_table(q_open, "id", "who", "To"))
            out.append(f"\n## HANDOFFS.md — open or missing status ({len(h_open)} of {len(h_rows)})\n")
            out.append(bi.render_table(h_open, "date"))
            out.append(f"\n<details><summary>QUESTIONS.md — closed ({len(q_closed)})</summary>\n\n")
            out.append(bi.render_table(q_closed, "id", "who", "To"))
            out.append("\n</details>\n")
            out.append(f"\n<details><summary>HANDOFFS.md — closed ({len(h_closed)})</summary>\n\n")
            out.append(bi.render_table(h_closed, "date"))
            out.append("\n</details>\n")

            idx_file.write_text("\n".join(out), encoding="utf-8")

            # Verify index content parses cleanly via parser.parse_index
            idx_data = parse_index(idx_file)
            self.assertEqual(idx_data["questions_total_count"], 3)
            self.assertEqual(idx_data["questions_open_count"], 1)
            self.assertEqual(idx_data["handoffs_total_count"], 2)
            self.assertEqual(idx_data["handoffs_open_count"], 1)

    def test_build_index_cli_execution(self):
        """Tests that build_index.py CLI executes successfully and writes a valid INDEX.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "INDEX.md"
            res = subprocess.run(
                [sys.executable, str(BUILD_INDEX_PATH), "--out", str(out_file)],
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            self.assertEqual(res.returncode, 0, f"build_index.py CLI failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
            self.assertTrue(out_file.exists())
            idx_data = parse_index(out_file)
            self.assertGreaterEqual(idx_data["questions_total_count"], 0)



if __name__ == "__main__":
    unittest.main(verbosity=2)
