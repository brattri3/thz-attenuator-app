#!/usr/bin/env python3
"""check_rules.py - validate `.claude/rules/*.md` path globs against documented limits.

Path-scoped rules are the one part of this scaffold that is not a local invention: the
`paths:` frontmatter list is a native Claude Code mechanism, and it has published limits
that fail QUIETLY when exceeded. That is the whole reason this checker exists -- an invalid
glob does not error, it simply matches nothing, so the rule you wrote never loads and
nothing tells you.

The three documented rules, each checked here:

  * A rule's whole `paths:` list shares one budget of 1,000 expanded patterns and 4 MiB.
    Each brace group multiplies: `{a,b}/{c,d}/*.{ts,tsx}` is eight patterns. Over budget,
    Claude Code uses the pattern UNEXPANDED, and its literal braces then match no files.
  * `[` starts a bracket expression. A `[` that cannot be read as one makes the pattern
    invalid: it matches nothing, while the rule's other patterns keep working. A literal
    bracket must be escaped as `\\[`.
  * A rule with no `paths:` key loads unconditionally, like CLAUDE.md itself. That is legal
    and sometimes intended, so it is reported at most as a note, never as a failure.

Stdlib only, and no YAML dependency: the frontmatter shape this needs is a single list of
strings, which is not worth a third-party parser in a scaffold that promises to have none.

    python3 coordination/tools/check_rules.py
    python3 coordination/tools/check_rules.py --rules-dir .claude/rules --strict
"""

import argparse
import json
import re
import sys
from pathlib import Path

PATTERN_BUDGET = 1000
BYTE_BUDGET = 4 * 1024 * 1024

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_LIST_ITEM = re.compile(r"^\s*-\s*(.+?)\s*$")
_BRACE_GROUP = re.compile(r"(?<!\\)\{([^{}]*)\}")


def parse_paths_frontmatter(text):
    """Return the `paths:` list, or None when the file has no `paths:` key.

    Distinguishes "no frontmatter at all" and "frontmatter without paths" from "paths: []",
    because the first two mean *loads unconditionally* and the third means *matches
    nothing* -- opposite outcomes that a truthiness test would collapse into one.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return None
    in_paths = False
    values = []
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^paths\s*:", line):
            in_paths = True
            inline = line.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                body = inline[1:-1].strip()
                if body:
                    values.extend(_unquote(part) for part in body.split(","))
                return values
            continue
        if in_paths:
            item = _LIST_ITEM.match(line)
            if item:
                values.append(_unquote(item.group(1)))
                continue
            if not line.startswith((" ", "\t")):
                in_paths = False
    return values if in_paths or values else None


def _unquote(raw):
    """Strip YAML quoting, undoing double-quote escapes.

    In a double-quoted YAML scalar `"photos \\\\[2024/**"` denotes the glob
    `photos \\[2024/**` -- one backslash, correctly escaping the bracket. Returning the raw
    two-backslash text would make this checker report a valid pattern as an unclosed
    bracket expression, and a checker that cries wolf is worse than no checker.
    Single-quoted scalars process no escapes, so they are returned verbatim.
    """
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        body = text[1:-1]
        if text[0] == '"':
            return body.replace("\\\\", "\\")
        return body
    return text


def expansion_count(pattern):
    """How many patterns one glob expands to. Each brace group multiplies the total."""
    total = 1
    for group in _BRACE_GROUP.findall(pattern):
        total *= max(1, group.count(",") + 1)
    return total


def bracket_error(pattern):
    """Describe an unusable `[`, or None when the pattern's brackets are fine.

    An unescaped `[` with no closing `]` is the case that silently disables a pattern.
    """
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                return (
                    "unclosed `[` at position %d: glob reads it as a bracket expression, so "
                    "this pattern matches nothing. Escape it as `\\[` for a literal bracket."
                    % index
                )
        index += 1
    return None


def check_rule(path):
    """Validate one rule file. Returns (problems, notes, patterns)."""
    problems = []
    notes = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()

    patterns = parse_paths_frontmatter(text)
    if patterns is None:
        notes.append("no `paths:` key - this rule loads unconditionally, like CLAUDE.md")
        return problems, notes, []
    if not patterns:
        problems.append("`paths:` is present but empty, so this rule never loads")
        return problems, notes, []

    expanded = 0
    byte_total = 0
    for pattern in patterns:
        error = bracket_error(pattern)
        if error:
            problems.append("%s: %s" % (pattern, error))
        count = expansion_count(pattern)
        if count > 1:
            expanded += count
            byte_total += count * len(pattern.encode("utf-8"))

    if expanded > PATTERN_BUDGET:
        problems.append(
            "brace expansion produces %d patterns, over the %d budget the whole `paths:` "
            "list shares; over budget the pattern is used unexpanded and its literal braces "
            "match no files" % (expanded, PATTERN_BUDGET)
        )
    if byte_total > BYTE_BUDGET:
        problems.append(
            "brace expansion produces %d bytes, over the %d byte budget" % (byte_total, BYTE_BUDGET)
        )
    return problems, notes, patterns


def find_rules_dir(explicit=None):
    """Walk up from the cwd looking for `.claude/rules`, the only layout a project has.

    The skill's own repository stages rule files under `assets/dot-claude/rules`, and this
    function used to look there too. That made the tool's answer depend on which repository
    it happened to be standing in; `--rules-dir` already says it explicitly.
    """
    if explicit:
        return Path(explicit)
    here = Path.cwd().resolve()
    for base in [here, *here.parents]:
        candidate = base / ".claude" / "rules"
        if candidate.is_dir():
            return candidate
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rules-dir", help="directory of rule files (default: discover)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when any rule has a problem")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rules_dir = find_rules_dir(args.rules_dir)
    if rules_dir is None or not rules_dir.is_dir():
        print("check_rules: no rules directory found", file=sys.stderr)
        return 0

    report = []
    failed = False
    for path in sorted(rules_dir.rglob("*.md")):
        problems, notes, patterns = check_rule(path)
        failed = failed or bool(problems)
        report.append({
            "file": str(path), "patterns": patterns,
            "problems": problems, "notes": notes,
        })

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if (failed and args.strict) else 0

    for entry in report:
        for problem in entry["problems"]:
            print("PROBLEM %s: %s" % (entry["file"], problem), file=sys.stderr)
        for note in entry["notes"]:
            print("note    %s: %s" % (entry["file"], note))
    checked = len(report)
    if not failed:
        print("check_rules: %d rule file(s) checked, no problems" % checked)
    return 1 if (failed and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
