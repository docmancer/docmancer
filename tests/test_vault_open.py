from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from docmancer.vault.operations import open_vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "# Test\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic open
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_creates_structure(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")

    config_path, count = open_vault(vault)

    assert (vault / ".docmancer").is_dir()
    assert (vault / "raw").is_dir()
    assert (vault / "wiki").is_dir()
    assert (vault / "outputs").is_dir()
    assert config_path == vault / "docmancer.yaml"
    assert config_path.exists()


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_symlinks_existing_files(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md", "# Page")
    _make_file(vault / "another.txt", "hello")

    _, count = open_vault(vault)

    assert count == 2
    link = vault / "raw" / "page.md"
    assert link.is_symlink()
    assert link.resolve() == (vault / "page.md").resolve()
    assert link.read_text() == "# Page"

    link2 = vault / "raw" / "another.txt"
    assert link2.is_symlink()
    assert link2.read_text() == "hello"


# ---------------------------------------------------------------------------
# Directory structure preservation
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_preserves_nested_structure(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "research" / "deep" / "paper.md", "# Paper")
    _make_file(vault / "daily" / "2026-04-07.md", "# Today")

    _, count = open_vault(vault)

    assert count == 2
    assert (vault / "raw" / "research" / "deep" / "paper.md").is_symlink()
    assert (vault / "raw" / "daily" / "2026-04-07.md").is_symlink()
    assert (vault / "raw" / "research" / "deep" / "paper.md").read_text() == "# Paper"


# ---------------------------------------------------------------------------
# Skipping rules
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_skips_dot_directories(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")
    _make_file(vault / ".obsidian" / "config.json", "{}")
    _make_file(vault / ".git" / "HEAD", "ref: refs/heads/main")
    _make_file(vault / ".trash" / "deleted.md", "gone")

    _, count = open_vault(vault)

    assert count == 1  # only page.md
    assert not (vault / "raw" / ".obsidian").exists()
    assert not (vault / "raw" / ".git").exists()
    assert not (vault / "raw" / ".trash").exists()


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_skips_managed_directories(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")
    # Pre-create a file in raw/ (as if vault was partially set up)
    _make_file(vault / "raw" / "existing.md", "already here")
    _make_file(vault / "wiki" / "compiled.md", "wiki page")

    _, count = open_vault(vault)

    # Should only symlink page.md, not files already in raw/ or wiki/
    assert count == 1
    link = vault / "raw" / "page.md"
    assert link.is_symlink()
    # existing.md should still be a real file, not a symlink
    assert not (vault / "raw" / "existing.md").is_symlink()


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_skips_unsupported_extensions(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")
    _make_file(vault / "data.json", '{"key": "value"}')
    _make_file(vault / "script.py", "print('hi')")

    _, count = open_vault(vault)

    assert count == 1  # only page.md


# ---------------------------------------------------------------------------
# Idempotent re-open
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_is_idempotent(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")

    _, count1 = open_vault(vault)
    assert count1 == 1

    _, count2 = open_vault(vault)
    assert count2 == 0  # no new symlinks


# ---------------------------------------------------------------------------
# Incremental pickup
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_picks_up_new_files(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "page.md")

    _, count1 = open_vault(vault)
    assert count1 == 1

    # Add a new file after first open
    _make_file(vault / "new_note.md", "# New")

    _, count2 = open_vault(vault)
    assert count2 == 1  # picks up the new file
    assert (vault / "raw" / "new_note.md").is_symlink()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_open_vault_raises_on_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_vault(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# Supported file types
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_open_vault_symlinks_supported_types(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "doc.md")
    _make_file(vault / "note.txt")
    (vault / "image.png").write_bytes(b"\x89PNG")
    (vault / "photo.jpg").write_bytes(b"\xff\xd8")

    _, count = open_vault(vault)

    assert count == 4


# ---------------------------------------------------------------------------
# Relative symlink targets
# ---------------------------------------------------------------------------


@patch("docmancer.vault.registry.VaultRegistry.register")
def test_symlinks_are_relative(mock_register, tmp_path):
    vault = tmp_path / "notes"
    _make_file(vault / "sub" / "page.md")

    open_vault(vault)

    link = vault / "raw" / "sub" / "page.md"
    assert link.is_symlink()
    # The symlink target should be relative, not absolute
    raw_target = Path(link.parent / link.readlink()).resolve()
    assert raw_target == (vault / "sub" / "page.md").resolve()
