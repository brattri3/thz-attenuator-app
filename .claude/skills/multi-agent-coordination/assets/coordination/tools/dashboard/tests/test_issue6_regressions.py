"""
test_issue6_regressions.py - one test per defect reported in issue #6, plus the invariants
that stop them recurring.

Every test here fails against the code as it stood at 2e37500.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import build_index
from coordlib import diagnostics as diag
from coordlib import schema
from parser import parse_board, parse_handoffs, parse_questions

TOOLS_DIR = Path(__file__).resolve().parent.parent.parent
ASSETS_COORDINATION = TOOLS_DIR.parent
BUILD_INDEX_PY = TOOLS_DIR / "build_index.py"


# ======================================================================================
# The phantom template role  (parser.py:86)
# ======================================================================================


def test_shipped_board_template_row_is_not_a_live_role():
    """BOARD.md ships `| \\<ID\\> | active (YYYY-MM-DD) | ... |` as its example row.

    The old guard was `clean_role.startswith("<")`, which the backslash escape defeats, so
    the placeholder rendered as a live role and was counted active in the KPI bar.
    """
    roles = parse_board(ASSETS_COORDINATION / "BOARD.md")
    assert [r["role"] for r in roles] == ["ORCH"]


def test_shipped_questions_template_rows_are_not_live_questions():
    questions = parse_questions(ASSETS_COORDINATION / "QUESTIONS.md")
    assert all(not schema.is_placeholder_text(q["id"]) for q in questions)


# ======================================================================================
# The fenced format example read as a live handoff
# ======================================================================================


def test_fenced_format_example_is_not_a_live_handoff():
    """HANDOFFS.md documents its entry format inside a ``` fence.

    No parser skipped fences, so the *example* was returned as an entry dated "ISO-date"
    with status "open|taken|done". build_index.py happened to drop it (its header regex
    demands a real date) while the dashboard kept it - a seventh way the two disagreed.
    """
    entries = parse_handoffs(ASSETS_COORDINATION / "HANDOFFS.md")
    assert "ISO-date" not in [e["date"] for e in entries]


# ======================================================================================
# One vocabulary, agreed across every caller
# ======================================================================================

_VOCABULARY_CASES = [
    "open", "taken", "done", "resolved", "closed",
    "OPEN", "**open**", "`done`",
    "открыт", "в работе", "решён",
    "in_progress", "in progress",
    "reopened", "not open",
    "", "   ",
]


@pytest.mark.parametrize("value", _VOCABULARY_CASES)
def test_status_classification_is_identical_across_all_callers(value, tmp_path):
    """The anti-regression for the five divergent copies.

    build_index kept its own substring rule while parser.py had two more and components.py
    a fourth, so the same word meant different things in the index, the KPI bar and the
    badge beside it.

    This goes through the real parse, not through a helper only the test calls: a wrapper
    that build_index itself never invokes can agree with `schema` while the index does not.
    """
    questions_md = tmp_path / "QUESTIONS.md"
    questions_md.write_text(
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Does it? | - | blocking | %s |\n" % value,
        encoding="utf-8",
    )
    rows = build_index.parse_questions(str(questions_md))

    assert len(rows) == 1
    assert rows[0]["state"] == schema.classify_item_status(value)


def test_unrecognised_status_is_not_reported_as_closed(tmp_path):
    """The headline symptom: a Russian journal showing "Open Questions: 0".

    is_open must be None, never False - False is indistinguishable from a resolved question.
    """
    questions_md = tmp_path / "QUESTIONS.md"
    questions_md.write_text(
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Первый? | — | blocking | открыт |\n",
        encoding="utf-8",
    )
    diagnostics = []
    rows = parse_questions(questions_md, diagnostics=diagnostics)

    assert len(rows) == 1
    assert rows[0]["is_open"] is None, "unrecognised must not collapse to False"
    assert any(d.code == "unknown-status" and d.observed == "открыт" for d in diagnostics)


# ======================================================================================
# Table identity: the reporter's corruption case, at read time
# ======================================================================================


def test_measurements_table_is_reported_not_read_as_questions(tmp_path):
    """The reporter's QUESTIONS.md ends with a table of physical measurements.

    Anything keying off "the last table in the file" treats those rows as questions. The
    signature check rejects them and names the headers it actually saw.
    """
    questions_md = tmp_path / "QUESTIONS.md"
    questions_md.write_text(
        "## Batch 1\n\n"
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Real question? | yes | blocking | resolved |\n\n"
        "## Measurements attached to Q-1\n\n"
        "| Sample | Value | Unit |\n"
        "|---|---|---|\n"
        "| A | 1.5 | THz |\n",
        encoding="utf-8",
    )
    diagnostics = []
    rows = parse_questions(questions_md, diagnostics=diagnostics)

    assert [r["id"] for r in rows] == ["Q-1"]
    schema_complaints = [d for d in diagnostics if d.code == "unknown-table-schema"]
    assert len(schema_complaints) == 1
    assert "Sample" in schema_complaints[0].observed


# ======================================================================================
# build_index.py CLI
# ======================================================================================


def _run_build_index(coord_dir, out_path, *extra):
    return subprocess.run(
        [sys.executable, "-B", str(BUILD_INDEX_PY),
         "--coordination-dir", str(coord_dir), "--out", str(out_path), *extra],
        capture_output=True, text=True,
    )


@pytest.fixture
def russian_coordination(tmp_path):
    coord = tmp_path / "coordination"
    coord.mkdir()
    (coord / "QUESTIONS.md").write_text(
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Первый? | — | blocking | открыт |\n"
        "| Q-2 | Второй? | Да | blocking | resolved |\n",
        encoding="utf-8",
    )
    (coord / "HANDOFFS.md").write_text(
        "## [2026-08-27] FROM a TO b — Задача\n- What: сделать\n- **Status:** открыт\n",
        encoding="utf-8",
    )
    return coord


def test_build_index_lists_unrecognised_rows_in_the_artifact(russian_coordination, tmp_path):
    """The report must be visible in INDEX.md, not only in a terminal nobody watched."""
    out = tmp_path / "INDEX.md"
    result = _run_build_index(russian_coordination, out)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "Unrecognised" in text
    assert "открыт" in text
    assert "QUESTIONS.md — open (0 of 2)" in text
    # The one genuinely resolved question is still counted as closed.
    assert "closed (1)" in text


def test_build_index_warns_on_stderr_but_exits_zero(russian_coordination, tmp_path):
    """Warn, never block: the budget/diagnostic signals are cost signals, not gates."""
    result = _run_build_index(russian_coordination, tmp_path / "INDEX.md")
    assert result.returncode == 0
    assert "unknown-status" in result.stderr
    assert "открыт" in result.stderr


def test_build_index_strict_exits_two(russian_coordination, tmp_path):
    result = _run_build_index(russian_coordination, tmp_path / "INDEX.md", "--strict")
    assert result.returncode == 2


def test_build_index_is_silent_on_a_clean_journal(tmp_path):
    coord = tmp_path / "coordination"
    coord.mkdir()
    (coord / "QUESTIONS.md").write_text(
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Real? | yes | blocking | resolved |\n",
        encoding="utf-8",
    )
    (coord / "HANDOFFS.md").write_text(
        "## [2026-08-27] FROM a TO b — T\n- What: x\n- **Status:** done\n", encoding="utf-8"
    )
    result = _run_build_index(coord, tmp_path / "INDEX.md")
    assert result.returncode == 0
    assert "WARN" not in result.stderr


# ======================================================================================
# The scaffold must satisfy its own schema
# ======================================================================================


def test_shipped_templates_parse_with_zero_diagnostics():
    """The highest-value invariant here.

    Every parser over every shipped template must report nothing. If the scaffold cannot
    read its own templates cleanly, no project instantiated from it can either.
    """
    diagnostics = []
    parse_board(ASSETS_COORDINATION / "BOARD.md", diagnostics=diagnostics)
    parse_questions(ASSETS_COORDINATION / "QUESTIONS.md", diagnostics=diagnostics)
    parse_handoffs(ASSETS_COORDINATION / "HANDOFFS.md", diagnostics=diagnostics)
    assert [str(d) for d in diagnostics] == []


# ======================================================================================
# One cell value, agreed across every reader
# ======================================================================================

def test_both_readers_return_the_same_string_for_an_escaped_pipe(tmp_path):
    """Two shipped readers of the same bytes must not return different values.

    `dashboard/parser.py` unescaped `\\|` for the question and answer columns;
    `build_index.py` did not. So a question containing a shell pipeline arrived as
    `grep -E "a|b"` through one module and `grep -E "a\\|b"` through the other, and which one
    a consumer saw depended on which import it happened to use. Both now go through
    `md_table.unescape_pipe`, the declared inverse of the `escape_pipe` used on the way out.
    """
    questions_md = tmp_path / "QUESTIONS.md"
    questions_md.write_text(
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Use `grep -E \"a\\|b\"`? | took `a\\|b` | blocking | open |\n",
        encoding="utf-8",
    )

    core = build_index.parse_questions(str(questions_md))[0]
    addon = parse_questions(questions_md)[0]

    assert core["text"] == addon["question"]
    assert 'a|b' in core["text"] and "\\|" not in core["text"]


