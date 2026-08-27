"""
test_git_service.py - Comprehensive Unit Test Suite for GitService.
Tests get_repo_root, list_worktrees, create_worktree, and auto_commit_file.
Asserts strict git isolation (git commit --only), trailer formatting per CHARTER.md §4,
change detection (noop), lock contention retries, and robust error handling.
"""

from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

from git_service import GitService


# ============================================================================
# 1. Tests for GitService.get_repo_root
# ============================================================================

def test_get_repo_root_at_root(mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]
    discovered = GitService.get_repo_root(repo_dir)
    assert discovered == repo_dir.resolve()


def test_get_repo_root_from_nested_dir_and_file(mock_git_repo):
    coord_dir = mock_git_repo["coord_dir"]
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]

    # Discovery from nested subdirectory
    assert GitService.get_repo_root(coord_dir) == repo_dir.resolve()

    # Discovery from file path
    assert GitService.get_repo_root(board_file) == repo_dir.resolve()


def test_get_repo_root_outside_git(tmp_path):
    non_git_dir = tmp_path / "non_git_workspace"
    non_git_dir.mkdir()

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(128, ["git"])), \
         patch("pathlib.Path.exists", return_value=False):
        # When git rev-parse fails and no .git directory exists in parent chain
        discovered = GitService.get_repo_root(non_git_dir)
        assert discovered is None



# ============================================================================
# 2. Tests for GitService.auto_commit_file (Isolation & Trailers)
# ============================================================================

def test_auto_commit_file_success(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]

    # Modify BOARD.md
    board_file.write_text(board_file.read_text(encoding="utf-8") + "\n<!-- modification -->\n", encoding="utf-8")

    res = GitService.auto_commit_file(
        file_path=board_file,
        message="docs: update roles board",
        author_role="lead",
        trailers={"Topic": "dashboard-ui"},
        repo_root=repo_dir
    )

    assert res["status"] == "success"
    assert len(res["sha"]) == 7
    assert len(res["full_sha"]) == 40
    assert res["message"] == "docs: update roles board"
    assert "BOARD.md" in res["file"]

    # Verify git log contains commit and trailers
    log_out = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True
    ).stdout

    assert "docs: update roles board" in log_out
    assert "Role: lead" in log_out
    assert "Topic: dashboard-ui" in log_out


def test_auto_commit_file_strict_isolation(mock_git_repo):
    """
    CRITICAL REQUIREMENT: Modifying and auto-committing File A MUST NOT commit
    other staged or unstaged modifications in File B (via `git commit --only`).
    """
    repo_dir = mock_git_repo["repo_dir"]
    board_file = mock_git_repo["board_file"]

    # Create and stage a secondary file (File B)
    other_file = repo_dir / "UNRELATED_STAGED.txt"
    other_file.write_text("Unrelated staged work\n", encoding="utf-8")
    subprocess.run(["git", "add", "UNRELATED_STAGED.txt"], cwd=repo_dir, check=True)

    # Modify BOARD.md (File A)
    board_file.write_text(board_file.read_text(encoding="utf-8") + "\n| `new_agent` | active | Working |\n", encoding="utf-8")

    # Auto-commit ONLY BOARD.md
    res = GitService.auto_commit_file(
        file_path=board_file,
        message="coord: add new agent to board",
        author_role="worker_1",
        repo_root=repo_dir
    )
    assert res["status"] == "success"

    # Verify that UNRELATED_STAGED.txt is STILL STAGED and was NOT committed
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True
    )
    status_output = status_proc.stdout.strip()
    assert "A  UNRELATED_STAGED.txt" in status_output or "A  \"UNRELATED_STAGED.txt\"" in status_output

    # Check commit files in the latest commit
    show_files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True
    ).stdout.strip()

    assert "BOARD.md" in show_files
    assert "UNRELATED_STAGED.txt" not in show_files


def test_auto_commit_file_noop_when_no_changes(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]

    # File has no changes
    res = GitService.auto_commit_file(
        file_path=board_file,
        message="docs: no changes",
        repo_root=repo_dir
    )

    assert res["status"] == "noop"
    assert "No changes detected" in res["message"]


