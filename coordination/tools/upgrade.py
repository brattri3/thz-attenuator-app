#!/usr/bin/env python3
"""upgrade.py - what changed upstream, what you changed, and where those overlap.

The scaffold is copied into a project and the link is severed. Fixes made upstream --
including ones for defects that corrupt files or make a journal report zero open questions
and be believed -- never reach any project already running it. This is the delivery
direction that the skill's `references/upstream-feedback.md` does not cover.

**This reports; it does not merge.** Three-way auto-merge of markdown that humans have
edited cannot be done without lying about the result, and a wrong merge of CHARTER.md is
worse than no upgrade channel at all. What a human actually needs is the short list of
places where a decision is required, and that is what this prints.

It works offline. `.scaffold-version` records the pristine hash of every installed file, so
"did you change this?" is answerable without contacting anything; `--from` points at a newer
checkout of the skill, which is on disk already because that is how the skill is used.

    python3 coordination/tools/upgrade.py --from /path/to/skill/assets
    python3 coordination/tools/upgrade.py --from /path/to/skill/assets --json
    python3 coordination/tools/upgrade.py --adopt --from /path/to/skill/assets
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coordlib import manifest  # noqa: E402
from coordlib.paths import find_coordination_dir, find_repo_root  # noqa: E402

#: Categories, in the order a reader should work through them.
UNCHANGED = "unchanged"
ALREADY_CURRENT = "already-current"
UPSTREAM_DELETED = "upstream-deleted"
UPSTREAM_ONLY = "upstream-only"
UPSTREAM_ONLY_BUT_CUSTOMIZED = "upstream-only-but-customized"
LOCAL_ONLY = "local-only"
BOTH = "both"
DELETED_LOCALLY = "deleted-locally"
NEW_UPSTREAM = "new-upstream"
SEED_CHANGED = "seed-changed"

#: Only these classes have a local file whose content is supposed to equal the source, so
#: only these can meaningfully be called "locally modified". Project-owned files grow by
#: design -- ACTIVITY.md is longer every day, and reporting that as drift every run is how
#: a report earns being ignored.
COMPARABLE_CLASSES = (manifest.TOOL, manifest.DOCTRINE)


def project_root_for(coordination_dir):
    """The directory the manifest's paths are relative to: the parent of coordination/."""
    return Path(coordination_dir).resolve().parent


def hash_upstream(assets_dir):
    """{installed_path: (sha256, asset_path)} for a newer scaffold checkout."""
    assets_dir = Path(assets_dir)
    upstream = {}
    for asset_path, digest in manifest.hash_tree(assets_dir).items():
        upstream[manifest.installed_path_for(asset_path)] = (digest, asset_path)
    return upstream


