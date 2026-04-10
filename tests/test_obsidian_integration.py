"""Integration tests for the Obsidian-native vault workflow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from docmancer.core.config import DocmancerConfig
from docmancer.vault.manifest import ContentKind, VaultManifest
from docmancer.vault.operations import init_obsidian_vault, init_vault
from docmancer.vault.scanner import scan_vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


WEB_CLIPPER_ARTICLE = (
    "---\n"
    "title: Understanding Transformers\n"
    "source: https://example.com/transformers\n"
    "author: Research Author\n"
    "published: 2026-03-01\n"
    "created: 2026-04-07\n"
    "tags:\n"
    "  - ml\n"
    "  - transformers\n"
    "---\n\n"
    "# Understanding Transformers\n\n"
    "Transformers are a type of neural network architecture...\n"
)


# ---------------------------------------------------------------------------
# 1. init --template obsidian creates correct structure
# ---------------------------------------------------------------------------


def test_init_obsidian_creates_config(tmp_path: Path) -> None:
    config_path = init_obsidian_vault(tmp_path)
    assert config_path.exists()

    with open(config_path) as f:
        data = yaml.safe_load(f)

    assert data["vault"]["scan_dirs"] == ["."]
    assert data["vault"]["scan_cooldown_seconds"] == 30
    assert (tmp_path / ".docmancer" / "manifest.json").exists()


def test_init_obsidian_does_not_create_rigid_dirs(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)
    for d in ["raw", "wiki", "outputs", "assets"]:
        assert not (tmp_path / d).exists()


def test_init_obsidian_updates_obsidian_ignore(tmp_path: Path) -> None:
    # Create .obsidian/app.json first
    obsidian_dir = tmp_path / ".obsidian"
    obsidian_dir.mkdir()
    app_json = obsidian_dir / "app.json"
    app_json.write_text(json.dumps({"userIgnoreFilters": []}), encoding="utf-8")

    init_obsidian_vault(tmp_path)

    data = json.loads(app_json.read_text())
    assert ".docmancer" in data["userIgnoreFilters"]


def test_init_obsidian_migrates_existing_config_into_obsidian_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "docmancer.yaml"
    config_path.write_text(
        "vector_store:\n"
        "  collection_name: knowledge_base\n"
        "vault:\n"
        "  scan_dirs:\n"
        "    - raw\n",
        encoding="utf-8",
    )

    init_obsidian_vault(tmp_path, name="My Research")

    config = DocmancerConfig.from_yaml(config_path)
    assert config.vault is not None
    assert config.vault.effective_scan_dirs() == ["."]
    assert config.vector_store.collection_name == "obsidian_my_research"


@patch("docmancer.vault.registry.VaultRegistry")
def test_init_obsidian_registers_and_tags_existing_config(mock_registry_cls, tmp_path: Path) -> None:
    (tmp_path / "docmancer.yaml").write_text(
        "vector_store:\n"
        "  collection_name: knowledge_base\n",
        encoding="utf-8",
    )

    init_obsidian_vault(tmp_path, name="research")

    registry = mock_registry_cls.return_value
    registry.register.assert_called_once()
    registry.add_tags.assert_called_once_with("research", ["obsidian"])


# ---------------------------------------------------------------------------
# 2. init --template vault still works (regression)
# ---------------------------------------------------------------------------


def test_init_vault_still_creates_dirs(tmp_path: Path) -> None:
    config_path = init_vault(tmp_path)
    assert config_path.exists()
    for d in ["raw", "wiki", "outputs", "assets", ".docmancer"]:
        assert (tmp_path / d).is_dir()


# ---------------------------------------------------------------------------
# 3. Web Clipper file is picked up by scan with flexible kind inference
# ---------------------------------------------------------------------------


def test_webclipper_file_scanned_and_indexed(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)
    _write_md(tmp_path / "Clippings" / "transformers.md", WEB_CLIPPER_ARTICLE)

    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    result = scan_vault(tmp_path, manifest, ["."])

    assert len(result.added) == 1
    entry = manifest.get_by_path("Clippings/transformers.md")
    assert entry is not None
    assert entry.kind == ContentKind.raw
    assert entry.source_url == "https://example.com/transformers"
    assert entry.title == "Understanding Transformers"
    assert "ml" in entry.tags
    assert "transformers" in entry.tags


# ---------------------------------------------------------------------------
# 4. Content kind inference in whole-vault mode
# ---------------------------------------------------------------------------


def test_kind_inference_by_folder(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)

    _write_md(tmp_path / "Clippings" / "clip.md", "---\ntitle: Clip\n---\nContent")
    _write_md(tmp_path / "Notes" / "note.md", "---\ntitle: Note\n---\nContent")
    _write_md(tmp_path / "Reports" / "report.md", "---\ntitle: Report\n---\nContent")

    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    scan_vault(tmp_path, manifest, ["."])

    assert manifest.get_by_path("Clippings/clip.md").kind == ContentKind.raw
    assert manifest.get_by_path("Notes/note.md").kind == ContentKind.wiki
    assert manifest.get_by_path("Reports/report.md").kind == ContentKind.output


def test_kind_inference_by_frontmatter(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)
    _write_md(tmp_path / "mixed" / "page.md", "---\ntitle: Wiki Page\nkind: wiki\n---\nContent")

    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    scan_vault(tmp_path, manifest, ["."])

    assert manifest.get_by_path("mixed/page.md").kind == ContentKind.wiki


def test_image_inferred_as_asset(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)
    img = tmp_path / "diagram.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    scan_vault(tmp_path, manifest, ["."])

    assert manifest.get_by_path("diagram.png").kind == ContentKind.asset


# ---------------------------------------------------------------------------
# 5. .obsidian/ directory is excluded from scan
# ---------------------------------------------------------------------------


def test_obsidian_dir_excluded(tmp_path: Path) -> None:
    init_obsidian_vault(tmp_path)
    _write_md(tmp_path / "note.md", "# Hello")
    (tmp_path / ".obsidian").mkdir(exist_ok=True)
    _write_md(tmp_path / ".obsidian" / "workspace.md", "internal")

    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    scan_vault(tmp_path, manifest, ["."])

    paths = [e.path for e in manifest.all_entries()]
    assert "note.md" in paths
    assert not any(".obsidian" in p for p in paths)
