"""Tests for optional Playwright browser fallback."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from docmancer.connectors.fetchers.pipeline.browser import BrowserRenderer, _check_playwright_available


class TestBrowserAvailability:
    def test_is_available_reflects_import(self):
        result = BrowserRenderer.is_available()
        assert isinstance(result, bool)

    def test_check_playwright_returns_bool(self):
        result = _check_playwright_available()
        assert isinstance(result, bool)

    @patch("docmancer.connectors.fetchers.pipeline.browser._check_playwright_available", return_value=False)
    def test_init_raises_without_playwright(self, mock_check):
        with pytest.raises(ImportError, match="Playwright is not installed"):
            BrowserRenderer()

    @patch("docmancer.connectors.fetchers.pipeline.browser._check_playwright_available", return_value=True)
    def test_init_succeeds_with_playwright(self, mock_check):
        renderer = BrowserRenderer()
        assert renderer is not None


class TestBrowserRenderer:
    @patch("docmancer.connectors.fetchers.pipeline.browser._check_playwright_available", return_value=True)
    def test_render_calls_playwright(self, mock_check):
        """Test that render() calls playwright correctly (mocked)."""
        mock_page = MagicMock()
        mock_page.content.return_value = "<html><body>Rendered</body></html>"

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw_ctx = MagicMock()
        mock_pw_ctx.chromium = mock_chromium

        mock_sync_playwright = MagicMock()
        mock_sync_playwright.return_value.__enter__ = MagicMock(return_value=mock_pw_ctx)
        mock_sync_playwright.return_value.__exit__ = MagicMock(return_value=False)

        # Mock the playwright module's sync_api submodule
        mock_module = MagicMock()
        mock_module.sync_playwright = mock_sync_playwright
        mock_playwright = MagicMock()
        mock_playwright.sync_api = mock_module

        with patch.dict(sys.modules, {
            "playwright": mock_playwright,
            "playwright.sync_api": mock_module,
        }):
            renderer = BrowserRenderer()
            html = renderer.render("https://example.com")

        assert "Rendered" in html
        mock_page.goto.assert_called_once()
        mock_browser.close.assert_called_once()

    @patch("docmancer.connectors.fetchers.pipeline.browser._check_playwright_available", return_value=True)
    def test_render_and_extract_links(self, mock_check):
        """Test that link extraction works (mocked)."""
        mock_page = MagicMock()
        mock_page.eval_on_selector_all.return_value = [
            "https://example.com/docs/page1",
            "https://example.com/docs/page2",
        ]

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw_ctx = MagicMock()
        mock_pw_ctx.chromium = mock_chromium

        mock_sync_playwright = MagicMock()
        mock_sync_playwright.return_value.__enter__ = MagicMock(return_value=mock_pw_ctx)
        mock_sync_playwright.return_value.__exit__ = MagicMock(return_value=False)

        mock_module = MagicMock()
        mock_module.sync_playwright = mock_sync_playwright
        mock_playwright = MagicMock()
        mock_playwright.sync_api = mock_module

        with patch.dict(sys.modules, {
            "playwright": mock_playwright,
            "playwright.sync_api": mock_module,
        }):
            renderer = BrowserRenderer()
            links = renderer.render_and_extract_links("https://example.com")

        assert len(links) == 2
        assert "https://example.com/docs/page1" in links
