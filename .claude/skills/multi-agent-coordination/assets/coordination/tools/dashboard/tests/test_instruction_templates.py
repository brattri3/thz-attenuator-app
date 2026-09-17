"""
test_instruction_templates.py - the AGENTS.md / CLAUDE.md template split.

Claude Code reads CLAUDE.md and does NOT read AGENTS.md. The split therefore only works if
CLAUDE.md.template actually imports the other file; drop that one line and every
vendor-neutral instruction silently stops reaching the session, with no error anywhere.
"""

import re
import subprocess
from pathlib import Path

import pytest

_ASSETS_DIR = Path(__file__).resolve().parents[4]
AGENTS = _ASSETS_DIR / "AGENTS.md.template"
CLAUDE = _ASSETS_DIR / "CLAUDE.md.template"

LINE_TARGET = 200


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


@pytest.mark.skill_repo
def test_claude_template_imports_agents_on_its_first_line():
    """The import must not sit inside a code span or fence, where it is not parsed."""
    first = _read(CLAUDE).splitlines()[0].strip()
    assert first == "@AGENTS.md"


@pytest.mark.skill_repo
def test_both_templates_are_within_the_documented_line_target():
    """Claude Code targets under 200 lines per instruction file, and both load at launch."""
    for path in (AGENTS, CLAUDE):
        assert len(_read(path).splitlines()) <= LINE_TARGET, path.name


@pytest.mark.skill_repo
def test_claude_only_commands_stay_out_of_the_vendor_neutral_file():
    """A `claude` invocation in AGENTS.md is an instruction other agents cannot follow."""
    agents = _read(AGENTS)
    for token in ("claude agents", "claude -n", ".claude/rules", "/rename"):
        assert token not in agents, "%r belongs in CLAUDE.md.template" % token


@pytest.mark.skill_repo
def test_claude_template_carries_the_tool_specific_half():
    claude = _read(CLAUDE)
    for token in ("claude agents --json", ".claude/rules", "COORDINATION_ROLE"):
        assert token in claude


@pytest.mark.skill_repo
def test_templates_have_no_control_bytes_and_are_lf_only():
    for path in (AGENTS, CLAUDE):
        raw = _read(path)
        assert "\r" not in raw, path.name
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw), path.name


# ---------------------------------------------------------------------------------------
# Shipped files must not point at paths that only exist in the skill
# ---------------------------------------------------------------------------------------

_CITATION = re.compile(r"references/\w+\.md")


