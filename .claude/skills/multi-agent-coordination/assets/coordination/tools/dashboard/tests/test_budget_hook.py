"""
test_budget_hook.py - the SessionStart cold-start budget hook.

The hook is an asset copied into user projects (assets/dot-claude/hooks/), not part of the
dashboard package, so it is exercised as a subprocess exactly as Claude Code invokes it.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import shipped_hook  # noqa: E402

#: Resolved rather than hardcoded: this file ships into consumer projects, where the hook
#: lives at `.claude/hooks/` and not at the skill repo's `dot-claude/` staging path (#54).
HOOK = shipped_hook("check-context-budget.py")


def _run(cwd, stdin_text="", *args):
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), *args],
        cwd=str(cwd), input=stdin_text, capture_output=True, text=True,
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / ".claude" / "hooks").mkdir(parents=True)
    (root / "coordination" / "roles").mkdir(parents=True)
    (root / "coordination" / "roles" / "BIG.md").write_text("x" * 300, encoding="utf-8")
    (root / "coordination" / "roles" / "small.md").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    return root


def _write_budget(root, glob, limit):
    (root / ".claude" / "hooks" / "budget.json").write_text(
        json.dumps({"unit": "bytes", "files": [{"glob": glob, "limit_bytes": limit}]}),
        encoding="utf-8",
    )


def test_warns_on_an_oversized_role_file(project):
    _write_budget(project, "coordination/roles/*.md", 100)
    result = _run(project, '{"source":"startup"}')

    assert result.returncode == 0, "the budget warns; it must never block"
    payload = json.loads(result.stdout)
    assert "BIG.md" in payload["systemMessage"]
    assert "small.md" not in payload["systemMessage"]


def test_is_silent_when_everything_fits(project):
    _write_budget(project, "coordination/roles/*.md", 10_000)
    result = _run(project, '{"source":"startup"}')
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_sources_that_do_not_reread_the_cold_start_file(project):
    _write_budget(project, "coordination/roles/*.md", 100)
    for source in ("resume", "compact"):
        result = _run(project, json.dumps({"source": source}))
        assert result.stdout.strip() == "", f"{source} must not warn"


def test_config_glob_is_actually_globbed(project):
    """budget.json used to be decorative.

    The previous hook substring-matched the literal string "coordination/roles/*.md" purely
    to extract limit_bytes, then scanned a hardcoded directory. Any other glob was ignored
    and the limit silently reverted to the built-in default.
    """
    _write_budget(project, "coordination/**/*.md", 1)
    result = _run(project, '{"source":"startup"}', "--json")
    payload = json.loads(result.stdout)
    names = {item["file"] for item in payload["oversized"]}
    assert names == {"coordination/roles/BIG.md", "coordination/roles/small.md"}
    assert all(item["limit"] == 1 for item in payload["oversized"])


def test_survives_absent_stdin(project):
    """sys.stdin can be None for a detached process on Windows; isatty() then raises."""
    _write_budget(project, "coordination/roles/*.md", 100)
    result = subprocess.run(
        [sys.executable, "-B", str(HOOK), "--json"],
        cwd=str(project), stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "BIG.md" in result.stdout


def test_reports_unreadable_files_instead_of_skipping_them(project):
    """A role file nobody can read is not a compliant one.

    The previous hook swallowed every error with a bare `except: continue`.
    """
    _write_budget(project, "coordination/roles/*.md", 100)
    blocked = project / "coordination" / "roles" / "locked.md"
    blocked.write_text("x" * 500, encoding="utf-8")
    blocked.chmod(0o000)
    try:
        result = _run(project, '{"source":"startup"}', "--json")
        payload = json.loads(result.stdout)
        if payload["unreadable"]:  # skipped when running as root, which ignores the mode
            assert "coordination/roles/locked.md" in payload["unreadable"]
    finally:
        blocked.chmod(0o644)


def test_strict_exits_two(project):
    _write_budget(project, "coordination/roles/*.md", 100)
    assert _run(project, '{"source":"startup"}', "--strict", "--json").returncode == 2
    _write_budget(project, "coordination/roles/*.md", 10_000)
    assert _run(project, '{"source":"startup"}', "--strict", "--json").returncode == 0


def test_message_is_english(project):
    """assets/ is an English asset tree; docs/ru/ is the only Russian surface.

    The message was previously hardcoded Russian, and asserted in the past tense that the
    agent had already deleted context ("Вы самостоятельно удалили...") rather than telling
    it not to.
    """
    _write_budget(project, "coordination/roles/*.md", 100)
    message = json.loads(_run(project, '{"source":"startup"}').stdout)["systemMessage"]
    assert message.isascii(), message
    assert "soft limit" in message


def test_finds_the_root_from_a_subdirectory_of_a_git_worktree(project, tmp_path):
    """`.git` is a FILE inside a worktree, and worktrees are this scaffold's own model.

    Root discovery tested `os.path.isdir(".git")`, so when the worktree root has no
    .claude/ of its own the walk-up ran past it to the filesystem root and fell back to the
    starting directory. Run from a subdirectory, that fallback is wrong, coordination/roles
    does not exist there, and the check silently did nothing.
    """
    _write_budget(project, "coordination/roles/*.md", 100)
    # The worktree will have no .claude/, so no budget.json: the hook falls back to its
    # built-in default limit. Size the file past that, leaving root discovery as the only
    # variable this test is measuring.
    (project / "coordination" / "roles" / "BIG.md").write_text("x" * 5000, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=project, check=True, capture_output=True)

    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "-b", "role/qa"],
        cwd=project, check=True, capture_output=True,
    )
    assert (worktree / ".git").is_file(), "a worktree's .git must be a file for this test"
    # The realistic case: .claude/ is not present at the worktree root, which is common
    # since projects often gitignore it.
    shutil.rmtree(worktree / ".claude")

    result = _run(worktree / "coordination", '{"source":"startup"}', "--json", "--force")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert any(item["file"].endswith("BIG.md") for item in payload["oversized"]), (
        "the hook must find the worktree root from a subdirectory"
    )


# ---------------------------------------------------------------------------------------
# Line limits for instruction files
#
# Byte limits suit role files, which are budgeted in tokens. Instruction files are budgeted
# by Claude Code in LINES ("target under 200 lines per CLAUDE.md file"), with a 4 MiB hard
# cliff past which the file is skipped entirely and silently. Warning in the documented unit
# is the point: a limit we invented ourselves would drift from the one that actually bites.
# ---------------------------------------------------------------------------------------

def _write_budget_json(project, payload):
    path = project / ".claude" / "hooks" / "budget.json"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle)


def test_line_limit_reports_in_lines_not_bytes(project):
    _write_budget_json(project, {"files": [
        {"glob": "AGENTS.md", "limit_lines": 200, "limit_bytes": 4194304},
    ]})
    with open(project / "AGENTS.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("line\n" * 250)

    result = _run(project, '{"source":"startup"}', "--json", "--force")
    assert result.returncode == 0, result.stderr
    oversized = json.loads(result.stdout)["oversized"]
    assert [(item["file"], item["bytes"], item["unit"]) for item in oversized] == [
        ("AGENTS.md", 250, "lines")
    ]


def test_line_limited_file_is_not_also_judged_by_the_role_byte_default(project):
    """A lines-only rule must not inherit the 2400-byte role budget.

    Instruction files are legitimately larger than a role file. Falling back to the role
    default would flag every CLAUDE.md the moment the rule was added, and a warning that
    always fires is a warning nobody reads.
    """
    _write_budget_json(project, {"files": [{"glob": "AGENTS.md", "limit_lines": 200}]})
    with open(project / "AGENTS.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("x" * 9000 + "\n")

    result = _run(project, '{"source":"startup"}', "--json", "--force")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["oversized"] == []


def test_line_limit_within_budget_is_silent(project):
    _write_budget_json(project, {"files": [{"glob": "AGENTS.md", "limit_lines": 200}]})
    with open(project / "AGENTS.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("line\n" * 10)

    result = _run(project, '{"source":"startup"}', "--json", "--force")
    assert json.loads(result.stdout)["oversized"] == []


# ---------------------------------------------------------------------------------------
# The resolver itself (#54)
# ---------------------------------------------------------------------------------------

def test_the_hook_this_suite_tests_actually_exists():
    """Whichever tree this is, the constant must point at a real file.

    Trivial-looking, and it is the assertion that was missing: in an installed project this
    path pointed into `dot-claude/`, which the installer renames away, so 29 tests failed on
    a file-not-found that had nothing to do with the hook.
    """
    assert HOOK.is_file(), HOOK


def test_the_resolver_prefers_the_installed_layout(tmp_path, monkeypatch):
    """Both layouts in one tree -- a project that vendored the skill inside itself -- must
    resolve to the hook the project actually runs, not the staging copy."""
    import conftest

    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / "dot-claude" / "hooks").mkdir(parents=True)
    for layout in (".claude", "dot-claude"):
        (tmp_path / layout / "hooks" / "x.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(conftest, "SCAFFOLD_ROOT", tmp_path)
    assert conftest.shipped_hook("x.py") == tmp_path / ".claude" / "hooks" / "x.py"

    (tmp_path / ".claude" / "hooks" / "x.py").unlink()
    assert conftest.shipped_hook("x.py") == tmp_path / "dot-claude" / "hooks" / "x.py"