def test_both_readers_agree_on_an_entry_with_two_status_lines(tmp_path):
    """The second of the four reader divergences #43 listed as blocking.

    `build_index.py` took the FIRST `**Status:**` match in an entry and
    `dashboard/parser.py` the LAST, so an entry carrying two of them was open to one reader
    and done to the other. Both now take the last, matching the shape HANDOFFS.md documents,
    where the status line is the final line of the entry.

    The ambiguity is reported rather than resolved quietly. That also gives
    `malformed-status-line` its first emitter: the code had been declared since the
    diagnostics channel was written and never once raised.
    """
    handoffs = tmp_path / "HANDOFFS.md"
    handoffs.write_text(
        "## [2026-09-09] FROM a TO b - thing\n"
        "- What: do it\n"
        "- **Status:** open\n"
        "- **Status:** done\n",
        encoding="utf-8",
    )

    core_diags = diag.DiagnosticList()
    addon_diags = diag.DiagnosticList()
    core = build_index.parse_handoffs(str(handoffs), core_diags)
    addon = parse_handoffs(handoffs, diagnostics=addon_diags)

    assert core[0]["status"] == addon[0]["status"] == "done"
    for sink in (core_diags, addon_diags):
        assert diag.MALFORMED_STATUS_LINE in sink.codes(), [str(d) for d in sink]


def test_a_single_status_line_is_not_reported(tmp_path):
    """The guard must stay silent on a well-formed entry, or every project starts noisy."""
    handoffs = tmp_path / "HANDOFFS.md"
    handoffs.write_text(
        "## [2026-09-09] FROM a TO b - thing\n"
        "- What: do it\n"
        "- **Status:** open\n",
        encoding="utf-8",
    )
    sink = diag.DiagnosticList()
    build_index.parse_handoffs(str(handoffs), sink)
    assert diag.MALFORMED_STATUS_LINE not in sink.codes(), [str(d) for d in sink]
