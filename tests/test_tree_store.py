"""Release A production tree package tests (checklist A.1-A.3, A.5, A.13)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from docmancer.memory.tree.contracts import TREE_SCHEMA_VERSION
from docmancer.memory.tree.errors import (
    AddressNotFoundError,
    AlreadyExistsError,
    AmbiguousAddressError,
    ForbiddenPathError,
    InvalidFrontmatterFieldError,
    StaleWriteError,
)
from docmancer.memory.tree.parser import parse_tree_file, render_tree_file
from docmancer.memory.tree.store import TreeStore


def test_write_generates_stable_id_and_is_durable(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/release.md", text="# Release\n\nDeploy steps.\n", expect="absent")

    assert entry.memory_id
    assert entry.address.startswith("docmancer://memory/")
    assert entry.schema_version == TREE_SCHEMA_VERSION
    assert entry.path.is_file()
    assert "Deploy steps." in entry.path.read_text(encoding="utf-8")
    assert list(entry.path.parent.glob(".*.tmp-*")) == []


def test_atomic_write_fsyncs_file_and_parent_directory(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    with patch("docmancer.memory.tree.store.os.fsync") as fsync:
        store.write(relative_path="a.md", text="# A\n\nDurable.\n", expect="absent")

    assert fsync.call_count >= 2


def test_replace_failure_preserves_existing_file_and_cleans_temp(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    first = store.write(relative_path="a.md", text="# A\n\nOriginal.\n", expect="absent")

    with patch("docmancer.memory.tree.store.os.replace", side_effect=OSError("simulated crash")):
        with pytest.raises(OSError, match="simulated crash"):
            store.edit(first.address, text="# A\n\nReplacement.\n", expected_hash=first.content_hash)

    assert "Original." in first.path.read_text(encoding="utf-8")
    assert list(first.path.parent.glob(".*.tmp-*")) == []


def test_create_only_rejects_existing_target(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    with pytest.raises(AlreadyExistsError):
        store.write(relative_path="a.md", text="# A2\n\nOther.\n", expect="absent")


def test_update_requires_expected_hash(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    first = store.write(relative_path="a.md", text="# A\n\nOriginal.\n", expect="absent")

    with pytest.raises(StaleWriteError):
        store.write(relative_path="a.md", text="# A\n\nConflict.\n", expect="wrong-hash")
    assert "Original." in first.path.read_text(encoding="utf-8")

    second = store.write(relative_path="a.md", text="# A\n\nRevised.\n", expect=first.content_hash)
    assert second.memory_id == first.memory_id
    assert second.parent_revision_ids == [first.revision_id]
    assert "Revised." in second.path.read_text(encoding="utf-8")


def test_update_with_no_expect_on_existing_file_is_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="a.md", text="# A\n\nOriginal.\n", expect="absent")
    with pytest.raises(StaleWriteError):
        store.write(relative_path="a.md", text="# A\n\nNo hash supplied.\n")


def test_idempotent_resubmission_does_not_bump_revision(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    first = store.write(relative_path="a.md", text="# A\n\nSame.\n", expect="absent")
    again = store.write(
        relative_path="a.md",
        text="# A\n\nSame.\n",
        memory_type=first.type,
        scope=first.scope,
        authority=first.authority,
        sources=first.sources,
        status=first.status,
        tags=first.tags,
        curation_origin=first.curation_origin,
        expect=first.content_hash,
    )
    assert again.revision_id == first.revision_id
    assert again.memory_id == first.memory_id


def test_invalid_frontmatter_choice_is_rejected(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    with pytest.raises(InvalidFrontmatterFieldError):
        store.write(relative_path="a.md", text="# A\n\nBody.\n", authority="urgent", expect="absent")


def test_forbidden_path_traversal(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    with pytest.raises(ForbiddenPathError):
        store.write(relative_path="../../etc/passwd", text="nope", expect="absent")


def test_edit_preserves_frontmatter_and_updates_body_only(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(
        relative_path="a.md", text="# A\n\nOriginal.\n",
        authority="mandatory", tags=["ops"], sources=["s1"], expect="absent",
    )
    edited = store.edit(entry.address, text="# A\n\nEdited.\n", expected_hash=entry.content_hash)
    assert edited.authority == "mandatory"
    assert edited.tags == ["ops"]
    assert edited.sources == ["s1"]
    assert "Edited." in edited.body


def test_move_preserves_stable_address(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="deployment/a.md", text="# A\n\nBody.\n", expect="absent")
    moved = store.move(entry.address, "deployment/production.md", expected_hash=entry.content_hash)
    assert moved.memory_id == entry.memory_id
    assert not (tmp_path / "memory" / "deployment" / "a.md").exists()

    resolved = store.read(entry.address)
    assert resolved.memory_id == entry.memory_id
    assert resolved.path.name == "production.md"


def test_move_rejects_stale_hash(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    with pytest.raises(StaleWriteError):
        store.move(entry.address, "b.md", expected_hash="wrong")


def test_duplicate_creates_new_stable_id_with_same_content(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nBody.\n", sources=["s1"], expect="absent")
    dup = store.duplicate(entry.address, "b.md", expected_hash=entry.content_hash)
    assert dup.memory_id != entry.memory_id
    assert dup.body == entry.body
    assert dup.sources == entry.sources


def test_trash_and_restore_round_trip(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    token = store.trash(entry.address, expected_hash=entry.content_hash)
    manifest = json.loads((store.trash_root / f"{token}.manifest.json").read_text(encoding="utf-8"))
    assert manifest["actor_surface"] == "local"
    assert not entry.path.exists()
    with pytest.raises(AddressNotFoundError):
        store.read(entry.address)

    restored = store.restore(token)
    assert restored.memory_id == entry.memory_id
    assert restored.path == entry.path
    assert "Body." in restored.body


def test_restore_refuses_to_overwrite_a_newer_file(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    token = store.trash(entry.address, expected_hash=entry.content_hash)
    store.write(relative_path="a.md", text="# A\n\nNewer.\n", expect="absent")

    with pytest.raises(AlreadyExistsError):
        store.restore(token)


def test_ambiguous_title_returns_candidates(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    a = store.write(relative_path="x/a.md", text="# Same title\n\nA.\n", expect="absent")
    b = store.write(relative_path="y/b.md", text="# Same title\n\nB.\n", expect="absent")
    with pytest.raises(AmbiguousAddressError) as excinfo:
        store.read("Same title")
    assert set(excinfo.value.candidates) == {a.address, b.address}


def test_explicit_path_title_project_and_wildcard_addresses(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "tree")
    entry = store.write(
        relative_path="deployment/production-release.md",
        text="# Production release process\n\nDeploy on Railway.\n",
        scope="project",
        project_id="my-project",
        expect="absent",
    )

    assert store.read("docmancer://path/deployment/production-release").address == entry.address
    assert store.read("docmancer://title/Production%20release%20process").address == entry.address
    assert store.read("docmancer://project/my-project/deployment/production-release").address == entry.address
    assert store.read("docmancer://search/deployment/*").address == entry.address


def test_project_address_cannot_cross_project_scope(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "tree")
    store.write(
        relative_path="deployment/release.md",
        text="# Release\n\nProject A only.\n",
        scope="project",
        project_id="project-a",
        expect="absent",
    )

    with pytest.raises(AddressNotFoundError):
        store.read("docmancer://project/project-b/deployment/release")


def test_wildcard_address_is_bounded_and_never_guesses(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "tree")
    first = store.write(relative_path="deployment/a.md", text="# A\n\nOne.\n", expect="absent")
    second = store.write(relative_path="deployment/b.md", text="# B\n\nTwo.\n", expect="absent")

    with pytest.raises(AmbiguousAddressError) as excinfo:
        store.read("docmancer://search/deployment/*")
    assert excinfo.value.candidates == sorted([first.address, second.address])

    with pytest.raises(AddressNotFoundError):
        store.read("docmancer://search/**")


def test_index_deletion_and_rebuild_preserves_files(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    store.drop_index()
    assert entry.path.is_file()
    count = store.rebuild_index()
    assert count >= 1
    resolved = store.read(entry.address)
    assert resolved.memory_id == entry.memory_id


def test_unknown_frontmatter_and_body_round_trip(tmp_path: Path) -> None:
    raw = (
        "---\n"
        "schema_version: 1\n"
        "memory_id: fixed-id\n"
        "type: preference\n"
        "scope: project\n"
        "authority: advisory\n"
        "project_id: null\n"
        "created_at: '2026-07-01T00:00:00+00:00'\n"
        "updated_at: '2026-07-01T00:00:00+00:00'\n"
        "sources: []\n"
        "status: active\n"
        "revision_id: rev-1\n"
        "parent_revision_ids: []\n"
        "tags: [ops]\n"
        "curation_origin: deliberate_write\n"
        "owner: gaurang\n"
        "---\n\n"
        "# Deployment guide\n\n"
        "- [decision] Use blue/green deploys #ops\n"
        "- supersedes [[Old deployment guide]]\n\n"
        "See also [[Runbook]].\n"
    )
    path = tmp_path / "deployment-guide.md"
    path.write_text(raw, encoding="utf-8")
    entry = parse_tree_file(path)
    assert entry is not None
    assert entry.extra_frontmatter == {"owner": "gaurang"}
    assert entry.observations == [("decision", "Use blue/green deploys #ops")]
    assert ("supersedes", "Old deployment guide") in entry.relations
    assert ("links_to", "Runbook") in entry.relations

    rendered = render_tree_file(entry)
    reparsed_path = tmp_path / "roundtrip.md"
    reparsed_path.write_bytes(rendered)
    reparsed = parse_tree_file(reparsed_path)
    assert reparsed is not None
    assert reparsed.extra_frontmatter == {"owner": "gaurang"}
    assert reparsed.relations == entry.relations


def test_malformed_frontmatter_degrades_safely(tmp_path: Path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("---\n[this is not valid: yaml: at all\n---\n\nBody text.\n", encoding="utf-8")
    entry = parse_tree_file(path)
    assert entry is not None
    assert "Body text" in entry.body or "[this is not valid" in entry.body


def test_plain_markdown_with_no_frontmatter_parses(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# Plain note\n\nJust prose.\n", encoding="utf-8")
    entry = parse_tree_file(path)
    assert entry is not None
    assert entry.title == "Plain note"
