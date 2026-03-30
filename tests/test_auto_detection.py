"""Tests for auto-detection provider routing in DocmancerAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from docmancer.agent import DocmancerAgent
from docmancer.connectors.fetchers.gitbook import GitBookFetcher
from docmancer.connectors.fetchers.mintlify import MintlifyFetcher
from docmancer.connectors.fetchers.web import WebFetcher


def _mock_http_response(html: str, headers: dict | None = None):
    resp = MagicMock()
    resp.text = html
    resp.headers = headers or {"content-type": "text/html"}
    return resp


class TestAutoDetection:
    def _get_fetcher_for_html(self, html: str, url: str = "https://example.com"):
        """Helper: run _auto_detect_provider with mocked HTML response."""
        agent = DocmancerAgent(_lazy_init=True)
        resp = _mock_http_response(html)
        mock_client = MagicMock()
        mock_client.get.return_value = resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("docmancer.agent.httpx.Client", return_value=mock_client):
            return agent._get_fetcher(provider=None, url=url)

    def test_gitbook_returns_gitbook_fetcher(self):
        html = '<html><head><meta name="generator" content="GitBook"></head><body></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, GitBookFetcher)

    def test_mintlify_returns_mintlify_fetcher(self):
        html = '<html><head><meta name="generator" content="Mintlify"></head><body></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, MintlifyFetcher)

    def test_docusaurus_returns_web_fetcher(self):
        html = '<html><head><meta name="generator" content="Docusaurus v3.0"></head><body></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, WebFetcher)

    def test_mkdocs_returns_web_fetcher(self):
        html = '<html><head><meta name="generator" content="mkdocs-1.5"></head><body></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, WebFetcher)

    def test_sphinx_returns_web_fetcher(self):
        html = '<html><head><meta name="generator" content="Sphinx 7.2"></head><body></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, WebFetcher)

    def test_generic_returns_web_fetcher(self):
        html = '<html><body><h1>Custom docs</h1></body></html>'
        fetcher = self._get_fetcher_for_html(html)
        assert isinstance(fetcher, WebFetcher)

    def test_explicit_provider_overrides_auto(self):
        agent = DocmancerAgent(_lazy_init=True)
        fetcher = agent._get_fetcher(provider="web", url="https://example.com")
        assert isinstance(fetcher, WebFetcher)

    def test_explicit_gitbook_provider(self):
        agent = DocmancerAgent(_lazy_init=True)
        fetcher = agent._get_fetcher(provider="gitbook")
        assert isinstance(fetcher, GitBookFetcher)

    def test_explicit_mintlify_provider(self):
        agent = DocmancerAgent(_lazy_init=True)
        fetcher = agent._get_fetcher(provider="mintlify")
        assert isinstance(fetcher, MintlifyFetcher)

    def test_network_error_falls_back_to_web_fetcher(self):
        """If auto-detection HTTP call fails, fall back to WebFetcher."""
        agent = DocmancerAgent(_lazy_init=True)
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("docmancer.agent.httpx.Client", return_value=mock_client):
            fetcher = agent._get_fetcher(provider=None, url="https://unreachable.com")
        assert isinstance(fetcher, WebFetcher)
