"""Tests for mapping harvested memory entries into OKF concepts."""

from dataclasses import dataclass, field

from docmancer.okf.adapters import (
    concepts_from_documents,
    concepts_from_draft,
    concepts_from_memory_entries,
)


@dataclass
class FakeEntry:
    harness: str
    scope: str
    title: str
    content: str
    path: str
    extra: dict = field(default_factory=dict)


def test_kind_maps_to_okf_type():
    entries = [
        FakeEntry("claude-code", "project:/p", "Note", "body", "/p/n.md", {"kind": "agent-memory"}),
        FakeEntry("codex", "global:codex", "AGENTS", "body", "/g/AGENTS.md", {"kind": "instructions"}),
        FakeEntry("cursor", "project:/p", "rule", "body", "/p/.cursor/r.md", {"kind": "rules"}),
    ]
    concepts = concepts_from_memory_entries(entries)
    types = {c.title: c.type for c in concepts}
    assert types["Note"] == "Agent Memory"
    assert types["AGENTS"] == "Instructions"
    assert types["rule"] == "Rule"


def test_concept_carries_resource_body_and_tags():
    e = FakeEntry("claude-code", "project:/myapp", "Deploy", "We use Railway.", "/myapp/CLAUDE.md", {"kind": "instructions"})
    [concept] = concepts_from_memory_entries([e])
    assert concept.body == "We use Railway."
    assert concept.resource == "/myapp/CLAUDE.md"
    assert "claude-code" in concept.tags
    # scope prefix (global/project) is captured as a tag too
    assert "project" in concept.tags


def test_filename_is_grouped_by_harness_subdirectory():
    e = FakeEntry("claude-code", "project:/p", "Pick Railway", "b", "/p/n.md", {"kind": "agent-memory"})
    [concept] = concepts_from_memory_entries([e])
    assert concept.filename == "claude-code/pick-railway.md"


def test_timestamp_from_file_mtime_when_present(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("hello")
    e = FakeEntry("claude-code", "project:/p", "Note", "hello", str(f), {"kind": "agent-memory"})
    [concept] = concepts_from_memory_entries([e])
    # ISO 8601-ish timestamp string
    assert concept.timestamp and "T" in concept.timestamp


def test_missing_file_yields_no_timestamp():
    e = FakeEntry("claude-code", "project:/p", "Note", "hello", "/does/not/exist.md", {"kind": "agent-memory"})
    [concept] = concepts_from_memory_entries([e])
    assert concept.timestamp is None


@dataclass
class FakeDoc:
    source: str
    content: str
    metadata: dict = field(default_factory=dict)


def test_documents_become_documentation_page_concepts():
    docs = [
        FakeDoc("https://docs.example.com/api/auth", "# Auth\n\nDetails.", {"title": "Auth"}),
        FakeDoc("https://docs.example.com/guide", "# Guide", {}),
    ]
    concepts = concepts_from_documents(docs)
    assert all(c.type == "Documentation Page" for c in concepts)
    # resource is the canonical source URL
    assert concepts[0].resource == "https://docs.example.com/api/auth"
    assert concepts[0].title == "Auth"
    assert concepts[0].body.startswith("# Auth")


def test_draft_becomes_summary_plus_section_concepts():
    from docmancer.ai.memory_schemas import (
        ConsolidatedMemoryDraft,
        ConsolidatedMemorySection,
    )

    draft = ConsolidatedMemoryDraft(
        title="Master Memory",
        summary="Everything we know.",
        sections=[
            ConsolidatedMemorySection(heading="Deploy", body="Railway, pnpm."),
            ConsolidatedMemorySection(heading="Style", body="No em dashes."),
        ],
        source_paths=["/p/CLAUDE.md"],
        warnings=["one note"],
    )
    concepts = concepts_from_draft(draft)
    types = [c.type for c in concepts]
    titles = [c.title for c in concepts]
    # A summary concept plus one concept per section.
    assert "Summary" in types
    assert "Deploy" in titles and "Style" in titles
    # Every concept has a non-empty type (OKF requirement).
    assert all(c.type for c in concepts)
    # The summary concept carries the overall draft title and source paths.
    summary = next(c for c in concepts if c.type == "Summary")
    assert "Everything we know" in summary.body


def test_document_filenames_are_unique_slugs_from_url_path():
    docs = [
        FakeDoc("https://docs.example.com/api/auth", "a"),
        FakeDoc("https://docs.example.com/", "root"),
    ]
    concepts = concepts_from_documents(docs)
    names = [c.filename for c in concepts]
    # Root path collapses to a non-reserved name (not index.md).
    assert "index.md" not in names
    assert len(set(names)) == len(names)
