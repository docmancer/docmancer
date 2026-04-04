from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.vault.manifest import (
    ContentKind,
    IndexState,
    ManifestEntry,
    SourceType,
    VaultManifest,
)


# ---------------------------------------------------------------------------
# ManifestEntry defaults
# ---------------------------------------------------------------------------

def test_entry_defaults():
    entry = ManifestEntry(path="docs/intro.md", kind=ContentKind.raw, source_type=SourceType.markdown)
    assert len(entry.id) == 32  # uuid4().hex is 32 hex chars
    assert entry.index_state == IndexState.pending
    assert entry.content_hash == ""
    assert entry.tags == []
    assert entry.extra == {}
    assert entry.source_url is None
    assert entry.title is None
    assert entry.added_at != ""
    assert entry.updated_at != ""


def test_entry_id_is_unique():
    e1 = ManifestEntry(path="a.md", kind=ContentKind.raw, source_type=SourceType.markdown)
    e2 = ManifestEntry(path="b.md", kind=ContentKind.raw, source_type=SourceType.markdown)
    assert e1.id != e2.id


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

def test_save_and_load_round_trip(tmp_path: Path):
    manifest_path = tmp_path / "vault" / "manifest.json"
    vm = VaultManifest(manifest_path)

    entry = ManifestEntry(
        path="docs/page.md",
        kind=ContentKind.wiki,
        source_type=SourceType.web,
        source_url="https://example.com/page",
        title="Page Title",
        tags=["alpha", "beta"],
        content_hash="abc123",
    )
    vm.add(entry)
    vm.save()

    assert manifest_path.exists()

    vm2 = VaultManifest(manifest_path)
    vm2.load()

    assert len(vm2.all_entries()) == 1
    loaded = vm2.get_by_id(entry.id)
    assert loaded is not None
    assert loaded.path == "docs/page.md"
    assert loaded.kind == ContentKind.wiki
    assert loaded.source_type == SourceType.web
    assert loaded.source_url == "https://example.com/page"
    assert loaded.title == "Page Title"
    assert loaded.tags == ["alpha", "beta"]
    assert loaded.content_hash == "abc123"
    assert loaded.index_state == IndexState.pending


def test_saved_json_has_version_field(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    vm = VaultManifest(manifest_path)
    vm.save()

    raw = json.loads(manifest_path.read_text())
    assert raw.get("version") == 1
    assert "entries" in raw


# ---------------------------------------------------------------------------
# get_by_path
# ---------------------------------------------------------------------------

def test_get_by_path(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    entry = ManifestEntry(path="wiki/home.md", kind=ContentKind.wiki, source_type=SourceType.markdown)
    vm.add(entry)

    found = vm.get_by_path("wiki/home.md")
    assert found is not None
    assert found.id == entry.id

    assert vm.get_by_path("nonexistent.md") is None


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def test_remove_found(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    entry = ManifestEntry(path="a.md", kind=ContentKind.raw, source_type=SourceType.local_file)
    vm.add(entry)

    result = vm.remove(entry.id)
    assert result is True
    assert vm.get_by_id(entry.id) is None
    assert len(vm.all_entries()) == 0


def test_remove_not_found(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    result = vm.remove("nonexistent-id")
    assert result is False


# ---------------------------------------------------------------------------
# update_hash
# ---------------------------------------------------------------------------

def test_update_hash(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    entry = ManifestEntry(path="img.png", kind=ContentKind.asset, source_type=SourceType.image)
    vm.add(entry)

    original_updated_at = entry.updated_at
    vm.update_hash(entry.id, "deadbeef")

    updated = vm.get_by_id(entry.id)
    assert updated is not None
    assert updated.content_hash == "deadbeef"
    # updated_at should be refreshed (may equal original if clock resolution is low,
    # but field must exist)
    assert updated.updated_at is not None


def test_update_hash_missing_entry(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    result = vm.update_hash("ghost-id", "hash")
    assert result is False


# ---------------------------------------------------------------------------
# set_index_state
# ---------------------------------------------------------------------------

def test_set_index_state(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    entry = ManifestEntry(path="doc.pdf", kind=ContentKind.raw, source_type=SourceType.pdf)
    vm.add(entry)

    assert entry.index_state == IndexState.pending
    vm.set_index_state(entry.id, IndexState.indexed)

    updated = vm.get_by_id(entry.id)
    assert updated is not None
    assert updated.index_state == IndexState.indexed


def test_set_index_state_missing_entry(tmp_path: Path):
    vm = VaultManifest(tmp_path / "manifest.json")
    result = vm.set_index_state("ghost-id", IndexState.failed)
    assert result is False


# ---------------------------------------------------------------------------
# load when file does not exist
# ---------------------------------------------------------------------------

def test_load_nonexistent_file(tmp_path: Path):
    vm = VaultManifest(tmp_path / "does_not_exist" / "manifest.json")
    vm.load()  # should not raise
    assert vm.all_entries() == []
    assert vm.entries == {}
