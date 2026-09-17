"""
test_manifest_and_upgrade.py - the install stamp and the drift report.

The two tests that decide whether this tooling is worth shipping are the NEGATIVE ones:
`ACTIVITY.md` grows by design and a CRLF checkout changes every byte, and if either shows
up as drift then every report is noise and nobody reads the one that matters. They are
marked in place so a later refactor cannot quietly drop them.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parents[1]
_ASSETS_DIR = _TESTS_DIR.parents[3]

if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import upgrade as upgrade_cli  # noqa: E402
from coordlib import manifest  # noqa: E402


def _write(path: Path, text: str, newline: str = "\n") -> Path:
    """Write with an explicit newline. `Path.write_text(newline=)` is 3.10+, floor is 3.9."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    return path


@pytest.fixture
def upstream(tmp_path):
    """A miniature scaffold source tree, shaped like the real assets/ directory."""
    root = tmp_path / "upstream"
    _write(root / "coordination" / "tools" / "build_index.py", "print('index')\n")
    _write(root / "coordination" / "tools" / "kpi_git.py", "print('kpi')\n")
    _write(root / "coordination" / "tools" / "coordlib" / "schema.py", "X = 1\n")
    _write(root / "coordination" / "CHARTER.md", "# Charter\n\nRules.\n")
    _write(root / "coordination" / "ACTIVITY.md", "# Activity\n")
    _write(root / "coordination" / "OWNERSHIP.md", "# Ownership\n")
    _write(root / "coordination" / "roles" / "ROLE_ID.md", "# Role\n")
    _write(root / "dot-claude" / "hooks" / "check-context-budget.py", "print('budget')\n")
    _write(root / "dot-claude" / "hooks" / "budget.json.template", "{}\n")
    _write(root / "AGENTS.md.template", "# Agents\n")
    return root


@pytest.fixture
def project(tmp_path, upstream):
    """A project with the scaffold installed from `upstream` and stamped."""
    root = tmp_path / "proj"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    stamp = manifest.build_stamp(
        upstream, root, source_commit="c0ffee", source_ref="main")
    manifest.write_stamp(root / "coordination", stamp)
    return root


def _report(project, upstream):
    stamp = manifest.read_stamp(project / "coordination")
    rows = upgrade_cli.compare(
        stamp, project, upgrade_cli.hash_upstream(upstream))
    return {row["path"]: row["category"] for row in rows}


# ---------------------------------------------------------------------------------------
# Hashing and classification
# ---------------------------------------------------------------------------------------

def test_crlf_and_lf_hash_identically():
    """Otherwise a checkout with core.autocrlf=true reports every file as modified."""
    assert manifest.hash_bytes(b"a\r\nb\r\n") == manifest.hash_bytes(b"a\nb\n")


def test_binary_content_is_hashed_verbatim():
    """A 0x0d byte in binary data is data, not a line ending."""
    assert manifest.hash_bytes(b"\x00\r\n") != manifest.hash_bytes(b"\x00\n")


def test_unreadable_file_hashes_to_none(tmp_path):
    assert manifest.hash_file(tmp_path / "absent.md") is None


@pytest.mark.parametrize("path,expected", [
    ("coordination/tools/build_index.py", manifest.TOOL),
    (".claude/hooks/check-context-budget.py", manifest.TOOL),
    ("coordination/CHARTER.md", manifest.DOCTRINE),
    (".claude/rules/EXAMPLE_RULE.md", manifest.DOCTRINE),
    ("coordination/ACTIVITY.md", manifest.PROJECT),
    ("coordination/OWNERSHIP.md", manifest.PROJECT),
    ("coordination/roles/ORCH.md", manifest.PROJECT),
    ("AGENTS.md", manifest.PROJECT),
    ("AGENTS.md.template", manifest.CONFIG_SEED),
    ("coordination/tools/kpi_config.json.template", manifest.CONFIG_SEED),
])
def test_classification(path, expected):
    assert manifest.classify(path) == expected


@pytest.mark.parametrize("installed,source,expected", [
    (".claude/hooks/budget.json", "dot-claude/hooks/budget.json.template",
     manifest.CONFIG_SEED),
    ("coordination/tools/kpi_config.json", "coordination/tools/kpi_config.json.template",
     manifest.CONFIG_SEED),
    # Project-owned wins over seed-ness: AGENTS.md is the project's own file whatever it
    # was seeded from.
    ("AGENTS.md", "AGENTS.md.template", manifest.PROJECT),
    ("coordination/tools/build_index.py", "coordination/tools/build_index.py",
     manifest.TOOL),
])
def test_classification_uses_the_source_for_seed_ness(installed, source, expected):
    """`installed_path_for` drops `.template`, so the seed is invisible once installed."""
    assert manifest.classify(installed, source) == expected


