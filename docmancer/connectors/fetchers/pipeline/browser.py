"""Optional Playwright-based browser rendering for JS-heavy sites.

This module is only loaded when the user has installed the [browser] extra:
    pip install docmancer[browser]

If Playwright is not installed, BrowserRenderer.is_available() returns False
and render() raises ImportError with a helpful message.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _check_playwright_available() -> bool:
    """Check if playwright is importable."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserRenderer:
    """Renders JavaScript-heavy pages using a headless Chromium browser.

    Requires the [browser] extra: ``pip install docmancer[browser]``
    and browser binaries: ``playwright install chromium``
    """

    def __init__(self) -> None:
        if not _check_playwright_available():
            raise ImportError(
                "Playwright is not installed. Install it with:\n"
                "  pip install docmancer[browser]\n"
                "  playwright install chromium"
            )

    @staticmethod
    def is_available() -> bool:
        """Check if the browser renderer can be used."""
        return _check_playwright_available()

    def render(self, url: str, timeout: int = 30000) -> str:
        """Render a page with headless Chromium and return the full HTML.

        Args:
            url: The URL to render.
            timeout: Navigation timeout in milliseconds.

        Returns:
            The rendered HTML content.

        Raises:
            ImportError: If Playwright is not installed.
            RuntimeError: If browser rendering fails.
        """
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=timeout, wait_until="networkidle")
                    html = page.content()
                    return html
                finally:
                    browser.close()
        except Exception as exc:
            raise RuntimeError(f"Browser rendering failed for {url}: {exc}") from exc

    def render_and_extract_links(self, url: str, timeout: int = 30000) -> list[str]:
        """Render a page and extract all navigation link hrefs.

        Args:
            url: The URL to render.
            timeout: Navigation timeout in milliseconds.

        Returns:
            List of absolute link URLs found in nav elements.
        """
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=timeout, wait_until="networkidle")
                    links = page.eval_on_selector_all(
                        "nav a[href], .sidebar a[href], [role='navigation'] a[href]",
                        """elements => elements.map(el => {
                            const href = el.getAttribute('href');
                            if (href && href.startsWith('/')) {
                                return new URL(href, window.location.origin).href;
                            }
                            return href;
                        }).filter(Boolean)"""
                    )
                    return links
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning("Browser link extraction failed for %s: %s", url, exc)
            return []
