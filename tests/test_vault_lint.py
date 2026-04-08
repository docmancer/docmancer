"""Tests for docmancer.vault.lint."""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.vault.lint import LintIssue, lint_vault
from docmancer.vault.manifest import VaultManifest
from docmancer.vault.scanner import scan_vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scaffold_vault(tmp_path: Path) -> None:
    from docmancer.vault.operations import init_vault
    init_vault(tmp_path)


def _scan(tmp_path: Path) -> None:
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    scan_vault(tmp_path, manifest, ["raw", "wiki", "outputs"])
    manifest.save()


def _write_file(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_VALID_WIKI_FM = """\
---
title: Test Article
tags: [test]
sources: [raw/source.md]
created: 2026-01-01
updated: 2026-01-01
---
"""

_VALID_OUTPUT_FM = """\
---
title: Test Output
tags: [test]
created: 2026-01-01
---
"""


# ---------------------------------------------------------------------------
# 1. test_lint_catches_broken_wikilinks
# ---------------------------------------------------------------------------

def test_lint_catches_broken_wikilinks(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "article.md",
        _VALID_WIKI_FM + "\nSee [[nonexistent]] for more.\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    wikilink_issues = [i for i in issues if i.check == "broken_wikilink"]
    assert len(wikilink_issues) >= 1
    assert "nonexistent" in wikilink_issues[0].message
    assert wikilink_issues[0].severity == "error"


# ---------------------------------------------------------------------------
# 2. test_lint_passes_valid_wikilinks
# ---------------------------------------------------------------------------

def test_lint_passes_valid_wikilinks(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "target.md",
        _VALID_WIKI_FM + "\nTarget content.\n",
    )
    _write_file(
        tmp_path / "wiki" / "source.md",
        _VALID_WIKI_FM + "\nSee [[target]] for more.\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    wikilink_issues = [i for i in issues if i.check == "broken_wikilink"]
    assert wikilink_issues == []


# ---------------------------------------------------------------------------
# 3. test_lint_catches_missing_frontmatter
# ---------------------------------------------------------------------------

def test_lint_catches_missing_frontmatter(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "bare.md",
        "No frontmatter here, just content.\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    fm_issues = [i for i in issues if i.check == "missing_frontmatter" and i.path == "wiki/bare.md"]
    assert len(fm_issues) == 5  # title, tags, sources, created, updated
    assert all(i.severity == "warning" for i in fm_issues)
    missing_keys = {i.message.split(": ")[-1] for i in fm_issues}
    assert missing_keys == {"title", "tags", "sources", "created", "updated"}


# ---------------------------------------------------------------------------
# 4. test_lint_catches_manifest_file_mismatch
# ---------------------------------------------------------------------------

def test_lint_catches_manifest_file_mismatch(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    f = _write_file(tmp_path / "raw" / "deleted.md", "will be deleted")
    _scan(tmp_path)

    # Now delete the file but leave manifest intact
    f.unlink()

    issues = lint_vault(tmp_path)
    missing_issues = [i for i in issues if i.check == "manifest_missing_file"]
    assert len(missing_issues) == 1
    assert missing_issues[0].path == "raw/deleted.md"
    assert missing_issues[0].severity == "error"


# ---------------------------------------------------------------------------
# 5. test_lint_catches_untracked_files
# ---------------------------------------------------------------------------

def test_lint_catches_untracked_files(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(tmp_path / "raw" / "tracked.md", "tracked content")
    _scan(tmp_path)

    # Add a new file without rescanning
    _write_file(tmp_path / "raw" / "untracked.md", "untracked content")

    issues = lint_vault(tmp_path)
    untracked_issues = [i for i in issues if i.check == "untracked_file"]
    assert len(untracked_issues) == 1
    assert untracked_issues[0].path == "raw/untracked.md"
    assert untracked_issues[0].severity == "warning"


# ---------------------------------------------------------------------------
# 6. test_lint_catches_broken_local_links
# ---------------------------------------------------------------------------

def test_lint_catches_broken_local_links(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "article.md",
        _VALID_WIKI_FM + "\nSee [guide](./missing-guide.md) for details.\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    link_issues = [i for i in issues if i.check == "broken_local_link"]
    assert len(link_issues) >= 1
    assert "missing-guide.md" in link_issues[0].message
    assert link_issues[0].severity == "error"


# ---------------------------------------------------------------------------
# 7. test_lint_catches_broken_image_refs
# ---------------------------------------------------------------------------

def test_lint_catches_broken_image_refs(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "article.md",
        _VALID_WIKI_FM + "\n![diagram](./images/missing.png)\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    img_issues = [i for i in issues if i.check == "broken_image_ref"]
    assert len(img_issues) >= 1
    assert "missing.png" in img_issues[0].message
    assert img_issues[0].severity == "error"


# ---------------------------------------------------------------------------
# 8. test_lint_output_is_structured
# ---------------------------------------------------------------------------

def test_lint_output_is_structured(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    # Create a file that will generate at least one issue (missing frontmatter)
    _write_file(tmp_path / "wiki" / "bare.md", "No frontmatter.\n")
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    assert len(issues) > 0

    for issue in issues:
        assert isinstance(issue, LintIssue)
        assert issue.severity in ("error", "warning")
        assert isinstance(issue.check, str) and len(issue.check) > 0
        assert isinstance(issue.path, str) and len(issue.path) > 0
        assert isinstance(issue.message, str) and len(issue.message) > 0


# ---------------------------------------------------------------------------
# 9. test_lint_clean_vault
# ---------------------------------------------------------------------------

def test_lint_clean_vault(tmp_path: Path) -> None:
    _scaffold_vault(tmp_path)
    # Create a raw source file with required frontmatter (title, source, created)
    _write_file(
        tmp_path / "raw" / "source.md",
        "---\ntitle: Source\nsource: \"https://example.com\"\ncreated: 2026-01-01\n---\n# Source\nSome raw content.\n",
    )
    # Create a well-formed wiki file with valid wikilink to itself
    _write_file(
        tmp_path / "wiki" / "article.md",
        _VALID_WIKI_FM + "\nSee [[source]] for the raw data.\n",
    )
    # Create a well-formed output file
    _write_file(
        tmp_path / "outputs" / "report.md",
        _VALID_OUTPUT_FM + "\nFinal report content.\n",
    )
    _scan(tmp_path)

    issues = lint_vault(tmp_path)
    assert issues == [], f"Expected zero issues but got: {issues}"
