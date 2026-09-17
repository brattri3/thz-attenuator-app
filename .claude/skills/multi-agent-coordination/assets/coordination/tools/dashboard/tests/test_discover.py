"""
test_discover.py - repository reconnaissance.

The cases worth writing are the ones where a naive implementation is confidently wrong: a
target that is not a git repository, a git worktree (`.git` is a FILE), a repository with
no commits, and a language guess flipped by a single "Русская версия" link in an otherwise
English README. Each of those produced a wrong answer during development.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parents[1]
_ASSETS_DIR = _TESTS_DIR.parents[3]
_REPO_ROOT = _ASSETS_DIR.parent

if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import discover as discover_cli  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A small git repository with two authors touching different directories."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@example.com")
    _git(root, "config", "user.name", "Alice")

    _write(root / "src" / "core.py", "x = 1\n")
    _write(root / "README.md", "# Demo\n\nAn English readme.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "alice: core")

    _git(root, "config", "user.email", "b@example.com")
    _git(root, "config", "user.name", "Bob")
    _write(root / "web" / "index.html", "<h1>hi</h1>\n" * 20)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "bob: web")
    return root


# ---------------------------------------------------------------------------------------
# Degrading without git
# ---------------------------------------------------------------------------------------

def test_a_directory_that_is_not_a_repository_still_reports(tmp_path):
    """Not being a git repo is a finding, not a failure: the other probes still run."""
    plain = tmp_path / "plain"
    _write(plain / "src" / "a.py", "x = 1\n")
    _write(plain / "package.json", json.dumps({"scripts": {"test": "jest"}}))

    report = discover_cli.discover(plain)
    assert report["is_git_repo"] is False
    assert report["ownership_map"] == []
    assert "src" in report["top_level_directories"]
    assert report["verification_commands"]["package.json"] == ["test"]


def test_repository_with_no_commits_does_not_raise(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    report = discover_cli.discover(root)
    assert report["is_git_repo"] is True
    assert report["ownership_map"] == []
    assert report["ownership_map_warning"] is None, \
        "an empty repo is not a warning -- it genuinely has no history"


def test_worktree_is_handled(repo, tmp_path):
    """`.git` is a FILE inside a worktree; this scaffold's tooling has tripped on it twice."""
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "role/qa")
    assert (worktree / ".git").is_file(), "a worktree's .git must be a file for this test"

    report = discover_cli.discover(worktree)
    assert report["is_git_repo"] is True
    assert {zone["path"] for zone in report["ownership_map"]} >= {"src", "web"}


# ---------------------------------------------------------------------------------------
# The empirical ownership map
# ---------------------------------------------------------------------------------------

def test_ownership_map_attributes_directories_to_their_real_authors(repo):
    zones = {zone["path"]: zone for zone in discover_cli.discover(repo)["ownership_map"]}
    assert zones["src"]["top_author"] == "Alice"
    assert zones["web"]["top_author"] == "Bob"
    assert zones["web"]["dominance_pct"] == 100.0


def test_ownership_map_survives_a_binary_file(repo):
    """git numstat writes `-` for binary files, and int("-") raises."""
    with open(repo / "assets.bin", "wb") as handle:
        handle.write(bytes(range(256)))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add binary")
    report = discover_cli.discover(repo)
    assert report["ownership_map"], "history became unreadable when a binary file appeared"


# ---------------------------------------------------------------------------------------
# ownership_map's timeout, previously indistinguishable from "no history"
# ---------------------------------------------------------------------------------------

def test_shallow_clone_is_detected_and_skipped_with_a_warning(repo, tmp_path):
    """A shallow clone is missing commits outright -- `--numstat` over it is misleading, not
    just slow, so this must be caught before the log walk, not after it times out."""
    shallow = tmp_path / "shallow"
    # --no-local: a same-filesystem clone otherwise takes a hardlink shortcut that ignores
    # --depth entirely, so the clone below would come out non-shallow and the test would be
    # asserting nothing.
    subprocess.run(["git", "clone", "--no-local", "--depth", "1", str(repo), str(shallow)],
                    capture_output=True, text=True, check=True)
    assert (_git(shallow, "rev-parse", "--is-shallow-repository").stdout.strip() == "true")

    zones, warning = discover_cli.ownership_map(shallow)
    assert zones == []
    assert warning is not None and "shallow" in warning


def test_partial_clone_markers_are_detected_even_though_history_is_complete(repo, tmp_path):
    """A `--filter=blob:none` clone has every commit, unlike a shallow one -- only the blob
    content is missing, fetched lazily on demand. Setting up a real filtered clone needs a
    remote that speaks protocol v2; the config it leaves behind is simulated directly instead,
    since that config is exactly what detection reads."""
    clone = tmp_path / "partial"
    subprocess.run(["git", "clone", str(repo), str(clone)],
                    capture_output=True, text=True, check=True)
    _git(clone, "config", "remote.origin.promisor", "true")
    _git(clone, "config", "remote.origin.partialclonefilter", "blob:none")

    zones, warning = discover_cli.ownership_map(clone)
    assert zones == []
    assert warning is not None and "partial" in warning


