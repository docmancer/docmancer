from __future__ import annotations

from urllib.parse import urlparse


def detect_fetcher_provider(url: str, provider: str | None = None) -> str:
    """Return the concrete fetcher provider for a URL."""
    if provider and provider != "auto":
        return provider.lower()

    parsed = urlparse(url)
    if parsed.netloc.lower() == "github.com":
        return "github"

    return "web"


def build_fetcher(
    url: str,
    provider: str | None = None,
    *,
    timeout: float = 30.0,
    max_pages: int = 500,
    strategy: str | None = None,
    browser: bool = False,
    respect_robots: bool = True,
    delay: float = 0.5,
    workers: int = 8,
):
    """Build the fetcher shared by the CLI and registry pipeline."""
    concrete = detect_fetcher_provider(url, provider)

    if concrete == "gitbook":
        from docmancer.connectors.fetchers.gitbook import GitBookFetcher

        return GitBookFetcher()
    if concrete == "mintlify":
        from docmancer.connectors.fetchers.mintlify import MintlifyFetcher

        return MintlifyFetcher()
    if concrete == "github":
        from docmancer.connectors.fetchers.github import GitHubFetcher

        return GitHubFetcher(timeout=timeout)

    if concrete == "crawl4ai":
        from docmancer.connectors.fetchers.crawl4ai import Crawl4AIFetcher

        return Crawl4AIFetcher(
            timeout=timeout,
            max_pages=max_pages,
            respect_robots=respect_robots,
            delay=delay,
            workers=workers,
        )

    from docmancer.connectors.fetchers.web import WebFetcher

    return WebFetcher(
        timeout=timeout,
        max_pages=max_pages,
        strategy=strategy,
        browser=browser,
        respect_robots=respect_robots,
        delay=delay,
        workers=workers,
    )
