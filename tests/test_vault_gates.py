"""Tests for pre-publish quality gates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from docmancer.vault.gates import GateResult, run_pre_publish_gates
from docmancer.vault.lint import LintIssue
from docmancer.vault.manifest import (
    ContentKind,
    ManifestEntry,
    SourceType,
    VaultManifest,
)
from docmancer.vault.operations import init_vault


def _scaffold_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "test-vault"
    init_vault(vault_root)
    return vault_root


def _add_file(vault_root: Path, rel_path: str, content: str) -> None:
    file_path = vault_root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _add_manifest_entry(vault_root: Path, path: str, kind: ContentKind) -> None:
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    manifest.add(ManifestEntry(
        path=path, kind=kind, source_type=SourceType.markdown,
    ))
    manifest.save()


class TestGateResult:
    def test_defaults(self) -> None:
        result = GateResult()
        assert result.passed is True
        assert result.lint_issues == []
        assert result.eval_result is None
        assert result.critical_errors == []
        assert result.warnings == []


class TestPrePublishGates:
    def test_clean_vault_passes(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_file(
            vault_root, "wiki/good.md",
            "---\ntitle: Good\ntags: []\nsources: []\ncreated: '2024-01-01'\nupdated: '2024-01-01'\n---\n# Good article",
        )
        _add_manifest_entry(vault_root, "wiki/good.md", ContentKind.wiki)

        result = run_pre_publish_gates(vault_root)

        assert result.passed is True
        assert result.critical_errors == []

    def test_lint_errors_block(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        # Add manifest entry pointing to non-existent file
        _add_manifest_entry(vault_root, "raw/missing.md", ContentKind.raw)

        result = run_pre_publish_gates(vault_root, block_on_errors=True)

        assert result.passed is False
        assert len(result.critical_errors) > 0

    def test_lint_errors_can_be_bypassed(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        _add_manifest_entry(vault_root, "raw/missing.md", ContentKind.raw)

        result = run_pre_publish_gates(vault_root, block_on_errors=False)

        assert result.passed is True
        # Errors are still recorded
        assert len(result.critical_errors) > 0

    def test_warnings_only_passes(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)
        # Wiki file without proper frontmatter generates a warning
        _add_file(vault_root, "wiki/no_fm.md", "# No Frontmatter\nContent.")
        _add_manifest_entry(vault_root, "wiki/no_fm.md", ContentKind.wiki)

        result = run_pre_publish_gates(vault_root)

        # Missing frontmatter is a warning, not an error
        assert result.passed is True

    def test_no_eval_without_dataset(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)

        result = run_pre_publish_gates(vault_root)

        assert result.eval_result is None

    def test_lint_failure_is_warning(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)

        with patch("docmancer.vault.gates.lint_vault", side_effect=Exception("lint crashed")):
            result = run_pre_publish_gates(vault_root)

        assert result.passed is True
        assert any("lint" in w.lower() for w in result.warnings)

    def test_empty_vault_passes(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault(tmp_path)

        result = run_pre_publish_gates(vault_root)

        assert result.passed is True