def test_a_genuine_timeout_is_distinguished_from_no_history(repo, monkeypatch):
    """Not every slow `git log` is a detectable shallow/partial clone -- a huge full clone on
    a slow disk can still time out. That case must not collapse back into `zones == []` with
    no explanation either."""
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git log", timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr(discover_cli.subprocess, "run", _raise_timeout)
    zones, warning = discover_cli.ownership_map(repo)
    assert zones == []
    assert warning is not None and "timed out" in warning


def test_an_ordinary_repository_still_reports_cleanly_with_no_warning(repo):
    """The true case must still fire: a normal repo produces zones and no warning at all."""
    zones, warning = discover_cli.ownership_map(repo)
    assert zones
    assert warning is None


# ---------------------------------------------------------------------------------------
# Language: the guess that was wrong first time
# ---------------------------------------------------------------------------------------

def test_a_translation_link_does_not_flip_the_language_guess(tmp_path):
    """This repository's own README is English with one "Русская версия" link.

    Presence-based detection called the project Russian on the strength of 69 characters in
    about 5,000. The interview would then have been conducted in the wrong language.
    """
    root = tmp_path / "mostly-english"
    root.mkdir()
    _write(root / "README.md",
           "# Project\n\n" + ("An English sentence about the project. " * 60) +
           "\n\nРусская версия документации: docs/ru/README.md\n")
    language = discover_cli.documentation_language(root)
    assert language["guess"] == "english"
    assert language["counts"]["cyrillic"] > 0


def test_a_genuinely_russian_project_is_detected(tmp_path):
    root = tmp_path / "russian"
    root.mkdir()
    _write(root / "README.md", "# Проект\n\n" + ("Описание проекта на русском языке. " * 40))
    assert discover_cli.documentation_language(root)["guess"] == "russian"