def compare(stamp, project_root, upstream):
    """Classify every file into exactly one category.

    Three inputs, per the plan: the pristine hash recorded at install time, the file on
    disk now, and the same file in a newer scaffold. `both` is the only category that
    requires a human, and keeping it small is the whole design goal.
    """
    project_root = Path(project_root)
    recorded = stamp.get("files", {})
    rows = []
    seen = set()

    for installed_path, entry in sorted(recorded.items()):
        seen.add(installed_path)
        file_class = entry.get("class", manifest.DOCTRINE)
        installed_baseline = entry.get("sha256")
        upstream_baseline = entry.get("upstream_sha256", installed_baseline)
        upstream_digest, asset_path = upstream.get(installed_path, (None, entry.get("source")))

        # The two baselines differ only when the file was ALREADY the project's own content
        # at the moment the baseline was frozen -- the case `pre_existing_divergence()`
        # reports once during --adopt and then forgets. Persisted here on every stamp entry,
        # it is what keeps "unchanged since baseline" from being read as "still the shipped
        # seed" on every later run. A stamp written before `upstream_sha256` existed defaults
        # the two to equal, so an old stamp reports False rather than guessing.
        customized_at_baseline = (installed_baseline is not None
                                  and upstream_baseline is not None
                                  and installed_baseline != upstream_baseline)

        row = {
            "path": installed_path,
            "class": file_class,
            "source": asset_path,
            "customized_at_baseline": customized_at_baseline,
            # Compared against the UPSTREAM baseline, never the installed one: a file the
            # installer filled in differs from its source by design, and measuring upstream
            # movement against the filled copy would report a change nobody made.
            "upstream_changed": (upstream_digest is not None
                                 and upstream_digest != upstream_baseline),
        }

        if upstream_digest is None and (project_root / installed_path).exists():
            # Gone from upstream, still here. Reaching this by falling through to
            # `unchanged` is how issue #53 broke a consumer's tree: `upstream_changed` is
            # false when there is no upstream digest, so three files whose module had been
            # refactored away sat in the bucket whose summary line is "N file(s)
            # unchanged", and taking their dependants stopped the suite from collecting.
            # The mirror image has had `deleted-locally` since the beginning; this
            # direction needs a name of its own for the same reason.
            row["local_changed"] = None
            row["category"] = UPSTREAM_DELETED
            rows.append(row)
            continue

        if file_class not in COMPARABLE_CLASSES:
            # The local file is meant to differ; only the upstream side is comparable.
            row["local_changed"] = None
            row["category"] = SEED_CHANGED if row["upstream_changed"] else UNCHANGED
            rows.append(row)
            continue

        local_digest = manifest.hash_file(project_root / installed_path)
        if local_digest is None:
            row["local_changed"] = None
            row["category"] = DELETED_LOCALLY
            rows.append(row)
            continue

        local_changed = local_digest != installed_baseline
        row["local_changed"] = local_changed

        # The question every other branch here forgets to ask: is the file ALREADY the
        # upstream one? Both baselines can say "changed" about a copy that is byte-identical
        # to the new upstream -- which is exactly what taking an update by hand produces,
        # since this tool reports and does not merge. Without this, a consumer's second run
        # reports every file they took as `both` ("reconcile by hand") and exits 1 forever:
        # issue #52, 28 of 28 rows, all verified identical to upstream by sha256.
        #
        # Guarded on either side having moved so that the quiet case stays quiet: a file
        # nobody has touched on either side is still plain `unchanged`, not a row claiming
        # an update was taken.
        if (upstream_digest is not None and local_digest == upstream_digest
                and (local_changed or row["upstream_changed"])):
            row["category"] = ALREADY_CURRENT
        elif local_changed and row["upstream_changed"]:
            row["category"] = BOTH
        elif row["upstream_changed"]:
            # "Untouched since baseline" carries two different histories. For a file that was
            # installed verbatim it means "still the generic template", and taking the new
            # upstream copy is right. For one that was already hand-written when the baseline
            # was frozen it means "still the project's own content" -- copying upstream over
            # it discards exactly what --adopt was for. Same digest comparison, opposite
            # correct action, so they cannot share a bucket called "safe to take".
            row["category"] = (UPSTREAM_ONLY_BUT_CUSTOMIZED if customized_at_baseline
                               else UPSTREAM_ONLY)
        elif local_changed:
            row["category"] = LOCAL_ONLY
        else:
            row["category"] = UNCHANGED
        rows.append(row)

    for installed_path, (digest, asset_path) in sorted(upstream.items()):
        if installed_path in seen:
            continue
        rows.append({
            "path": installed_path,
            "class": manifest.classify(installed_path),
            "source": asset_path,
            "customized_at_baseline": False,
            "upstream_changed": True,
            "local_changed": None,
            "category": NEW_UPSTREAM,
        })

    return rows


