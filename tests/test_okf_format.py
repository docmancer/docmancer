"""Tests for the OKF (Open Knowledge Format) frontmatter primitives.

OKF v0.1: a directory of markdown files with YAML frontmatter. The only
required frontmatter field is ``type``; ``title``, ``description``,
``resource``, ``tags``, and ``timestamp`` are recommended.
Reserved filenames are ``index.md`` and ``log.md``.
"""

from docmancer.okf import (
    OKF_VERSION,
    RESERVED_FILENAMES,
    dump_frontmatter,
    parse_frontmatter,
)


def test_okf_version_is_0_1():
    assert OKF_VERSION == "0.1"


def test_reserved_filenames():
    assert "index.md" in RESERVED_FILENAMES
    assert "log.md" in RESERVED_FILENAMES


def test_dump_frontmatter_emits_yaml_block_then_body():
    out = dump_frontmatter({"type": "Decision"}, "The body text.")
    assert out.startswith("---\n")
    head, _, body = out.partition("\n---\n")
    assert "type: Decision" in head
    assert body.strip() == "The body text."


def test_roundtrip_preserves_fields_and_body():
    fields = {
        "type": "Decision",
        "title": "Pick Railway",
        "tags": ["infra", "deploy"],
    }
    body = "We chose Railway for production.\n\nIt was cheaper."
    parsed_fields, parsed_body = parse_frontmatter(dump_frontmatter(fields, body))
    assert parsed_fields["type"] == "Decision"
    assert parsed_fields["title"] == "Pick Railway"
    assert parsed_fields["tags"] == ["infra", "deploy"]
    assert parsed_body.strip() == body.strip()


def test_parse_document_without_frontmatter_returns_empty_dict():
    fields, body = parse_frontmatter("# Just a heading\n\nNo frontmatter here.")
    assert fields == {}
    assert "Just a heading" in body


def test_dump_omits_none_and_empty_values():
    out = dump_frontmatter(
        {
            "type": "Reference",
            "title": None,
            "description": "",
            "tags": [],
            "resource": "https://example.com",
        },
        "body",
    )
    fields, _ = parse_frontmatter(out)
    assert fields == {"type": "Reference", "resource": "https://example.com"}


def test_dump_orders_reserved_fields_first():
    out = dump_frontmatter(
        {
            "custom_extra": "x",
            "timestamp": "2026-06-19T00:00:00Z",
            "type": "Convention",
            "title": "T",
        },
        "body",
    )
    head = out.split("\n---\n", 1)[0]
    # type must appear before title, which appears before timestamp,
    # which appears before any non-reserved extension key.
    assert head.index("type:") < head.index("title:")
    assert head.index("title:") < head.index("timestamp:")
    assert head.index("timestamp:") < head.index("custom_extra:")