def test_dotted_paths_classify_correctly():
    """Regression guard: the `lstrip("./")` bug made `.claude/hooks/*` fall through."""
    assert manifest.classify(".claude/hooks/check-path-ownership.py") == manifest.TOOL
    assert manifest.classify("./coordination/ACTIVITY.md") == manifest.PROJECT


@pytest.mark.parametrize("asset,installed", [
    ("dot-claude/hooks/x.py", ".claude/hooks/x.py"),
    ("dot-github/workflows/ci.yml.template", ".github/workflows/ci.yml"),
    ("AGENTS.md.template", "AGENTS.md"),
    ("coordination/tools/build_index.py", "coordination/tools/build_index.py"),
])
def test_install_path_mapping(asset, installed):
    """Both renames in one place: a mismatch here reports every file as new."""
    assert manifest.installed_path_for(asset) == installed


def test_pycache_is_excluded():
    assert manifest.is_excluded("coordination/tools/__pycache__/x.cpython-311.pyc")
    assert manifest.is_excluded("__pycache__")
    assert not manifest.is_excluded("coordination/tools/build_index.py")


def test_hash_tree_skips_excluded(tmp_path):
    _write(tmp_path / "keep.py", "x = 1\n")
    _write(tmp_path / "__pycache__" / "junk.pyc", "junk\n")
    assert sorted(manifest.hash_tree(tmp_path)) == ["keep.py"]


# ---------------------------------------------------------------------------------------
# The stamp
# ---------------------------------------------------------------------------------------

def test_stamp_round_trips(project):
    stamp = manifest.read_stamp(project / "coordination")
    assert stamp is not None
    assert stamp["format"] == manifest.FORMAT_VERSION
    assert stamp["source_commit"] == "c0ffee"
    assert "coordination/tools/build_index.py" in stamp["files"]
    assert stamp["files"]["AGENTS.md"]["source"] == "AGENTS.md.template"


def test_stamp_records_both_baselines(project, upstream):
    """The load-bearing decision: one hash per side, not one hash total.

    A single hash cannot distinguish "you edited it" from "the installer filled it in", so
    every customised file would report as drift on the first run and forever after.
    """
    stamp = manifest.read_stamp(project / "coordination")
    entry = stamp["files"]["coordination/CHARTER.md"]
    assert "sha256" in entry and "upstream_sha256" in entry


def test_a_file_customised_at_install_is_not_drift(tmp_path, upstream):
    """The skill's references/setup.md tells the installer to fill in CHARTER.md sections.

    The installed file therefore differs from its source on purpose. It must read as
    unchanged until somebody edits it AFTER the install.
    """
    root = tmp_path / "filled"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    _write(root / "coordination" / "CHARTER.md",
           "# Charter\n\nRules.\n\n## Conflict hot spots\n\nsrc/core.\n")
    manifest.write_stamp(root / "coordination", manifest.build_stamp(upstream, root))

    assert _report(root, upstream)["coordination/CHARTER.md"] == upgrade_cli.UNCHANGED

    with open(root / "coordination" / "CHARTER.md", "a", encoding="utf-8") as fh:
        fh.write("later edit\n")
    assert _report(root, upstream)["coordination/CHARTER.md"] == upgrade_cli.LOCAL_ONLY


def test_unreadable_stamp_reads_as_none(tmp_path):
    """A malformed stamp must be actionable ("run --adopt"), not a traceback."""
    coordination = tmp_path / "coordination"
    _write(coordination / manifest.STAMP_NAME, "{not json")
    assert manifest.read_stamp(coordination) is None


def test_absent_stamp_reads_as_none(tmp_path):
    assert manifest.read_stamp(tmp_path) is None


# ---------------------------------------------------------------------------------------
# Drift, category by category
# ---------------------------------------------------------------------------------------

def test_fresh_install_has_no_drift(project, upstream):
    categories = set(_report(project, upstream).values())
    assert categories == {upgrade_cli.UNCHANGED}