def test_language_is_undetermined_without_any_text(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert discover_cli.documentation_language(root)["guess"] is None


# ---------------------------------------------------------------------------------------
# _git's decoding: previously followed the ambient console codepage
# ---------------------------------------------------------------------------------------

def test_git_helper_forces_utf8_decoding_explicitly(repo, monkeypatch):
    """On Windows the default console codepage for non-English locales is not UTF-8 (e.g.
    `cp1251`), and `text=True` without an explicit encoding follows it -- a Cyrillic commit
    message could then raise inside the subprocess reader. Assert the fix directly: the
    encoding is forced rather than left to the environment."""
    captured = {}
    real_run = subprocess.run

    def _spy(cmd, **kwargs):
        captured.update(kwargs)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(discover_cli.subprocess, "run", _spy)
    discover_cli._git(repo, "rev-parse", "--git-dir")
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"


def test_cyrillic_commit_subjects_are_read_and_detected(tmp_path):
    """The true case this fix must keep working: Cyrillic commit subjects are read at all,
    and contribute to the language guess -- not just "doesn't crash"."""
    root = tmp_path / "ru"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@example.com")
    _git(root, "config", "user.name", "Alice")
    _write(root / "a.py", "x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Добавить модуль обработки данных на русском языке")

    language = discover_cli.documentation_language(root)
    assert language["sources"]["commits"] is True
    assert language["guess"] == "russian"


# ---------------------------------------------------------------------------------------
# The other probes
# ---------------------------------------------------------------------------------------

def test_existing_instruction_files_are_reported_for_import(tmp_path):
    """Found instruction files must be surfaced so the installer imports rather than clobbers."""
    root = tmp_path / "p"
    _write(root / "AGENTS.md", "# Agents\n")
    _write(root / ".cursorrules", "be nice\n")
    _write(root / ".cursor" / "rules" / "api.md", "---\npaths: []\n---\n")
    found = {item["path"] for item in discover_cli.existing_instructions(root)}
    assert {"AGENTS.md", ".cursorrules", ".cursor/rules"} <= found


def test_existing_ownership_and_charter_are_reported_for_reading_not_overwriting(tmp_path):
    """The two files `SKILL.md` calls archaeological on an existing project. Missing this
    check has already contributed to a real near-miss: a fresh OWNERSHIP.md almost overwrote
    one with real content, caught only by `git status` right before commit."""
    root = tmp_path / "p"
    _write(root / "coordination" / "OWNERSHIP.md", "# Ownership\n\nline two\n")
    _write(root / "coordination" / "CHARTER.md", "# Charter\n")
    found = {item["path"]: item["lines"] for item in discover_cli.existing_coordination_files(root)}
    assert found == {"coordination/OWNERSHIP.md": 3, "coordination/CHARTER.md": 1}


def test_absent_coordination_files_report_nothing(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert discover_cli.existing_coordination_files(root) == []


def test_existing_codeowners_is_parsed(tmp_path):
    root = tmp_path / "p"
    _write(root / ".github" / "CODEOWNERS",
           "# comment\n\n*           @org/core\n/docs/      @writer\n")
    found = discover_cli.existing_codeowners(root)
    assert found["file"] == ".github/CODEOWNERS"
    assert [rule["pattern"] for rule in found["rules"]] == ["*", "/docs/"]
    assert found["rules"][0]["owners"] == ["@org/core"]


def test_malformed_package_json_does_not_crash(tmp_path):
    root = tmp_path / "p"
    _write(root / "package.json", "{ this is not json")
    assert discover_cli.verification_commands(root) == {}


def test_makefile_targets_are_found_but_not_recipe_lines(tmp_path):
    root = tmp_path / "p"
    _write(root / "Makefile", "test:\n\tpytest\n\nlint:\n\truff check .\n\nVAR := 1\n")
    assert discover_cli.verification_commands(root)["Makefile"] == ["lint", "test"]


def test_scaffold_state_detects_an_unstamped_install(tmp_path):
    """The pre-feature project: installed, no baseline, needs --adopt."""
    root = tmp_path / "p"
    _write(root / "coordination" / "OWNERSHIP.md", "# Ownership\n")
    state = discover_cli.scaffold_state(root)
    assert state["installed"] is True
    assert state["stamp"] is None
    assert "--adopt" in state["note"]


def test_scaffold_state_when_absent(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert discover_cli.scaffold_state(root)["installed"] is False


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------

def test_cli_json_is_valid_and_exit_is_zero(repo, capsys):
    assert discover_cli.main(["--root", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["is_git_repo"] is True
    assert "ownership_map_warning" in payload
    assert "existing_coordination_files" in payload


def test_cli_human_output_names_what_it_could_not_answer(repo, capsys):
    """The report must hand the interview its remaining questions, not just findings."""
    discover_cli.main(["--root", str(repo)])
    out = capsys.readouterr().out
    for token in ("roles", "orchestrator", "guardrails"):
        assert token in out


def test_cli_on_a_missing_directory_does_not_fail_the_caller(tmp_path, capsys):
    assert discover_cli.main(["--root", str(tmp_path / "nope")]) == 0


# ---------------------------------------------------------------------------------------
# Against this repository
# ---------------------------------------------------------------------------------------

@pytest.mark.skill_repo
def test_discovery_of_this_repository(capsys):
    """The one repository we can always guarantee exists."""
    report = discover_cli.discover(_REPO_ROOT)
    assert report["is_git_repo"] is True
    paths = {zone["path"] for zone in report["ownership_map"]}
    assert {"assets", "references"} <= paths
    assert report["ownership_map_warning"] is None
    assert "pytest" in report["verification_commands"]
    # English despite docs/ru/ and the Russian link in the README.
    assert report["documentation_language"]["guess"] == "english"
    # This is the skill's own template tree: no installed OWNERSHIP.md/CHARTER.md at the root.
    assert report["existing_coordination_files"] == []


def test_the_new_tools_are_covered_by_the_dependency_guard():
    """The guard globs `tools/*.py`; a future move into a subpackage would escape it.

    Both new tools must stay flat in `tools/` or the streamlit/dashboard import ban stops
    applying to them silently.
    """
    flat = {path.name for path in (_ASSETS_DIR / "coordination" / "tools").glob("*.py")}
    assert {"discover.py", "upgrade.py"} <= flat


def test_scaffold_is_found_where_the_project_actually_keeps_it(tmp_path):
    """discover and upgrade must agree about where the scaffold may live.

    `upgrade.py` has always taken `--coordination-dir`; discovery hardcoded
    `<root>/coordination`, so a project that had moved the directory read as "not installed"
    to one tool while the other worked against it normally.
    """
    root = tmp_path / "proj"
    moved = root / "meta" / "coordination"
    moved.mkdir(parents=True)
    (moved / "BOARD.md").write_text("# Board\n", encoding="utf-8")

    assert discover_cli.scaffold_state(root) == {"installed": False}

    found = discover_cli.scaffold_state(root, "meta/coordination")
    assert found["installed"] is True
    assert found["coordination_dir"] == "meta/coordination"


def test_discovery_does_not_fall_back_to_the_authoring_layout(tmp_path):
    """`assets/coordination` is this skill's staging path, not a project layout.

    `coordlib.paths.find_coordination_dir` accepts it and is already imported here, so
    reaching for it is the obvious move -- and it would make discovery report the skill's
    own checkout as a project with the scaffold installed, reintroducing exactly the branch
    PR #39 removed from build_index.py and check_rules.py.
    """
    root = tmp_path / "vendored"
    staged = root / "assets" / "coordination"
    staged.mkdir(parents=True)
    (staged / "BOARD.md").write_text("# Board\n", encoding="utf-8")

    assert discover_cli.scaffold_state(root) == {"installed": False}
