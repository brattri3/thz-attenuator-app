"""manifest.py - what was installed, in what state, and who is allowed to change it.

`discover.py` and `upgrade.py` both need the same three answers, so they live here once:

  * **What is the pristine content of an installed file?** Recorded as a hash at install
    time. Without that record, "your copy is locally modified" is undecidable offline, and
    an upgrade channel that needs the network to answer a local question is not much of a
    channel.
  * **Which files is the project SUPPOSED to change?** `ACTIVITY.md` grows by design. A
    drift report that flags it every run is noise, and a noisy report gets ignored, which is
    worse than no report -- so classification is part of the manifest, not an afterthought
    in the reporting tool.
  * **Which files are not part of the scaffold at all?** `__pycache__` and friends.

Stdlib only, like everything that ships with the core scaffold.

STABILITY: INTERNAL. The stamp's path and its `format` field are promised; this reader is not. Nothing outside this package should depend on the
names or shapes here; they may change without notice. See the skill's
references/extension-contract.md for what IS promised.
"""

import fnmatch
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .ownership import strip_leading_dot_slash

#: Where the stamp lives inside an installed project, relative to the coordination directory.
STAMP_NAME = ".scaffold-version"

#: Manifest format version -- which era of the tool wrote this stamp. Bumped when the on-disk
#: shape changes incompatibly, so a newer tool can tell "written by an older installer" from
#: "corrupt", and (from 2 onward) when the DEFAULT reading of an unchanged shape changes,
#: which is the same question asked of the same field.
#:
#: Version 2 adds no keys and stays readable by a version-1 tool. It marks a stamp written by
#: a tool that tells `upstream-only-but-customized` apart from `upstream-only`.
#:
#: Nothing branches on it. `upgrade.py` did for one day -- it read this field to decide
#: whether that category should fail a build -- which made the same drift exit differently in
#: two projects for a reason visible only inside a JSON file. The gate is now one rule plus
#: `--strict`, and this stays a record of which era wrote a stamp rather than an input to
#: behaviour. Read it when you need to know what a baseline could see; do not gate on it.
FORMAT_VERSION = 2

#: Never part of the scaffold: build artifacts, caches, and anything git already ignores by
#: convention. Matched against the POSIX relative path and against each path segment.
EXCLUDED_PATTERNS = (
    "__pycache__",
    "*.py[cod]",
    ".pytest_cache",
    ".coverage",
    ".coverage.*",
    "htmlcov",
    ".DS_Store",
)

# --------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------

#: A file the scaffold owns. Upgrading it when the local copy is untouched is safe and is
#: the entire point of having an upgrade channel -- these carry the bug fixes.
TOOL = "tool"

#: Written rules and worked examples. The scaffold authors them, but a project may
#: legitimately adapt them, so an upstream change is offered and never assumed.
DOCTRINE = "doctrine"

#: Seeded once, then owned by the project. The journals, the role files, the ownership
#: matrix. These are EXCLUDED from drift reporting entirely: they are meant to diverge, and
#: divergence is the project working, not a problem to report.
PROJECT = "project"

#: A `.template` that the installer renames and fills in. Reported once when upstream
#: changes so the owner can compare, never overwritten.
CONFIG_SEED = "config-seed"

CLASSES = (TOOL, DOCTRINE, PROJECT, CONFIG_SEED)

#: Paths, relative to the project root, that the project owns once seeded. Matched as
#: prefixes for directories and exactly for files.
_PROJECT_OWNED = (
    "coordination/ACTIVITY.md",
    "coordination/BOARD.md",
    "coordination/HANDOFFS.md",
    "coordination/LAUNCH_PROMPTS.md",
    "coordination/ORCH_BRIEF.md",
    "coordination/OWNERSHIP.md",
    "coordination/PROJECT.md",
    "coordination/QUESTIONS.md",
    "coordination/roles/",
    "AGENTS.md",
    "CLAUDE.md",
)


def classify(relative_path: str, source_path: Optional[str] = None) -> str:
    """Classify a file by its project-relative POSIX path, and its source when known.

    `source_path` is not decoration. `installed_path_for` strips the `.template` suffix, so
    by the time a file is on disk it is `AGENTS.md`, not `AGENTS.md.template`, and the
    seed-ness is only visible in where it came from. Classifying the installed path alone
    made CONFIG_SEED unreachable in practice -- a class that no real file could ever have.

    Order matters. The project-owned list wins over seed-ness, because `AGENTS.md` is a
    file the project writes whatever it was seeded from, and it is checked before the tools
    prefix so `OWNERSHIP.md` does not fall through to the default.
    """
    path = strip_leading_dot_slash(relative_path.replace("\\", "/"))
    seeded = bool(source_path) and source_path.endswith(".template")

    if path.endswith(".template"):
        return CONFIG_SEED
    for owned in _PROJECT_OWNED:
        if owned.endswith("/"):
            if path.startswith(owned):
                return PROJECT
        elif path == owned:
            return PROJECT
    if seeded:
        return CONFIG_SEED
    if path.startswith("coordination/tools/") or path.startswith(".claude/hooks/"):
        return TOOL
    return DOCTRINE