def test_local_edit_alone(project, upstream):
    with open(project / "coordination" / "tools" / "kpi_git.py", "a", encoding="utf-8") as fh:
        fh.write("# mine\n")
    assert _report(project, upstream)["coordination/tools/kpi_git.py"] == \
        upgrade_cli.LOCAL_ONLY


def test_upstream_change_alone(project, upstream):
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed\n")
    assert _report(project, upstream)["coordination/tools/build_index.py"] == \
        upgrade_cli.UPSTREAM_ONLY


@pytest.fixture
def adopted_project(tmp_path, upstream):
    """A project whose CHARTER.md was ALREADY hand-written when the baseline was frozen.

    This is the case `--adopt` exists for: a live project whose doctrine files are its own
    content, blessed rather than overwritten. The stamp therefore records a local hash that
    differs from the source hash from the very first day.
    """
    root = tmp_path / "adopted"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    _write(root / "coordination" / "CHARTER.md",
           "# CHARTER\n\nThis project's own rules, never the shipped seed.\n")
    manifest.write_stamp(root / "coordination",
                         manifest.build_stamp(upstream, root, adopted=True))
    return root


def test_customised_at_adoption_is_not_reported_as_safe_to_take(adopted_project, upstream):
    """Same digest test, opposite correct action.

    CHARTER.md is untouched *since* the baseline, which used to put it under "your copy is
    untouched" and invite copying upstream across content that was the project's own before
    the baseline existed.
    """
    with open(upstream / "coordination" / "CHARTER.md", "a", encoding="utf-8") as fh:
        fh.write("\nAn unrelated upstream sentence.\n")
    assert _report(adopted_project, upstream)["coordination/CHARTER.md"] == \
        upgrade_cli.UPSTREAM_ONLY_BUT_CUSTOMIZED


def test_a_pristine_file_in_an_adopted_project_is_still_safe_to_take(adopted_project, upstream):
    """The true case must keep firing: in the SAME adopted project, a file that really was
    installed verbatim still belongs in the safe bucket."""
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed\n")
    assert _report(adopted_project, upstream)["coordination/tools/build_index.py"] == \
        upgrade_cli.UPSTREAM_ONLY


def test_customised_file_with_no_upstream_movement_stays_unchanged(adopted_project, upstream):
    """No behaviour change for the common case: customised, but upstream stood still."""
    assert _report(adopted_project, upstream)["coordination/CHARTER.md"] == \
        upgrade_cli.UNCHANGED


def test_a_stamp_without_upstream_hashes_does_not_guess(project, upstream):
    """A stamp written before `upstream_sha256` existed has no evidence either way.

    Report the ordinary category rather than inventing a customisation that may not have
    happened -- a false "you customised this" is as misleading as the bug being fixed.
    """
    coordination = project / "coordination"
    stamp = manifest.read_stamp(coordination)
    for entry in stamp["files"].values():
        entry.pop("upstream_sha256", None)
    manifest.write_stamp(coordination, stamp)
    with open(upstream / "coordination" / "CHARTER.md", "a", encoding="utf-8") as fh:
        fh.write("\nlater\n")
    rows = {row["path"]: row for row in upgrade_cli.compare(
        manifest.read_stamp(coordination), project, upgrade_cli.hash_upstream(upstream))}
    assert rows["coordination/CHARTER.md"]["customized_at_baseline"] is False
    assert rows["coordination/CHARTER.md"]["category"] == upgrade_cli.UPSTREAM_ONLY


def test_the_customised_bucket_renders_above_safe_to_take(adopted_project, upstream):
    """Ordering is the fix, not decoration: a reader who copies everything under the first
    heading that sounds safe has to meet the customised rows first."""
    with open(upstream / "coordination" / "CHARTER.md", "a", encoding="utf-8") as fh:
        fh.write("\nlater\n")
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed\n")
    stamp = manifest.read_stamp(adopted_project / "coordination")
    rows = upgrade_cli.compare(stamp, adopted_project, upgrade_cli.hash_upstream(upstream))
    text = upgrade_cli.render(rows, stamp)
    assert text.index("CUSTOMISED BEFORE ADOPTION") < text.index("Safe to take")


def test_both_sides_changed_is_the_only_one_needing_a_human(project, upstream):
    target = "coordination/tools/coordlib/schema.py"
    with open(project / target, "a", encoding="utf-8") as fh:
        fh.write("# mine\n")
    with open(upstream / target, "a", encoding="utf-8") as fh:
        fh.write("# theirs\n")
    assert _report(project, upstream)[target] == upgrade_cli.BOTH


