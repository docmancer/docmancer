"""Tests for docmancer.vault.scanner."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docmancer.vault.manifest import (
    ContentKind,
    IndexState,
    ManifestEntry,
    SourceType,
    VaultManifest,
)
from docmancer.vault.scanner import (
    ScanResult,
    _infer_kind,
    _infer_source_type,
    _sha256,
    scan_vault,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(tmp_path: Path) -> VaultManifest:
    manifest_path = tmp_path / "manifest.json"
    m = VaultManifest(manifest_path)
    return m


def _write_file(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. _sha256 computes correct hash
# ---------------------------------------------------------------------------

def test_sha256_correct(tmp_path: Path) -> None:
    f = _write_file(tmp_path / "file.txt", "hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert _sha256(f) == expected


def test_sha256_binary_content(tmp_path: Path) -> None:
    data = bytes(range(256))
    f = tmp_path / "bin.pdf"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert _sha256(f) == expected


def test_sha256_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    expected = hashlib.sha256(b"").hexdigest()
    assert _sha256(f) == expected


# ---------------------------------------------------------------------------
# 2. Scan discovers new files — correct kind and source_type
# ---------------------------------------------------------------------------

def test_scan_adds_new_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "doc.md", "# Title")
    _write_file(vault / "wiki" / "page.md", "# Wiki Page")
    _write_file(vault / "outputs" / "report.txt", "output")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw", "wiki", "outputs"])

    assert len(result.added) == 3
    assert result.updated == []
    assert result.removed == []
    assert result.unchanged == 0

    # Verify kinds
    raw_entry = manifest.get_by_path("raw/doc.md")
    assert raw_entry is not None
    assert raw_entry.kind == ContentKind.raw
    assert raw_entry.source_type == SourceType.markdown
    assert raw_entry.index_state == IndexState.pending

    wiki_entry = manifest.get_by_path("wiki/page.md")
    assert wiki_entry is not None
    assert wiki_entry.kind == ContentKind.wiki

    out_entry = manifest.get_by_path("outputs/report.txt")
    assert out_entry is not None
    assert out_entry.kind == ContentKind.output
    assert out_entry.source_type == SourceType.local_file


def test_scan_correct_source_type_for_images(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg"):
        _write_file(vault / "raw" / f"img{ext}", "fake-image-data")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw"])

    assert len(result.added) == 5
    for path in result.added:
        entry = manifest.get_by_path(path)
        assert entry is not None
        assert entry.source_type == SourceType.image


def test_scan_pdf_source_type(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "doc.pdf", "%PDF-1.4")

    manifest = _make_manifest(tmp_path)
    scan_vault(vault, manifest, ["raw"])

    entry = manifest.get_by_path("raw/doc.pdf")
    assert entry is not None
    assert entry.source_type == SourceType.pdf


# ---------------------------------------------------------------------------
# 3. Scan detects stale files (content changed → hash mismatch)
# ---------------------------------------------------------------------------

def test_scan_detects_stale_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    f = _write_file(vault / "raw" / "doc.md", "original content")

    manifest = _make_manifest(tmp_path)
    # First scan — adds the file
    scan_vault(vault, manifest, ["raw"])

    # Mutate file content
    f.write_text("modified content", encoding="utf-8")

    # Second scan — should detect change
    result2 = scan_vault(vault, manifest, ["raw"])

    assert result2.added == []
    assert len(result2.updated) == 1
    assert result2.updated[0] == "raw/doc.md"
    assert result2.removed == []
    assert result2.unchanged == 0

    # Manifest entry should now be stale with updated hash
    entry = manifest.get_by_path("raw/doc.md")
    assert entry is not None
    assert entry.index_state == IndexState.stale
    expected_hash = hashlib.sha256(b"modified content").hexdigest()
    assert entry.content_hash == expected_hash


# ---------------------------------------------------------------------------
# 4. Scan removes deleted files from manifest
# ---------------------------------------------------------------------------

def test_scan_removes_deleted_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    f = _write_file(vault / "raw" / "doc.md", "content")
    _write_file(vault / "raw" / "keep.md", "keep this")

    manifest = _make_manifest(tmp_path)
    scan_vault(vault, manifest, ["raw"])

    assert len(manifest.all_entries()) == 2

    # Delete one file
    f.unlink()

    result2 = scan_vault(vault, manifest, ["raw"])

    assert result2.removed == ["raw/doc.md"]
    assert result2.added == []
    assert result2.unchanged == 1
    assert len(manifest.all_entries()) == 1
    assert manifest.get_by_path("raw/doc.md") is None
    assert manifest.get_by_path("raw/keep.md") is not None


# ---------------------------------------------------------------------------
# 5. Scan reports unchanged files on second scan
# ---------------------------------------------------------------------------

def test_scan_unchanged_on_second_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "a.md", "alpha")
    _write_file(vault / "raw" / "b.md", "beta")

    manifest = _make_manifest(tmp_path)
    r1 = scan_vault(vault, manifest, ["raw"])
    assert r1.added == sorted(["raw/a.md", "raw/b.md"])
    assert r1.unchanged == 0

    r2 = scan_vault(vault, manifest, ["raw"])
    assert r2.added == []
    assert r2.updated == []
    assert r2.removed == []
    assert r2.unchanged == 2


# ---------------------------------------------------------------------------
# 6. Scan skips unsupported extensions
# ---------------------------------------------------------------------------

def test_scan_skips_unsupported_extensions(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "data.json", '{"key": "value"}')
    _write_file(vault / "raw" / "script.py", "print('hi')")
    _write_file(vault / "raw" / "doc.md", "# Valid")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw"])

    assert len(result.added) == 1
    assert result.added[0] == "raw/doc.md"
    assert manifest.get_by_path("raw/data.json") is None
    assert manifest.get_by_path("raw/script.py") is None


# ---------------------------------------------------------------------------
# 7. Scan skips missing directories gracefully
# ---------------------------------------------------------------------------

def test_scan_skips_missing_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    # "raw" directory does not exist

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw", "wiki", "outputs"])

    assert result.added == []
    assert result.updated == []
    assert result.removed == []
    assert result.unchanged == 0


def test_scan_partial_missing_dirs(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "doc.md", "content")
    # wiki and outputs do not exist

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw", "wiki", "outputs"])

    assert len(result.added) == 1
    assert result.added[0] == "raw/doc.md"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_scan_hydrates_manifest_metadata_from_frontmatter(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(
        vault / "wiki" / "guide.md",
        "---\n"
        "title: API Guide\n"
        "tags: [api, auth]\n"
        "sources: [https://docs.example.com/auth]\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "---\n\n"
        "# API Guide\n\nBody.",
    )

    manifest = _make_manifest(tmp_path)
    scan_vault(vault, manifest, ["wiki"])

    entry = manifest.get_by_path("wiki/guide.md")
    assert entry is not None
    assert entry.title == "API Guide"
    assert entry.tags == ["api", "auth"]
    assert entry.source_url == "https://docs.example.com/auth"


def test_scan_does_not_remove_entries_outside_selected_roots(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "tracked.md", "# Tracked")

    manifest = _make_manifest(tmp_path)
    asset_entry = ManifestEntry(
        path="assets/diagram.png",
        kind=ContentKind.asset,
        source_type=SourceType.image,
        content_hash="abc",
    )
    manifest.add(asset_entry)

    result = scan_vault(vault, manifest, ["raw"])

    assert result.removed == []
    assert manifest.get_by_path("assets/diagram.png") is not None

def test_infer_kind_for_known_dirs() -> None:
    assert _infer_kind("raw/file.md") == ContentKind.raw
    assert _infer_kind("wiki/page.md") == ContentKind.wiki
    assert _infer_kind("outputs/report.txt") == ContentKind.output


def test_infer_kind_for_unknown_dir() -> None:
    assert _infer_kind("assets/image.png") == ContentKind.asset
    assert _infer_kind("other/thing.md") == ContentKind.asset


def test_infer_kind_no_subdir() -> None:
    # No slash in path — first_part is empty string, falls back to asset
    assert _infer_kind("file.md") == ContentKind.asset


def test_infer_source_type(tmp_path: Path) -> None:
    assert _infer_source_type(Path("doc.md")) == SourceType.markdown
    assert _infer_source_type(Path("doc.txt")) == SourceType.local_file
    assert _infer_source_type(Path("doc.pdf")) == SourceType.pdf
    assert _infer_source_type(Path("img.PNG")) == SourceType.image  # case-insensitive
    assert _infer_source_type(Path("img.JPG")) == SourceType.image
    assert _infer_source_type(Path("img.svg")) == SourceType.image
    assert _infer_source_type(Path("unknown.xyz")) == SourceType.local_file


def test_scan_nested_subdirectory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_file(vault / "raw" / "subdir" / "nested.md", "nested content")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(vault, manifest, ["raw"])

    assert len(result.added) == 1
    assert result.added[0] == "raw/subdir/nested.md"

    entry = manifest.get_by_path("raw/subdir/nested.md")
    assert entry is not None
    # Kind inferred from first path component "raw"
    assert entry.kind == ContentKind.raw


def test_scan_content_hash_stored_correctly(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    content = "exact content for hashing"
    _write_file(vault / "raw" / "check.md", content)

    manifest = _make_manifest(tmp_path)
    scan_vault(vault, manifest, ["raw"])

    entry = manifest.get_by_path("raw/check.md")
    assert entry is not None
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert entry.content_hash == expected


def test_scan_result_is_dataclass() -> None:
    r = ScanResult()
    assert r.added == []
    assert r.updated == []
    assert r.removed == []
    assert r.unchanged == 0
