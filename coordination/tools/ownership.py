#!/usr/bin/env python3
"""ownership.py - render `.github/CODEOWNERS` from `coordination/OWNERSHIP.md`.

`dot-github/CODEOWNERS.template` already tells you to "mirror OWNERSHIP.md's Exclusive
zones table exactly -- same paths, same owners, so the two files can't silently drift
apart". Nothing enforced that, and two hand-maintained copies of the same table drift on
the first busy day. This renders one from the other and can fail CI when they disagree.

Stdlib only, like every tool that ships with the core scaffold.

Reading is the default and writing is opt-in (`--output`), matching the invariant in
`docs/ru/CONCEPT.md` section 6.5: a tool projects git state, it does not quietly mutate it.

    python3 coordination/tools/ownership.py --map ORCH=@alice --map B=@bob
    python3 coordination/tools/ownership.py --map-file coordination/tools/owners.json \
        --output .github/CODEOWNERS
    python3 coordination/tools/ownership.py --map-file owners.json --check   # CI drift gate
"""

import argparse
import json
import os
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coordlib import diagnostics as diag  # noqa: E402
from coordlib.ownership import parse_ownership  # noqa: E402
from coordlib.paths import find_coordination_dir, find_repo_root  # noqa: E402

HEADER = """# CODEOWNERS - GENERATED FROM coordination/OWNERSHIP.md. Do not edit by hand.
#
# Regenerate:  python3 coordination/tools/ownership.py --map-file <owners.json> -o .github/CODEOWNERS
# Verify:      python3 coordination/tools/ownership.py --map-file <owners.json> --check
#
# GitHub uses the LAST matching rule, so rules are emitted least-specific first and the
# most specific zone wins - the same precedence OWNERSHIP.md's table is read with.
#
# CODEOWNERS is a REVIEW ROUTE, not a write barrier: it only gates a merge once branch
# protection has "Require review from Code Owners" enabled, and only when the listed owners
# are different accounts with write access. To actually stop a write as it happens, see
# .claude/hooks/check-path-ownership.py.
"""


def to_codeowners_pattern(pattern: str) -> str:
    """Translate an OWNERSHIP.md glob into CODEOWNERS syntax.

    CODEOWNERS follows gitignore matching, where a trailing slash already means "this
    directory and everything under it" -- so `src/core/**` is written `/src/core/`. A
    leading slash anchors to the repository root, which is what the matrix means; without
    it, `docs/` would also match `src/vendor/docs/`.
    """
    cleaned = pattern.strip().lstrip("/")
    if cleaned.endswith("/**"):
        return "/" + cleaned[: -len("/**")] + "/"
    if cleaned.endswith("/"):
        return "/" + cleaned
    if "*" in cleaned or "?" in cleaned:
        return "/" + cleaned
    return "/" + cleaned


def load_map(map_file, pairs):
    """Build the role-id -> @github-handle map from a JSON file plus CLI overrides."""
    mapping = {}
    if map_file:
        with open(map_file, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("owner map must be a JSON object of {role: '@handle'}")
        mapping.update({str(k): str(v) for k, v in loaded.items()})
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError("--map expects ROLE=@handle, got %r" % pair)
        role, handle = pair.split("=", 1)
        mapping[role.strip()] = handle.strip()
    return mapping


def handle_for(owner: str, mapping) -> str:
    """The GitHub handle for a role id, or the template's placeholder when unmapped.

    An unmapped role produces `@<ROLE_GITHUB_USER>` rather than being dropped: a silently
    missing line looks like "this path has no owner", which is the opposite of the truth.
    """
    handle = mapping.get(owner)
    if not handle:
        return "@<%s_GITHUB_USER>" % owner.upper()
    return handle if handle.startswith(("@", "#")) else "@" + handle


def render(zones, mapping) -> str:
    """Render the CODEOWNERS body, least-specific rule first."""
    lines = [HEADER.rstrip("\n")]
    unmapped = sorted({z.owner for z in zones if z.owner not in mapping})
    if unmapped:
        lines.append(
            "# Unmapped roles (replace the placeholders below with real accounts): %s"
            % ", ".join(unmapped)
        )
    lines.append("")
    width = 0
    ordered = sorted(zones, key=lambda z: (z.specificity, z.pattern))
    rendered = [(to_codeowners_pattern(z.pattern), handle_for(z.owner, mapping), z) for z in ordered]
    for pattern, _, _ in rendered:
        width = max(width, len(pattern))
    for pattern, handle, zone in rendered:
        lines.append("%-*s  %s  # OWNERSHIP.md:%s" % (width, pattern, handle, zone.line))
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coordination-dir", help="path to the coordination/ directory")
    parser.add_argument("--map", action="append", metavar="ROLE=@handle",
                        help="map one role id to a GitHub handle; repeatable")
    parser.add_argument("--map-file", help="JSON object of {role: '@handle'}")
    parser.add_argument("-o", "--output", help="write CODEOWNERS here instead of stdout")
    parser.add_argument("--check", action="store_true",
                        help="compare against --output (or .github/CODEOWNERS) and exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="emit the parsed zones as JSON")
    args = parser.parse_args(argv)

    if args.coordination_dir:
        coord_dir = Path(args.coordination_dir).resolve()
    else:
        coord_dir = find_coordination_dir()
    if coord_dir is None or not (coord_dir / "OWNERSHIP.md").is_file():
        print("ownership: no coordination/OWNERSHIP.md found", file=sys.stderr)
        return 2

    sink = diag.DiagnosticList()
    zones = parse_ownership(coord_dir / "OWNERSHIP.md", diagnostics=sink)
    for item in sink:
        print("WARN %s" % item, file=sys.stderr)

    try:
        mapping = load_map(args.map_file, args.map)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ownership: %s" % error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(
            [{"pattern": z.pattern, "owner": z.owner, "line": z.line,
              "codeowners": to_codeowners_pattern(z.pattern),
              "handle": handle_for(z.owner, mapping)} for z in zones],
            indent=2, ensure_ascii=False))
        return 0

    if not zones:
        print("ownership: OWNERSHIP.md has no actionable zones yet (only template rows)",
              file=sys.stderr)

    text = render(zones, mapping)

    if args.check:
        root = find_repo_root()
        target = Path(args.output) if args.output else (
            (root or Path.cwd()) / ".github" / "CODEOWNERS")
        if not Path(target).is_file():
            print("ownership: --check found no %s to compare against" % target, file=sys.stderr)
            return 1
        with open(target, "r", encoding="utf-8") as handle:
            current = handle.read()
        if current == text:
            print("ownership: %s matches OWNERSHIP.md" % target)
            return 0
        print("ownership: %s has drifted from OWNERSHIP.md; regenerate it" % target,
              file=sys.stderr)
        return 1

    if args.output:
        target = Path(args.output)
        os.makedirs(target.parent, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        print("ownership: wrote %s (%d zones)" % (target, len(zones)))
        return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
