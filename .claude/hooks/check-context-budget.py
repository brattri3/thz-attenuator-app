#!/usr/bin/env python3
"""Cold-start context budget checker. Warns; never blocks.

Checks the files named by .claude/hooks/budget.json against their byte limits and, when any
are over, prints one JSON object with a systemMessage. Exit status is 0 either way unless
--strict is passed: the budget is a cost signal, not a correctness gate, and blocking on it
would make emergency work harder for no safety gain.

Size is measured in UTF-8 bytes with CRLF normalised to LF, so a checkout with Windows line
endings does not appear ~4% larger than the same file on Linux.
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys

DEFAULT_LIMIT = 2400
DEFAULT_GLOB = "coordination/roles/*.md"

#: Claude Code's own published thresholds for an instruction file, used when a rule gives a
#: line limit without a byte one. It targets "under 200 lines per CLAUDE.md file" and skips a
#: file over 4 MiB entirely -- a skip is silent, so the file that most needs to be read is the
#: one that stops being read. Pinning our defaults to the documented numbers means this hook
#: warns before that cliff instead of at some limit we invented.
INSTRUCTION_LINE_TARGET = 200
INSTRUCTION_HARD_BYTES = 4 * 1024 * 1024


def get_project_root(start_dir):
    """Walk up to the project root.

    Prefers git, then a directory containing .claude, then a directory containing .git.

    The `.git` test uses exists(), not isdir(): inside a `git worktree` -- which
    CHARTER.md §5 recommends and this scaffold's own tooling creates -- `.git` is a FILE.
    An isdir() test walks straight past the worktree root, so the hook silently found no
    role files and did nothing in exactly the setup the scaffold recommends.
    """
    start = os.path.abspath(start_dir)
    try:
        result = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        root = result.stdout.strip()
        if root and os.path.isdir(root):
            return root
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    current = start
    while True:
        if os.path.isdir(os.path.join(current, ".claude")):
            return current
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return start
        current = parent


def load_rules(root):
    """Read budget.json into [(glob, limit_bytes), ...].

    Every entry in `files` is honoured, and the glob is used AS a glob. The previous version
    substring-matched the literal string "coordination/roles/*.md" purely to extract
    limit_bytes and then scanned a hardcoded directory, so editing budget.json to point
    anywhere else silently did nothing -- the config was decorative.
    """
    config_path = os.path.join(root, ".claude", "hooks", "budget.json")
    if not os.path.exists(config_path):
        return [(DEFAULT_GLOB, DEFAULT_LIMIT, None)]
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
    except (OSError, ValueError):
        return [(DEFAULT_GLOB, DEFAULT_LIMIT, None)]

    rules = []
    for rule in cfg.get("files", []):
        pattern = rule.get("glob")
        if not pattern:
            continue
        limit_lines = rule.get("limit_lines")
        # A rule may set either limit or both. Defaulting the byte limit only when no line
        # limit was given keeps a lines-only rule from also tripping the 2400-byte default,
        # which would report every instruction file as oversized the day it was added.
        default_bytes = INSTRUCTION_HARD_BYTES if limit_lines else DEFAULT_LIMIT
        rules.append((pattern, rule.get("limit_bytes", default_bytes), limit_lines))
    return rules or [(DEFAULT_GLOB, DEFAULT_LIMIT, None)]


def iter_matches(root, pattern):
    """Yield files under `root` matching a POSIX-style glob, including `**`."""
    normalised = pattern.replace("\\", "/")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if fnmatch.fnmatch(rel, normalised):
                yield rel, full


def measure(path):
    """(bytes, lines) with CRLF normalised, or None if the file cannot be read."""
    try:
        with open(path, "rb") as handle:
            data = handle.read().replace(b"\r\n", b"\n")
    except OSError:
        return None
    return len(data), data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


def should_run(argv_forced):
    """True when this invocation should check.

    SessionStart fires for several sources; only startup and clear re-read the cold-start
    file, so warning on resume/compact is noise. Anything unparseable runs the check --
    failing open is the right default for a warning.

    sys.stdin can be None on Windows for a detached process, and the isatty() call itself
    then raises; both are handled here rather than one line later.
    """
    if argv_forced:
        return True
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return True
        payload = json.loads(sys.stdin.read())
    except Exception:
        return True
    return payload.get("source") in ("startup", "clear")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit 2 when a file is over budget (default: warn, exit 0)")
    ap.add_argument("--json", action="store_true",
                    help="print the findings as JSON on stdout for a CI step to parse")
    ap.add_argument("--force", action="store_true",
                    help="check regardless of the SessionStart source on stdin")
    args = ap.parse_args()

    if not should_run(args.force):
        return 0

    root = get_project_root(os.getcwd())
    oversized = []
    unreadable = []

    for pattern, limit, limit_lines in load_rules(root):
        for rel, full in iter_matches(root, pattern):
            measured = measure(full)
            if measured is None:
                # Never silently skip: a role file nobody can read is not a compliant one.
                unreadable.append(rel)
                continue
            size, lines = measured
            if size > limit:
                oversized.append({"file": rel, "bytes": size, "limit": limit,
                                  "unit": "bytes"})
            elif limit_lines and lines > limit_lines:
                oversized.append({"file": rel, "bytes": lines, "limit": limit_lines,
                                  "unit": "lines"})

    if args.json:
        print(json.dumps({"oversized": oversized, "unreadable": unreadable}))
        return 2 if (args.strict and oversized) else 0

    if not oversized and not unreadable:
        return 0

    parts = []
    if oversized:
        listed = "\n".join(
            f"  - {item['file']} ({item['bytes']} {item.get('unit', 'bytes')} > "
            f"{item['limit']} limit)"
            for item in oversized
        )
        parts.append("[Context budget] Oversized cold-start files:\n" + listed)
    if unreadable:
        parts.append("[Context budget] Could not read: " + ", ".join(unreadable))

    parts.append(
        "\nThis is a soft limit, not an error. It reports the cost of the file every "
        "session pays at cold start.\n"
        "Do NOT delete or compress project content to satisfy it on your own: what to cut "
        "is the human's call. Move resolved detail into ACTIVITY.md and leave a one-line "
        "pointer, or ask the owner."
    )

    # Encode explicitly: on a legacy Windows console, print() uses the codepage and can
    # raise UnicodeEncodeError on non-ASCII content in a file name.
    payload = json.dumps({"systemMessage": "\n".join(parts)}, ensure_ascii=False)
    sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()

    return 2 if (args.strict and oversized) else 0


if __name__ == "__main__":
    raise SystemExit(main())