def test_locally_deleted_file(project, upstream):
    os.remove(project / ".claude" / "hooks" / "check-context-budget.py")
    assert _report(project, upstream)[".claude/hooks/check-context-budget.py"] == \
        upgrade_cli.DELETED_LOCALLY


def test_new_upstream_file(project, upstream):
    _write(upstream / "coordination" / "tools" / "brand_new.py", "print('new')\n")
    assert _report(project, upstream)["coordination/tools/brand_new.py"] == \
        upgrade_cli.NEW_UPSTREAM


def test_seed_change_is_reported_without_claiming_local_drift(project, upstream):
    """A filled-in AGENTS.md differs from its template by design.

    The upstream template changing is worth reporting; calling the project's own file
    "modified" because it no longer matches a template would be nonsense.
    """
    with open(project / "AGENTS.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# My actual project\n")
    _write(upstream / "AGENTS.md.template", "# Agents\n\nNew section.\n")
    rows = {r["path"]: r for r in upgrade_cli.compare(
        manifest.read_stamp(project / "coordination"), project,
        upgrade_cli.hash_upstream(upstream))}
    assert rows["AGENTS.md"]["category"] == upgrade_cli.SEED_CHANGED
    assert rows["AGENTS.md"]["local_changed"] is None


# ---------------------------------------------------------------------------------------
# The two tests that decide whether anyone keeps running this
# ---------------------------------------------------------------------------------------

def test_growing_a_journal_is_never_drift(project, upstream):
    """ACTIVITY.md is append-only by design and grows every day.

    Reporting it as "locally modified" on every run would make the report pure noise, and a
    noisy report is worse than none: the `both` rows that genuinely need a human get lost
    in it. This is the single most important assertion in the file.
    """
    with open(project / "coordination" / "ACTIVITY.md", "a", encoding="utf-8") as fh:
        for index in range(50):
            fh.write("- [ORCH] entry %d\n" % index)
    assert _report(project, upstream)["coordination/ACTIVITY.md"] == upgrade_cli.UNCHANGED


def test_crlf_conversion_is_never_drift(project, upstream):
    """A Windows checkout must not read as wholly rewritten."""
    target = project / "coordination" / "CHARTER.md"
    with open(target, "rb") as fh:
        data = fh.read()
    with open(target, "wb") as fh:
        fh.write(data.replace(b"\n", b"\r\n"))
    assert _report(project, upstream)["coordination/CHARTER.md"] == upgrade_cli.UNCHANGED


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------

def test_cli_exit_codes_and_json(project, upstream, capsys):
    coordination = str(project / "coordination")
    assert upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination]) == 0

    target = "coordination/tools/coordlib/schema.py"
    with open(project / target, "a", encoding="utf-8") as fh:
        fh.write("# mine\n")
    with open(upstream / target, "a", encoding="utf-8") as fh:
        fh.write("# theirs\n")
    capsys.readouterr()

    assert upgrade_cli.main(
        ["--from", str(upstream), "--coordination-dir", coordination, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    both = [r for r in payload["rows"] if r["category"] == upgrade_cli.BOTH]
    assert [r["path"] for r in both] == [target]


def _customise_and_move_upstream(adopted_project, upstream):
    """Put the adopted project in the state the exit-code rules are about."""
    with open(upstream / "coordination" / "CHARTER.md", "a", encoding="utf-8") as fh:
        fh.write("\nlater\n")
    return str(adopted_project / "coordination")


def test_the_customised_category_does_not_fail_a_build_by_default(adopted_project, upstream, capsys):
    """One rule everywhere: red means a `both` row unless the caller asked for more.

    The customised-before-adoption category is a warning by default. It carries the same
    risk as a `both` row, but making it fail a build is a decision each project takes in its
    CI step rather than one the tool takes on the project's behalf.
    """
    coordination = _customise_and_move_upstream(adopted_project, upstream)
    assert upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination]) == 0
    assert "do not affect the exit code" in capsys.readouterr().out


def test_strict_gates_on_the_customised_category(adopted_project, upstream, capsys):
    coordination = _customise_and_move_upstream(adopted_project, upstream)
    assert upgrade_cli.main(
        ["--from", str(upstream), "--coordination-dir", coordination, "--strict"]) == 1
    assert "FAIL the exit code" in capsys.readouterr().out


