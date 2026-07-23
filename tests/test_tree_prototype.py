"""Release 0 prototype tests (checklist 0.3 and 0.4).

Every fixture here is temporary (``tmp_path``), matching the checklist's
"temporary global and project tree fixtures" framing. Nothing in this file
exercises the production record store or write path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.memory.tree_prototype import (
    AddressNotFoundError,
    AmbiguousAddressError,
    ForbiddenPathError,
    MemoryTreeStore,
    StaleWriteError,
    parse_tree_file,
    render_tree_file,
)


RAW_FIXTURE = """---
memory_id: fixed-id-123
type: preference
scope: project
authority: advisory
project_id: null
created_at: '2026-07-01T00:00:00+00:00'
updated_at: '2026-07-01T00:00:00+00:00'
sources: []
status: active
revision_id: rev-1
parent_revision_ids: []
tags: [ops]
curation_origin: deliberate_write
owner: gaurang
---

# Deployment guide

- [decision] Use blue/green deploys #ops
- supersedes [[Old deployment guide]]

See also [[Runbook]] for the rollback steps.
"""


def test_tolerant_parser_preserves_unknown_frontmatter_and_body(tmp_path: Path) -> None:
    path = tmp_path / "deployment-guide.md"
    path.write_text(RAW_FIXTURE, encoding="utf-8")

    entry = parse_tree_file(path)
    assert entry is not None
    assert entry.memory_id == "fixed-id-123"
    assert entry.type == "preference"
    assert entry.extra_frontmatter == {"owner": "gaurang"}
    assert entry.title == "Deployment guide"
    assert entry.observations == [("decision", "Use blue/green deploys #ops")]
    assert ("supersedes", "Old deployment guide") in entry.relations
    assert ("links_to", "Runbook") in entry.relations
    # "Old deployment guide" is a typed relation target, not a duplicate bare link.
    assert entry.relations.count(("links_to", "Old deployment guide")) == 0

    # Round-trip: rendering and re-parsing must not lose the unknown key or body.
    rendered = render_tree_file(entry)
    reparsed_path = tmp_path / "roundtrip.md"
    reparsed_path.write_text(rendered, encoding="utf-8")
    reparsed = parse_tree_file(reparsed_path)
    assert reparsed is not None
    assert reparsed.extra_frontmatter == {"owner": "gaurang"}
    assert reparsed.observations == entry.observations
    assert reparsed.relations == entry.relations


def test_parser_degrades_safely_for_plain_markdown_with_no_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "plain-note.md"
    path.write_text("# Plain note\n\nJust ordinary prose, no frontmatter at all.\n", encoding="utf-8")

    entry = parse_tree_file(path)
    assert entry is not None
    assert entry.title == "Plain note"
    assert "ordinary prose" in entry.body


def test_write_context_md_produces_human_readable_directory_description(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    store.write_context_md(
        "architecture",
        "# architecture\n\nCovers system design decisions. Excludes deployment runbooks.\n",
    )

    raw = (tmp_path / "memory" / "architecture" / "context.md").read_text(encoding="utf-8")
    assert "Covers system design decisions" in raw
    assert "Excludes deployment runbooks" in raw


def test_curate_real_corpus_fact_with_source_citation_without_touching_the_source(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    plan_doc = repo_root.parent / "docs" / "memory-harness" / (
        "2026-07-22-actionable-context-workbench-and-memory-intelligence-plan.md"
    )
    assert plan_doc.is_file(), "expected the real plan doc to exist for this curation fixture"
    before_bytes = plan_doc.read_bytes()

    store = MemoryTreeStore(tmp_path / "memory")
    curated = store.write(
        relative_path="workflow/curated-tree-decision.md",
        text=(
            "# Curated Markdown memory tree is the canonical memory\n\n"
            "- [decision] Docmancer replaced the claims-projection architecture with a "
            "curated, source-attributed Markdown tree as canonical memory. #architecture\n"
        ),
        memory_type="decision",
        sources=[str(plan_doc)],
        curation_origin="deterministic",
    )

    assert curated.sources == [str(plan_doc)]
    assert plan_doc.read_bytes() == before_bytes, "curation must never rewrite the harvested source file"


def test_inbox_stays_physically_separate_from_curated_tree(tmp_path: Path) -> None:
    curated_root = tmp_path / "memory"
    inbox_root = tmp_path / "inbox"
    inbox_root.mkdir(parents=True)
    (inbox_root / "raw-capture.md").write_text("Uncurated session note.\n", encoding="utf-8")

    store = MemoryTreeStore(curated_root)
    store.write(relative_path="workflow/note.md", text="# Note\n\nCurated content.\n")

    assert inbox_root not in curated_root.parents
    assert curated_root not in inbox_root.parents
    curated_texts = [entry.body for entry in store._entries()]
    assert not any("Uncurated session note" in text for text in curated_texts)


def test_file_first_write_is_durable_and_leaves_no_temp_file(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/release.md", text="# Release\n\nDeploy steps.\n")

    assert entry.path.is_file()
    assert entry.path.read_text(encoding="utf-8").endswith("Deploy steps.\n")
    leftover_temp_files = list(entry.path.parent.glob(".*.tmp-*"))
    assert leftover_temp_files == []


def test_stale_hash_guard_blocks_update_and_correct_hash_succeeds(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    first = store.write(relative_path="deployment/release.md", text="# Release\n\nOriginal steps.\n")

    with pytest.raises(StaleWriteError):
        store.write(
            relative_path="deployment/release.md",
            text="# Release\n\nConflicting steps.\n",
            expected_hash="not-the-real-hash",
        )
    # A stale write must never have been applied.
    assert "Original steps." in first.path.read_text(encoding="utf-8")

    second = store.write(
        relative_path="deployment/release.md",
        text="# Release\n\nRevised steps.\n",
        expected_hash=first.content_hash,
    )
    assert second.memory_id == first.memory_id
    assert second.parent_revision_ids == [first.revision_id]
    assert "Revised steps." in second.path.read_text(encoding="utf-8")


def test_forbidden_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    with pytest.raises(ForbiddenPathError):
        store.write(relative_path="../../etc/passwd", text="nope")


def test_stable_address_resolves_after_rename_and_move(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/release.md", text="# Release\n\nDeploy steps.\n")
    address = entry.address

    moved = store.move(address, "deployment/production-release.md")
    assert moved.memory_id == entry.memory_id
    assert not (tmp_path / "memory" / "deployment" / "release.md").exists()

    resolved = store.read(address)
    assert resolved.memory_id == entry.memory_id
    assert resolved.path.name == "production-release.md"
    assert "Deploy steps." in resolved.body


def test_ambiguous_title_returns_candidates_instead_of_guessing(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    first = store.write(relative_path="deployment/a.md", text="# Release process\n\nFrom team A.\n")
    second = store.write(relative_path="architecture/b.md", text="# Release process\n\nFrom team B.\n")

    with pytest.raises(AmbiguousAddressError) as excinfo:
        store.read("Release process")
    assert set(excinfo.value.candidates) == {first.address, second.address}


def test_path_address_resolves_the_same_file_as_the_stable_id(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/release.md", text="# Release\n\nDeploy steps.\n")

    by_path = store.read("deployment/release.md")
    assert by_path.memory_id == entry.memory_id


def test_not_found_address_raises_typed_error(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    store.write(relative_path="deployment/a.md", text="# Something else\n\nBody.\n")
    with pytest.raises(AddressNotFoundError):
        store.read("docmancer://memory/does-not-exist")


def test_deleting_the_prototype_index_does_not_lose_the_file_or_stable_id(tmp_path: Path) -> None:
    store = MemoryTreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/release.md", text="# Release\n\nDeploy steps.\n")
    address = entry.address

    store.drop_index()
    assert store._index == {}
    # The file on disk is untouched by dropping the disposable index.
    assert entry.path.is_file()

    rebuilt_count = store.rebuild_index()
    assert rebuilt_count >= 1
    resolved = store.read(address)
    assert resolved.memory_id == entry.memory_id
    assert "Deploy steps." in resolved.body