def group(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    return grouped


_EXPLANATIONS = (
    (BOTH, "CHANGED ON BOTH SIDES - the only rows that need you",
     "Upstream changed these and so did you. Read both diffs and decide; nothing else here "
     "requires a judgement call."),
    (UPSTREAM_ONLY_BUT_CUSTOMIZED,
     "CUSTOMISED BEFORE ADOPTION, and upstream has moved since - review by hand",
     "You have not touched these since the baseline was frozen, but they were already your "
     "own content when that happened -- never the shipped seed. Read them like the rows "
     "above, not like the ones below: copying upstream across discards the customisation."),
    (UPSTREAM_ONLY, "Safe to take - upstream changed, your copy is untouched",
     "These carry the fixes. Copy them across."),
    (UPSTREAM_DELETED, "GONE FROM UPSTREAM - yours alone now",
     "Upstream removed these; your copy is all that is left. Keep, archive or delete them "
     "deliberately -- and check what still imports them before you take anything else, "
     "because a file above may be the module these were written against."),
    (NEW_UPSTREAM, "New upstream - did not exist when you installed",
     "Review and install the ones you want."),
    (DELETED_LOCALLY, "Missing locally",
     "Removed on purpose, or lost. Reinstall or confirm the removal."),
    (SEED_CHANGED, "Seed or template changed upstream",
     "Your filled-in copy is yours; compare against the new seed and port what applies."),
    (LOCAL_ONLY, "Yours alone - upstream unchanged",
     "Nothing to do. Listed so you can see what you have customised."),
    (ALREADY_CURRENT, "Already current - identical to upstream",
     "You have taken these already; your copy matches upstream byte for byte. Listed so a "
     "run after an update shows the work landing, rather than silence."),
)


def render(rows, stamp, upstream_ref="", strict=False):
    grouped = group(rows)
    lines = []

    installed_at = stamp.get("installed_at", "unknown")
    source = stamp.get("source_commit", "") or stamp.get("source_ref", "") or "unrecorded"
    lines.append("Scaffold drift report")
    lines.append("  installed %s from %s" % (installed_at, source))
    if upstream_ref:
        lines.append("  compared against %s" % upstream_ref)
    if stamp.get("adopted"):
        lines.append("  ! baseline was ADOPTED from files already on disk: what any")
        lines.append("    pre-adoption edits changed is invisible to this comparison, though")
        lines.append("    a file that already differed is marked customised, not pristine")
    if grouped.get(UPSTREAM_ONLY_BUT_CUSTOMIZED):
        # Whether these rows fail a build is a real difference in behaviour, and the reader
        # deciding what to do with them is exactly who needs to know which way it went.
        lines.append("  customised-before-adoption rows %s the exit code%s"
                     % ("FAIL" if strict else "do not affect",
                        "" if strict else " (--strict to change)"))
    lines.append("")

    actionable = 0
    for category, title, explanation in _EXPLANATIONS:
        items = grouped.get(category)
        if not items:
            continue
        if category not in (LOCAL_ONLY, ALREADY_CURRENT):
            actionable += len(items)
        lines.append("%s (%d)" % (title, len(items)))
        lines.append("  %s" % explanation)
        for row in items:
            lines.append("    %-52s [%s]" % (row["path"], row["class"]))
        lines.append("")

    unchanged = len(grouped.get(UNCHANGED, []))
    lines.append("%d file(s) unchanged." % unchanged)
    if not actionable:
        lines.append("Nothing to do.")
    return "\n".join(lines)


def pre_existing_divergence(assets_dir, project_root):
    """Files that already differ from `assets_dir` before a baseline is frozen.

    Adoption blesses whatever is on disk, which necessarily hides every edit made before
    it. Printing this list once, at the moment of adoption, is the difference between a
    documented limitation and a silent one -- afterwards no tool can recover it.

    Only classes whose installed content is supposed to equal the source are listed;
    a filled-in template differing from its seed is the installer working, not divergence.
    """
    assets_dir = Path(assets_dir)
    project_root = Path(project_root)
    diverged = []
    for asset_path, upstream_digest in sorted(manifest.hash_tree(assets_dir).items()):
        installed = manifest.installed_path_for(asset_path)
        if manifest.classify(installed) not in COMPARABLE_CLASSES:
            continue
        local_digest = manifest.hash_file(project_root / installed)
        if local_digest is not None and local_digest != upstream_digest:
            diverged.append(installed)
    return diverged


def upstream_provenance(assets_dir):
    """(commit, ref) of the checkout `--from` points into, or ("", "") if it is not one.

    The stamp has always had `source_commit` and `source_ref` fields, and nothing ever
    filled them: the only caller of `build_stamp` passed neither, so every stamp recorded
    an empty provenance and the report printed "installed <date> from unrecorded" forever.
    The information was never far away -- `--from` names a directory inside the skill's own
    checkout -- it was simply never asked for.

    A missing or broken git is not an error here. A baseline with no provenance is worth
    less than one with it, and worth far more than a failed adopt.
    """
    def ask(*args):
        try:
            out = subprocess.run(
                ("git", "-C", str(assets_dir)) + args,
                capture_output=True, text=True, encoding="utf-8",
            )
        except (OSError, ValueError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    commit = ask("rev-parse", "HEAD")
    ref = ask("rev-parse", "--abbrev-ref", "HEAD")
    # Detached HEAD reports the branch as "HEAD", which is not a ref anyone can check out.
    return commit, ("" if ref == "HEAD" else ref)


def build_adopted(coordination_dir, assets_dir):
    """Baseline for a project installed before stamping existed.

    Hashes what is ON DISK now for the local side, so the first report reads "no drift"
    rather than flagging every local customisation as a conflict on day one.
    """
    commit, ref = upstream_provenance(assets_dir)
    return manifest.build_stamp(
        Path(assets_dir), project_root_for(coordination_dir),
        source_commit=commit, source_ref=ref, adopted=True)


def looks_like_the_skill_itself(coordination_dir):
    """True when the discovered coordination/ is this skill's own authoring copy.

    `find_coordination_dir` falls back to `<root>/assets/coordination`, so running this
    tool inside the skill repository resolves to the templates rather than to an installed
    project. Comparing the skill against itself produces a confusing empty report instead
    of an error, which is a bad first experience for whoever maintains it.
    """
    return "assets" in Path(coordination_dir).resolve().parts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="upstream", required=True,
                        help="path to a newer checkout of the skill's assets/ directory")
    parser.add_argument("--coordination-dir", help="path to coordination/ (default: discover)")
    parser.add_argument("--adopt", action="store_true",
                        help="write a baseline from the files currently on disk, for a "
                             "project installed before stamping existed")
    parser.add_argument("--json", action="store_true")
    # An ordinary boolean, like --strict on build_index.py and check_rules.py. It used to be
    # three-state, with the default read out of the stamp's format version, so the same drift
    # in two projects could exit differently and neither invocation said which rule applied.
    parser.add_argument("--strict", action="store_true",
                        help="also exit 1 when a file customised before adoption has moved "
                             "upstream (default: exit 1 only on a `both` row)")
    args = parser.parse_args(argv)

    upstream_dir = Path(args.upstream)
    if not upstream_dir.is_dir():
        print("upgrade: --from %s is not a directory" % upstream_dir, file=sys.stderr)
        return 2

    explicit_dir = bool(args.coordination_dir)
    if explicit_dir:
        coordination = Path(args.coordination_dir).resolve()
    else:
        coordination = find_coordination_dir()
    if coordination is None or not Path(coordination).is_dir():
        print("upgrade: no coordination/ directory found", file=sys.stderr)
        return 2

    if not explicit_dir and looks_like_the_skill_itself(coordination):
        print("upgrade: %s is the skill's own template tree, not an installed project.\n"
              "         Run this inside a project that installed the scaffold, or pass\n"
              "         --coordination-dir explicitly if you really mean this directory."
              % coordination, file=sys.stderr)
        return 2

    if args.adopt:
        diverged = pre_existing_divergence(upstream_dir, project_root_for(coordination))
        payload = build_adopted(coordination, upstream_dir)
        target = manifest.write_stamp(coordination, payload)
        print("upgrade: adopted a baseline of %d file(s) into %s"
              % (len(payload["files"]), target))
        if diverged:
            print("", file=sys.stderr)
            print("These %d file(s) ALREADY differ from %s and are now frozen into the"
                  % (len(diverged), upstream_dir), file=sys.stderr)
            print("baseline as your content rather than as the shipped seed:", file=sys.stderr)
            for path in diverged:
                print("    %s" % path, file=sys.stderr)
        print("         WHAT those edits were is not recoverable from here on: the baseline")
        print("         records their result, not the seed they departed from. That they")
        print("         happened is kept -- a later report files such a file under")
        print("         \"customised before adoption\" instead of \"safe to take\".")
        return 0

    stamp = manifest.read_stamp(coordination)
    if stamp is None:
        print("upgrade: no usable %s in %s.\n"
              "         This project was installed before stamping existed, or the stamp is\n"
              "         unreadable. Run with --adopt to record a baseline from what is on\n"
              "         disk now; drift becomes measurable from that point forward."
              % (manifest.STAMP_NAME, coordination), file=sys.stderr)
        return 2

    upstream = hash_upstream(upstream_dir)
    rows = compare(stamp, project_root_for(coordination), upstream)

    # One rule, the same in every project: red means a `both` row unless the caller asked for
    # more. A customised-before-adoption row carries the same risk -- a hand-written file that
    # upstream has also moved -- and a project that wants its build to stop on those writes
    # --strict in the CI step, where the next reader can see it. The alternative, deciding
    # from the stamp's format version, kept an existing project's CI meaning intact but made
    # the exit code depend on a JSON field nobody reads; --strict in a CI file is backward
    # compatible for everyone and visible to anyone.
    if args.json:
        print(json.dumps({"stamp": {k: stamp.get(k) for k in
                                    ("source_commit", "source_ref", "installed_at", "adopted",
                                     "format")},
                          "upstream": str(upstream_dir),
                          "strict": args.strict,
                          "rows": rows}, indent=2, ensure_ascii=False))
    else:
        print(render(rows, stamp, upstream_ref=str(upstream_dir), strict=args.strict))

    gating = (BOTH, UPSTREAM_ONLY_BUT_CUSTOMIZED) if args.strict else (BOTH,)
    return 1 if any(row["category"] in gating for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
