#!/usr/bin/env python3
"""KPI from git: per-role output, pace, and time distribution.

Why git and nothing else: git history is the one source of truth equally reachable from every
machine and every ephemeral cloud session working on the project — unlike a live process
registry or local chat transcripts, which are tied to one machine and blind to subagents.

What this can NOT do: it has no idea about cost in dollars or tokens — that data doesn't exist
in git. If you need that, look at your model provider's usage telemetry (for Claude Code,
CLAUDE_CODE_ENABLE_TELEMETRY + OTLP gives claude_code.cost.usage with an agent.name attribute).
This script gives you output and pace, and nothing more.

Configuration (coordination/tools/kpi_config.json, optional):
    {
      "excluded_commits": {"<sha-or-prefix>": "why (e.g. bulk import, not authored work)"},
      "not_authored_prefixes": ["data_pool/", "archive/"]
    }

`excluded_commits` — commits that are bulk imports of a working tree rather than a role's own
work (e.g. re-creating the repo, or an initial import of a pre-existing project). Including them
attributes the whole project's pre-history to whoever happened to run the import command.

`not_authored_prefixes` — path prefixes that a role doesn't write by hand: measurement data,
generated fit output, archived snapshots. Counting these as "output" makes whoever commits the
most raw data look like the top contributor by lines changed, which is not what you want a KPI
for. Tune this per project — a project with no bulk data commits can leave it empty.

Usage (from repo root):
    python coordination/tools/kpi_git.py                 # text summary
    python coordination/tools/kpi_git.py --json out.json # plus machine-readable output
    python coordination/tools/kpi_git.py --config coordination/tools/kpi_config.json
"""

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys

ROLE_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\]")
MERGE_RE = re.compile(r"^Merge (branch|remote-tracking branch|pull request)")

SEP = "\x1f"
REC = "\x1e"


def load_config(path):
    if not path or not os.path.exists(path):
        return {}, ()
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return cfg.get("excluded_commits", {}), tuple(cfg.get("not_authored_prefixes", []))


def git(*args):
    try:
        out = subprocess.run(
            ("git",) + args, capture_output=True, text=True, check=True, encoding="utf-8"
        )
    except FileNotFoundError:
        sys.exit("git not found on PATH")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git {' '.join(args)} -> exit {exc.returncode}\n{exc.stderr.strip()}")
    return out.stdout


def collect(excluded_commits, not_authored):
    def is_authored(path):
        return not path.startswith(not_authored)

    def excluded(sha):
        return any(sha.startswith(key) for key in excluded_commits)

    raw = git(
        "log", "--all", "--numstat",
        f"--format={REC}%H{SEP}%ad{SEP}%s", "--date=short",
    )

    commits = []
    for chunk in raw.split(REC):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        head, _, body = chunk.partition("\n")
        sha, date, subject = head.split(SEP, 2)
        if excluded(sha):
            continue

        added = removed = files = 0
        data_added = 0
        for line in body.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            files += 1
            a = int(parts[0]) if parts[0] != "-" else 0
            r = int(parts[1]) if parts[1] != "-" else 0
            if is_authored(parts[2]):
                added += a
                removed += r
            else:
                data_added += a

        match = ROLE_RE.match(subject)
        if match:
            role = match.group(1)
        elif MERGE_RE.match(subject):
            role = "(merge)"
        else:
            role = "(untagged)"

        commits.append(
            {
                "sha": sha[:7], "date": date, "role": role, "subject": subject,
                "added": added, "removed": removed, "data_added": data_added, "files": files,
            }
        )
    return commits


def aggregate(commits):
    roles = collections.defaultdict(
        lambda: {"commits": 0, "added": 0, "removed": 0, "data_added": 0, "files": 0, "days": set()}
    )
    for c in commits:
        agg = roles[c["role"]]
        agg["commits"] += 1
        agg["added"] += c["added"]
        agg["removed"] += c["removed"]
        agg["data_added"] += c["data_added"]
        agg["files"] += c["files"]
        agg["days"].add(c["date"])

    out = {}
    for role, agg in roles.items():
        days = sorted(agg["days"])
        out[role] = {
            "commits": agg["commits"], "added": agg["added"], "removed": agg["removed"],
            "data_added": agg["data_added"], "files_touched": agg["files"],
            "active_days": len(days), "first": days[0], "last": days[-1],
            "lines_per_commit": round(agg["added"] / agg["commits"]) if agg["commits"] else 0,
        }
    return out


def by_week(commits):
    weeks = collections.Counter()
    for c in commits:
        day = datetime.date.fromisoformat(c["date"])
        monday = day - datetime.timedelta(days=day.weekday())
        weeks[monday.isoformat()] += 1
    return dict(sorted(weeks.items()))


def report(commits, roles, weeks, excluded_commits, not_authored):
    print("KPI from git — per-role output")
    print(f"generated: {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print()
    print(f"Commits counted: {len(commits)}")
    if excluded_commits:
        excl = ", ".join(f"{sha[:7]} ({why})" for sha, why in excluded_commits.items())
        print(f"Excluded as import/bulk: {excl}")
    print()

    head = (
        f"{'role':<12}{'commits':>8}{'+work':>10}{'-work':>9}"
        f"{'+data':>10}{'days':>6}{'lines/commit':>14}  period"
    )
    print(head)
    print("-" * len(head))
    order = sorted(roles.items(), key=lambda kv: (kv[0].startswith("("), -kv[1]["commits"]))
    for role, r in order:
        print(
            f"{role:<12}{r['commits']:>8}{r['added']:>10}{r['removed']:>9}"
            f"{r['data_added']:>10}{r['active_days']:>6}{r['lines_per_commit']:>14}"
            f"  {r['first']}..{r['last']}"
        )
    if not_authored:
        print()
        print("\"work\" = code/docs/journal entries; \"data\" = " + ", ".join(not_authored) + ":")
        print("bulk measurements, generated fit output, archived snapshots — added by a role, not written by one.")

    print()
    print("Commits by week (Monday = week start):")
    peak = max(weeks.values()) if weeks else 1
    for monday, n in weeks.items():
        print(f"  {monday}  {'#' * max(1, round(n * 40 / peak)):<40} {n}")

    print()
    print("Not here: cost and tokens — git doesn't have them. Use your provider's usage telemetry")
    print("(for Claude Code: /usage, /insights, or OTLP claude_code.cost.usage by agent.name).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", metavar="FILE", help="write machine-readable output")
    parser.add_argument(
        "--config", metavar="FILE", default="coordination/tools/kpi_config.json",
        help="JSON config with excluded_commits / not_authored_prefixes (default: %(default)s)",
    )
    args = parser.parse_args()

    excluded_commits, not_authored = load_config(args.config)

    commits = collect(excluded_commits, not_authored)
    if not commits:
        sys.exit("no commits counted — run this from the repo root")

    roles = aggregate(commits)
    weeks = by_week(commits)
    report(commits, roles, weeks, excluded_commits, not_authored)

    if args.json:
        payload = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "excluded_commits": excluded_commits,
            "not_authored_prefixes": list(not_authored),
            "commits_counted": len(commits),
            "roles": roles,
            "commits_by_week": weeks,
            "caveat": "git has no cost/token data; output and pace is all this contains",
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\nmachine-readable output: {args.json}")


if __name__ == "__main__":
    main()
