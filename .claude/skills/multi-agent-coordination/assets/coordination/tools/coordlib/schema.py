"""
schema.py - the one place that decides what a status word means.

Before this module the same decision was made in five places, by three different rules:

  parser.py:150        "open" in status or "taken" in status      (substring)
  parser.py:226        status in ("open","taken","missing",...)   (exact tuple)
  build_index.py:37    "open" in s or "taken" in s                (substring, its own copy)
  components.py:69     s in ("open","открыт")                     (exact, plus Cyrillic)
  components.py:24     r.get("status") == "active"                (exact equality)

They disagreed. `открыт` rendered a red OPEN badge via components.py and was simultaneously
filed as closed by parser.py. `in progress` was TAKEN in one and closed in the other.

THE CONVENTION THAT MAKES THIS WORK: every classifier returns None for "not recognised",
never False. `False` says "I understood this and it is closed"; `None` says "I did not
understand this, ask a human". Callers must not collapse the two -- see UNKNOWN_* handling
in the parsers and the third KPI partition in the dashboard.

ON LANGUAGE: the status and type keywords are protocol tokens, not prose. Write questions,
answers, summaries and handoff bodies in whatever language the project uses; these keywords
and the table headers stay English, because tooling parses them. The skill's references/rationale.md
records what happened to the source project when that was left implicit. The tools do not
guess at a translation -- they report `unknown-status` and let a human fix the file.

STABILITY: PROMISED. An external extension may depend on the names and behaviour in this
module -- breaking them is a breaking change. The vocabularies, the classifiers and the
header/signature resolution are the normative definition an outside reader must agree with;
the skill's references/extension-contract.md points here rather than restating them.
"""

import re
from typing import Optional, Sequence

# --------------------------------------------------------------------------------------
# Vocabularies, exactly as the templates document them.
# --------------------------------------------------------------------------------------

#: coordination/HANDOFFS.md -- the mandated line is `- **Status:** open|taken|done`.
HANDOFF_STATUSES = ("open", "taken", "done")

#: coordination/QUESTIONS.md `Status` column.
QUESTION_STATUSES = ("open", "resolved", "closed")

#: coordination/QUESTIONS.md `Type` column.
QUESTION_TYPES = ("blocking", "non-blocking")

#: coordination/BOARD.md `Status (date)` column.
BOARD_STATUSES = ("active", "idle", "stale", "blocked")

#: Synthetic sentinel: a handoff entry with no status line at all. The parsers set it
#: themselves and it counts as open, so a request nobody has answered stays visible instead of
#: disappearing into the closed pile.
#:
#: It used to be described here as "not a documented value", which was true and was the
#: problem: consumers see it in the `status` field alongside the three real words, so it was a
#: fourth token nothing declared. HANDOFFS.md now names it -- as a word the tools produce and a
#: person must never write.
MISSING = "missing"

_OPEN_STATUSES = frozenset({"open", "taken"})
_CLOSED_STATUSES = frozenset({"done", "resolved", "closed"})


# --------------------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------------------

#: Markdown decoration that can wrap a cell value without changing it: bold/italic markers,
#: code spans, and the backslashes markdown uses to escape literal `<`/`>`.
_DECORATION = "`* \\"

_PLACEHOLDER_RE = re.compile(r"^<[^>]*>$")


def strip_decoration(raw: Optional[str]) -> str:
    """Strip markdown decoration from a cell value, preserving case.

    For identifiers such as role names and question IDs, where `**ORCH**` and `ORCH` are the
    same role but the displayed casing matters. Use normalise() when comparing vocabulary.
    """
    return (raw or "").strip().strip(_DECORATION).strip()


def normalise(raw: Optional[str]) -> str:
    """Strip markdown decoration and case from a cell value.

    `**active**`, `` `active` `` and `active` must all classify identically -- issue #6
    reported role names keeping their `**` markers precisely because this was applied
    inconsistently (parser.py:84 stripped them, parser.py:101 did not).
    """
    return (raw or "").strip().strip(_DECORATION).strip().lower()


def is_placeholder_text(raw: Optional[str]) -> bool:
    """True for a template placeholder such as `<ID>` -- including the escaped `\\<ID\\>`.

    BOARD.md ships `| \\<ID\\> | active (YYYY-MM-DD) | ... |` as its example row. The old
    guard was `clean_role.startswith("<")`, which the leading backslash defeats, so the
    placeholder was rendered as a live role and counted as active in the KPI bar. Stripping
    the escape before the test is the fix, and it gives build_index.py a notion of
    placeholders it previously lacked entirely.
    """
    text = (raw or "").strip().strip(_DECORATION).strip()
    if not text:
        return True
    if _PLACEHOLDER_RE.match(text):
        return True
    # Date placeholders used by the handoff template.
    return text.upper() in {"YYYY-MM-DD", "ISO-DATE"}