def test_auto_commit_file_outside_repo(tmp_path, mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("Outside repository", encoding="utf-8")

    res = GitService.auto_commit_file(
        file_path=outside_file,
        message="outside",
        repo_root=repo_dir
    )

    assert res["status"] == "error"
    assert "outside repository" in res["message"].lower()


def test_auto_commit_file_not_in_git_repo(tmp_path):
    non_git_file = tmp_path / "standalone.md"
    non_git_file.write_text("Standalone", encoding="utf-8")

    with patch.object(GitService, "get_repo_root", return_value=None):
        res = GitService.auto_commit_file(non_git_file, "commit message")
        assert res["status"] == "error"
        assert "Not inside a git repository" in res["message"]


def test_auto_commit_file_lock_contention_retry(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]
    board_file.write_text(board_file.read_text(encoding="utf-8") + "\n<!-- lock test -->\n", encoding="utf-8")

    call_count = 0
    orig_run = subprocess.run

    def mock_subprocess_run(cmd, *args, **kwargs):
        nonlocal call_count
        if "commit" in cmd:
            call_count += 1
            if call_count == 1:
                # First attempt fails with index.lock error
                raise subprocess.CalledProcessError(
                    128, cmd, stderr="fatal: Unable to create '.git/index.lock': File exists."
                )
        return orig_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        res = GitService.auto_commit_file(
            file_path=board_file,
            message="docs: retry on lock",
            repo_root=repo_dir,
            max_retries=3,
            retry_delay=0.01
        )
        assert res["status"] == "success"
        assert call_count == 2


def test_auto_commit_file_lock_contention_exhaustion(mock_git_repo):
    board_file = mock_git_repo["board_file"]
    repo_dir = mock_git_repo["repo_dir"]
    board_file.write_text(board_file.read_text(encoding="utf-8") + "\n<!-- lock fail -->\n", encoding="utf-8")

    orig_run = subprocess.run

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "commit" in cmd:
            raise subprocess.CalledProcessError(
                128, cmd, stderr="fatal: Unable to create '.git/index.lock': File exists."
            )
        return orig_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        res = GitService.auto_commit_file(
            file_path=board_file,
            message="docs: will exhaust retries",
            repo_root=repo_dir,
            max_retries=2,
            retry_delay=0.01
        )
        assert res["status"] == "error"
        assert "contention failed" in res["message"].lower()



# ============================================================================
# 3. Tests for list_worktrees and create_worktree
# ============================================================================

def test_list_worktrees(mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]
    worktrees = GitService.list_worktrees(repo_dir)

    assert len(worktrees) == 1
    main_wt = worktrees[0]
    assert main_wt["is_main"] is True
    assert main_wt["branch"] == "main"
    assert main_wt["role"] is None


def test_create_worktree_lifecycle(mock_git_repo):
    repo_dir = mock_git_repo["repo_dir"]

    # 1. Create worktree for worker_1
    res1 = GitService.create_worktree("worker_1", repo_root=repo_dir)
    assert res1["status"] == "success"
    assert res1["branch"] == "role/worker_1"
    assert Path(res1["path"]).exists()

    # 2. Check list_worktrees reflects the new worktree
    worktrees = GitService.list_worktrees(repo_dir)
    assert len(worktrees) == 2
    w1_wt = next(w for w in worktrees if w["branch"] == "role/worker_1")
    assert w1_wt["role"] == "worker_1"
    assert w1_wt["is_main"] is False

    # 3. Attempting to create same worktree again returns noop
    res2 = GitService.create_worktree("worker_1", repo_root=repo_dir)
    assert res2["status"] == "noop"
    assert "already exists" in res2["message"]


def test_list_and_create_worktree_outside_git(tmp_path):
    with patch.object(GitService, "get_repo_root", return_value=None):
        assert GitService.list_worktrees() == []
        res = GitService.create_worktree("role_x")
        assert res["status"] == "error"
        assert "Not inside a git repository" in res["message"]
