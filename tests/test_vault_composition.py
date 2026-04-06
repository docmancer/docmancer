"""Tests for vault composition and dependency resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from docmancer.vault.composition import (
    install_with_dependencies,
    list_dependencies,
    resolve_dependencies,
)
from docmancer.vault.operations import init_vault


def _scaffold_vault_with_deps(tmp_path: Path, name: str, deps: list[dict]) -> Path:
    vault_root = tmp_path / name
    init_vault(vault_root)
    config_path = vault_root / "docmancer.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    if "vault" not in config:
        config["vault"] = {}
    config["vault"]["dependencies"] = deps
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    return vault_root


class TestListDependencies:
    def test_no_dependencies(self, tmp_path: Path) -> None:
        vault_root = tmp_path / "empty-vault"
        init_vault(vault_root)

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            MockRegistry.return_value = MagicMock()
            deps = list_dependencies(vault_root)

        assert deps == []

    def test_with_dependencies(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault_with_deps(tmp_path, "my-vault", [
            {"name": "react-docs", "version": ">=1.0.0", "repository": "docmancer/vault-react"},
            {"name": "typescript-docs"},
        ])

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.get_vault.side_effect = lambda name: (
                {"name": name} if name == "react-docs" else None
            )
            MockRegistry.return_value = mock_registry

            deps = list_dependencies(vault_root)

        assert len(deps) == 2
        assert deps[0]["name"] == "react-docs"
        assert deps[0]["installed"] is True
        assert deps[1]["name"] == "typescript-docs"
        assert deps[1]["installed"] is False

    def test_no_config_file(self, tmp_path: Path) -> None:
        deps = list_dependencies(tmp_path / "nonexistent")
        assert deps == []


class TestResolveDependencies:
    def test_all_already_installed(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault_with_deps(tmp_path, "my-vault", [
            {"name": "dep-a"},
            {"name": "dep-b"},
        ])

        mock_installer = MagicMock()

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.get_vault.return_value = {"name": "exists"}
            MockRegistry.return_value = mock_registry

            result = resolve_dependencies(vault_root, mock_installer)

        assert len(result) == 2
        mock_installer.install.assert_not_called()

    def test_installs_missing(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault_with_deps(tmp_path, "my-vault", [
            {"name": "dep-a", "repository": "owner/dep-a"},
        ])

        mock_installer = MagicMock()

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.get_vault.return_value = None
            MockRegistry.return_value = mock_registry

            result = resolve_dependencies(vault_root, mock_installer)

        assert "dep-a" in result
        mock_installer.install.assert_called_once()

    def test_skips_failed_install(self, tmp_path: Path) -> None:
        vault_root = _scaffold_vault_with_deps(tmp_path, "my-vault", [
            {"name": "will-fail", "repository": "owner/fail"},
        ])

        mock_installer = MagicMock()
        mock_installer.install.side_effect = RuntimeError("install failed")

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.get_vault.return_value = None
            MockRegistry.return_value = mock_registry

            result = resolve_dependencies(vault_root, mock_installer)

        assert result == []


class TestInstallWithDependencies:
    def test_circular_dependency_detected(self, tmp_path: Path) -> None:
        mock_installer = MagicMock()

        with pytest.raises(ValueError, match="Circular dependency"):
            install_with_dependencies(
                "vault-a", mock_installer, repo="owner/a",
                _visited={"vault-a"},
            )

    def test_max_depth_respected(self, tmp_path: Path) -> None:
        mock_installer = MagicMock()
        mock_installer.install.return_value = tmp_path

        with patch("docmancer.vault.composition._load_vault_dependencies", return_value=[]):
            result = install_with_dependencies(
                "deep-vault", mock_installer, repo="owner/deep",
                max_depth=3, _depth=4,
            )

        assert result == []
        mock_installer.install.assert_not_called()

    def test_installs_vault_and_deps(self, tmp_path: Path) -> None:
        """Root vault with one dependency."""
        root_dir = tmp_path / "root"
        dep_dir = tmp_path / "dep"
        root_dir.mkdir()
        dep_dir.mkdir()

        call_count = 0

        def mock_install(name, **kwargs):
            nonlocal call_count
            call_count += 1
            if name == "root-vault":
                return root_dir
            return dep_dir

        mock_installer = MagicMock()
        mock_installer.install.side_effect = mock_install
        mock_installer._reindex = MagicMock()

        def mock_deps(vault_root):
            if vault_root == root_dir:
                return [{"name": "dep-vault", "repository": "owner/dep"}]
            return []

        with patch("docmancer.vault.composition._load_vault_dependencies", side_effect=mock_deps):
            result = install_with_dependencies(
                "root-vault", mock_installer, repo="owner/root",
            )

        assert "root-vault" in result
        assert "dep-vault" in result
        assert call_count == 2
