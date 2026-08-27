---
paths:
  - "src/pipeline/**"
---
# Example path-scoped rule — delete or replace this file

This is a demonstration of `.claude/rules/*.md` with a `paths:` frontmatter glob: this file's
body is only loaded into context when a session actually reads or edits a file matching one of
the globs above — not at every cold start. That makes it the right place for domain knowledge
that's real and useful, but only to the roles whose work actually touches these paths (run
commands, a data format spec, a "here's what's already established, don't re-derive it" summary
for a specific subsystem).

Contrast with:
- **`CLAUDE.md`** — loads unconditionally, every session, every cold start. Reserve it for
  things every role needs regardless of what they're about to touch.
- **A Skill** (this mechanism you're reading right now, at the meta level) — never loads by path;
  triggers only by matching a task description or being invoked explicitly by name. Wrong tool
  for "always show this when someone touches this directory."
- **A `.claude/rules/*.md` file with no `paths:` key at all** — loads unconditionally like
  `CLAUDE.md`, just as a separate file. Useful for splitting a large always-loaded doc into
  named pieces, not for making something conditional.

Delete this file once you've written your project's real path-scoped rules, or keep it as a
worked example alongside them — either is fine, it's inert either way.
