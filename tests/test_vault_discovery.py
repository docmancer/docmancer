"""Tests for vault discovery via GitHub."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docmancer.vault.discovery import VaultDiscovery, VaultListEntry
from docmancer.vault.packaging import VaultCard


class TestVaultListEntry:
    def test_defaults(self) -> None:
        entry = VaultListEntry(name="test")
        assert entry.name == "test"
        assert entry.description == ""
        assert entry.stars == 0

    def test_full_entry(self) -> None:
        entry = VaultListEntry(
            name="react-docs",
            description="React documentation vault",
            version="1.0.0",
            repository="docmancer/vault-react",
            stars=42,
        )
        assert entry.repository == "docmancer/vault-react"
        assert entry.stars == 42


class TestVaultDiscovery:
    def test_search_returns_entries(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "name": "vault-react",
                    "description": "React docs vault",
                    "full_name": "docmancer/vault-react",
                    "stargazers_count": 10,
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                {
                    "name": "vault-nextjs",
                    "description": "Next.js docs",
                    "full_name": "docmancer/vault-nextjs",
                    "stargazers_count": 5,
                    "updated_at": "2024-02-01T00:00:00Z",
                },
            ],
        }

        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp

            discovery = VaultDiscovery(token="test")
            results = discovery.search("react")

            assert len(results) == 2
            assert results[0].name == "vault-react"
            assert results[0].stars == 10

    def test_search_empty_results(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}

        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp

            discovery = VaultDiscovery(token="test")
            results = discovery.search()

            assert results == []

    def test_search_api_error_returns_empty(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp

            discovery = VaultDiscovery()
            results = discovery.search("test")

            assert results == []

    def test_search_exception_returns_empty(self) -> None:
        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            MockClient.side_effect = Exception("network error")

            discovery = VaultDiscovery()
            results = discovery.search("test")

            assert results == []

    def test_get_details_success(self) -> None:
        card_data = VaultCard(
            name="vault-react", version="1.0.0", description="React docs",
        ).model_dump()

        contents_resp = MagicMock()
        contents_resp.status_code = 200
        contents_resp.json.return_value = {
            "download_url": "https://raw.githubusercontent.com/docmancer/vault-react/main/vault-card.json",
        }

        card_resp = MagicMock()
        card_resp.status_code = 200
        card_resp.json.return_value = card_data

        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = [contents_resp, card_resp]

            discovery = VaultDiscovery(token="test")
            card = discovery.get_details("docmancer/vault-react")

            assert card is not None
            assert card.name == "vault-react"

    def test_get_details_not_found(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("docmancer.vault.discovery.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp

            discovery = VaultDiscovery()
            card = discovery.get_details("nonexistent/repo")

            assert card is None
