"""
test_badges.py - the badge vocabulary.

The module is stdlib-only by design, so this file runs without streamlit. That is
deliberate: a badge that disagrees with the parser is how an unrecognised status ends up
rendered as a documented one, and a property that can only be tested with an optional
heavyweight dependency installed will not be tested.
"""

import badges

# ======================================================================================
# Badges agree with the parser
# ======================================================================================


def test_badges_carry_a_text_label_not_only_an_emoji():
    """Colour and emoji alone are not a usable encoding.

    The same glyph also meant different things across the two badge sets: ⚪ was CLOSED in
    one and Idle in the other, 🟢 was DONE in one and Active in the other.
    """
    for rendered in (
        badges.render_status_badge("open"),
        badges.render_status_badge("done"),
        badges.render_role_badge("active"),
        badges.render_type_badge("blocking"),
    ):
        assert any(char.isalpha() for char in rendered), rendered


def test_unrecognised_status_renders_as_unclassified_not_as_a_real_state():
    """components.py used to render `открыт` as a red OPEN badge beside a row that
    parser.py had already classified as closed."""
    rendered = badges.render_status_badge("открыт")
    assert "UNCLASSIFIED" in rendered
    assert "открыт" in rendered


def test_unrecognised_type_is_not_silently_non_blocking():
    rendered = badges.render_type_badge("блокирующий")
    assert "UNCLASSIFIED" in rendered
    assert "Non-blocking" not in rendered


def test_unrecognised_role_status_is_not_rendered_as_a_documented_one():
    assert "UNCLASSIFIED" in badges.render_role_badge("активен (2026-08-27)")


def test_question_partition_has_three_buckets():
    questions = [
        {"is_open": True}, {"is_open": True},
        {"is_open": False},
        {"is_open": None},
    ]
    opened, closed, unclassified = badges.partition_questions(questions)
    assert (len(opened), len(closed), len(unclassified)) == (2, 1, 1)


def test_role_partition_keeps_unclassified_separate_from_inactive():
    roles = [
        {"status_known": "active"},
        {"status_known": "idle"},
        {"status_known": None},
    ]
    active, other, unclassified = badges.partition_roles(roles)
    assert (len(active), len(other), len(unclassified)) == (1, 1, 1)
