"""Tests for vault packaging — package/extract round-trip and vault card generation."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from docmancer.core.config import DocmancerConfig, VaultConfig
from docmancer.vault.manifest import (
    ContentKind,
    ManifestEntry,
    SourceType,
    VaultManifest,
)
from docmancer.vault.operations import init_vault
from docmancer.vault.packaging import (
    ContentStats,
    QualityReport,
    VaultCard,
    VaultDependency,
    build_vault_card,
    extract_vault_package,
    generate_vault_readme,
    load_vault_card,
    package_vault,
)


def _scaffold_vault(tmp_path: Path, name: str = "test-vault") -> Path:
    vault_root = tmp_path / name
    init_vault(vault_root)
    return vault_root


def _add_file(vault_root: Path, rel_path: str, content: str) -> None:
    file_path = vault_root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _add_manifest_entry(
    vault_root: Path, path: str, kind: ContentKind, title: str = "",
) -> None:
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    manifest.add(ManifestEntry(
        path=path,
        kind=kind,
        source_type=SourceType.markdown,
        title=title or path,
        tags=["test"],
    ))
    manifest.save()


class TestBuildVaultCard:
    def test_basic_card_generation(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc1.md", "# Doc 1\nContent.")
        _add_manifest_entry(vault_root, "raw/doc1.md", ContentKind.raw, "Doc 1")

        config = DocmancerConfig(vault=VaultConfig(
            version="1.0.0", description="Test vault", author="tester",
        ))
        card = build_vault_card(vault_root, config)

        assert card.name == "test-vault"
        assert card.version == "1.0.0"
        assert card.description == "Test vault"
        assert card.author == "tester"
        assert card.content_stats.raw_count == 1
        assert card.content_stats.total_entries == 1

    def test_counts_by_kind(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/r1.md", "raw 1")
        _add_file(vault_root, "raw/r2.md", "raw 2")
        _add_file(vault_root, "wiki/w1.md", "wiki 1")
        _add_file(vault_root, "outputs/o1.md", "output 1")
        _add_manifest_entry(vault_root, "raw/r1.md", ContentKind.raw)
        _add_manifest_entry(vault_root, "raw/r2.md", ContentKind.raw)
        _add_manifest_entry(vault_root, "wiki/w1.md", ContentKind.wiki)
        _add_manifest_entry(vault_root, "outputs/o1.md", ContentKind.output)

        config = DocmancerConfig(vault=VaultConfig())
        card = build_vault_card(vault_root, config)

        assert card.content_stats.raw_count == 2
        assert card.content_stats.wiki_count == 1
        assert card.content_stats.output_count == 1
        assert card.content_stats.total_entries == 4

    def test_dependencies_in_card(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        config = DocmancerConfig(vault=VaultConfig(
            dependencies=[
                {"name": "react-docs", "version": ">=1.0.0"},
                {"name": "typescript-docs"},
            ],
        ))
        card = build_vault_card(vault_root, config)

        assert len(card.dependencies) == 2
        assert card.dependencies[0].name == "react-docs"
        assert card.dependencies[0].version == ">=1.0.0"
        assert card.dependencies[1].name == "typescript-docs"

    def test_total_size_computed(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc.md", "x" * 1000)

        config = DocmancerConfig(vault=VaultConfig())
        card = build_vault_card(vault_root, config)

        assert card.content_stats.total_size_bytes >= 1000

    def test_no_config_defaults(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        config = DocmancerConfig()
        card = build_vault_card(vault_root, config)

        assert card.version == "0.1.0"
        assert card.description == ""


class TestGenerateVaultReadme:
    def test_basic_readme(self) -> None:
        card = VaultCard(
            name="my-vault",
            version="1.0.0",
            description="A test vault for demos.",
            author="tester",
            content_stats=ContentStats(raw_count=5, wiki_count=3, total_entries=8),
        )
        readme = generate_vault_readme(card)

        assert "# my-vault" in readme
        assert "A test vault for demos." in readme
        assert "**Version:** 1.0.0" in readme
        assert "**Author:** tester" in readme
        assert "| Raw sources | 5 |" in readme
        assert "docmancer vault install my-vault" in readme

    def test_readme_with_dependencies(self) -> None:
        card = VaultCard(
            name="fullstack",
            version="2.0.0",
            dependencies=[
                VaultDependency(name="react-docs", version=">=1.0.0"),
                VaultDependency(name="nextjs-docs"),
            ],
        )
        readme = generate_vault_readme(card)

        assert "## Dependencies" in readme
        assert "react-docs" in readme
        assert "nextjs-docs" in readme

    def test_readme_with_eval_scores(self) -> None:
        card = VaultCard(
            name="scored-vault",
            version="1.0.0",
            eval_scores={"mrr": 0.85, "hit_rate": 0.92},
        )
        readme = generate_vault_readme(card)

        assert "## Eval Scores" in readme
        assert "0.8500" in readme
        assert "0.9200" in readme


class TestPackageVault:
    def test_package_creates_tar_gz(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc.md", "# Test\nContent.")
        _add_manifest_entry(vault_root, "raw/doc.md", ContentKind.raw)

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        assert archive.exists()
        assert archive.suffix == ".gz"
        assert ".tar" in archive.name

    def test_package_contains_expected_files(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc.md", "# Test\nContent.")
        _add_file(vault_root, "wiki/article.md", "# Article\nWiki content.")
        _add_manifest_entry(vault_root, "raw/doc.md", ContentKind.raw)
        _add_manifest_entry(vault_root, "wiki/article.md", ContentKind.wiki)

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()

        # Check expected files are present (paths are prefixed with archive name)
        name_set = {n.split("/", 1)[1] if "/" in n else n for n in names}
        assert "vault-card.json" in name_set
        assert "README.md" in name_set
        assert "manifest.json" in name_set
        assert "raw/doc.md" in name_set
        assert "wiki/article.md" in name_set

    def test_package_with_version_override(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        output_dir = tmp_path / "dist"

        archive = package_vault(vault_root, output_dir, version="2.5.0")

        assert "2.5.0" in archive.name

    def test_package_with_quality_report(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        output_dir = tmp_path / "dist"

        report = QualityReport(lint_errors=0, lint_warnings=2, passed=True)
        archive = package_vault(vault_root, output_dir, quality_report=report)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()

        name_set = {n.split("/", 1)[1] if "/" in n else n for n in names}
        assert "quality-report.json" in name_set

    def test_package_includes_eval_dataset(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        eval_dataset = vault_root / ".docmancer" / "eval_dataset.json"
        eval_dataset.write_text('{"entries": []}', encoding="utf-8")

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()

        name_set = {n.split("/", 1)[1] if "/" in n else n for n in names}
        assert ".docmancer/eval_dataset.json" in name_set


class TestExtractVaultPackage:
    def test_round_trip(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc.md", "# Round Trip\nContent here.")
        _add_file(vault_root, "wiki/article.md", "# Article\nWiki.")
        _add_manifest_entry(vault_root, "raw/doc.md", ContentKind.raw)
        _add_manifest_entry(vault_root, "wiki/article.md", ContentKind.wiki)

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        extract_dir = tmp_path / "extracted"
        extracted_root = extract_vault_package(archive, extract_dir)

        assert (extracted_root / "raw" / "doc.md").exists()
        assert (extracted_root / "wiki" / "article.md").exists()
        assert (extracted_root / "vault-card.json").exists()
        assert (extracted_root / "README.md").exists()

        # Manifest should be in .docmancer/
        assert (extracted_root / ".docmancer" / "manifest.json").exists()

    def test_content_preserved(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        original_content = "# Preserved Content\nThis should survive packaging."
        _add_file(vault_root, "raw/preserve.md", original_content)
        _add_manifest_entry(vault_root, "raw/preserve.md", ContentKind.raw)

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        extract_dir = tmp_path / "extracted"
        extracted_root = extract_vault_package(archive, extract_dir)

        restored = (extracted_root / "raw" / "preserve.md").read_text(encoding="utf-8")
        assert restored == original_content

    def test_vault_card_loadable_after_extract(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(vault_root, "raw/doc.md", "content")
        _add_manifest_entry(vault_root, "raw/doc.md", ContentKind.raw)

        output_dir = tmp_path / "dist"
        archive = package_vault(vault_root, output_dir)

        extract_dir = tmp_path / "extracted"
        extracted_root = extract_vault_package(archive, extract_dir)

        card = load_vault_card(extracted_root)
        assert card is not None
        assert card.name == "test-vault"


class TestLoadVaultCard:
    def test_load_missing(self, tmp_path: Path) -> None:
        assert load_vault_card(tmp_path) is None

    def test_load_valid(self, tmp_path: Path) -> None:
        card_data = VaultCard(name="test", version="1.0.0").model_dump()
        (tmp_path / "vault-card.json").write_text(
            json.dumps(card_data), encoding="utf-8"
        )
        card = load_vault_card(tmp_path)
        assert card is not None
        assert card.name == "test"

    def test_load_corrupt(self, tmp_path: Path) -> None:
        (tmp_path / "vault-card.json").write_text("not json", encoding="utf-8")
        assert load_vault_card(tmp_path) is None


class TestPathTraversalSafety:
    def test_rejects_absolute_paths(self, tmp_path: Path) -> None:
        # Create a malicious archive with absolute path
        archive_path = tmp_path / "evil.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            import io
            data = b"malicious content"
            info = tarfile.TarInfo(name="/etc/evil.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        with pytest.raises(ValueError, match="Unsafe path"):
            extract_vault_package(archive_path, tmp_path / "extract")

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        archive_path = tmp_path / "evil.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            import io
            data = b"malicious content"
            info = tarfile.TarInfo(name="vault/../../../etc/evil.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        with pytest.raises(ValueError, match="Unsafe path"):
            extract_vault_package(archive_path, tmp_path / "extract")
