"""Tests for docmancer.vault.freshness — scan-on-query freshness gate."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from docmancer.vault.manifest import VaultManifest
from docmancer.vault.freshness import needs_scan, auto_scan_if_needed, reset_cooldown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path) -> VaultManifest:
    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    m = VaultManifest(manifest_path)
    return m


def _write_file(path: Path, content: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# needs_scan
# ---------------------------------------------------------------------------


def test_needs_scan_empty_manifest(tmp_path: Path) -> None:
    reset_cooldown()
    _write_file(tmp_path / "note.md", "# Hello")
    manifest = _make_manifest(tmp_path)
    assert needs_scan(tmp_path, manifest, ["."], cooldown_seconds=0) is True


def test_needs_scan_no_changes(tmp_path: Path) -> None:
    reset_cooldown()
    _write_file(tmp_path / "raw" / "note.md", "# Hello")
    manifest = _make_manifest(tmp_path)

    # Do a scan first so manifest has entries
    from docmancer.vault.scanner import scan_vault
    scan_vault(tmp_path, manifest, ["raw"])
    manifest.save()

    # Now check — file hasn't changed, should not need scan
    # Give a tiny sleep so that the mtime check is after the updated_at
    time.sleep(0.05)
    assert needs_scan(tmp_path, manifest, ["raw"], cooldown_seconds=0) is False


def test_needs_scan_detects_new_file(tmp_path: Path) -> None:
    reset_cooldown()
    _write_file(tmp_path / "raw" / "note.md", "# Hello")
    manifest = _make_manifest(tmp_path)

    from docmancer.vault.scanner import scan_vault
    scan_vault(tmp_path, manifest, ["raw"])
    manifest.save()

    # Add a new file after the scan
    time.sleep(0.05)
    _write_file(tmp_path / "raw" / "new.md", "# New")

    assert needs_scan(tmp_path, manifest, ["raw"], cooldown_seconds=0) is True


def test_needs_scan_respects_cooldown(tmp_path: Path) -> None:
    reset_cooldown()
    _write_file(tmp_path / "note.md", "# Hello")
    manifest = _make_manifest(tmp_path)

    # First check should trigger (empty manifest)
    assert needs_scan(tmp_path, manifest, ["."], cooldown_seconds=0) is True

    # Simulate that a scan just happened by setting _last_auto_scan_ts
    import docmancer.vault.freshness as freshness_mod
    freshness_mod._last_auto_scan_ts = time.time()

    # With cooldown, should return False even though there are changes
    assert needs_scan(tmp_path, manifest, ["."], cooldown_seconds=9999) is False


# ---------------------------------------------------------------------------
# auto_scan_if_needed
# ---------------------------------------------------------------------------


def test_auto_scan_if_needed_triggers_scan(tmp_path: Path) -> None:
    reset_cooldown()
    _write_file(tmp_path / "raw" / "note.md", "# Hello")
    (tmp_path / ".docmancer").mkdir(parents=True, exist_ok=True)

    manifest = _make_manifest(tmp_path)

    # Mock sync_vault_index to avoid actual embedding
    from unittest.mock import patch
    with patch("docmancer.vault.operations.sync_vault_index"):
        result = auto_scan_if_needed(tmp_path, ["raw"], manifest, cooldown_seconds=0)

    assert result is not None
    assert len(result.added) == 1
    assert result.added[0] == "raw/note.md"
    # Manifest should now have the entry
    assert manifest.get_by_path("raw/note.md") is not None


def test_auto_scan_if_needed_returns_none_when_not_needed(tmp_path: Path) -> None:
    reset_cooldown()
    (tmp_path / ".docmancer").mkdir(parents=True, exist_ok=True)
    manifest = _make_manifest(tmp_path)
    # Empty vault, no files — no scan needed beyond checking empty manifest
    # Actually, empty manifest with no files means needs_scan returns True (empty manifest check)
    # So let's create a scenario where scan is not needed
    _write_file(tmp_path / "raw" / "note.md", "# Hello")

    from docmancer.vault.scanner import scan_vault
    scan_vault(tmp_path, manifest, ["raw"])
    manifest.save()

    time.sleep(0.05)

    from unittest.mock import patch
    with patch("docmancer.vault.operations.sync_vault_index"):
        result = auto_scan_if_needed(tmp_path, ["raw"], manifest, cooldown_seconds=0)

    assert result is None