def test_the_exit_code_does_not_depend_on_the_stamp_version(adopted_project, upstream):
    """The same drift must exit the same way in every project.

    It briefly did not: the default was read out of the stamp's `format` field, so a
    baseline written by a newer tool gated on the new category and an older one did not.
    That kept an existing project's CI meaning intact, at the price of an exit code that
    depended on a JSON field nobody reads, and of `--strict` meaning something different
    here than on `build_index.py` and `check_rules.py`, where it is an ordinary flag.
    """
    coordination = _customise_and_move_upstream(adopted_project, upstream)
    stamp_path = adopted_project / "coordination"

    for version in (1, 2):
        stamp = manifest.read_stamp(stamp_path)
        stamp["format"] = version
        manifest.write_stamp(stamp_path, stamp)

        assert upgrade_cli.main(
            ["--from", str(upstream), "--coordination-dir", coordination]) == 0, version
        assert upgrade_cli.main(
            ["--from", str(upstream), "--coordination-dir", coordination, "--strict"]) == 1, version


def test_the_default_never_hides_a_both_row(project, upstream):
    """The relaxed default relaxes only the new category. The original gate is not negotiable."""
    target = "coordination/tools/coordlib/schema.py"
    for tree, note in ((project, "# mine\n"), (upstream, "# theirs\n")):
        with open(tree / target, "a", encoding="utf-8") as fh:
            fh.write(note)
    assert upgrade_cli.main(["--from", str(upstream),
                             "--coordination-dir", str(project / "coordination")]) == 1


def test_json_reports_which_gate_was_applied(adopted_project, upstream, capsys):
    """A CI run that goes red should be able to say why without re-deriving the rule."""
    coordination = _customise_and_move_upstream(adopted_project, upstream)

    upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination, "--json"])
    assert json.loads(capsys.readouterr().out)["strict"] is False

    upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination,
                      "--json", "--strict"])
    assert json.loads(capsys.readouterr().out)["strict"] is True


def test_cli_without_a_stamp_says_run_adopt(tmp_path, upstream, capsys):
    coordination = tmp_path / "bare" / "coordination"
    coordination.mkdir(parents=True)
    assert upgrade_cli.main(
        ["--from", str(upstream), "--coordination-dir", str(coordination)]) == 2
    assert "--adopt" in capsys.readouterr().err


def test_running_inside_the_skill_itself_is_refused(tmp_path, upstream, capsys):
    """`find_coordination_dir` falls back to assets/coordination in the skill repo."""
    assert upgrade_cli.looks_like_the_skill_itself(
        tmp_path / "skill" / "assets" / "coordination") is True
    assert upgrade_cli.looks_like_the_skill_itself(
        tmp_path / "proj" / "coordination") is False


def test_adopt_prints_pre_existing_divergence_once(tmp_path, upstream, capsys):
    """Adoption freezes local edits as pristine. That has to be visible exactly once."""
    root = tmp_path / "legacy"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    with open(root / "coordination" / "tools" / "kpi_git.py", "a", encoding="utf-8") as fh:
        fh.write("# customised long ago\n")

    upgrade_cli.main(["--from", str(upstream),
                      "--coordination-dir", str(root / "coordination"), "--adopt"])
    captured = capsys.readouterr()
    assert "coordination/tools/kpi_git.py" in captured.err
    assert "ALREADY differ" in captured.err


def test_adopt_creates_a_baseline_that_reports_clean(tmp_path, upstream, capsys):
    """Adoption must start from "no drift", or a customised project sees only noise."""
    root = tmp_path / "legacy"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    # A pre-existing local customisation, made before adoption.
    with open(root / "coordination" / "tools" / "kpi_git.py", "a", encoding="utf-8") as fh:
        fh.write("# customised long ago\n")

    coordination = str(root / "coordination")
    assert upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination,
                             "--adopt"]) == 0
    capsys.readouterr()
    assert upgrade_cli.main(["--from", str(upstream), "--coordination-dir", coordination]) == 0

    stamp = manifest.read_stamp(root / "coordination")
    assert stamp["adopted"] is True


def test_adopted_report_admits_what_it_cannot_see(project, upstream, capsys):
    """An adopted baseline hides pre-adoption edits; the report must say so."""
    stamp = manifest.read_stamp(project / "coordination")
    stamp["adopted"] = True
    manifest.write_stamp(project / "coordination", stamp)
    upgrade_cli.main(["--from", str(upstream),
                      "--coordination-dir", str(project / "coordination")])
    assert "ADOPTED" in capsys.readouterr().out