# --------------------------------------------------------------------------------------
# Classifiers. None means "not recognised" -- never "no".
# --------------------------------------------------------------------------------------


def classify_item_status(raw: Optional[str]) -> Optional[str]:
    """Map a question or handoff status onto 'open' / 'closed', or None if unrecognised.

    Exact match against the documented vocabulary. The old substring test also matched
    `reopened` as open and `not open` as open, which is the other half of the same bug.
    """
    value = normalise(raw)
    if not value:
        return None
    if value == MISSING or value in _OPEN_STATUSES:
        return "open"
    if value in _CLOSED_STATUSES:
        return "closed"
    return None


def classify_role_status(raw: Optional[str]) -> Optional[str]:
    """Map a BOARD.md status onto its canonical form, or None if unrecognised.

    Accepts the `status (YYYY-MM-DD)` shape the template documents and ignores the date.
    """
    # Split the date off FIRST: `**active** (2026-08-27)` ends with `)`, so stripping
    # decoration from the ends of the whole string leaves the `**` around the keyword.
    keyword, _date = split_role_status_date(raw)
    keyword = normalise(keyword)
    return keyword if keyword in BOARD_STATUSES else None


def classify_question_type(raw: Optional[str]) -> Optional[str]:
    """Map a QUESTIONS.md Type onto 'blocking' / 'non-blocking', or None if unrecognised.

    Note the old rule (`"blocking" in t and "non" not in t`) silently labelled *everything*
    unrecognised as non-blocking -- so an urgent question in any other wording lost its
    urgency, and the red "N blocking" highlight never fired.
    """
    value = normalise(raw)
    if not value:
        return None
    if value in QUESTION_TYPES:
        return value
    return None


def split_role_status_date(raw: Optional[str]):
    """Split `active (2026-08-27)` into ('active', '2026-08-27').

    Returns the raw keyword unvalidated -- callers classify it separately, so an
    unrecognised word can still be reported verbatim in a diagnostic.
    """
    text = (raw or "").strip()
    match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", text)
    if match:
        return match.group(1).strip().strip(_DECORATION).strip(), match.group(2).strip()
    return text.strip(_DECORATION).strip(), ""


# --------------------------------------------------------------------------------------
# Column resolution
# --------------------------------------------------------------------------------------

#: Canonical column key -> the header spellings the templates actually use.
#: Matching is EXACT against this table after normalisation. The previous implementation
#: (mutator.py:71-93) used a bidirectional substring test, which meant an empty header cell
#: matched every column (`"" in anything` is True) and silently rewrote the wrong one.
_COLUMN_ALIASES = {
    "id": ("#", "id", "№"),
    "role": ("role", "to"),
    "status": ("status", "status (date)"),
    "summary": ("one-line summary", "summary"),
    "question": ("question",),
    "answer": ("owner's answer", "answer"),
    "type": ("type",),
    "line": ("line",),
    "path": ("path",),
    "owner": ("owner",),
    "others": ("others",),
}

_ALIAS_TO_KEY = {alias: key for key, aliases in _COLUMN_ALIASES.items() for alias in aliases}


def resolve_column(header_cell: Optional[str]) -> Optional[str]:
    """Map one header cell onto a canonical column key, or None if unrecognised.

    An empty header cell resolves to None, never to a wildcard.
    """
    value = normalise(header_cell)
    if not value:
        return None
    return _ALIAS_TO_KEY.get(value)


def resolve_headers(cells: Sequence[str]):
    """Resolve a whole header row: returns {canonical_key: column_index}.

    First occurrence wins, so a duplicated header cannot silently shift the index of the
    column that was already found.
    """
    resolved = {}
    for index, cell in enumerate(cells):
        key = resolve_column(cell)
        if key is not None and key not in resolved:
            resolved[key] = index
    return resolved


#: Minimum canonical columns a table must expose to be treated as that kind of table.
#: A table qualifies by header signature, not by position, so a measurements table sitting
#: in QUESTIONS.md is reported rather than read as questions.
QUESTIONS_TABLE_SIGNATURE = frozenset({"id", "question", "status"})
BOARD_TABLE_SIGNATURE = frozenset({"role", "status"})
OWNERSHIP_TABLE_SIGNATURE = frozenset({"path", "owner"})


def matches_signature(resolved_headers, signature) -> bool:
    """True when a resolved header map covers every column in `signature`."""
    return signature.issubset(set(resolved_headers))
