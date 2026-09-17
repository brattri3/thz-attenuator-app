"""
test_ownership.py - the OWNERSHIP.md zone matrix, its CODEOWNERS renderer, and the
PreToolUse hook that enforces it.

Three consumers read the same table and must never disagree: `coordlib.ownership` parses
it, `tools/ownership.py` renders `.github/CODEOWNERS` from it, and
`.claude/hooks/check-path-ownership.py` blocks writes with it. A test that only covered one
would let the other two drift, which is the exact failure the shared parser exists to
prevent.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parents[1]
_ASSETS_DIR = _TESTS_DIR.parents[3]

if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import ownership as ownership_cli  # noqa: E402
from coordlib import diagnostics as diag  # noqa: E402
from coordlib.ownership import matches, owner_of, parse_ownership  # noqa: E402

from conftest import shipped_hook  # noqa: E402

#: See test_budget_hook.py: resolved for both layouts, per #54.
HOOK = shipped_hook("check-path-ownership.py")
SHIPPED_MATRIX = _ASSETS_DIR / "coordination" / "OWNERSHIP.md"

MATRIX = """# OWNERSHIP

## Exclusive zones

| Path | Owner | Others |
|---|---|---|
| *(fill in per role, e.g.)* `src/core/**` | B | read |
| `docs/**` (if a role owns documentation) | \\<ID\\> | read |
| `coordination/**`, `CLAUDE.md` | ORCH | read |
| `coordination/roles/<ID>.md` | **that role, `<ID>`, itself** | read |
| `archive/**` -- frozen layers (see the `archive/README.md` template) | ORCH | read |
| `web/**` | frontend | read |
"""


@pytest.fixture
def matrix(tmp_path):
    path = tmp_path / "OWNERSHIP.md"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(MATRIX)
    return path


# ---------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------

def test_parses_only_actionable_rows(matrix):
    zones = parse_ownership(matrix)
    assert {(z.pattern, z.owner) for z in zones} == {
        ("src/core/**", "B"),
        ("coordination/**", "ORCH"),
        ("CLAUDE.md", "ORCH"),
        ("archive/**", "ORCH"),
        ("web/**", "frontend"),
    }


def test_template_placeholder_row_is_not_an_owner(matrix):
    """`\\<ID\\>` is a template placeholder; obeying it would hand docs/ to a phantom role."""
    zones = parse_ownership(matrix)
    assert all(z.owner != "<ID>" for z in zones)
    assert owner_of("docs/guide.md", zones) is None


def test_prose_owner_cell_is_not_turned_into_a_rule(matrix):
    """"**that role, `<ID>`, itself**" is documentation, not an enforceable id."""
    zones = parse_ownership(matrix)
    assert all("that role" not in z.owner for z in zones)


def test_cross_reference_in_commentary_is_not_a_zone(matrix):
    """A backticked path inside the trailing commentary is a citation, not a claim.

    The shipped matrix writes ``(see the `archive/README.md` template)``. Collecting every
    code span in the cell would register that file as its own zone; only the leading run of
    spans is the claim.
    """
    zones = parse_ownership(matrix)
    assert "archive/README.md" not in {z.pattern for z in zones}


def test_leading_italic_aside_does_not_hide_the_glob(matrix):
    """``*(fill in per role, e.g.)* `src/core/**` `` still yields src/core/**."""
    assert "src/core/**" in {z.pattern for z in parse_ownership(matrix)}


def test_missing_table_is_reported(tmp_path):
    path = tmp_path / "OWNERSHIP.md"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# OWNERSHIP\n\nNo table here yet.\n")
    sink = diag.DiagnosticList()
    assert parse_ownership(path, diagnostics=sink) == []
    assert diag.UNKNOWN_TABLE_SCHEMA in sink.codes()


def test_absent_file_is_not_an_error(tmp_path):
    assert parse_ownership(tmp_path / "nope.md") == []


# ---------------------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("pattern,path,expected", [
    ("src/core/**", "src/core/engine.py", True),
    ("src/core/**", "src/core/deep/nested/x.py", True),
    ("src/core/**", "src/core", True),
    ("src/core/**", "src/corex/engine.py", False),
    ("src/core/**", "other/src/core/x.py", False),
    ("CLAUDE.md", "CLAUDE.md", True),
    ("CLAUDE.md", "docs/CLAUDE.md", False),
    ("web/*", "web/index.html", True),
    ("web/*", "web/a/index.html", False),
])
def test_glob_semantics(pattern, path, expected):
    """`*` must not cross a `/`; that is why fnmatch is unusable here."""
    assert matches(pattern, path) is expected


@pytest.mark.parametrize("pattern,path", [
    (".github/**", ".github/workflows/ci.yml"),
    (".github/**", ".github"),
    (".claude/**", ".claude/hooks/check-context-budget.py"),
    (".config/app/**", ".config/app/settings.json"),
])
def test_zone_on_a_dotted_directory_matches(pattern, path):
    """Regression: a zone whose top-level directory starts with a dot.

    Normalisation used `lstrip("./")`, which strips leading `.` and `/` CHARACTERS rather
    than the `./` prefix, so `.github/workflows/ci.yml` became `github/workflows/ci.yml`
    and a `.github/**` zone matched nothing. The ownership hook therefore permitted writes
    into `.github/` no matter who owned it, and `ownership.py` emitted a CODEOWNERS rule
    covering no files -- both failing silently, in the direction of allowing too much.
    """
    assert matches(pattern, path) is True


def test_leading_dot_slash_is_still_stripped():
    """The prefix the old code meant to remove must still be removed."""
    assert matches("docs/**", "./docs/guide.md") is True


def test_most_specific_zone_wins(tmp_path):
    path = tmp_path / "OWNERSHIP.md"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "| Path | Owner |\n|---|---|\n"
            "| `coordination/**` | ORCH |\n"
            "| `coordination/roles/shared/**` | qa |\n"
        )
    zones = parse_ownership(path)
    assert owner_of("coordination/BOARD.md", zones).owner == "ORCH"
    assert owner_of("coordination/roles/shared/notes.md", zones).owner == "qa"


def test_unclaimed_path_has_no_owner(matrix):
    """Unlisted is not forbidden - the matrix's own rule is "add a row"."""
    assert owner_of("some/new/area.py", parse_ownership(matrix)) is None


# ---------------------------------------------------------------------------------------
# CODEOWNERS rendering
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("glob,expected", [
    ("src/core/**", "/src/core/"),
    ("archive/**", "/archive/"),
    ("CLAUDE.md", "/CLAUDE.md"),
    ("web/*.html", "/web/*.html"),
])
def test_codeowners_pattern_translation(glob, expected):
    """A trailing slash already means "and everything under it" in CODEOWNERS syntax."""
    assert ownership_cli.to_codeowners_pattern(glob) == expected


def test_codeowners_orders_least_specific_first(matrix):
    """GitHub applies the LAST matching rule, so the specific zone must come last."""
    text = ownership_cli.render(parse_ownership(matrix), {"ORCH": "@alice"})
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    positions = {line.split()[0]: index for index, line in enumerate(body)}
    assert positions["/coordination/"] < positions["/src/core/"]


def test_unmapped_role_becomes_a_visible_placeholder(matrix):
    """Dropping the line would read as "nobody owns this", which is the opposite of true."""
    text = ownership_cli.render(parse_ownership(matrix), {"ORCH": "@alice"})
    assert "@<B_GITHUB_USER>" in text
    assert "Unmapped roles" in text
    assert "B" in text


def test_bare_handle_gets_an_at_sign(matrix):
    text = ownership_cli.render(parse_ownership(matrix), {"ORCH": "alice"})
    assert "@alice" in text


def test_check_mode_detects_drift(tmp_path, matrix):
    coord = tmp_path / "coordination"
    coord.mkdir()
    os.replace(str(matrix), str(coord / "OWNERSHIP.md"))
    target = tmp_path / "CODEOWNERS"

    written = ownership_cli.main(
        ["--coordination-dir", str(coord), "--map", "ORCH=@alice", "-o", str(target)])
    assert written == 0

    unchanged = ownership_cli.main(
        ["--coordination-dir", str(coord), "--map", "ORCH=@alice", "--check", "-o", str(target)])
    assert unchanged == 0

    with open(target, "a", encoding="utf-8") as handle:
        handle.write("/sneaky/ @someone\n")
    drifted = ownership_cli.main(
        ["--coordination-dir", str(coord), "--map", "ORCH=@alice", "--check", "-o", str(target)])
    assert drifted == 1


# ---------------------------------------------------------------------------------------
# The PreToolUse hook
# ---------------------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "coordination").mkdir(parents=True)
    (root / ".claude").mkdir()
    with open(root / "coordination" / "OWNERSHIP.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MATRIX)
    tools = root / "coordination" / "tools"
    tools.mkdir()
    import shutil
    shutil.copytree(_TOOLS_DIR / "coordlib", tools / "coordlib")
    return root


def _run_hook(root, payload, role=None):
    env = dict(os.environ)
    env.pop("COORDINATION_ROLE", None)
    env.pop("COORDINATION_ROLE_ID", None)
    if role is not None:
        env["COORDINATION_ROLE"] = role
    return subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        cwd=str(root), input=json.dumps(payload), capture_output=True, text=True, env=env,
    )


def _edit(root, relative):
    return {"tool_name": "Edit", "cwd": str(root),
            "tool_input": {"file_path": str(root / relative)}}


def _decision(result):
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_hook_denies_a_write_outside_the_session_zone(project):
    result = _run_hook(project, _edit(project, "coordination/BOARD.md"), role="frontend")
    assert result.returncode == 0, result.stderr
    assert _decision(result) == "deny"
    reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "ORCH" in reason and "coordination/**" in reason


def test_hook_allows_the_owner(project):
    assert _decision(_run_hook(project, _edit(project, "coordination/BOARD.md"), "ORCH")) is None


def test_hook_allows_an_unclaimed_path(project):
    """Denying by default would block every new file the project ever adds."""
    assert _decision(_run_hook(project, _edit(project, "notes.md"), "frontend")) is None


def test_hook_is_inert_without_a_configured_role(project):
    """An unconfigured install must never block work."""
    assert _decision(_run_hook(project, _edit(project, "coordination/BOARD.md"))) is None


def test_hook_ignores_bash(project):
    """Documented limit: a shell command that writes is not caught, and must not pretend."""
    payload = {"tool_name": "Bash", "cwd": str(project),
               "tool_input": {"command": "rm -rf coordination"}}
    assert _decision(_run_hook(project, payload, "frontend")) is None


def test_hook_survives_malformed_stdin(project):
    result = subprocess.run(
        [sys.executable, "-B", str(HOOK)], cwd=str(project),
        input="not json at all", capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_hook_allows_a_write_outside_the_project(project, tmp_path):
    outside = tmp_path / "elsewhere.md"
    payload = {"tool_name": "Write", "cwd": str(project),
               "tool_input": {"file_path": str(outside)}}
    assert _decision(_run_hook(project, payload, "frontend")) is None


def test_hook_is_inert_without_coordlib(tmp_path):
    """A project with a matrix but no tools/ must degrade to allow, not crash."""
    root = tmp_path / "bare"
    (root / "coordination").mkdir(parents=True)
    with open(root / "coordination" / "OWNERSHIP.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MATRIX)
    result = _run_hook(root, _edit(root, "coordination/BOARD.md"), "frontend")
    assert result.returncode == 0
    assert _decision(result) is None


# ---------------------------------------------------------------------------------------
# The shipped template must satisfy its own parser
# ---------------------------------------------------------------------------------------

def test_shipped_matrix_parses_without_diagnostics():
    sink = diag.DiagnosticList()
    parse_ownership(SHIPPED_MATRIX, diagnostics=sink)
    assert list(sink.codes()) == [], [str(item) for item in sink]


def test_shipped_matrix_claims_the_coordination_directory():
    """The one zone the scaffold asserts about itself, in every project it installs into."""
    zones = parse_ownership(SHIPPED_MATRIX)
    zone = owner_of("coordination/BOARD.md", zones)
    assert zone is not None and zone.owner == "ORCH"


def test_control_character_diagnostic_points_at_the_real_line(tmp_path):
    """A jump target that is wrong is worse than no jump target.

    The emitter destructured `scan_control_characters`, which yields
    (line number, description), as (offset, char) and then recomputed the line by counting
    newlines within the first N characters -- where N was already a line number. So the
    further down the file the damage sat, the more confidently the diagnostic pointed
    somewhere else, and `observed` carried the description instead of anything observed.
    """
    matrix = tmp_path / "OWNERSHIP.md"
    padding = "\n".join("Prose line %d, nothing wrong with it." % n for n in range(1, 40))
    matrix.write_text(
        padding + "\n"
        "| Path | Owner |\n"
        "|---|---|\n"
        "| `src/**` | dev |\n"
        "| `docs/\x07**` | writer |\n",
        encoding="utf-8",
    )

    sink = diag.DiagnosticList()
    parse_ownership(matrix, diagnostics=sink)

    found = [item for item in sink if item.code == diag.CONTROL_CHARACTER]
    assert len(found) == 1, [str(item) for item in sink]
    assert found[0].line == 43, str(found[0])
    assert "0x07" in found[0].detail
