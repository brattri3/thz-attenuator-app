"""
paths.py - locating the repo root and the coordination directory.

Two layouts must both work, and conflating them was a real bug:

  authoring layout   <skill repo>/assets/coordination/...   (this repository)
  installed layout   <project>/coordination/...             (a project using the skill)

git_service.py hardcoded `<root>/assets/.worktrees/`, which only exists in the authoring
layout, while worktree_launcher.py used `<root>/.worktrees/`. They coincided here and
diverged in every installed project, leaving the two tools blind to each other's worktrees.

STABILITY: INTERNAL. Layout discovery is this package's own business. Nothing outside this package should depend on the
names or shapes here; they may change without notice. See the skill's
references/extension-contract.md for what IS promised.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Return the git repository root, or None if `start` is not inside one.

    Asks git first. The fallback walks parents looking for a `.git` entry and tests
    `exists()` rather than `is_dir()`: inside a `git worktree` -- which CHARTER.md §5
    recommends and this scaffold's own tooling creates -- `.git` is a *file*, so an
    is_dir() test walks straight past the worktree root.
    """
    base = Path(start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent

    try:
        result = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root = result.stdout.strip()
        if root:
            return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def find_coordination_dir(start: Optional[Path] = None) -> Optional[Path]:
    """Return the coordination directory, trying the installed layout before the authoring one."""
    root = find_repo_root(start)
    if root is None:
        return None
    for candidate in (root / "coordination", root / "assets" / "coordination"):
        if candidate.is_dir():
            return candidate
    return None


def worktrees_dir(root: Path) -> Path:
    """Where role worktrees live: `<repo root>/.worktrees`.

    Not `assets/.worktrees` -- `assets/` is an artifact of this repository's own layout and
    does not exist in a project that installed the skill.
    """
    return Path(root) / ".worktrees"


def is_within(path: Path, base: Path) -> bool:
    """True if `path` is `base` or lives underneath it, after resolving symlinks.

    Used to reject a role name like `../../evil` before it reaches a filesystem path.
    Written with os.path.commonpath rather than Path.is_relative_to to keep the 3.8 floor
    available if the project ever needs it.
    """
    try:
        resolved = Path(path).resolve()
        anchor = Path(base).resolve()
        return os.path.commonpath([str(resolved), str(anchor)]) == str(anchor)
    except (ValueError, OSError):
        return False
