"""
badges.py - status rendering. Stdlib only; deliberately no streamlit import.

Extracted from components.py, which kept its own status vocabulary:

    components.py:72  s in ("open", "открыт")            -> red OPEN
    parser.py:150     "open" in status                   -> classified closed

so a Russian `открыт` rendered a red OPEN badge beside a row the parser had already
filed as closed. Everything here now keys off coordlib.schema, so the badge and the
count cannot disagree.

Each badge carries a text label as well as an emoji. Colour and emoji alone are not a
usable encoding: they vanish in monochrome and are ambiguous to colour-blind readers, and
the same glyph meant different things in the two badge sets (⚪ was CLOSED in one and Idle
in the other; 🟢 was DONE in one and Active in the other).
"""

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from coordlib import schema  # noqa: E402

#: Canonical status -> (emoji, label). The label is what makes the badge readable without
#: colour; the emoji is decoration on top of it.
_ITEM_BADGES = {
    "open": ("🔴", "OPEN"),
    "taken": ("🟡", "TAKEN"),
    "done": ("🟢", "DONE"),
    "resolved": ("🟢", "RESOLVED"),
    "closed": ("⚪", "CLOSED"),
    schema.MISSING: ("⚠️", "MISSING"),
}

_ROLE_BADGES = {
    "active": ("🟢", "Active"),
    "idle": ("⚪", "Idle"),
    "stale": ("🟠", "Stale"),
    "blocked": ("🟣", "Blocked"),
}

#: Shown when a value is outside the documented vocabulary. Never silently mapped onto a
#: real state -- that is the whole point of the None convention in coordlib.schema.
UNCLASSIFIED = ("❓", "UNCLASSIFIED")


def render_status_badge(status: str) -> str:
    """Badge for a question or handoff status."""
    value = schema.normalise(status)
    if value in _ITEM_BADGES:
        emoji, label = _ITEM_BADGES[value]
        return f"{emoji} **{label}**"
    if schema.classify_item_status(status) is None:
        emoji, label = UNCLASSIFIED
        return f"{emoji} **{label}** (`{status}`)"
    return f"🔹 **{(status or '').upper()}**"


def render_type_badge(q_type: str) -> str:
    """Badge for a question type.

    Unrecognised is reported, not silently rendered as non-blocking. The old rule
    (`"blocking" in t and "non" not in t`) labelled everything it did not understand
    non-blocking, so an urgent question in any other wording lost its urgency and the red
    "N blocking" highlight never fired.
    """
    resolved = schema.classify_question_type(q_type)
    if resolved == "blocking":
        return "🚨 **Blocking**"
    if resolved == "non-blocking":
        return "ℹ️ **Non-blocking**"
    emoji, label = UNCLASSIFIED
    return f"{emoji} **{label}** (`{q_type}`)"


def render_role_badge(status: str) -> str:
    """Badge for a BOARD.md role status."""
    resolved = schema.classify_role_status(status)
    if resolved in _ROLE_BADGES:
        emoji, label = _ROLE_BADGES[resolved]
        return f"{emoji} {label}"
    emoji, label = UNCLASSIFIED
    return f"{emoji} {label} (`{status}`)"


def partition_questions(questions):
    """Split questions into (open, closed, unclassified).

    Three buckets, not two. Folding unclassified rows into either side is exactly how a
    Russian journal reported "Open Questions: 0" and was believed.
    """
    opened = [q for q in questions if q.get("is_open") is True]
    closed = [q for q in questions if q.get("is_open") is False]
    unclassified = [q for q in questions if q.get("is_open") is None]
    return opened, closed, unclassified


def partition_roles(roles):
    """Split board roles into (active, other_known, unclassified)."""
    active = [r for r in roles if r.get("status_known") == "active"]
    other = [r for r in roles if r.get("status_known") not in (None, "active")]
    unclassified = [r for r in roles if r.get("status_known") is None]
    return active, other, unclassified
