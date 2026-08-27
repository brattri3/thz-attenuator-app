#!/usr/bin/env bash
# SessionStart hook — warns when a role's cold-start file grows past budget.
#
# Why this exists: a written rule ("keep roles/<ID>.md under N tokens") rots silently —
# files grow, nobody notices, and every session ends up reading a bloated cold-start file
# without realizing the number in the docs stopped being true. A rule that's checked by a
# hook instead of remembered by a human stays true. This hook only warns (via
# systemMessage) — it never blocks the session — because the budget is a cost signal, not
# a correctness gate; blocking on it would make emergency work harder for no safety gain.
#
# Unit: UTF-8 bytes (`wc -c`), not Unicode codepoints and not tokens. Pick your own
# bytes-per-token calibration empirically for your content and language — it varies with
# script (Cyrillic/CJK/Latin) and formatting density, so don't trust a number you didn't
# measure against your own files. See budget.json's `_comment` for how to do that once.
#
# Fires on SessionStart, source=startup|clear only — resume/compact don't re-read the
# cold-start file, so warning there is pure noise.
set -uo pipefail
input=$(cat)

case "$input" in
  *'"source":"startup"'*|*'"source": "startup"'*) ;;
  *'"source":"clear"'*|*'"source": "clear"'*) ;;
  *) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-}"
[ -d "$root" ] || root=$(git rev-parse --show-toplevel 2>/dev/null)
[ -d "$root" ] || exit 0

budget="$root/.claude/hooks/budget.json"
[ -f "$budget" ] || exit 0

limit=$(grep -o '"limit_bytes"[[:space:]]*:[[:space:]]*[0-9]*' "$budget" | head -1 | grep -o '[0-9]*$')
[ -n "${limit:-}" ] || exit 0

over=""
for f in "$root"/coordination/roles/*.md; do
  [ -f "$f" ] || continue
  # Local patch 2026-08-27: strip CR before counting. On Windows git checks files
  # out with CRLF, adding one byte per line (~35 per role file). Without this, role
  # files trimmed to exactly the limit upstream are all reported as over budget, the
  # warning fires every session and stops being read -- the very failure the hook exists
  # to prevent. Upstream still has the unpatched form; worth sending back.
  size=$(tr -d '\r' < "$f" | wc -c | tr -d '[:space:]')
  [ "$size" -gt "$limit" ] || continue
  over="${over}${over:+, }$(basename "$f") ($size/$limit B)"
done
[ -n "$over" ] || exit 0

printf '{"systemMessage":"Cold-start budget exceeded: %s. Limit for coordination/roles/*.md is %s bytes (see .claude/hooks/budget.json)."}\n' "$over" "$limit"
exit 0
