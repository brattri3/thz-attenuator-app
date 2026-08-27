"""
git_service.py - Git repository discovery, porcelain worktree parser, and isolated auto-commit engine.
Adheres strictly to CHARTER.md §4 trailer rules and commit isolation via `git commit --only`.
"""

from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional


class GitService:
    @staticmethod
    def get_repo_root(start_path: Optional[Path] = None) -> Optional[Path]:
        """
        Discover the root of the git repository using git rev-parse with fallback to parent directory search.
        """
        target = start_path or Path.cwd()
        target_dir = target if target.is_dir() else target.parent

        try:
            out = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=target_dir,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            )
            return Path(out.stdout.strip()).resolve()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback: search parents for .git directory or pointer file
            curr = target_dir.resolve()
            for p in [curr] + list(curr.parents):
                if (p / ".git").exists():
                    return p
            return None

    @staticmethod
    def list_worktrees(repo_root: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Runs `git worktree list --porcelain` and parses output into structured worktree records.
        """
        root = repo_root or GitService.get_repo_root()
        if root is None:
            return []

        try:
            out = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

        records: List[Dict[str, Any]] = []
        for block in out.strip().split("\n\n"):
            if not block.strip():
                continue
            wt: Dict[str, Any] = {
                "path": "",
                "head": "",
                "branch": "",
                "is_main": False,
                "role": None,
                "locked": None,
                "prunable": None
            }
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("worktree "):
                    wt_path = Path(line[len("worktree "):].strip()).resolve()
                    wt["path"] = str(wt_path)
                    wt["is_main"] = (wt_path == root)
                elif line.startswith("HEAD "):
                    wt["head"] = line[len("HEAD "):].strip()
                elif line.startswith("branch "):
                    b = line[len("branch "):].strip()
                    if b.startswith("refs/heads/"):
                        b = b[len("refs/heads/"):]
                    wt["branch"] = b
                elif line == "detached":
                    wt["branch"] = "(detached)"
                elif line == "bare":
                    wt["branch"] = "(bare)"
                elif line.startswith("locked"):
                    wt["locked"] = line[len("locked"):].strip() or True
                elif line.startswith("prunable"):
                    wt["prunable"] = line[len("prunable"):].strip() or True

            # Extract role if present in branch or path
            branch_name = wt["branch"]
            if branch_name.startswith("role/"):
                wt["role"] = branch_name[len("role/"):]
            elif ".worktrees" in wt["path"]:
                wt["role"] = Path(wt["path"]).name

            records.append(wt)

        return records

    @staticmethod
    def auto_commit_file(
        file_path: Path,
        message: str,
        trailers: Optional[Dict[str, str]] = None,
        author_role: Optional[str] = None,
        repo_root: Optional[Path] = None,
        max_retries: int = 3,
        retry_delay: float = 0.1
    ) -> Dict[str, Any]:
        """
        Safely commits ONLY the specified file with trailer formatting and lock contention retry.
        Uses `git commit --only <file>` so any other staged or unstaged changes remain untouched.
        """
        root = repo_root or GitService.get_repo_root(file_path)
        if root is None:
            return {"status": "error", "message": "Not inside a git repository"}

        target_file = file_path.resolve()
        try:
            rel_path = target_file.relative_to(root)
        except ValueError:
            return {"status": "error", "message": f"File {file_path} is outside repository root {root}"}

        # Check if file has modifications (avoid creating empty commit error)
        try:
            status_proc = subprocess.run(
                ["git", "status", "--porcelain", str(rel_path)],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            )
            if not status_proc.stdout.strip():
                return {
                    "status": "noop",
                    "message": "No changes detected to commit",
                    "file": str(rel_path)
                }
        except subprocess.CalledProcessError as exc:
            return {
                "status": "error",
                "message": f"git status failed: {exc.stderr.strip()}"
            }

        # Compose isolated commit command
        cmd = ["git", "commit", "--only", str(rel_path), "-m", message]

        all_trailers: Dict[str, str] = {}
        if author_role:
            all_trailers["Role"] = author_role
        if trailers:
            all_trailers.update(trailers)

        for k, v in all_trailers.items():
            cmd.extend(["--trailer", f"{k}: {v}"])

        # Execute with lock contention retry loop
        last_error = ""
        for attempt in range(max_retries):
            try:
                commit_proc = subprocess.run(
                    cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8"
                )
                sha_proc = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8"
                )
                full_sha = sha_proc.stdout.strip()
                return {
                    "status": "success",
                    "sha": full_sha[:7],
                    "full_sha": full_sha,
                    "message": message,
                    "file": str(rel_path),
                    "stdout": commit_proc.stdout.strip()
                }
            except subprocess.CalledProcessError as exc:
                last_error = exc.stderr.strip()
                if exc.returncode == 128 and ("index.lock" in last_error or "Unable to create" in last_error):
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                return {
                    "status": "error",
                    "message": f"Git commit failed (exit code {exc.returncode})",
                    "stderr": last_error
                }
            except FileNotFoundError:
                return {
                    "status": "error",
                    "message": "git executable not found on system PATH"
                }

        return {
            "status": "error",
            "message": f"Git lock contention failed after {max_retries} attempts",
            "stderr": last_error
        }

    @staticmethod
    def create_worktree(role: str, repo_root: Optional[Path] = None) -> Dict[str, Any]:
        """
        Creates a new git worktree for a role at assets/.worktrees/<role> on branch role/<role>.
        """
        root = repo_root or GitService.get_repo_root()
        if root is None:
            return {"status": "error", "message": "Not inside a git repository"}

        clean_role = role.strip()
        branch_name = f"role/{clean_role}"
        worktree_path = root / "assets" / ".worktrees" / clean_role

        if worktree_path.exists():
            return {
                "status": "noop",
                "message": f"Worktree for '{clean_role}' already exists at {worktree_path}",
                "path": str(worktree_path)
            }

        try:
            branches = subprocess.run(
                ["git", "branch", "--list", branch_name],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            ).stdout

            if branch_name in branches:
                subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), branch_name],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8"
                )
            else:
                subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8"
                )

            return {
                "status": "success",
                "message": f"Created worktree for role '{clean_role}'",
                "path": str(worktree_path),
                "branch": branch_name
            }
        except subprocess.CalledProcessError as exc:
            return {
                "status": "error",
                "message": f"Failed to create worktree: {exc.stderr.strip()}"
            }
