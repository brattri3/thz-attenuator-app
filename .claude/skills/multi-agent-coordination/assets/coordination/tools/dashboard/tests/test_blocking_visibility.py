"""
test_blocking_visibility.py - a blocking question must be impossible to walk past.

`PROJECT.md`'s question protocol says a `blocking` question means the role STOPS and makes
no changes until it is answered. So an unanswered one is not an item on a list -- it is a
halted session, and the owner is the only one who can restart it.

Before this, the `Type` column was not parsed at all: "blocking" was a word in a markdown
table that no tool read, and a stopped session looked exactly like a working one.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parents[1]
_ASSETS_DIR = _TESTS_DIR.parents[3]

if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import build_index  # noqa: E402
from coordlib import diagnostics as diag  # noqa: E402

WORKFLOW = _ASSETS_DIR / "dot-github" / "workflows" / "coordination-checks.yml.template"

QUESTIONS = """# QUESTIONS

| # | Question | Owner's answer | Type | Status |
|---|---|---|---|---|
| Q-1 | Which database do we commit to? |  | blocking | open |
| Q-2 | Tabs or spaces? | took the default | non-blocking | resolved |
| Q-3 | Rename the module? |  | non-blocking | open |
| Q-4 | Already answered blocker | yes | blocking | resolved |
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


@pytest.fixture
def coord(tmp_path):
    _write(tmp_path / "QUESTIONS.md", QUESTIONS)
    _write(tmp_path / "HANDOFFS.md", "# HANDOFFS\n")
    return tmp_path


def test_the_type_column_is_actually_parsed(coord):
    """It was not, which is why nothing could act on it."""
    rows = build_index.parse_questions(str(coord / "QUESTIONS.md"))
    by_id = {row["id"]: row for row in rows}
    assert by_id["Q-1"]["type"] == "blocking"
    assert by_id["Q-3"]["type"] == "non-blocking"


def test_only_OPEN_blocking_questions_count(coord):
    """An answered blocker is not a stopped session, and must not keep the check red."""
    text, _, _, blocking = build_index.build_index_text(str(coord))
    assert blocking == 1
    assert "Q-1" in text


def test_blocking_section_comes_before_everything_else(coord):
    """A section below three tables is a section nobody scrolls to."""
    text, _, _, _ = build_index.build_index_text(str(coord))
    assert text.index("BLOCKING") < text.index("QUESTIONS.md — open")


