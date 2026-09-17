#!/usr/bin/env python3
"""discover.py - read what the repository already knows, before asking anyone anything.

The install interview asks the owner six questions, several of which the repository has
already answered: which directories exist, who actually edits them, how the project is
tested, whether a CODEOWNERS is in place, whether another agent tool has left instructions.
Asking those anyway is not merely wasted time -- a questionnaire that asks what is already
written teaches the owner to click through it, and then the questions that DO matter get
clicked through too.

This tool answers them from evidence so the interview can ask only what evidence cannot
settle, and present the rest as defaults to confirm.

It writes nothing, ever. Exit status is always 0: it is a reporter, and a reporter that can
fail a script invites being wrapped in `|| true`, which is how a check stops being read.

    python3 coordination/tools/discover.py
    python3 coordination/tools/discover.py --json --root /path/to/project
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coordlib import manifest  # noqa: E402
from coordlib.ownership import parse_ownership  # noqa: E402
from coordlib.paths import find_repo_root  # noqa: E402

#: Instruction files other agent tools leave behind. Found ones are to be IMPORTED, never
#: overwritten -- destroying a project's existing agent instructions is the fastest way to
#: make the scaffold unwelcome, and the damage is not obvious until someone notices their
#: rules stopped applying.
INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".github/copilot-instructions.md",
)
INSTRUCTION_DIRS = (".cursor/rules", ".windsurf/rules", ".claude/rules")

#: Directories that are never candidate zones: not project code, or noise in a per-path
#: ownership tally.
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".tox", "vendor", "target", ".idea", ".vscode",
}

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_CJK = re.compile(r"[぀-ヿ一-鿿]")


def _git(root, *args, timeout=30):
    """Run a git command, returning stdout or None. Never raises.

    A target project may not be a git repository at all, may have no commits, or may not
    have git installed. All three are ordinary and none is this tool's business to fail on.

    `encoding="utf-8", errors="replace"` is explicit rather than relying on `text=True`'s
    default, which follows the ambient console codepage. On Windows against a repository with
    non-ASCII commit messages (Cyrillic, say) that default can be `cp1251`, and a message it
    can't decode raised inside the subprocess reader -- recovered from by the caller, so the
    tool still printed a report, but a degraded one (`documentation_language`'s commit-based
    signal silently went missing). Forcing UTF-8 with replacement means a genuinely malformed
    byte becomes a `�` in one field rather than losing the whole probe.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, encoding="utf-8", errors="replace", check=True,
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return None
    return result.stdout


def is_git_repo(root):
    return _git(root, "rev-parse", "--git-dir") is not None


def top_level_entries(root):
    """Candidate zones from the directory layout alone. Works without git."""
    entries = []
    try:
        for name in sorted(os.listdir(root)):
            if name in SKIP_DIRS or name.startswith("."):
                continue
            if os.path.isdir(os.path.join(root, name)):
                entries.append(name)
    except OSError:
        return []
    return entries


def _clone_is_shallow_or_partial(root):
    """True when this checkout's history is incomplete: a shallow clone, or a partial one.

    `--numstat` needs the full blob content of every changed file in every commit it walks.
    A shallow clone (`--depth`) is missing commits outright. A partial clone
    (`--filter=blob:none`, the shape `git clone --filter=blob:none` and similar bootstrap
    commands produce) has every commit but must lazily fetch each blob's content over the
    network on first use -- against a slow connection, `git log --numstat -n 2000` on exactly
    such a clone has been measured taking 20+ minutes, not the 30 seconds `ownership_map`
    otherwise allows before giving up.
    """
    if (_git(root, "rev-parse", "--is-shallow-repository", timeout=10) or "").strip() == "true":
        return True
    promisor = (_git(root, "config", "--get", "remote.origin.promisor", timeout=10) or "").strip()
    if promisor == "true":
        return True
    filt = (_git(root, "config", "--get", "remote.origin.partialclonefilter", timeout=10) or "").strip()
    return bool(filt)


