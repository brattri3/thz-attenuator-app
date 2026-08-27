#!/usr/bin/env python3
"""CLI dashboard for multi-agent coordination.
Aggregates BOARD.md, open issues in INDEX.md, and running git worktrees.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COORD = os.path.join(ROOT, "coordination")

def read_board():
    path = os.path.join(COORD, "BOARD.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            print(f.read().strip())
    else:
        print(f"BOARD.md not found at {path}")

def print_index_summary():
    path = os.path.join(COORD, "INDEX.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            # Simple heuristic to extract open count from headers
            for line in content.splitlines():
                if line.startswith("## ") and "open" in line.lower():
                    print(line)
    else:
        print("INDEX.md not found (Run build_index.py to generate it)")

def get_worktrees():
    try:
        out = subprocess.check_output(["git", "worktree", "list"], text=True, cwd=ROOT)
        print("Git Worktrees:")
        print(out.strip())
    except Exception as e:
        print("Could not list git worktrees.")

def main():
    print("=" * 60)
    print("  MULTI-AGENT COORDINATION STATUS")
    print("=" * 60)
    print("\n[ROLES BOARD]")
    read_board()
    print("\n[OPEN BACKLOG]")
    print_index_summary()
    print("\n[ACTIVE WORKTREES]")
    get_worktrees()
    print("=" * 60)

if __name__ == "__main__":
    main()
