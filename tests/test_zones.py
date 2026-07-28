import pytest

from docmancer.memory.tree.zones import (
    BANNER_TEMPLATE,
    ZoneViolation,
    generated_zone_changed,
    render_zones,
    replace_pinned,
    split_zones,
)


def _rendered(pinned="- keep me", generated="## Constraint\n- generated line"):
    return render_zones(
        pinned=pinned,
        generated=generated,
        revision="abc123",
        section="preferences",
    )


def test_round_trips_both_zones():
    zones = split_zones(_rendered())
    assert zones.pinned == "- keep me"
    assert zones.generated == "## Constraint\n- generated line"
    assert zones.generated_revision == "abc123"
    assert zones.has_markers is True


def test_legacy_body_without_markers_is_all_generated():
    """Every existing machine has unmarked section files. They must migrate as a
    no-op, not as a file with its whole body silently promoted to pinned."""
    zones = split_zones("# Preferences\n\n## Constraint\n- old line\n")
    assert zones.pinned == ""
    assert zones.generated == "# Preferences\n\n## Constraint\n- old line"
    assert zones.has_markers is False


def test_empty_and_none_bodies_are_safe():
    for value in ("", None):
        zones = split_zones(value)
        assert zones.pinned == ""
        assert zones.generated == ""


def test_unterminated_generated_marker_is_treated_as_generated():
    """Ambiguous content must fall to the generated side. Treating it as pinned
    would freeze the section permanently with no visible cause."""
    body = "<!-- docmancer:generated revision=x -->\n## Truncated\n- line"
    zones = split_zones(body)
    assert zones.pinned == ""
    assert "- line" in zones.generated


def test_multiple_pinned_blocks_are_merged():
    body = (
        "<!-- docmancer:pinned -->\n- one\n<!-- /docmancer:pinned -->\n"
        "middle\n"
        "<!-- docmancer:pinned -->\n- two\n<!-- /docmancer:pinned -->\n"
    )
    assert split_zones(body).pinned == "- one\n- two"


def test_replace_pinned_leaves_generated_byte_identical():
    body = _rendered()
    updated = replace_pinned(body, "- a new note", section="preferences")
    assert split_zones(updated).generated == split_zones(body).generated
    assert split_zones(updated).pinned == "- a new note"


def test_pinned_zone_precedes_generated_zone():
    """The context compiler truncates from the end of a body, so the user's own
    words have to come first to survive a tight token budget."""
    body = _rendered()
    assert body.index("- keep me") < body.index("generated line")


def test_generated_zone_changed_ignores_whitespace_but_catches_edits():
    body = _rendered()
    assert generated_zone_changed(body, replace_pinned(body, "- changed", section="preferences")) is False
    assert generated_zone_changed(body, body.replace("generated line", "tampered")) is True
    assert generated_zone_changed(body, body.replace("- generated line", "-  generated   line")) is False


def test_pinned_lines_ignores_blank_lines():
    zones = split_zones(_rendered(pinned="- one\n\n\n- two\n"))
    assert zones.pinned_lines == ["- one", "- two"]


def test_banner_avoids_retrieval_vocabulary():
    """Regression guard for the Release 0 finding.

    The banner is repeated in every section file. Any token it shares with the
    self-description's alias vocabulary becomes corpus-ubiquitous, drops to zero
    IDF, and stops distinguishing that document. An earlier draft named the
    `docmancer memory canonical pin` command here and knocked the
    self-description off the top of every terminology query.
    """
    from docmancer.memory.laptop import _SELF_DESCRIPTION_ALIASES
    from docmancer.memory.tree.compiler import _tokens

    # Score the banner with the compiler's own tokenizer so this guard tracks
    # the real scoring rules: words the compiler already discards as stopwords
    # carry no IDF weight and are not worth banning from ordinary prose.
    banner_tokens = _tokens(BANNER_TEMPLATE)
    reserved = {
        token
        for alias in (*_SELF_DESCRIPTION_ALIASES, "docmancer")
        for token in _tokens(alias)
    }
    assert not (banner_tokens & reserved)


def test_zone_violation_payload_is_structured_and_recoverable():
    violation = ZoneViolation("preferences.md", pin_hint='docmancer memory canonical pin preferences "x"')
    payload = violation.payload()
    assert payload["ok"] is False
    assert payload["error"] == "generated_zone_readonly"
    assert payload["address"] == "preferences.md"
    assert "pin" in payload["recovery"]
    with pytest.raises(ValueError):
        raise violation
