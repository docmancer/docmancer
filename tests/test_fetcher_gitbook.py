from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from docmancer.connectors.fetchers.gitbook import GitBookFetcher


def _make_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class TestGitBookFetcherLlmsFullTxt:
    def test_fetch_llms_full_txt_success(self):
        """llms-full.txt returns 200 with content — single Document returned."""
        content = "# Welcome\n\nThis is the full docs."
        mock_client = MagicMock()
        mock_client.get.return_value = _make_response(200, content)
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitBookFetcher()
            docs = fetcher.fetch("https://docs.example.com")

        assert len(docs) == 1
        assert docs[0].source == "https://docs.example.com/llms-full.txt"
        assert docs[0].content == content
        assert docs[0].metadata["fetch_method"] == "llms-full.txt"
        assert docs[0].metadata["format"] == "markdown"


class TestGitBookFetcherLlmsTxt:
    def test_fetch_falls_back_to_llms_txt(self):
        """llms-full.txt returns 404, llms.txt returns bare URLs — 2 Documents."""
        index_content = (
            "https://docs.example.com/page1\n"
            "https://docs.example.com/page2\n"
        )
        page_content = "# Page content"

        responses = {
            "https://docs.example.com/llms-full.txt": _make_response(404),
            "https://docs.example.com/llms.txt": _make_response(200, index_content),
            "https://docs.example.com/page1": _make_response(200, page_content),
            "https://docs.example.com/page2": _make_response(200, page_content),
        }

        mock_client = MagicMock()
        mock_client.get.side_effect = lambda url: responses[url]
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitBookFetcher()
            docs = fetcher.fetch("https://docs.example.com")

        assert len(docs) == 2
        sources = {d.source for d in docs}
        assert "https://docs.example.com/page1" in sources
        assert "https://docs.example.com/page2" in sources
        for doc in docs:
            assert doc.metadata["fetch_method"] == "llms.txt"

    def test_fetch_llms_txt_markdown_links(self):
        """llms.txt with markdown link format — 2 URLs parsed and fetched."""
        index_content = (
            "[Intro](https://docs.example.com/intro)\n"
            "[Guide](https://docs.example.com/guide)\n"
        )
        page_content = "# Content"

        responses = {
            "https://docs.example.com/llms-full.txt": _make_response(404),
            "https://docs.example.com/llms.txt": _make_response(200, index_content),
            "https://docs.example.com/intro": _make_response(200, page_content),
            "https://docs.example.com/guide": _make_response(200, page_content),
        }

        mock_client = MagicMock()
        mock_client.get.side_effect = lambda url: responses[url]
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitBookFetcher()
            docs = fetcher.fetch("https://docs.example.com")

        assert len(docs) == 2
        sources = {d.source for d in docs}
        assert "https://docs.example.com/intro" in sources
        assert "https://docs.example.com/guide" in sources


class TestGitBookFetcherFailure:
    def test_fetch_raises_on_failure(self):
        """Both llms-full.txt and llms.txt return 404 — ValueError raised."""
        mock_client = MagicMock()
        mock_client.get.return_value = _make_response(404)
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitBookFetcher()
            with pytest.raises(ValueError, match="Could not fetch docs from"):
                fetcher.fetch("https://docs.example.com")

    def test_fetch_raises_on_network_error(self):
        """Network errors should be converted to ValueError."""
        import httpx
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client_cls.return_value.__exit__.return_value = False
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")

            fetcher = GitBookFetcher()
            with pytest.raises(ValueError) as ctx:
                fetcher.fetch("https://docs.example.com")
            assert "Network error" in str(ctx.value)


class TestParseLlmsTxt:
    def test_parse_llms_txt_bare_urls(self):
        """_parse_llms_txt handles bare URLs, markdown links, comments, blank lines."""
        content = (
            "# This is a comment\n"
            "\n"
            "https://docs.example.com/page1\n"
            "  \n"
            "[Title](https://docs.example.com/page2)\n"
            "# Another comment\n"
            "https://docs.example.com/page3  trailing text\n"
        )
        urls = GitBookFetcher._parse_llms_txt(content)

        assert urls == [
            "https://docs.example.com/page1",
            "https://docs.example.com/page2",
            "https://docs.example.com/page3",
        ]

    def test_parse_llms_txt_empty(self):
        """Empty content returns empty list."""
        assert GitBookFetcher._parse_llms_txt("") == []

    def test_parse_llms_txt_comments_only(self):
        """Content with only comments and blank lines returns empty list."""
        content = "# heading\n\n# another heading\n"
        assert GitBookFetcher._parse_llms_txt(content) == []

    def test_parse_llms_txt_http_url(self):
        """http:// bare URLs are included."""
        content = "http://docs.example.com/page\n"
        urls = GitBookFetcher._parse_llms_txt(content)
        assert urls == ["http://docs.example.com/page"]