def test_cli_rejects_a_missing_upstream(project, capsys):
    assert upgrade_cli.main(
        ["--from", "/definitely/not/here",
         "--coordination-dir", str(project / "coordination")]) == 2


# ---------------------------------------------------------------------------------------
# The shipped scaffold must satisfy its own tooling
# ---------------------------------------------------------------------------------------

@pytest.mark.skill_repo
def test_shipped_assets_classify_without_falling_through(tmp_path):
    """Every shipped file lands in a real class, and the four classes are all populated.

    A file quietly classified `doctrine` because a prefix check missed it would be offered
    for upgrade when it should not be, or excluded when it should not be.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "assets"], cwd=str(_ASSETS_DIR.parent),
        capture_output=True, text=True, check=True).stdout.split()
    assert tracked, "no tracked files under assets/ - wrong repo root"

    seen = {}
    for path in tracked:
        asset = path[len("assets/"):]
        installed = manifest.installed_path_for(asset)
        seen.setdefault(manifest.classify(installed, asset), []).append(installed)

    assert set(seen) == set(manifest.CLASSES), sorted(seen)
    assert "coordination/ACTIVITY.md" in seen[manifest.PROJECT]
    assert ".claude/hooks/check-context-budget.py" in seen[manifest.TOOL]
    assert "coordination/CHARTER.md" in seen[manifest.DOCTRINE]
    assert ".claude/hooks/budget.json" in seen[manifest.CONFIG_SEED]


def test_shipped_assets_stamp_and_report_clean(tmp_path):
    """Install the real assets/ into a tmp project and confirm the report is empty."""
    source = _ASSETS_DIR
    root = tmp_path / "real"
    for asset in manifest.hash_tree(source):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / asset, destination)
    manifest.write_stamp(root / "coordination", manifest.build_stamp(source, root))

    rows = upgrade_cli.compare(
        manifest.read_stamp(root / "coordination"), root, upgrade_cli.hash_upstream(source))
    assert rows, "no rows produced - the shipped tree was not read"
    assert {row["category"] for row in rows} == {upgrade_cli.UNCHANGED}


# ======================================================================================
# The stamp's provenance fields
# ======================================================================================

def _bare_project(tmp_path, upstream):
    """A project with the files installed but no stamp yet -- what `--adopt` is run against."""
    root = tmp_path / "to-adopt"
    for asset in manifest.hash_tree(upstream):
        destination = root / manifest.installed_path_for(asset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / asset, destination)
    return root


def _git(cwd, *args):
    return subprocess.run(
        ("git", "-C", str(cwd)) + args,
        capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout.strip()


def test_adopt_records_which_upstream_commit_it_came_from(tmp_path, upstream):
    """The question the stamp exists to answer, and could not.

    `build_stamp` has always taken `source_commit` and `source_ref`; its only caller passed
    neither, so every stamp recorded an empty provenance, the report printed "installed
    <date> from unrecorded" forever, and discover.py's branch for showing the source could
    never be reached. The information was one `git rev-parse` away the whole time.
    """
    _git(upstream, "init", "-q", "-b", "trunk")
    _git(upstream, "config", "user.email", "test@example.invalid")
    _git(upstream, "config", "user.name", "Test")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "upstream")
    head = _git(upstream, "rev-parse", "HEAD")

    project_root = _bare_project(tmp_path, upstream)
    coordination = project_root / "coordination"
    assert upgrade_cli.main(
        ["--from", str(upstream), "--coordination-dir", str(coordination), "--adopt"]) == 0

    stamp = manifest.read_stamp(coordination)
    assert stamp["source_commit"] == head
    assert stamp["source_ref"] == "trunk"


def test_adopt_against_a_non_git_upstream_still_works(tmp_path, upstream):
    """A baseline with no provenance beats a failed adopt.

    `--from` can point at an unpacked copy with no history. That is worth less than a real
    checkout and must not be an error.
    """
    project_root = _bare_project(tmp_path, upstream)
    coordination = project_root / "coordination"
    assert upgrade_cli.main(
        ["--from", str(upstream), "--coordination-dir", str(coordination), "--adopt"]) == 0

    stamp = manifest.read_stamp(coordination)
    assert stamp["source_commit"] == ""
    assert stamp["source_ref"] == ""


# ---------------------------------------------------------------------------------------
# The update channel, end to end: report -> take the files -> report again
#
# Both defects below were reported from a live installation (issues #52 and #53), and both
# are about the SECOND run. The first report is useful; what a consumer does next is take
# the files by hand -- this tool reports and does not merge -- and it was that step the
# comparison could not see.
# ---------------------------------------------------------------------------------------

def _take(project, upstream, rows_by_path, category):
    """Copy every row in `category` from upstream over the project's copy.

    This is the documented workflow, performed literally: the report names files, a human
    copies them across.
    """
    taken = []
    for path, found in rows_by_path.items():
        if found != category:
            continue
        asset = upstream / _asset_for(upstream, path)
        shutil.copyfile(asset, project / path)
        taken.append(path)
    return taken


def _asset_for(upstream, installed_path):
    for asset in manifest.hash_tree(upstream):
        if manifest.installed_path_for(asset) == installed_path:
            return asset
    raise AssertionError("no upstream asset maps to %s" % installed_path)


def test_a_file_taken_from_upstream_is_current_not_a_conflict(project, upstream):
    """Issue #52: the channel used to break on its second use.

    Both baselines say "changed" about a copy that is byte-identical to the new upstream,
    so every file a consumer took came back as `both` -- the loudest category the tool has,
    reserved for rows that need a human -- and stayed there forever.
    """
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed upstream\n")

    first = _report(project, upstream)
    assert first["coordination/tools/build_index.py"] == upgrade_cli.UPSTREAM_ONLY
    assert _take(project, upstream, first, upgrade_cli.UPSTREAM_ONLY)

    second = _report(project, upstream)
    assert second["coordination/tools/build_index.py"] == upgrade_cli.ALREADY_CURRENT, (
        "a file identical to upstream was reported as needing reconciliation")


def test_taking_an_update_clears_the_gating_exit_code(project, upstream):
    """The half that actually blocked people: the shipped CI workflow keys on this code."""
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed upstream\n")
    coordination = project / "coordination"
    args = ["--from", str(upstream), "--coordination-dir", str(coordination)]

    assert upgrade_cli.main(args) == 0, "an untaken upstream-only row must not gate"
    _take(project, upstream, _report(project, upstream), upgrade_cli.UPSTREAM_ONLY)
    assert upgrade_cli.main(args) == 0, "taking the update left the build red"


def test_a_real_conflict_is_still_a_conflict(project, upstream):
    """The guard that keeps the fix honest: `already-current` must not swallow `both`."""
    with open(upstream / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# fixed upstream\n")
    with open(project / "coordination" / "tools" / "build_index.py", "a",
              encoding="utf-8") as fh:
        fh.write("# and mine, differently\n")

    assert _report(project, upstream)["coordination/tools/build_index.py"] == \
        upgrade_cli.BOTH


def test_a_file_deleted_upstream_is_not_filed_under_unchanged(project, upstream):
    """Issue #53: the category a consumer is told to ignore is where orphans landed.

    `upstream_changed` is false when there is no upstream digest at all, so a locally
    untouched file whose upstream copy had been deleted fell through to `unchanged`. A
    consumer then took its dependants and the import graph broke, with nothing in the
    report pointing at the cause.
    """
    (upstream / "coordination" / "tools" / "kpi_git.py").unlink()

    row = _report(project, upstream)["coordination/tools/kpi_git.py"]
    assert row == upgrade_cli.UPSTREAM_DELETED, (
        "a file gone from upstream was reported as %s" % row)


def test_a_file_gone_from_both_sides_is_reported_as_missing_locally(project, upstream):
    """The boundary: upstream-deleted means "still yours", not "retired everywhere"."""
    (upstream / "coordination" / "tools" / "kpi_git.py").unlink()
    (project / "coordination" / "tools" / "kpi_git.py").unlink()

    assert _report(project, upstream)["coordination/tools/kpi_git.py"] == \
        upgrade_cli.DELETED_LOCALLY


def test_the_upstream_deleted_bucket_says_to_check_what_imports_them(project, upstream):
    """The sentence that would have saved the reporter a debugging session."""
    (upstream / "coordination" / "tools" / "kpi_git.py").unlink()
    stamp = manifest.read_stamp(project / "coordination")
    rows = upgrade_cli.compare(stamp, project, upgrade_cli.hash_upstream(upstream))

    text = upgrade_cli.render(rows, stamp)
    assert "GONE FROM UPSTREAM" in text
    assert "imports" in text
