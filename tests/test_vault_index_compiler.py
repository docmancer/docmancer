"""Tests for docmancer.vault.index_compiler."""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.vault.index_compiler import (
    _extract_summary,
    _strip_frontmatter,
    compile_index,
    write_index,
)
from docmancer.vault.manifest import VaultManifest
from docmancer.vault.scanner import scan_vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_vault(tmp_path):
    (tmp_path / ".docmancer").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "outputs").mkdir()
    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest_path.write_text('{"version": 1, "entries": {}}', encoding="utf-8")
    return manifest_path


def _write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _scan(tmp_path: Path) -> None:
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    scan_vault(tmp_path, manifest, ["raw", "wiki", "outputs"])
    manifest.save()


# ---------------------------------------------------------------------------
# _strip_frontmatter
# ---------------------------------------------------------------------------


def test_strip_frontmatter():
    content = "---\ntitle: Hello\ntags: [a, b]\n---\nBody text here."
    result = _strip_frontmatter(content)
    assert "title:" not in result
    assert "tags:" not in result
    assert "Body text here." in result


def test_strip_frontmatter_no_frontmatter():
    content = "Just some plain text.\nAnother line."
    result = _strip_frontmatter(content)
    assert result == content


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------


def test_extract_summary_strips_frontmatter():
    content = "---\ntitle: Secret\n---\nThe real summary."
    result = _extract_summary(content)
    assert "Secret" not in result
    assert "The real summary." in result


def test_extract_summary_skips_headings():
    content = "# Main Heading\n## Sub Heading\nActual paragraph content."
    result = _extract_summary(content)
    assert result == "Actual paragraph content."


def test_extract_summary_truncation():
    long_text = "Word " * 100  # 500 chars
    result = _extract_summary(long_text)
    assert len(result) <= 204  # 200 + "..."
    assert result.endswith("...")


def test_extract_summary_empty_content():
    assert _extract_summary("") == ""
    assert _extract_summary("# Only headings\n## Nothing else") == ""


# ---------------------------------------------------------------------------
# compile_index
# ---------------------------------------------------------------------------


def test_compile_index_empty_vault(tmp_path):
    _scaffold_vault(tmp_path)
    result = compile_index(tmp_path)
    assert "# Vault Index" in result
    # No table headers should appear when no entries exist.
    assert "| Article" not in result
    assert "| Source" not in result


def test_compile_index_with_wiki_articles(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "authentication.md",
        "---\ntitle: Authentication Guide\ntags: [auth, security]\n---\nHow to authenticate users.",
    )
    _write_file(
        tmp_path / "wiki" / "getting-started.md",
        "---\ntitle: Getting Started\ntags: [intro]\n---\nA quick start guide for new users.",
    )
    _scan(tmp_path)

    result = compile_index(tmp_path)
    assert "## Wiki Articles" in result
    assert "[[authentication]]" in result
    assert "[[getting-started]]" in result
    assert "Authentication Guide" in result or "authentication" in result.lower()
    assert "`auth`" in result
    assert "`security`" in result
    assert "`intro`" in result


def test_compile_index_with_raw_sources(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "raw" / "api-reference.md",
        "---\ntitle: API Reference\n---\nEndpoint documentation for the REST API.",
    )
    _scan(tmp_path)

    result = compile_index(tmp_path)
    assert "## Raw Sources" in result
    assert "raw/api-reference.md" in result


# ---------------------------------------------------------------------------
# write_index
# ---------------------------------------------------------------------------


def test_write_index(tmp_path):
    _scaffold_vault(tmp_path)
    content = "# Test Index\nSome content."
    result_path = write_index(tmp_path, content)

    assert result_path == tmp_path / "wiki" / "_index.md"
    assert result_path.exists()
    assert result_path.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# _index.md excluded from scan
# ---------------------------------------------------------------------------


def test_index_excluded_from_scan(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(tmp_path / "wiki" / "_index.md", "# Auto Index\nGenerated content.")
    _write_file(tmp_path / "wiki" / "real-article.md", "# Real Article\nContent.")
    _scan(tmp_path)

    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    paths = [e.path for e in manifest.all_entries()]
    assert "wiki/_index.md" not in paths
    assert "wiki/real-article.md" in paths
