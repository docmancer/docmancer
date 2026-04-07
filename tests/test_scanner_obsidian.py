"""Tests for Obsidian-specific scanner features: kind inference, Web Clipper frontmatter, skip dirs."""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.vault.manifest import ContentKind, VaultManifest
from docmancer.vault.scanner import (
    _infer_kind,
    _infer_kind_flexible,
    _manifest_metadata_for_file,
    _should_skip_path,
    scan_vault,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path) -> VaultManifest:
    m = VaultManifest(tmp_path / "manifest.json")
    return m


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _should_skip_path
# ---------------------------------------------------------------------------


def test_skip_obsidian_dir(tmp_path: Path) -> None:
    f = tmp_path / ".obsidian" / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()
    assert _should_skip_path(f, tmp_path) is True


def test_skip_docmancer_dir(tmp_path: Path) -> None:
    f = tmp_path / ".docmancer" / "manifest.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()
    assert _should_skip_path(f, tmp_path) is True


def test_skip_git_dir(tmp_path: Path) -> None:
    f = tmp_path / ".git" / "config"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()
    assert _should_skip_path(f, tmp_path) is True


def test_no_skip_normal_file(tmp_path: Path) -> None:
    f = tmp_path / "notes" / "article.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()
    assert _should_skip_path(f, tmp_path) is False


# ---------------------------------------------------------------------------
# _infer_kind_flexible — priority chain
# ---------------------------------------------------------------------------


def test_flexible_explicit_frontmatter_kind(tmp_path: Path) -> None:
    f = tmp_path / "something.md"
    assert _infer_kind_flexible("something.md", f, {"kind": "wiki"}) == ContentKind.wiki


def test_flexible_explicit_frontmatter_kind_output(tmp_path: Path) -> None:
    f = tmp_path / "report.md"
    assert _infer_kind_flexible("report.md", f, {"kind": "output"}) == ContentKind.output


def test_flexible_invalid_kind_falls_through(tmp_path: Path) -> None:
    f = tmp_path / "file.md"
    # Invalid kind should fall through to next heuristic
    result = _infer_kind_flexible("file.md", f, {"kind": "nonsense"})
    assert result == ContentKind.raw  # default


def test_flexible_folder_clippings(tmp_path: Path) -> None:
    f = tmp_path / "Clippings" / "article.md"
    assert _infer_kind_flexible("Clippings/article.md", f, {}) == ContentKind.raw


def test_flexible_folder_inbox(tmp_path: Path) -> None:
    f = tmp_path / "inbox" / "note.md"
    assert _infer_kind_flexible("inbox/note.md", f, {}) == ContentKind.raw


def test_flexible_folder_wiki(tmp_path: Path) -> None:
    f = tmp_path / "wiki" / "concept.md"
    assert _infer_kind_flexible("wiki/concept.md", f, {}) == ContentKind.wiki


def test_flexible_folder_notes(tmp_path: Path) -> None:
    f = tmp_path / "Notes" / "idea.md"
    assert _infer_kind_flexible("Notes/idea.md", f, {}) == ContentKind.wiki


def test_flexible_folder_reports(tmp_path: Path) -> None:
    f = tmp_path / "Reports" / "q4.md"
    assert _infer_kind_flexible("Reports/q4.md", f, {}) == ContentKind.output


def test_flexible_folder_attachments(tmp_path: Path) -> None:
    f = tmp_path / "Attachments" / "diagram.png"
    assert _infer_kind_flexible("Attachments/diagram.png", f, {}) == ContentKind.asset


def test_flexible_source_url_raw(tmp_path: Path) -> None:
    f = tmp_path / "article.md"
    fm = {"source": "https://example.com/article"}
    assert _infer_kind_flexible("article.md", f, fm) == ContentKind.raw


def test_flexible_sources_plural_raw(tmp_path: Path) -> None:
    f = tmp_path / "article.md"
    fm = {"sources": ["https://example.com/article"]}
    assert _infer_kind_flexible("article.md", f, fm) == ContentKind.raw


def test_flexible_image_extension_asset(tmp_path: Path) -> None:
    f = tmp_path / "photo.jpg"
    assert _infer_kind_flexible("photo.jpg", f, {}) == ContentKind.asset


def test_flexible_default_raw(tmp_path: Path) -> None:
    f = tmp_path / "random.md"
    assert _infer_kind_flexible("random.md", f, {}) == ContentKind.raw


