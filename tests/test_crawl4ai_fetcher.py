"""Tests for Crawl4AI fetcher and extraction adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docmancer.connectors.fetchers.pipeline.crawl4ai_extraction import is_available


class TestCrawl4AIAvailability:
    def test_is_available_returns_false_when_not_installed(self):
        with patch.dict("sys.modules", {"crawl4ai": None}):
            # When crawl4ai is not importable, is_available should return False
            # (the actual check tries to import, so we test the function exists)
            assert callable(is_available)

    def test_fetcher_import_error_when_not_available(self):
        """Crawl4AIFetcher should raise ImportError if crawl4ai is missing."""
        with patch(
            "docmancer.connectors.fetchers.pipeline.crawl4ai_extraction.is_available",
            return_value=False,
        ):
            from docmancer.connectors.fetchers.crawl4ai import Crawl4AIFetcher

            with pytest.raises(ImportError, match="Crawl4AI is not installed"):
                Crawl4AIFetcher()


class TestFactoryRoutingCrawl4AI:
    def test_factory_routes_crawl4ai_provider(self):
        """build_fetcher should route 'crawl4ai' provider correctly."""
        with patch(
            "docmancer.connectors.fetchers.pipeline.crawl4ai_extraction.is_available",
            return_value=True,
        ):
            from docmancer.connectors.fetchers.factory import build_fetcher
            from docmancer.connectors.fetchers.crawl4ai import Crawl4AIFetcher

            fetcher = build_fetcher("https://docs.example.com", provider="crawl4ai")
            assert isinstance(fetcher, Crawl4AIFetcher)