def ownership_map(root, max_commits=2000, timeout=30):
    """Who actually edits each top-level directory, from git history.

    This is the empirical ownership map, and it is usually more honest than the declared
    one: OWNERSHIP.md says who *should* own a path, history says who does. Where they
    disagree, that disagreement is the most useful thing the interview can put in front of
    the owner.

    Churn is measured in lines added+removed. It is a blunt instrument -- a reformatting
    commit outweighs a subtle fix -- so the output names it `lines` rather than anything
    implying significance, and the interview treats it as a candidate, not a verdict.

    Returns `(zones, warning)`. `warning` is None on an ordinary run (whether or not any
    history was found -- an empty repo is not a warning) and a short string on the two ways
    this specific probe can silently degrade: a shallow/partial clone detected up front, or an
    actual timeout despite that check. Both used to collapse into `zones == []`, which reads
    identically to "this repo genuinely has no history" -- the failure mode this return shape
    exists to stop being silent.
    """
    if _clone_is_shallow_or_partial(root):
        return [], ("skipped: this checkout is a shallow or partial clone; `--numstat` would "
                     "need to fetch blob content over the network per changed file and has "
                     "been measured taking 20+ minutes on a slow connection")

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "--no-merges", "--format=%n%an", "--numstat",
             "-n", str(max_commits)],
            capture_output=True, encoding="utf-8", errors="replace", check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return [], "timed out after %ds (not detected as shallow/partial up front)" % timeout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return [], None
    out = result.stdout
    if not out:
        return [], None

    author = None
    churn = defaultdict(Counter)
    for line in out.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            author = line.strip()
            continue
        parts = line.split("\t")
        if len(parts) != 3 or author is None:
            continue
        added, removed, path = parts
        segment = path.split("/")[0] if "/" in path else "(root)"
        if segment in SKIP_DIRS:
            continue
        try:
            # A binary file's numstat columns are "-", which int() rejects. Count it as
            # touched-but-unmeasured rather than dropping the author's involvement.
            weight = int(added) + int(removed)
        except ValueError:
            weight = 1
        churn[segment][author] += weight

    zones = []
    for segment, authors in churn.items():
        total = sum(authors.values())
        if not total:
            continue
        top_author, top_lines = authors.most_common(1)[0]
        zones.append({
            "path": segment,
            "lines": total,
            "top_author": top_author,
            "dominance_pct": round(100.0 * top_lines / total, 1),
            "authors": len(authors),
        })
    zones.sort(key=lambda z: -z["lines"])
    return zones, None


def existing_codeowners(root):
    """Owners already declared in .github/CODEOWNERS, as (pattern, owners) pairs.

    A project with a CODEOWNERS has already answered "who owns what" in a machine-readable
    form. The interview should propose an OWNERSHIP.md built from it rather than an empty
    table -- and where the two later disagree, `ownership.py --check` is what catches it.
    """
    for candidate in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        path = Path(root) / candidate
        if not path.is_file():
            continue
        rules = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    text = line.split("#", 1)[0].strip()
                    if not text:
                        continue
                    fields = text.split()
                    if len(fields) < 2:
                        continue
                    rules.append({"pattern": fields[0], "owners": fields[1:], "line": number})
        except OSError:
            continue
        return {"file": candidate, "rules": rules}
    return None


def existing_instructions(root):
    """Agent instruction files already present, to import rather than replace."""
    found = []
    for relative in INSTRUCTION_FILES:
        path = Path(root) / relative
        if path.is_file():
            try:
                lines = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))
            except OSError:
                lines = None
            found.append({"path": relative, "kind": "file", "lines": lines})
    for relative in INSTRUCTION_DIRS:
        path = Path(root) / relative
        if path.is_dir():
            count = len(list(path.rglob("*.md")))
            found.append({"path": relative, "kind": "directory", "rule_files": count})
    return found


#: The two files `SKILL.md` singles out as "archaeological, not aspirational" on an existing
#: project. `existing_instructions` already reports generic agent-instruction files so the
#: installer imports rather than overwrites them; these two are this scaffold's own equivalent
#: and need the same explicit "already exists" signal, not a fold-in of the generic list --
#: silently missing it has already contributed to a real near-miss (a fresh OWNERSHIP.md
#: almost overwriting one with real, current content, caught only by `git status` before commit).
COORDINATION_FILES = (
    "coordination/OWNERSHIP.md",
    "coordination/CHARTER.md",
)


def existing_coordination_files(root):
    """OWNERSHIP.md and CHARTER.md already present, to read before writing, not assume blank."""
    found = []
    for relative in COORDINATION_FILES:
        path = Path(root) / relative
        if path.is_file():
            try:
                lines = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))
            except OSError:
                lines = None
            found.append({"path": relative, "lines": lines})
    return found


