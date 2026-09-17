"""
test_commit_trailers_hook.py - the PostToolUse commit-trailer hook.

The hook is an asset copied into user projects (assets/dot-claude/hooks/), not part of the
dashboard package, so it is exercised as a subprocess exactly as a harness invokes it.

Both sides are tested throughout, per the skill's references/upstream-feedback.md §4: a check that only
ever proves it stays quiet has moved the failure from "too noisy" to "misses real problems".
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import shipped_hook  # noqa: E402

#: See test_budget_hook.py: resolved for both layouts, per #54.
HOOK = shipped_hook("check-commit-trailers.py")

GOOD_MESSAGE = "[A] a good commit\n\nBody text.\n\nSession: A\nReason: because\n"

#: The measured real-world failure: `Session:` IS in the text, and the blank line before the
#: signature stops git from reading any of it as a trailer block.
BLANK_LINE_MESSAGE = (
    "[A] a bad commit\n\nBody text.\n\nSession: A\n\nCo-Authored-By: Someone <s@e>\n"
)

#: The other documented shape: a value wrapped onto a second line breaks the whole block.
WRAPPED_VALUE_MESSAGE = (
    "[A] a wrapped commit\n\nBody.\n\nSession: A\nReason: this reason is\ncontinued here\n"
)


def _git(root, *args, **kwargs):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          encoding="utf-8", errors="replace", check=True, **kwargs)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    return root


def _commit(root, message, filename="f.txt"):
    (root / filename).write_text(message[:12], encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-F", "-", input=message)


def _run(root, command="git commit -F -", env=None, tool_name="Bash"):
    payload = {"tool_name": tool_name, "tool_input": {"command": command}, "cwd": str(root)}
    return subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        cwd=str(root), input=json.dumps(payload), capture_output=True, text=True, env=env,
    )


def _blocked(result):
    """The parsed hook verdict, or None when it stayed silent."""
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------------------
# The case it exists to catch
# ---------------------------------------------------------------------------------------

def test_a_blank_line_before_a_signature_is_reported(repo):
    _commit(repo, BLANK_LINE_MESSAGE)
    verdict = _blocked(_run(repo))
    assert verdict["decision"] == "block"
    assert "Session" in verdict["reason"] and "Reason" in verdict["reason"]
    assert "a bad commit" in verdict["reason"]


def test_a_wrapped_trailer_value_is_reported(repo):
    _commit(repo, WRAPPED_VALUE_MESSAGE)
    assert _blocked(_run(repo))["decision"] == "block"


def test_a_commit_with_no_trailers_at_all_is_reported(repo):
    """The measured 1-in-7 case: the session simply dropped the block."""
    _commit(repo, "[A] no trailers here\n\nJust a body.\n")
    assert _blocked(_run(repo)) is not None


# ---------------------------------------------------------------------------------------
# The true case must still pass -- silence is the common path
# ---------------------------------------------------------------------------------------

def test_a_well_formed_commit_says_nothing(repo):
    _commit(repo, GOOD_MESSAGE)
    assert _blocked(_run(repo)) is None


def test_a_trailing_signature_after_the_block_is_fine(repo):
    """A signature INSIDE the block, with no blank line, is still one paragraph."""
    _commit(repo, "[A] signed\n\nBody.\n\nSession: A\nReason: because\n"
                  "Co-Authored-By: Someone <s@e>\n")
    assert _blocked(_run(repo)) is None


def test_a_cyrillic_subject_does_not_break_the_hook(repo):
    """Decoding is pinned to UTF-8; the ambient console codepage must not matter."""
    _commit(repo, "[A] почему-то по-русски\n\nТело.\n\nSession: A\nReason: потому что\n")
    assert _blocked(_run(repo)) is None


# ---------------------------------------------------------------------------------------
# Everything that must keep it quiet
# ---------------------------------------------------------------------------------------

def test_a_command_that_is_not_a_commit_is_ignored(repo):
    _commit(repo, BLANK_LINE_MESSAGE)
    assert _blocked(_run(repo, command="git status")) is None


def test_a_non_bash_tool_is_ignored(repo):
    _commit(repo, BLANK_LINE_MESSAGE)
    assert _blocked(_run(repo, command="git commit -m x", tool_name="Edit")) is None


def test_a_stale_head_is_not_reported(repo):
    """A `git commit` that FAILED leaves HEAD where it was. Reporting the previous commit
    would blame the session for something it did not just do.

    Note the field: the hook reads the COMMITTER date (`%ct`), not the author date, which is
    the only one of the two that answers "was this object created just now" -- an amended or
    rebased commit keeps its original author date indefinitely.
    """
    import os
    _commit(repo, BLANK_LINE_MESSAGE)
    _git(repo, "commit", "-q", "--amend", "--no-edit",
         env=dict(os.environ, GIT_COMMITTER_DATE="2001-01-01T00:00:00"))
    assert _blocked(_run(repo)) is None


def test_a_merge_commit_is_exempt(repo):
    """Git writes the merge message; CHARTER.md §4's block is not part of it, and this
    scaffold's own CI makes the same exemption."""
    _commit(repo, GOOD_MESSAGE)
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "[A] side\n\nB.\n\nSession: A\nReason: r\n", filename="side.txt")
    _git(repo, "checkout", "-q", "master") if _has_master(repo) else _git(
        repo, "checkout", "-q", "main")
    _commit(repo, "[A] main\n\nB.\n\nSession: A\nReason: r\n", filename="main.txt")
    _git(repo, "merge", "--no-ff", "-m", "Merge side", "side")
    assert _blocked(_run(repo)) is None


def _has_master(root):
    branches = _git(root, "branch", "--format=%(refname:short)").stdout.split()
    return "master" in branches


def test_a_directory_that_is_not_a_repository_is_ignored(tmp_path):
    assert _blocked(_run(tmp_path)) is None


def test_a_repository_with_no_commits_is_ignored(repo):
    assert _blocked(_run(repo)) is None


def test_unreadable_stdin_is_ignored(repo):
    result = subprocess.run([sys.executable, "-B", str(HOOK)], cwd=str(repo),
                            input="{not json", capture_output=True, text=True)
    assert result.returncode == 0 and not result.stdout.strip()


def test_running_it_interactively_does_not_hang(repo):
    """Issue #15's lesson, applied here from the start rather than after a report."""
    import os
    import pty
    pid, _fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child is replaced immediately
        os.chdir(str(repo))
        os.execv(sys.executable, [sys.executable, "-B", str(HOOK)])
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status)


# ---------------------------------------------------------------------------------------
# Configurability, which exists so a renamed convention cannot report every commit
# ---------------------------------------------------------------------------------------

def test_the_required_keys_can_be_renamed(repo):
    import os
    _commit(repo, "[A] custom keys\n\nB.\n\nTicket: PROJ-1\nWhy: because\n")
    env = dict(os.environ, COORDINATION_TRAILER_KEYS="Ticket,Why")
    assert _blocked(_run(repo, env=env)) is None
    assert _blocked(_run(repo, env=dict(os.environ))) is not None


def test_a_renamed_key_that_is_absent_is_still_reported(repo):
    """Renaming must not turn the check off -- only point it somewhere else."""
    import os
    _commit(repo, GOOD_MESSAGE)
    env = dict(os.environ, COORDINATION_TRAILER_KEYS="Ticket")
    assert _blocked(_run(repo, env=env))["decision"] == "block"
