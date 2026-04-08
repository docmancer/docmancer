"""Tests for vault installer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docmancer.vault.installer import (
    VaultInstaller,
    fetch_release_info,
)
from docmancer.vault.operations import init_vault
from docmancer.vault.packaging import package_vault
from docmancer.vault.manifest import (
    ContentKind,
    ManifestEntry,
    SourceType,
    VaultManifest,
)


def _scaffold_and_package(tmp_path: Path) -> Path:
    """Create a vault, add content, and package it. Returns archive path."""
    vault_root = tmp_path / "source-vault"
    init_vault(vault_root)

    # Add some content
    raw_file = vault_root / "raw" / "doc.md"
    raw_file.write_text("# Test Doc\nSome content.", encoding="utf-8")
    wiki_file = vault_root / "wiki" / "article.md"
    wiki_file.write_text(
        "---\ntitle: Test Article\ntags: [test]\nsources: []\n"
        "created: '2024-01-01'\nupdated: '2024-01-01'\n---\n# Article",
        encoding="utf-8",
    )

    # Add manifest entries
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    manifest.add(ManifestEntry(
        path="raw/doc.md", kind=ContentKind.raw, source_type=SourceType.markdown,
    ))
    manifest.add(ManifestEntry(
        path="wiki/article.md", kind=ContentKind.wiki, source_type=SourceType.markdown,
    ))
    manifest.save()

    output_dir = tmp_path / "dist"
    return package_vault(vault_root, output_dir, include_raw=True)


class TestVaultInstaller:
    def test_install_local(self, tmp_path: Path) -> None:
        archive = _scaffold_and_package(tmp_path)
        install_dir = tmp_path / "installed"

        installer = VaultInstaller(install_dir=install_dir)
        vault_root = installer.install_local(archive, name="my-vault")

        assert vault_root.exists()
        assert (vault_root / "raw" / "doc.md").exists()
        assert (vault_root / "wiki" / "article.md").exists()

    def test_install_local_registers_vault(self, tmp_path: Path) -> None:
        archive = _scaffold_and_package(tmp_path)
        install_dir = tmp_path / "installed"

        installer = VaultInstaller(install_dir=install_dir)

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_instance = MagicMock()
            MockRegistry.return_value = mock_instance

            installer.install_local(archive, name="my-vault")

            mock_instance.register_installed.assert_called_once()
            call_kwargs = mock_instance.register_installed.call_args
            assert call_kwargs[1]["name"] == "my-vault" or call_kwargs[0][0] == "my-vault"

    def test_install_local_reindexes_packaged_content(self, tmp_path: Path) -> None:
        archive = _scaffold_and_package(tmp_path)
        install_dir = tmp_path / "installed"

        installer = VaultInstaller(install_dir=install_dir)

        with patch("docmancer.vault.operations.sync_vault_index") as mock_sync:
            installer.install_local(archive, name="my-vault")

        added_paths = mock_sync.call_args.kwargs["added_paths"]
        assert "raw/doc.md" in added_paths
        assert "wiki/article.md" in added_paths

    def test_uninstall_removes_directory(self, tmp_path: Path) -> None:
        archive = _scaffold_and_package(tmp_path)
        install_dir = tmp_path / "installed"

        installer = VaultInstaller(install_dir=install_dir)

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_instance = MagicMock()
            MockRegistry.return_value = mock_instance

            vault_root = installer.install_local(archive, name="my-vault")
            assert vault_root.exists()

            result = installer.uninstall("my-vault")
            assert result is True
            assert not vault_root.exists()
            mock_instance.unregister.assert_called_with("my-vault")

    def test_uninstall_nonexistent(self, tmp_path: Path) -> None:
        install_dir = tmp_path / "installed"
        installer = VaultInstaller(install_dir=install_dir)

        with patch("docmancer.vault.registry.VaultRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.unregister.return_value = False
            MockRegistry.return_value = mock_instance

            result = installer.uninstall("nonexistent")
            assert result is False

    def test_install_local_missing_file(self, tmp_path: Path) -> None:
        installer = VaultInstaller(install_dir=tmp_path / "installed")
        with pytest.raises(FileNotFoundError):
            installer.install_local(Path("/nonexistent/file.tar.gz"))

    def test_install_requires_repo(self, tmp_path: Path) -> None:
        installer = VaultInstaller(install_dir=tmp_path / "installed")
        with pytest.raises(ValueError, match="Cannot resolve"):
            installer.install("some-vault")

    def test_install_from_owner_repo_name(self, tmp_path: Path) -> None:
        """When name contains '/', it should be treated as owner/repo."""
        installer = VaultInstaller(install_dir=tmp_path / "installed")

        with patch("docmancer.vault.installer.fetch_release_info") as mock_fetch:
            mock_fetch.return_value = None
            with pytest.raises(RuntimeError, match="No release found"):
                installer.install("owner/my-vault")

            # Verify it called fetch with the right repo
            mock_fetch.assert_called_once_with("owner/my-vault", version=None, token=None)


class TestFetchReleaseInfo:
    def test_returns_none_on_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("docmancer.vault.installer.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response

            result = fetch_release_info("owner/repo")
            assert result is None

    def test_returns_release_on_200(self) -> None:
        release_data = {"tag_name": "v1.0.0", "assets": []}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = release_data

        with patch("docmancer.vault.installer.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response

            result = fetch_release_info("owner/repo")
            assert result == release_data

    def test_version_adds_v_prefix(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("docmancer.vault.installer.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response

            fetch_release_info("owner/repo", version="1.0.0")
            mock_client.get.assert_called_once_with("/repos/owner/repo/releases/tags/v1.0.0")