def _json_scripts(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []
    return sorted(scripts)


def _makefile_targets(path):
    targets = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*:(?!=)", line)
                if match:
                    targets.append(match.group(1))
    except OSError:
        return []
    return sorted(set(targets))


def verification_commands(root):
    """The project's real Definition of Done, as already written down.

    CHARTER.md asks each role for verification commands. In a live project they exist
    already -- in package.json scripts, Makefile targets, pyproject config, CI steps -- and
    reading them beats asking, because what CI actually runs is the truth and what someone
    recalls in an interview is a summary of it.
    """
    root = Path(root)
    found = {}

    package_json = root / "package.json"
    if package_json.is_file():
        scripts = _json_scripts(package_json)
        if scripts:
            found["package.json"] = scripts

    for name in ("Makefile", "makefile", "GNUmakefile"):
        candidate = root / name
        if candidate.is_file():
            targets = _makefile_targets(candidate)
            if targets:
                found[name] = targets
            break

    if (root / "pyproject.toml").is_file():
        found["pyproject.toml"] = ["present"]
    if (root / "pytest.ini").is_file() or (root / "tox.ini").is_file():
        found["pytest"] = ["python -m pytest"]

    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        names = sorted(p.name for p in workflows.glob("*.y*ml"))
        if names:
            found[".github/workflows"] = names

    return found


#: Share of letters that must be in one non-Latin script before it is called the project's
#: language. Presence alone is uselessly sensitive: this repository's own README is English
#: with a single "Русская версия" link, and 69 Cyrillic characters in ~5,000 flipped the
#: guess to Russian. A translation link is not a translated project.
_SCRIPT_THRESHOLD = 0.10


def _script_counts(text):
    latin = len(re.findall(r"[A-Za-z]", text))
    return {
        "latin": latin,
        "cyrillic": len(_CYRILLIC.findall(text)),
        "cjk": len(_CJK.findall(text)),
    }


def documentation_language(root, sample=200):
    """Guess the project's working language from commit subjects and the README.

    Guessed rather than asked, and reported as a guess with its evidence, so the interview
    can show the owner *why* and be corrected in one word. It only decides which language
    prose is written in; the protocol tokens stay English regardless
    (the skill's `references/rationale.md`), so being wrong costs a correction, not a defect.

    Commit subjects and the README are counted separately because they genuinely disagree:
    a team often writes English commits over a README in its own language, and collapsing
    the two hides that.
    """
    subjects = _git(root, "log", "--no-merges", "--format=%s", "-n", str(sample)) or ""

    readme_text = ""
    readme_name = None
    for name in ("README.md", "README.rst", "README.txt", "README"):
        candidate = Path(root) / name
        if candidate.is_file():
            readme_name = name
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                    readme_text = handle.read(20000)
            except OSError:
                readme_text = ""
            break

    counts = _script_counts(subjects + readme_text)
    total = sum(counts.values())
    if total == 0:
        return {"guess": None, "basis": "no commit subjects or README to read",
                "counts": counts, "sources": {"commits": bool(subjects), "readme": readme_name}}

    shares = {script: count / total for script, count in counts.items()}
    non_latin = max(("cyrillic", "cjk"), key=lambda s: shares[s])
    if shares[non_latin] >= _SCRIPT_THRESHOLD:
        guess = "russian" if non_latin == "cyrillic" else "cjk"
        basis = "%s is %.0f%% of letters sampled" % (non_latin, 100 * shares[non_latin])
    else:
        guess = "english"
        basis = "latin is %.0f%% of letters sampled" % (100 * shares["latin"])
        if counts["cyrillic"] or counts["cjk"]:
            basis += "; some non-latin present but below the %.0f%% threshold" % (
                100 * _SCRIPT_THRESHOLD)

    return {
        "guess": guess,
        "basis": basis,
        "counts": counts,
        "sources": {"commits": bool(subjects), "readme": readme_name},
    }


def scaffold_state(root, coordination_dir=None):
    """Whether this scaffold is already installed here, and at what version.

    `coordination_dir` mirrors `upgrade.py`'s flag of the same name. The two tools used to
    disagree: upgrade could be pointed anywhere while discovery only ever looked at
    `<root>/coordination`, so a project that had moved the directory read as "not
    installed" to one tool and worked fine with the other.

    Deliberately NOT `coordlib.paths.find_coordination_dir`, though it is already imported
    in this module: that helper falls back to `<root>/assets/coordination`, which is this
    skill's own staging layout, and using it would both reintroduce the "shipped tool knows
    the authoring repository" branch removed in #39 and make discovery report the skill's
    own checkout as a project with the scaffold installed.
    """
    relative = coordination_dir or "coordination"
    coordination = Path(root) / relative
    if not coordination.is_dir():
        return {"installed": False}

    state = {"installed": True, "coordination_dir": str(relative)}
    stamp = manifest.read_stamp(coordination)
    if stamp is None:
        state["stamp"] = None
        state["note"] = (
            "installed but unstamped: run `upgrade.py --adopt` to record a baseline, "
            "after which drift becomes measurable"
        )
    else:
        state["stamp"] = {
            "source_commit": stamp.get("source_commit", ""),
            "source_ref": stamp.get("source_ref", ""),
            "installed_at": stamp.get("installed_at", ""),
            "adopted": stamp.get("adopted", False),
            "files": len(stamp.get("files", {})),
        }

    matrix = coordination / "OWNERSHIP.md"
    if matrix.is_file():
        zones = parse_ownership(matrix)
        state["declared_zones"] = [
            {"pattern": z.pattern, "owner": z.owner, "line": z.line} for z in zones
        ]
    return state


def discover(root, coordination_dir=None):
    """Everything this tool can establish without asking or writing."""
    root = Path(root)
    git = is_git_repo(root)
    zones, ownership_warning = ownership_map(root) if git else ([], None)
    return {
        "root": str(root),
        "is_git_repo": git,
        "top_level_directories": top_level_entries(root),
        "ownership_map": zones,
        "ownership_map_warning": ownership_warning,
        "existing_codeowners": existing_codeowners(root),
        "existing_instructions": existing_instructions(root),
        "existing_coordination_files": existing_coordination_files(root),
        "verification_commands": verification_commands(root),
        "documentation_language": documentation_language(root),
        "scaffold": scaffold_state(root, coordination_dir),
    }


def render(report):
    """Human-readable rendering. Says what it could NOT determine, not only what it could."""
    lines = ["Repository reconnaissance: %s" % report["root"], ""]

    if not report["is_git_repo"]:
        lines.append("  ! not a git repository - no ownership map, no language inference")
        lines.append("")

    scaffold = report["scaffold"]
    if scaffold.get("installed"):
        stamp = scaffold.get("stamp")
        if stamp:
            lines.append("Scaffold: installed, %d files stamped%s" % (
                stamp["files"], " (adopted baseline)" if stamp.get("adopted") else ""))
            if stamp.get("source_ref") or stamp.get("source_commit"):
                lines.append("          from %s %s" % (
                    stamp.get("source_ref", ""), stamp.get("source_commit", "")[:12]))
        else:
            lines.append("Scaffold: installed but UNSTAMPED - %s" % scaffold.get("note", ""))
    else:
        lines.append("Scaffold: not installed")
    lines.append("")

    zones = report["ownership_map"]
    warning = report.get("ownership_map_warning")
    if zones:
        lines.append("Who actually edits what (git history, lines added+removed):")
        for zone in zones[:12]:
            lines.append("  %-24s %8d lines   %s (%.0f%%, %d author%s)" % (
                zone["path"], zone["lines"], zone["top_author"],
                zone["dominance_pct"], zone["authors"],
                "" if zone["authors"] == 1 else "s"))
    elif warning:
        lines.append("Who actually edits what: NOT DETERMINED - %s" % warning)
    elif report["is_git_repo"]:
        lines.append("Who actually edits what: no commit history to read")
    lines.append("")

    coord_files = report["existing_coordination_files"]
    if coord_files:
        lines.append("Existing coordination files - READ before writing, archaeological not "
                     "aspirational:")
        for item in coord_files:
            detail = ("%s lines" % item["lines"]) if item["lines"] is not None else "unreadable"
            lines.append("  %-34s %s" % (item["path"], detail))
        lines.append("")

    codeowners = report["existing_codeowners"]
    if codeowners:
        lines.append("Existing %s: %d rules - propose OWNERSHIP.md from these, don't start empty"
                     % (codeowners["file"], len(codeowners["rules"])))
    else:
        lines.append("Existing CODEOWNERS: none")

    instructions = report["existing_instructions"]
    if instructions:
        lines.append("Existing agent instructions - IMPORT, never overwrite:")
        for item in instructions:
            detail = ("%s lines" % item["lines"]) if item.get("lines") is not None \
                else ("%s rule files" % item.get("rule_files", "?"))
            lines.append("  %-34s %s" % (item["path"], detail))
    else:
        lines.append("Existing agent instructions: none")
    lines.append("")

    commands = report["verification_commands"]
    if commands:
        lines.append("Verification commands already defined (the project's real DoD):")
        for source, items in sorted(commands.items()):
            shown = ", ".join(items[:10])
            more = "" if len(items) <= 10 else " (+%d more)" % (len(items) - 10)
            lines.append("  %-22s %s%s" % (source, shown, more))
    else:
        lines.append("Verification commands: none found - this one has to be asked")
    lines.append("")

    language = report["documentation_language"]
    lines.append("Documentation language: %s (%s)" % (
        language["guess"] or "undetermined", language["basis"]))
    lines.append("")
    lines.append("Everything above is evidence, not a decision. Confirm it with the owner;")
    lines.append("ask outright only what is not here: roles, orchestrator, guardrails,")
    lines.append("enforcement level, and whether work spans several machines.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="project to inspect (default: discovered repo root)")
    parser.add_argument("--coordination-dir", default=None,
                        help="path to coordination/ relative to the root, when the project "
                             "does not keep it at <root>/coordination (default: that path)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = find_repo_root() or Path.cwd()

    if not Path(root).is_dir():
        print("discover: %s is not a directory" % root, file=sys.stderr)
        return 0

    report = discover(root, args.coordination_dir)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