def test_flexible_frontmatter_overrides_folder(tmp_path: Path) -> None:
    """Explicit frontmatter kind should win over folder heuristic."""
    f = tmp_path / "Clippings" / "article.md"
    assert _infer_kind_flexible("Clippings/article.md", f, {"kind": "wiki"}) == ContentKind.wiki


# ---------------------------------------------------------------------------
# Web Clipper frontmatter mapping
# ---------------------------------------------------------------------------


def test_webclipper_source_singular(tmp_path: Path) -> None:
    f = _write_md(tmp_path / "article.md", (
        "---\n"
        "title: Test Article\n"
        "source: https://example.com/post\n"
        "author: Jane Doe\n"
        "published: 2026-03-15\n"
        "tags:\n"
        "  - python\n"
        "---\n\n"
        "Content here."
    ))
    metadata = _manifest_metadata_for_file(f)
    assert metadata["source_url"] == "https://example.com/post"
    assert metadata["extra"]["author"] == "Jane Doe"
    assert metadata["extra"]["published"] == "2026-03-15"
    assert metadata["tags"] == ["python"]


def test_webclipper_sources_plural_takes_precedence(tmp_path: Path) -> None:
    f = _write_md(tmp_path / "article.md", (
        "---\n"
        "title: Test\n"
        "sources:\n"
        "  - https://primary.com\n"
        "source: https://secondary.com\n"
        "---\n\n"
        "Content."
    ))
    metadata = _manifest_metadata_for_file(f)
    assert metadata["source_url"] == "https://primary.com"


def test_webclipper_created_field(tmp_path: Path) -> None:
    f = _write_md(tmp_path / "article.md", (
        "---\n"
        "title: Test\n"
        "created: 2026-04-07T10:00:00Z\n"
        "---\n\n"
        "Content."
    ))
    metadata = _manifest_metadata_for_file(f)
    assert "created_at" in metadata
    assert "2026-04-07" in metadata["created_at"]


# ---------------------------------------------------------------------------
# scan_vault with flexible kind inference (scan_dirs=["."])
# ---------------------------------------------------------------------------


def test_scan_whole_vault_skips_obsidian_dir(tmp_path: Path) -> None:
    _write_md(tmp_path / "note.md", "# Hello")
    _write_md(tmp_path / ".obsidian" / "config.json", "{}")
    _write_md(tmp_path / ".docmancer" / "manifest.json", "{}")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(tmp_path, manifest, ["."])

    paths = [e.path for e in manifest.all_entries()]
    assert "note.md" in paths
    assert not any(".obsidian" in p for p in paths)
    assert not any(".docmancer" in p for p in paths)


def test_scan_whole_vault_flexible_kind(tmp_path: Path) -> None:
    _write_md(tmp_path / "Clippings" / "clip.md", (
        "---\n"
        "title: Clipped\n"
        "source: https://example.com\n"
        "---\n\n"
        "Content."
    ))
    _write_md(tmp_path / "wiki" / "concept.md", (
        "---\n"
        "title: Concept\n"
        "tags: [ai]\n"
        "---\n\n"
        "Wiki content."
    ))

    manifest = _make_manifest(tmp_path)
    result = scan_vault(tmp_path, manifest, ["."])

    clip_entry = manifest.get_by_path("Clippings/clip.md")
    assert clip_entry is not None
    assert clip_entry.kind == ContentKind.raw

    wiki_entry = manifest.get_by_path("wiki/concept.md")
    assert wiki_entry is not None
    assert wiki_entry.kind == ContentKind.wiki


def test_scan_specific_dirs_uses_old_inference(tmp_path: Path) -> None:
    """When scan_dirs is specific (not '.'), the old directory-based inference is used."""
    _write_md(tmp_path / "raw" / "file.md", "# Raw content")
    _write_md(tmp_path / "wiki" / "page.md", "# Wiki page")

    manifest = _make_manifest(tmp_path)
    result = scan_vault(tmp_path, manifest, ["raw", "wiki"])

    raw_entry = manifest.get_by_path("raw/file.md")
    assert raw_entry is not None
    assert raw_entry.kind == ContentKind.raw

    wiki_entry = manifest.get_by_path("wiki/page.md")
    assert wiki_entry is not None
    assert wiki_entry.kind == ContentKind.wiki
