#!/usr/bin/env python3
"""PostToolUse hook: report a commit whose trailers git itself did not parse.

CHARTER.md §4 requires the trailer block to be the last paragraph, with a blank line before
it and none inside it, because that is what `git interpret-trailers` requires. The failure
mode is that the text looks right to a human and is invisible to git: a blank line before a
`Co-Authored-By:` signature, or a `Reason:` value wrapped onto a second line, and the whole
block stops being a trailer block. Nothing says so at commit time.

Two measurements, from two different projects, are why this ships rather than staying a
suggestion in the charter:

  * In the project this scaffold came from, 10 of 29 commits in one week carried a `Session:`
    trailer that git did not recognise. The rule was in the charter the whole time.
  * In a later controlled run, 1 of 7 commits made by role sessions had no trailer block at
    all -- from a session that had read this same CHARTER.md minutes earlier.

An LLM-driven session reading a rule does not reliably self-enforce it. That is the entire
argument for a hook, and CHARTER.md §4 already makes it ("a rule enforced by a hook stays
true; a rule that only lives in this document rots the moment nobody's checking").

**How it decides.** It does not read the command. Parsing a `git commit` invocation to find
the message means parsing a shell -- heredocs, quoting, `-F -` -- and getting it subtly wrong.
Instead it asks git what git sees on the resulting commit, which is the only authority on the
question this hook exists to answer.

**On inspecting `Bash` at all.** `check-path-ownership.py` deliberately refuses to, and that
is not a contradiction: it would have to *predict*, before the fact, whether a shell command
writes into someone's zone, and a prediction that is usually right invites exactly the
misplaced confidence a barrier must not have. This hook predicts nothing. It runs after the
command, inspects a commit that already exists, and asks git a question with a definite
answer. The costs of being wrong are different too -- a wrongly blocked write stops real work,
a spurious message here costs one line of output.

Wire it up per the skill's `references/setup.md §9` (it is opt-in, like the ownership hook):

    {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command",
         "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/check-commit-trailers.py\""}]}]}}

The path is anchored to the project rather than written relative, and that is not redundant
quoting to tidy away: a relative command resolves against the TOOL CALL's working directory.
One `cd` into a subdirectory and the file is not there any more, so the hook stops running --
reported live in issue #56, where a write barrier vanished because a session had changed
directory.

Deliberate choices, each a decision not to be clever:

  * Any doubt -> stay silent. Not a git repository, no commits yet, a `git commit` that
    failed, an unreadable payload, any exception: exit 0 saying nothing. A commit that
    already landed is not made better by a hook that fires on unrelated commands.
  * `decision: block` returns the reason to the session, it does not undo anything. The
    commit exists; the session fixes it with `git commit --amend` and moves on.
  * A merge commit is skipped. Git generates its message, and CHARTER.md §4's block is not
    part of it -- the same exemption this scaffold's CI workflow already makes.
  * The required keys are overridable. A project that renamed them in its own CHARTER.md
    would otherwise have every single commit reported, which is the fastest way to get a
    hook deleted. Silence when misconfigured is the house rule everywhere else in here.
"""

import json
import os
import subprocess
import sys
import time

#: What CHARTER.md §4's block is made of. Override for a project that renamed them:
#:     COORDINATION_TRAILER_KEYS=Session,Reason,Ticket
DEFAULT_KEYS = ("Session", "Reason")
KEYS_ENV_VAR = "COORDINATION_TRAILER_KEYS"

#: A `git commit` that failed leaves HEAD where it was, and this hook must not report a
#: commit made an hour ago because an unrelated command mentioned one. Anything older than
#: this is treated as "not the commit we just made".
FRESHNESS_SECONDS = 120


def required_keys():
    raw = os.environ.get(KEYS_ENV_VAR, "")
    keys = tuple(part.strip() for part in raw.split(",") if part.strip())
    return keys or DEFAULT_KEYS


def _git(cwd, *args, **kwargs):
    """git stdout, or None for any failure at all -- absence is the only signal used.

    Decoding is pinned to UTF-8 rather than the ambient console codepage: a Cyrillic commit
    subject on a Windows console otherwise raises inside the hook, and a hook that throws on
    a perfectly good commit is worse than no hook.
    """
    timeout = kwargs.pop("timeout", 10)
    try:
        result = subprocess.run(
            ["git", "-C", cwd] + list(args),
            capture_output=True, encoding="utf-8", errors="replace",
            check=True, timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return None
    return result.stdout


def mentions_a_commit(payload):
    """True when this Bash call plausibly made a commit.

    A substring is the right precision here. The hook does not act on this answer, it only
    uses it to decide whether asking git is worth the two subprocess calls; git's own view
    of HEAD is what actually decides anything.
    """
    if payload.get("tool_name") not in (None, "", "Bash"):
        return False
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        # Not every harness passes structured tool input; the raw payload still carries it.
        command = json.dumps(payload, ensure_ascii=False)
    return "git commit" in command


def unparsed_keys(cwd, keys, now=None):
    """The required keys git does NOT see on HEAD, or () when there is nothing to say."""
    if _git(cwd, "rev-parse", "--git-dir") is None:
        return ()

    parents = _git(cwd, "rev-list", "--parents", "-n", "1", "HEAD")
    if not parents:
        return ()
    if len(parents.split()) > 2:
        return ()

    committed_at = _git(cwd, "log", "-1", "--format=%ct")
    try:
        age = (time.time() if now is None else now) - int((committed_at or "").strip())
    except ValueError:
        return ()
    if age > FRESHNESS_SECONDS:
        return ()

    missing = []
    for key in keys:
        seen = _git(cwd, "log", "-1", "--format=%%(trailers:key=%s,valueonly)" % key)
        if seen is None or not seen.strip():
            missing.append(key)
    return tuple(missing)


def reason_for(subject, missing):
    return (
        "Commit \"{subject}\": git does NOT parse the trailer {keys}. The text may well be "
        "there -- git's parser is not seeing it, and that is what every tool reading this "
        "history will do too. It is almost always one of two things: a blank line between "
        "the trailers and a signature such as Co-Authored-By, or a value wrapped onto a "
        "second line. CHARTER.md §4: the block is the LAST paragraph, with a blank line "
        "before it, none inside it, and one line per trailer. Fix it in place with "
        "`git commit --amend`, then confirm git agrees: "
        "`git log -1 --format='%(trailers:key={first},valueonly)'`"
    ).format(subject=subject, keys=" and ".join(missing), first=missing[0])


def main():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return 0
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    try:
        if not mentions_a_commit(payload):
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        missing = unparsed_keys(cwd, required_keys())
        if not missing:
            return 0
        subject = (_git(cwd, "log", "-1", "--format=%s") or "").strip()[:70]
    except Exception as error:  # noqa: BLE001 - a hook fault must never derail a session
        print("check-commit-trailers: %s" % error, file=sys.stderr)
        return 0

    payload = json.dumps(
        {"decision": "block", "reason": reason_for(subject, missing)}, ensure_ascii=False)
    sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
