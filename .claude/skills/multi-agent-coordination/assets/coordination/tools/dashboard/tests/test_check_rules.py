"""
test_check_rules.py - the `.claude/rules/*.md` glob validator.

Every failure mode here is SILENT in Claude Code: an invalid bracket expression matches
nothing, an over-budget brace pattern is used unexpanded and its literal braces match
nothing, and an empty `paths:` list simply never fires. In all three the rule you wrote is
never loaded and nothing tells you. That is what makes a checker worth shipping.
"""

import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1]
_ASSETS_DIR = Path(__file__).resolve().parents[4]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import check_rules  # noqa: E402

SHIPPED_RULES = _ASSETS_DIR / "dot-claude" / "rules"


def _rule(tmp_path, name, text):
    path = tmp_path / name
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def test_unclosed_bracket_is_reported(tmp_path):
    """`photos [2024/**` reads as a bracket expression and matches nothing."""
    path = _rule(tmp_path, "a.md", '---\npaths:\n  - "photos [2024/**"\n---\nbody\n')
    problems, _, _ = check_rules.check_rule(path)
    assert any("unclosed `[`" in p for p in problems)


def test_escaped_bracket_is_accepted(tmp_path):
    """Both quoting styles, which need a DIFFERENT number of backslashes on disk.

    A double-quoted YAML scalar processes escapes, so the bracket is escaped by writing two
    backslashes and YAML hands the glob engine one. A single-quoted scalar processes none,
    so one backslash on disk is already one backslash in the pattern -- writing two there
    would mean a literal backslash followed by an unescaped `[`, which the checker should
    and does still reject.
    """
    double = _rule(tmp_path, "a.md", '---\npaths:\n  - "photos \\\\[2024/**"\n---\nbody\n')
    single = _rule(tmp_path, "b.md", "---\npaths:\n  - 'photos \\[2024/**'\n---\nbody\n")
    assert check_rules.check_rule(double)[0] == []
    assert check_rules.check_rule(single)[0] == []

    wrong = _rule(tmp_path, "c.md", "---\npaths:\n  - 'photos \\\\[2024/**'\n---\nbody\n")
    assert check_rules.check_rule(wrong)[0] != []


def test_valid_bracket_expression_is_accepted(tmp_path):
    path = _rule(tmp_path, "a.md", '---\npaths:\n  - "src/[abc]/**"\n---\nbody\n')
    problems, _, _ = check_rules.check_rule(path)
    assert problems == []


@pytest.mark.parametrize("pattern,count", [
    ("src/**/*.ts", 1),
    ("src/*.{ts,tsx}", 2),
    ("{a,b}/{c,d}/*.{ts,tsx}", 8),
])
def test_brace_expansion_is_counted_multiplicatively(pattern, count):
    assert check_rules.expansion_count(pattern) == count


def test_over_budget_expansion_is_reported(tmp_path):
    """10 x 10 x 10 x 2 = 2000 expanded patterns, twice the documented 1000 budget."""
    group = ",".join("abcdefghij")
    big = "{%s}/{%s}/{%s}/*.{ts,tsx}" % (group, group, group)
    path = _rule(tmp_path, "a.md", '---\npaths:\n  - "%s"\n---\nbody\n' % big)
    problems, _, _ = check_rules.check_rule(path)
    assert any("over the 1000 budget" in p for p in problems)


def test_empty_paths_list_is_a_problem_not_a_note(tmp_path):
    """`paths: []` means "matches nothing"; a missing key means "always loads"."""
    path = _rule(tmp_path, "a.md", "---\npaths: []\n---\nbody\n")
    problems, notes, _ = check_rules.check_rule(path)
    assert any("never loads" in p for p in problems)
    assert notes == []


def test_absent_frontmatter_is_a_note_not_a_problem(tmp_path):
    path = _rule(tmp_path, "a.md", "# always loaded\n")
    problems, notes, patterns = check_rules.check_rule(path)
    assert problems == []
    assert patterns == []
    assert any("loads unconditionally" in n for n in notes)


def test_inline_list_form_is_parsed(tmp_path):
    path = _rule(tmp_path, "a.md", '---\npaths: ["src/**", "lib/**"]\n---\nbody\n')
    _, _, patterns = check_rules.check_rule(path)
    assert patterns == ["src/**", "lib/**"]


@pytest.mark.skill_repo
def test_shipped_example_rule_is_valid():
    """The scaffold must satisfy the checker it ships.

    The directory assertion is not ceremony: with a wrong path this loop iterates zero
    times and the test passes while checking nothing, which is how it first went green.
    """
    shipped = sorted(SHIPPED_RULES.rglob("*.md"))
    assert shipped, "no shipped rules found at %s" % SHIPPED_RULES
    for path in shipped:
        problems, _, _ = check_rules.check_rule(path)
        assert problems == [], "%s: %s" % (path.name, problems)


def test_strict_mode_exits_nonzero_on_a_problem(tmp_path):
    _rule(tmp_path, "bad.md", '---\npaths:\n  - "photos [2024/**"\n---\nbody\n')
    assert check_rules.main(["--rules-dir", str(tmp_path), "--strict"]) == 1
    assert check_rules.main(["--rules-dir", str(tmp_path)]) == 0


def test_find_rules_dir_ignores_an_authoring_layout(tmp_path, monkeypatch):
    """`assets/dot-claude/rules` is this repository's staging path, not a project layout.

    The discovery walk used to accept it, so the tool's answer depended on which repository
    you were standing in. A project that happens to vendor another scaffold under `assets/`
    would have had its rules validated from there instead of from `.claude/rules`.
    """
    staged = tmp_path / "assets" / "dot-claude" / "rules"
    staged.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert check_rules.find_rules_dir() is None

    real = tmp_path / ".claude" / "rules"
    real.mkdir(parents=True)
    assert check_rules.find_rules_dir() == real