def installed_path_for(asset_relative_path: str) -> str:
    """Where a file under the skill's `assets/` lands in an installed project.

    Two renames happen at install time and both must be encoded here rather than guessed
    at each call site, because a comparison that keys the two trees differently silently
    reports every file as new:

      * a leading `dot-` becomes a dot: `dot-claude/hooks/x.py` -> `.claude/hooks/x.py`
      * the `.template` suffix is dropped: `AGENTS.md.template` -> `AGENTS.md`
    """
    path = strip_leading_dot_slash(asset_relative_path.replace("\\", "/"))
    segments = path.split("/")
    if segments and segments[0].startswith("dot-"):
        segments[0] = "." + segments[0][len("dot-"):]
    path = "/".join(segments)
    if path.endswith(".template"):
        path = path[: -len(".template")]
    return path


def is_excluded(relative_path: str) -> bool:
    """True for build artifacts and caches, which are never part of the manifest."""
    path = relative_path.replace("\\", "/")
    segments = path.split("/")
    for pattern in EXCLUDED_PATTERNS:
        if fnmatch.fnmatch(path, pattern):
            return True
        for segment in segments:
            if fnmatch.fnmatch(segment, pattern):
                return True
    return False


# --------------------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------------------

def hash_bytes(data: bytes) -> str:
    """SHA-256 of file content, with CRLF normalised to LF for text.

    Without the normalisation, a checkout with `core.autocrlf=true` reports every single
    file as locally modified, and the first Windows user to run the upgrade report
    concludes it is broken -- correctly, in the sense that a report where everything is
    flagged carries no information.

    Binary content is hashed verbatim: normalising it would corrupt the comparison, and a
    0x0d byte in a binary file is data, not a line ending.
    """
    if b"\x00" in data:
        return hashlib.sha256(data).hexdigest()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def hash_file(path) -> Optional[str]:
    """Hash a file, or None when it cannot be read (missing, a directory, no permission)."""
    try:
        with open(path, "rb") as handle:
            return hash_bytes(handle.read())
    except (OSError, ValueError):
        return None


def hash_tree(root, relative_to=None) -> Dict[str, str]:
    """Hash every non-excluded file under `root`, keyed by path relative to `relative_to`.

    `relative_to` defaults to `root`. It exists because the skill's own tree is rooted at
    `assets/` while an installed project's is rooted at the project directory, and the
    manifest keys must match across the two for any comparison to mean anything.
    """
    root = Path(root)
    base = Path(relative_to) if relative_to is not None else root
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded(d) and d != ".git"]
        for name in filenames:
            full = Path(dirpath) / name
            relative = full.relative_to(base).as_posix()
            if is_excluded(relative):
                continue
            digest = hash_file(full)
            if digest is not None:
                found[relative] = digest
    return found


# --------------------------------------------------------------------------------------
# The stamp
# --------------------------------------------------------------------------------------

def stamp_path(coordination_dir) -> Path:
    return Path(coordination_dir) / STAMP_NAME


def build_stamp(assets_dir, project_root, *, source_commit="", source_ref="",
                answers=None, adopted=False) -> dict:
    """Assemble the stamp by hashing BOTH sides of the install.

    Two hashes per entry, and the second one is not redundant -- it is what makes the whole
    report usable. Installed files are not byte-identical to their sources: the installer
    fills `<PROJECT NAME>`, the role ids, the zone tables, and the skill's `references/setup.md` §4
    explicitly tells it to fill CHARTER.md's "shared/core code" and "conflict hot spots"
    sections. With a single source hash, every file customised during a normal install
    reports as locally modified on the very first run, forever.

      * `sha256`          - the file AS INSTALLED. The baseline for "did you change it?"
      * `upstream_sha256` - the asset it came from. The baseline for "did they change it?"

    The two comparisons are then independent, and only their intersection needs a human.

    `adopted` records that the baseline was taken from files already on disk rather than
    from a fresh install. It matters: in an adopted project, edits made before adoption are
    invisible to every later comparison, and a report that does not say so overclaims.
    """
    assets_dir = Path(assets_dir)
    project_root = Path(project_root)
    files = {}
    for asset_path, upstream_digest in hash_tree(assets_dir).items():
        installed = installed_path_for(asset_path)
        installed_digest = hash_file(project_root / installed)
        if installed_digest is None:
            # Not installed here -- an optional subtree the project chose to skip. Recording
            # it would make every later run report a file the owner deliberately left out.
            continue
        files[installed] = {
            "sha256": installed_digest,
            "upstream_sha256": upstream_digest,
            "class": classify(installed, asset_path),
            "source": asset_path,
        }
    return {
        "format": FORMAT_VERSION,
        "source_commit": source_commit,
        "source_ref": source_ref,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "adopted": bool(adopted),
        "answers": answers or {},
        "files": {path: files[path] for path in sorted(files)},
    }


def write_stamp(coordination_dir, payload: dict) -> Path:
    """Write the stamp with LF endings, sorted, so it diffs cleanly in review."""
    target = stamp_path(coordination_dir)
    os.makedirs(target.parent, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=False)
        handle.write("\n")
    return target


def read_stamp(coordination_dir):
    """Read the stamp, or None when it is absent or unreadable.

    A malformed stamp returns None rather than raising: the caller's job is to say "this
    project has no usable baseline, run --adopt", which is actionable, where a traceback
    is not.
    """
    target = stamp_path(coordination_dir)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or "files" not in payload:
        return None
    return payload
