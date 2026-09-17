"""
test_adversarial.py - Adversarial correctness suite for parser.py and build_index.py.

Covers:
1. Escaped pipes (\\|) in table cells (math formulas, regex, backtick spans, raw pipes)
2. Cyrillic characters, emojis, and multibyte unicode symbols
3. build_index.py at the command line

It used to cover three more things, all of them properties of the dashboard's write path:
byte-level CRLF/LF preservation across a mutation, status lifecycle transitions driven
through the mutator, and build_index reading files the mutator had just rewritten. Those
went with the write path itself. What survives here is what the parsers still do, and each
of the tests below was already asserting that alongside the mutation it drove.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

# Ensure dashboard package is in sys.path
DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from coordlib import md_table
from parser import (
    split_table_row,
    parse_board,
    parse_questions,
    parse_index,
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


class TestAdversarialUnicodeCyrillicEmoji(unittest.TestCase):
    """Stress testing Cyrillic, emojis, and multibyte unicode symbols."""

    def test_cyrillic_schema_is_refused_and_cyrillic_content_is_preserved(self):
        """Inverted deliberately. This test used to assert that translated table headers and
        translated status values parsed into two live roles.

        They did parse - and then parser.py classified the translated status values as
        closed, so the same board rendered rows that were all silently counted inactive.
        Half-supporting a translated schema is what produced "Roles Active: 0 / 2" on a
        Russian project. The tools now say so instead of guessing.

        The second half of the test is the part that must keep working: Russian PROSE under
        canonical English headers is the supported shape for a non-English project.
        """
        translated_schema = (
            "# BOARD — роли проекта\n\n"
            "| Роль | Статус (дата) | Описание |\n"
            "|---|---|---|\n"
            "| Архитектор | активен (2026-08-27) | Разработка архитектуры |\n"
            "| Тестировщик | в_процессе (2026-08-27) | Написание стресс-тестов |\n"
        )
        canonical_schema = (
            "# BOARD — роли проекта\n\n"
            "| Role | Status (date) | One-line summary |\n"
            "|---|---|---|\n"
            "| Архитектор | active (2026-08-27) | Разработка архитектуры и контрактов |\n"
            "| Тестировщик | idle (2026-08-27) | Написание стресс-тестов |\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "BOARD_translated.md"
            bad.write_text(translated_schema, encoding="utf-8")

            diagnostics = []
            self.assertEqual(parse_board(bad, diagnostics=diagnostics), [])
            self.assertTrue(
                any(d.code == "unknown-table-schema" for d in diagnostics),
                "a translated schema must be reported, not silently skipped",
            )

            good = Path(tmpdir) / "BOARD.md"
            good.write_text(canonical_schema, encoding="utf-8")

            records = parse_board(good)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["role"], "Архитектор")
            self.assertEqual(records[0]["status_known"], "active")
            self.assertEqual(records[0]["date"], "2026-08-27")

    def test_emoji_and_multibyte_math_symbols(self):
        """Emoji and multibyte mathematics survive the parse unchanged.

        This used to write the awkward values in through the mutator and read them back.
        With no writer left, they are written into the fixture directly -- the property
        under test was always the parser's, and a cell is a cell however it got there.
        """
        content = (
            "| # | Question | Owner's answer | Type | Status |\n"
            "|---|---|---|---|---|\n"
            "| Q-1 | \U0001f680 Launch probe? | \u23f3 Waiting on \U0001f4e1 telemetry | \u26a1 high-priority | "
            "\u2705 approved (\U0001f680 launched) |\n"
            "| Q-2 | Compute \U0001d4b3 = \u222b \U0001d49f\u03d5 e^{iS}? | Resolved via \U0001d4b5 = \u222b \U0001d49f\u03c8 \U0001f31f | "
            "\U0001f52c physics | open |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "QUESTIONS.md"
            fpath.write_text(content, encoding="utf-8")

            questions = parse_questions(fpath)
            self.assertEqual(len(questions), 2)
            self.assertEqual(questions[0]["status"], "\u2705 approved (\U0001f680 launched)")
            self.assertEqual(questions[1]["answer"], "Resolved via \U0001d4b5 = \u222b \U0001d49f\u03c8 \U0001f31f")


class TestAdversarialBuildIndexCompatibility(unittest.TestCase):
    """build_index.py at the command line."""

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

    def test_build_index_refuses_a_coordination_dir_that_is_not_there(self):
        """A missing journal directory is an error, not an index reporting nothing open.

        Without the guard the run "succeeds": both journals parse as absent, and the written
        index says zero questions and zero handoffs. That is the failure this scaffold treats
        as its worst -- a journal believed to be empty -- and it is what a typo in
        --coordination-dir, or a scaffold not yet installed, produces.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "INDEX.md"
            res = subprocess.run(
                [sys.executable, str(BUILD_INDEX_PATH),
                 "--coordination-dir", str(Path(tmpdir) / "not-installed-here"),
                 "--out", str(out_file)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn("--coordination-dir", res.stderr)
            self.assertFalse(out_file.exists(), "an unusable run must not write an index")

    def test_a_pipe_in_a_question_does_not_shatter_the_index_table(self):
        """Issue #42: index rows were built by string interpolation, so a `|` in a question
        emitted a row with more columns than its header declared.

        Markdown renderers do not error on that -- they draw a broken table -- and the row
        that breaks is the one whose text was unusual, which is disproportionately the
        interesting one. The check is a round trip: tokenize the rendered row back and count
        cells, rather than eyeballing the string.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            coord = Path(tmpdir) / "coordination"
            coord.mkdir()
            (coord / "QUESTIONS.md").write_text(
                "| # | Question | Owner's answer | Type | Status |\n"
                "|---|---|---|---|---|\n"
                "| Q-1 | Use `grep -E \"a\\|b\"` or a union? | - | blocking | open |\n",
                encoding="utf-8",
            )
            out_file = Path(tmpdir) / "INDEX.md"
            res = subprocess.run(
                [sys.executable, str(BUILD_INDEX_PATH),
                 "--coordination-dir", str(coord), "--out", str(out_file)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

            # The row appears twice by design: once in the BLOCKING section at the top of the
            # index and once in the open-questions table. Both are rendered by the same
            # function, and both must tokenize back to the five columns their header declares.
            written = out_file.read_text(encoding="utf-8")
            rows = [line for line in written.splitlines() if line.startswith("| `Q-1`")]
            self.assertTrue(rows, written)
            for row in rows:
                self.assertEqual(len(split_table_row(row)), 5, row)

            # And the value survives the trip: escaped in the file, bare once tokenized.
            self.assertIn(r"a\|b", rows[0])
            self.assertIn('a|b', md_table.unescape_pipe(split_table_row(rows[0])[-1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
