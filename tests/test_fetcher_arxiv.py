from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from docmancer.connectors.fetchers.arxiv import ArxivFetcher

SAMPLE_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <title>Test Paper Title</title>
    <summary>This is the abstract of the test paper.</summary>
    <author><name>John Doe</name></author>
    <author><name>Jane Smith</name></author>
    <published>2023-01-01T00:00:00Z</published>
    <updated>2023-01-02T00:00:00Z</updated>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2301.00001" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2301.00001" rel="related" type="application/pdf" title="pdf"/>
    <id>http://arxiv.org/abs/2301.00001</id>
  </entry>
</feed>
"""

EMPTY_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
</feed>
"""


def _make_mock_client(response: MagicMock) -> MagicMock:
    mock_client = MagicMock()
    mock_client.get.return_value = response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def _make_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


class TestExtractPaperId:
    def test_extract_paper_id_from_abs_url(self):
        assert ArxivFetcher._extract_paper_id("https://arxiv.org/abs/2301.00001") == "2301.00001"

    def test_extract_paper_id_from_pdf_url(self):
        assert ArxivFetcher._extract_paper_id("https://arxiv.org/pdf/2301.00001") == "2301.00001"

    def test_extract_paper_id_from_pdf_url_with_extension(self):
        assert ArxivFetcher._extract_paper_id("https://arxiv.org/pdf/2301.00001.pdf") == "2301.00001"

    def test_extract_paper_id_with_version(self):
        assert ArxivFetcher._extract_paper_id("https://arxiv.org/abs/2301.00001v2") == "2301.00001"

    def test_extract_paper_id_bare(self):
        assert ArxivFetcher._extract_paper_id("2301.00001") == "2301.00001"

    def test_extract_paper_id_old_style(self):
        assert ArxivFetcher._extract_paper_id("hep-ph/0601001") == "hep-ph/0601001"


class TestFetch:
    def test_fetch_returns_document_with_metadata(self):
        mock_response = _make_response(200, SAMPLE_ATOM_XML)
        mock_client = _make_mock_client(mock_response)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = ArxivFetcher()
            docs = fetcher.fetch("2301.00001")

        assert len(docs) == 1
        doc = docs[0]

        # Verify content includes key fields.
        assert "Test Paper Title" in doc.content
        assert "John Doe" in doc.content
        assert "Jane Smith" in doc.content
        assert "This is the abstract of the test paper." in doc.content

        # Verify metadata fields.
        assert doc.metadata["paper_id"] == "2301.00001"
        assert doc.metadata["authors"] == ["John Doe", "Jane Smith"]
        assert doc.metadata["categories"] == ["cs.AI", "cs.LG"]
        assert doc.metadata["format"] == "markdown"

    def test_fetch_no_results_raises(self):
        mock_response = _make_response(200, EMPTY_ATOM_XML)
        mock_client = _make_mock_client(mock_response)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = ArxivFetcher()
            with pytest.raises(ValueError):
                fetcher.fetch("2301.00001")
