from __future__ import annotations

from docmancer.connectors.fetchers.llms_txt import LlmsTxtFetcher


class GitBookFetcher(LlmsTxtFetcher):
    """Fetches documentation from a GitBook site using its AI-native endpoints."""
