"""Tests for vault GitHub publishing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docmancer.vault.github import GitHubPublisher
from docmancer.vault.packaging import VaultCard


class TestGitHubPublisher:
    def test_create_release_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 123, "html_url": "https://github.com/test/repo/releases/1"}

        with patch("docmancer.vault.github.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp

            publisher = GitHubPublisher(token="test-token", repo="owner/repo")
            result = publisher.create_release("v1.0.0", "My Vault 1.0.0", "Release notes")

            assert result["id"] == 123
            mock_client.post.assert_called_once()

    def test_create_release_failure(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Already exists"

        with patch("docmancer.vault.github.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp

            publisher = GitHubPublisher(token="test-token", repo="owner/repo")
            with pytest.raises(RuntimeError, match="Failed to create release"):
                publisher.create_release("v1.0.0", "name", "body")

    def test_upload_asset_success(self, tmp_path: Path) -> None:
        # Create a test file
        test_file = tmp_path / "test.tar.gz"
        test_file.write_bytes(b"fake archive data")

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 456, "name": "test.tar.gz"}

        with patch("docmancer.vault.github.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp

            publisher = GitHubPublisher(token="test-token", repo="owner/repo")
            result = publisher.upload_release_asset(123, test_file)

            assert result["id"] == 456

    def test_upload_asset_failure(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.tar.gz"
        test_file.write_bytes(b"fake data")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server error"

        with patch("docmancer.vault.github.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp

            publisher = GitHubPublisher(token="test-token", repo="owner/repo")
            with pytest.raises(RuntimeError, match="Failed to upload"):
                publisher.upload_release_asset(123, test_file)

    def test_publish_vault_flow(self, tmp_path: Path) -> None:
        test_file = tmp_path / "vault.tar.gz"
        test_file.write_bytes(b"fake archive")

        card = VaultCard(name="my-vault", version="1.0.0", description="Test vault")

        publisher = GitHubPublisher(token="test-token", repo="owner/repo")

        with patch.object(publisher, "create_release") as mock_create, \
             patch.object(publisher, "upload_release_asset") as mock_upload:
            mock_create.return_value = {
                "id": 789,
                "html_url": "https://github.com/owner/repo/releases/v1.0.0",
            }
            mock_upload.return_value = {"id": 101}

            url = publisher.publish_vault(test_file, card)

            assert "github.com" in url
            mock_create.assert_called_once()
            mock_upload.assert_called_once_with(789, test_file)

            # Verify tag format
            call_args = mock_create.call_args
            assert call_args[0][0] == "v1.0.0"  # tag

    def test_publish_vault_draft(self, tmp_path: Path) -> None:
        test_file = tmp_path / "vault.tar.gz"
        test_file.write_bytes(b"fake archive")

        card = VaultCard(name="my-vault", version="2.0.0")

        publisher = GitHubPublisher(token="test-token", repo="owner/repo")

        with patch.object(publisher, "create_release") as mock_create, \
             patch.object(publisher, "upload_release_asset"):
            mock_create.return_value = {"id": 1, "html_url": "url"}

            publisher.publish_vault(test_file, card, draft=True)

            call_args = mock_create.call_args
            assert call_args[1]["draft"] is True or call_args[0][3] is True
