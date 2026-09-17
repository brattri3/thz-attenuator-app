#!/usr/bin/env python3
"""PreToolUse hook: refuse a write outside the session's zone in OWNERSHIP.md.

Why this exists. Claude Code's own documentation is explicit that instruction files are
context rather than configuration -- "Claude treats them as context, not enforced
configuration. To block an action regardless of what Claude decides, use a PreToolUse hook
instead." OWNERSHIP.md was pure prose, so "work only in your own zone" held exactly as well
as the model's attention did. This turns it into a real barrier.

Configure the session's identity through the environment; the hook is inert without it:

    COORDINATION_ROLE=frontend claude

Register it with the path anchored to the project -- `"$CLAUDE_PROJECT_DIR/.claude/hooks/..."`,
see the skill's references/setup.md §9. A relative path resolves against the tool call's working
directory, so one `cd` into a subdirectory and this barrier silently stops running (issue #56).
A barrier whose presence depends on the caller's cwd is not a barrier.

Deliberate design choices, each one a decision not to be clever:

  * Unset role, missing OWNERSHIP.md, unparseable matrix, unexpected payload, any exception
    at all -> allow, silently. A coordination aid that halts real work when it is
    misconfigured gets deleted within a day, and rightly.
  * A path no zone claims is ALLOWED. OWNERSHIP.md's own rule for unlisted paths is "add a
    row", not "nobody may write here"; denying by default would block every new file.
  * Only file-writing tools are inspected. A shell command that writes is NOT caught -- see
    "Known limits" below. Overselling this as airtight would be worse than the prose it
    replaces.

Known limits, stated plainly because a barrier you trust wrongly is a hazard:

  * `Bash` is not inspected. Deciding whether `make build` writes into someone else's zone
    means predicting a shell, and a check that is right most of the time invites exactly
    the misplaced confidence this hook exists to remove. Pair it with `permissions.deny`
    for the paths that genuinely must never be touched.
  * It governs the sessions that run it. A teammate on another machine without the hook
    installed is unaffected; `.github/CODEOWNERS` and branch protection are the rail that
    catches that case, which is why `tools/ownership.py` renders one from the same table.
"""

import json
import os
import subprocess
import sys

#: Tools whose input names a file this hook can resolve. `Bash` is deliberately absent.
_PATH_KEYS = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}

ROLE_ENV_VARS = ("COORDINATION_ROLE", "COORDINATION_ROLE_ID")


def find_project_root(start_dir):
    """Walk up to the project root: git first, then `.claude`, then `.git`.

    Kept byte-for-byte compatible with check-context-budget.py, including the `exists()`
    rather than `isdir()` test -- inside a `git worktree`, which this scaffold recommends,
    `.git` is a FILE, and an isdir() test walks straight past the worktree root.
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


def find_ownership_file(root):
    """Locate OWNERSHIP.md and the directory its patterns are relative TO.

    Returns `(ownership_file, base_dir)`. The two differ in this skill's own repository,
    where the scaffold lives under `assets/`: the matrix says `coordination/**`, so paths
    must be made relative to `assets/`, not to the repository root. In an instantiated
    project the two coincide, which is exactly why the distinction is easy to miss and
    worth encoding rather than assuming.
    """
    for relative in (
        os.path.join("coordination", "OWNERSHIP.md"),
        os.path.join("assets", "coordination", "OWNERSHIP.md"),
    ):
        candidate = os.path.join(root, relative)
        if os.path.isfile(candidate):
            return candidate, os.path.dirname(os.path.dirname(candidate))
    return None, None


def load_ownership_module(ownership_file):
    """Import coordlib.ownership from beside the OWNERSHIP.md we found.

    The hook lives in `.claude/hooks/` and the library in `coordination/tools/`, so the
    import path is derived from the matrix's own location rather than assumed.
    """
    tools_dir = os.path.join(os.path.dirname(ownership_file), "tools")
    if not os.path.isdir(tools_dir):
        return None
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        from coordlib import ownership  # noqa: WPS433
    except ImportError:
        return None
    return ownership


def relative_to_base(target, base):
    """POSIX path relative to `base`, or None when the target sits outside it."""
    try:
        relative = os.path.relpath(os.path.abspath(target), os.path.abspath(base))
    except (ValueError, OSError):
        return None
    if relative.startswith(os.pardir + os.sep) or relative == os.pardir:
        return None
    return relative.replace(os.sep, "/")


def deny(reason):
    """Emit the documented PreToolUse denial and stop.

    Exit status stays 0: the JSON decision is what blocks the call, and exit 2 would make
    the raw stderr the message instead of this reason.
    """
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, sys.stdout)
    sys.stdout.write("\n")
    return 0


def evaluate(payload, root=None, role=None):
    """Return a denial reason, or None to allow. Pure, so tests need no subprocess."""
    tool = payload.get("tool_name")
    key = _PATH_KEYS.get(tool)
    if key is None:
        return None

    target = (payload.get("tool_input") or {}).get(key)
    if not target:
        return None

    role = role or next(
        (os.environ[name] for name in ROLE_ENV_VARS if os.environ.get(name)), ""
    ).strip()
    if not role:
        return None

    root = root or find_project_root(payload.get("cwd") or os.getcwd())
    ownership_file, base = find_ownership_file(root)
    if ownership_file is None:
        return None

    module = load_ownership_module(ownership_file)
    if module is None:
        return None

    if not os.path.isabs(target):
        target = os.path.join(payload.get("cwd") or root, target)
    relative = relative_to_base(target, base)
    if relative is None:
        return None

    zones = module.parse_ownership(ownership_file)
    if not zones:
        return None

    zone = module.owner_of(relative, zones)
    if zone is None or zone.owner == role:
        return None

    return (
        "OWNERSHIP.md:{line} gives `{pattern}` to {owner}; this session is {role}. "
        "Writing to {relative} would cross a zone boundary. Request the change through "
        "HANDOFFS.md, or take it up with {owner} directly.".format(
            line=zone.line, pattern=zone.pattern, owner=zone.owner,
            role=role, relative=relative,
        )
    )


def main():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return 0
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    try:
        reason = evaluate(payload)
    except Exception as error:  # noqa: BLE001 - never let a hook fault block a write
        print("check-path-ownership: %s" % error, file=sys.stderr)
        return 0

    if reason is None:
        return 0
    return deny(reason)


if __name__ == "__main__":
    sys.exit(main())