def _shipped_files():
    """Every file under assets/ that a project receives, tracked by git."""
    listed = subprocess.run(
        ["git", "ls-files", "assets/"], cwd=str(_ASSETS_DIR.parent),
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return [_ASSETS_DIR.parent / name for name in listed]


@pytest.mark.skill_repo
def test_no_shipped_file_points_at_the_skills_references_as_if_local():
    """`references/` stays in the skill; `assets/` is what lands in a project.

    A shipped file citing one of those paths reads as project-relative and resolves to nothing
    there -- except for a session that happens to have the skill installed, which is the worst
    version: a pointer that works for some readers and silently fails for others. Naming the
    skill on the same line is the whole fix, and this keeps it from regressing.

    Matched as a real document path, so a fixture containing an escape like `\\references/y`
    is not mistaken for a citation.
    """
    offenders = []
    for path in _shipped_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _CITATION.search(line) and "skill" not in line:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "shipped files cite the skill's references/ without saying so:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.skill_repo
def test_every_shipped_writer_pins_the_line_ending():
    """A generated tree must not change shape with the platform that generated it.

    `open(..., "w")` without `newline=` translates every "\n" to `os.linesep`, so on Windows
    a generated file gains CRLF. `ownership.py` and `coordlib/manifest.py` already forced
    "\n"; `build_index.py` and `kpi_git.py` did not, which meant INDEX.md and the KPI JSON
    changed shape with the machine that produced them while CODEOWNERS and
    .scaffold-version, written beside them, did not.

    This is asserted over the source rather than by writing a file, because on a POSIX
    runner the platform default IS "\n" -- a behavioural test here passes whether or not the
    argument is present, which is how the omission survived in the first place.
    """
    offenders = []
    for path in _shipped_files():
        if path.suffix != ".py" or "/tests/" in path.as_posix():
            continue
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if "open(" not in line:
                continue
            if '"w"' not in line and "'w'" not in line:
                continue
            if "newline=" not in line:
                offenders.append("%s:%d %s" % (path.name, number, line.strip()))
    assert not offenders, "text-mode writes without an explicit newline=: %s" % offenders


# ======================================================================================
# The extension contract and the module docstrings state the same fact
# ======================================================================================

_COORDLIB = _ASSETS_DIR / "coordination" / "tools" / "coordlib"
_CONTRACT = _ASSETS_DIR.parent / "references" / "extension-contract.md"

#: Modules an external extension may depend on in full. Kept here rather than derived, so
#: widening the promise is a visible edit.
PROMISED_MODULES = {"schema", "diagnostics"}

#: Modules that are internal EXCEPT for named functions. `md_table` is here because §4 of the
#: contract makes these three normative for reading a row and there is no other tokenizer --
#: marking the whole module internal left an outside reader no legal way to read a table
#: (issue #50). Everything else in such a module stays free to change.
PROMISED_FUNCTIONS = {
    "md_table": {"split_table_row", "unescape_pipe", "iter_table_blocks"},
}


def _stability_line(name):
    text = _read(_COORDLIB / ("%s.py" % name))
    marks = [line for line in text.splitlines() if line.startswith("STABILITY:")]
    assert len(marks) == 1, "%s.py has %d STABILITY lines" % (name, len(marks))
    return marks[0]


def test_every_coordlib_module_declares_its_stability():
    """A vendored copy travels without references/, so the promise has to be in the code.

    The contract file states what is promised; the docstrings state the same thing where an
    outside reader will actually meet it. Two statements of one fact is what this project's own
    rationale warns about -- so they are checked against each other rather than kept in sync by
    hand.

    Three markers, because two were not enough to describe the truth: PROMISED, INTERNAL, and
    PARTIAL for a module whose named functions are promised while the rest of it is not.
    """
    modules = sorted(path.stem for path in _COORDLIB.glob("*.py")
                     if path.stem != "__init__")
    assert modules, "no coordlib modules found at %s" % _COORDLIB

    promised, partial, internal = set(), set(), set()
    for name in modules:
        mark = _stability_line(name)
        if mark.startswith("STABILITY: PARTIAL"):
            partial.add(name)
        elif "PROMISED" in mark:
            promised.add(name)
        else:
            internal.add(name)

    assert promised == PROMISED_MODULES, (
        "the promised set changed: %s. Widening it freezes a surface -- update the table in "
        "references/extension-contract.md and this test together, deliberately."
        % sorted(promised)
    )
    assert partial == set(PROMISED_FUNCTIONS), sorted(partial)
    assert internal == set(modules) - PROMISED_MODULES - set(PROMISED_FUNCTIONS)


def test_a_partial_module_names_its_promised_functions_and_defines_them():
    """The docstring must list them, and the module must actually have them.

    A promise to a name that no longer exists is the worse half of this failure: the vendored
    copy still carries the sentence, and the consumer finds out by ImportError.
    """
    for name, functions in PROMISED_FUNCTIONS.items():
        mark = _stability_line(name)
        text = _read(_COORDLIB / ("%s.py" % name))
        for function in sorted(functions):
            assert function in mark, (
                "%s.py's STABILITY line does not name %s" % (name, function))
            assert "\ndef %s(" % function in text, (
                "%s.py promises %s and does not define it" % (name, function))


def test_the_package_namespace_carries_only_the_promised_surface():
    """`from coordlib import X` must not be a way to reach an internal name.

    Flattening every module into one namespace was what made promised and internal
    indistinguishable at the call site (issue #50). This is the check that keeps it flat-only
    for things an extension may actually rely on.
    """
    init = _read(_COORDLIB / "__init__.py")
    for internal_name in ("SEP_RE", "TableBlock", "format_row", "escape_pipe",
                          "detect_line_ending", "is_separator_row", "scan_control_characters",
                          "find_repo_root", "find_coordination_dir", "worktrees_dir",
                          "is_within"):
        assert '"%s"' % internal_name not in init, (
            "%s is re-exported from coordlib/__init__.py; it is internal" % internal_name)


@pytest.mark.skill_repo
def test_the_contract_names_the_modules_it_promises():
    contract = _read(_CONTRACT)
    for name in PROMISED_MODULES:
        assert "coordlib.%s" % name in contract, name
    for name, functions in PROMISED_FUNCTIONS.items():
        for function in sorted(functions):
            assert function in contract, (
                "the contract does not name %s.%s, which the module promises"
                % (name, function))
    # And it must not quietly become the place the rules are restated: the whole point is that
    # it points at the module. A copy of the alias table here is a copy that will desync.
    assert "_COLUMN_ALIASES" not in contract


# ======================================================================================
# A documented hook registration must anchor its path to the project
# ======================================================================================

_SETUP = _ASSETS_DIR.parent / "references" / "setup.md"


def test_every_documented_hook_registration_anchors_to_the_project_dir():
    """A relative hook command resolves against the TOOL CALL's working directory.

    So the first `cd` into a subdirectory takes the hook out of service -- for a reporting
    hook that is a missed warning, for the two barrier hooks it is the barrier not being
    there, with nothing in the transcript to show it (issue #56).

    This is asserted over the documentation because the documentation is the thing that gets
    copied into a project's settings.json. It is also the line most likely to be "cleaned up"
    by someone who reads `$CLAUDE_PROJECT_DIR` as redundant quoting, which is why it is a
    test and not a comment.
    """
    offenders = []
    for number, line in enumerate(_read(_SETUP).splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith('"command":'):
            continue
        if ".claude/hooks/" not in stripped:
            continue
        if "$CLAUDE_PROJECT_DIR" not in stripped:
            offenders.append("setup.md:%d %s" % (number, stripped))
    assert not offenders, (
        "hook registrations documented with a path relative to the caller's cwd: %s"
        % offenders)


def test_the_shipped_hooks_document_the_anchored_form_too():
    """The wiring snippet inside a hook's own docstring travels with the file."""
    hooks = _ASSETS_DIR / "dot-claude" / "hooks"
    for name in ("check-commit-trailers.py", "check-path-ownership.py"):
        text = _read(hooks / name)
        assert "CLAUDE_PROJECT_DIR" in text, (
            "%s does not mention the project-anchored path anywhere" % name)
