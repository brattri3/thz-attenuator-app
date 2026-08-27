#!/usr/bin/env python3
"""Launch a git worktree for a specific agent role."""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    parser = argparse.ArgumentParser(description="Create a git worktree for a role")
    parser.add_argument("role", help="Role ID (e.g., frontend, physics)")
    args = parser.parse_args()
    
    role = args.role
    branch_name = f"role/{role}"
    worktree_path = os.path.join(ROOT, ".worktrees", role)
    
    if os.path.exists(worktree_path):
        print(f"Worktree for '{role}' already exists at {worktree_path}")
        return

    print(f"Creating worktree for '{role}'...")
    try:
        # Check if branch exists
        branches = subprocess.check_output(["git", "branch", "--list", branch_name], text=True, cwd=ROOT)
        if branch_name in branches:
            subprocess.check_call(["git", "worktree", "add", worktree_path, branch_name], cwd=ROOT)
        else:
            subprocess.check_call(["git", "worktree", "add", "-b", branch_name, worktree_path], cwd=ROOT)
        print(f"\nWorktree ready at {worktree_path}")
        print(f"To start working: cd .worktrees/{role} && claude (or your preferred agent)")
    except subprocess.CalledProcessError as e:
        print(f"Error creating worktree: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