def test_no_blocking_section_when_nothing_is_blocked(tmp_path):
    """A banner that is always present stops carrying information."""
    _write(tmp_path / "QUESTIONS.md",
           "# Q\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | x |  | non-blocking | open |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    text, _, _, blocking = build_index.build_index_text(str(tmp_path))
    assert blocking == 0
    assert "BLOCKING" not in text


def test_an_unrecognised_type_is_reported_not_guessed(tmp_path):
    """The None-means-unrecognised rule: a translated word is never assumed non-blocking."""
    _write(tmp_path / "QUESTIONS.md",
           "# Q\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | x |  | блокирующий | open |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    sink = diag.DiagnosticList()
    rows = build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)
    assert rows[0]["type"] is None
    assert diag.UNKNOWN_TYPE in sink.codes()


def _run(coord, out, *args):
    return subprocess.run(
        [sys.executable, "-B", str(_TOOLS_DIR / "build_index.py"),
         "--coordination-dir", str(coord), "--out", str(out), *args],
        capture_output=True, text=True,
    )


def test_cli_exits_1_only_with_the_flag(coord, tmp_path):
    """Default stays exit 0: an index build is not a gate unless asked to be one."""
    out = tmp_path / "INDEX.md"
    assert _run(coord, out).returncode == 0
    assert _run(coord, out, "--fail-on-blocking").returncode == 1


def test_cli_names_the_blockage_on_stderr(coord, tmp_path):
    result = _run(coord, tmp_path / "INDEX.md", "--fail-on-blocking")
    assert "BLOCKING" in result.stderr
    assert "waiting on the owner" in result.stderr


def test_cli_is_green_once_the_blocker_is_answered(tmp_path):
    _write(tmp_path / "QUESTIONS.md",
           "# Q\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | x | yes | blocking | resolved |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    assert _run(tmp_path, tmp_path / "INDEX.md", "--fail-on-blocking").returncode == 0


@pytest.mark.skill_repo
def test_the_shipped_workflow_wires_the_check_up():
    """A flag no template uses is a flag nobody runs."""
    with open(WORKFLOW, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert "blocking-questions:" in text
    assert "--fail-on-blocking" in text


def test_the_shipped_questions_template_has_no_open_blocker():
    """The scaffold must not ship a project into a red CI check on day one."""
    _, _, _, blocking = build_index.build_index_text(str(_ASSETS_DIR / "coordination"))
    assert blocking == 0


# ---------------------------------------------------------------------------------------
# Duplicate ids
# ---------------------------------------------------------------------------------------

def test_a_reused_id_is_reported(tmp_path):
    """Two roles appending a batch in parallel is the ordinary way this happens."""
    _write(tmp_path / "QUESTIONS.md",
           "# Q\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n"
           "| Q-1 | first | yes | non-blocking | resolved |\n"
           "| Q-1 | second, from another session | no | non-blocking | resolved |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    sink = diag.DiagnosticList()
    rows = build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)
    assert diag.DUPLICATE_ID in sink.codes()
    # Reported, not dropped: the row is perfectly readable, its id just no longer picks out
    # one row, and silently hiding half a journal would be the worse failure.
    assert len(rows) == 2


def test_a_reused_id_across_two_tables_is_reported(tmp_path):
    """The reported case: the template's example batch left in place above a real one."""
    _write(tmp_path / "QUESTIONS.md",
           "# Q\n\n## Example batch\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | example | x | non-blocking | resolved |\n"
           "\n## Real batch\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | the real one | y | non-blocking | resolved |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    sink = diag.DiagnosticList()
    build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)
    assert diag.DUPLICATE_ID in sink.codes()


def test_distinct_ids_report_nothing(tmp_path):
    """The true case: the check must stay silent on an ordinary journal."""
    _write(tmp_path / "QUESTIONS.md", QUESTIONS)
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    sink = diag.DiagnosticList()
    build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)
    assert diag.DUPLICATE_ID not in sink.codes()


def test_the_shipped_template_leaves_q1_free_for_a_real_question(tmp_path):
    """The fix that removes the collision rather than detecting it.

    A project that adds its first real question as `Q-1` without first deleting the example
    batch -- which nothing tells it to do -- must not collide with the shipped rows.
    """
    shipped = (_ASSETS_DIR / "coordination" / "QUESTIONS.md").read_text(encoding="utf-8")
    _write(tmp_path / "QUESTIONS.md", shipped +
           "\n## First real batch\n\n| # | Question | Owner's answer | Type | Status |\n"
           "|---|---|---|---|---|\n| Q-1 | a real one | yes | blocking | resolved |\n")
    _write(tmp_path / "HANDOFFS.md", "# H\n")
    sink = diag.DiagnosticList()
    rows = build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)
    assert diag.DUPLICATE_ID not in sink.codes()
    assert sorted(row["id"] for row in rows) == ["EX-1", "EX-2", "Q-1"]


# ======================================================================================
# A gate that cannot see the signal must not report the signal as absent
# ======================================================================================

_NO_TYPE_COLUMN = (
    "| # | Question | Owner's answer | Status |\n"
    "|---|---|---|---|\n"
    "| Q-1 | Stopped, need a decision | - | open |\n"
)


def test_a_questions_table_without_a_type_column_is_reported(tmp_path):
    """The table parses. That is the problem.

    {id, question, status} is the whole signature, so a table with no Type column is read
    normally and every row classifies as neither blocking nor non-blocking. Before this,
    that produced zero diagnostics -- the tool said nothing at all about a distinction it
    could not make.
    """
    (tmp_path / "QUESTIONS.md").write_text(_NO_TYPE_COLUMN, encoding="utf-8")
    sink = diag.DiagnosticList()
    rows = build_index.parse_questions(str(tmp_path / "QUESTIONS.md"), sink)

    assert [r["id"] for r in rows] == ["Q-1"]
    assert diag.MISSING_TYPE_COLUMN in sink.codes(), [str(d) for d in sink]


def test_the_gate_refuses_to_pass_a_table_it_cannot_classify(tmp_path):
    """`0 blocking` here means "could not tell", not "nothing is stopped".

    --fail-on-blocking is the one check this scaffold ships for a halted session. Against a
    journal with no Type column it used to exit 0 forever, which is the "Open Questions: 0"
    incident wearing a CI badge.
    """
    coord = tmp_path / "coordination"
    coord.mkdir()
    (coord / "QUESTIONS.md").write_text(_NO_TYPE_COLUMN, encoding="utf-8")
    out = tmp_path / "INDEX.md"

    assert _run(coord, out).returncode == 0, "without the flag this is still just a build"

    gated = _run(coord, out, "--fail-on-blocking")
    assert gated.returncode == 2, gated.stdout + gated.stderr
    assert "no Type column" in gated.stderr
    assert "CANNOT GATE" in gated.stderr


def test_the_shipped_template_can_be_gated(tmp_path):
    """The guard must not fire on a normal install, or every project starts red."""
    result = _run(_ASSETS_DIR / "coordination", tmp_path / "INDEX.md", "--fail-on-blocking")
    assert result.returncode == 0, result.stdout + result.stderr
