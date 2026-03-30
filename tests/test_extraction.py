"""Tests for the content extraction pipeline."""

from __future__ import annotations

from docmancer.connectors.fetchers.pipeline.extraction import (
    DocsMarkdownConverter,
    extract_content,
    extract_metadata,
    extract_section_path,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SIMPLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Getting Started</title>
<meta name="description" content="Learn how to get started">
<link rel="canonical" href="https://example.com/docs/getting-started">
</head>
<body>
<nav><a href="/">Home</a><a href="/docs">Docs</a></nav>
<main>
<h1>Getting Started</h1>
<p>Welcome to the documentation. This guide will help you get started
with our platform quickly and easily.</p>
<h2>Installation</h2>
<p>Install using pip:</p>
<pre><code class="language-bash">pip install example-lib</code></pre>
<h2>Quick Start</h2>
<p>Here is a quick example:</p>
<pre><code class="language-python">from example import Client
client = Client()
result = client.run()
print(result)</code></pre>
</main>
<footer>Copyright 2024</footer>
</body>
</html>
"""

HTML_WITH_ADMONITIONS = """
<html><body>
<main>
<h1>Configuration</h1>
<p>Configure the following settings.</p>
<div class="warning">
<p>Do not use this in production without proper testing.</p>
</div>
<div class="note">
<p>This feature requires version 2.0 or later.</p>
</div>
<div class="tip">
<p>Use environment variables for sensitive values.</p>
</div>
</main>
</body></html>
"""

HTML_WITH_TABLE = """
<html><body>
<main>
<h1>API Reference</h1>
<p>The following endpoints are available:</p>
<table>
<tr><th>Method</th><th>Path</th><th>Description</th></tr>
<tr><td>GET</td><td>/users</td><td>List all users</td></tr>
<tr><td>POST</td><td>/users</td><td>Create a user</td></tr>
</table>
</main>
</body></html>
"""

HTML_WITH_NOISE = """
<html><body>
<nav class="sidebar">
<a href="/page1">Page 1</a>
<a href="/page2">Page 2</a>
</nav>
<main>
<h1>Real Content</h1>
<p>This is the actual documentation content that should be preserved
in the extraction output. It contains useful information.</p>
</main>
<footer><p>Built with DocsFramework</p></footer>
<script>console.log("tracking")</script>
</body></html>
"""

HTML_WITH_BREADCRUMBS = """
<html><body>
<nav aria-label="breadcrumb">
<a href="/docs">Docs</a>
<span>›</span>
<a href="/docs/guides">Guides</a>
<span>›</span>
<a href="/docs/guides/auth">Authentication</a>
</nav>
<main><h1>Authentication</h1><p>Content here.</p></main>
</body></html>
"""

EMPTY_HTML = """
<html><body></body></html>
"""

PLAIN_MARKDOWN = """# Hello World

This is already markdown content, not HTML.

```python
print("hello")
```
"""


# ---------------------------------------------------------------------------
# extract_content tests
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_simple_html_extraction(self):
        result = extract_content(SIMPLE_HTML, url="https://example.com/docs/getting-started")
        assert "Getting Started" in result
        assert "Installation" in result or "pip install" in result
        # Should not include nav or footer
        assert "Copyright 2024" not in result

    def test_extracts_code_blocks(self):
        result = extract_content(SIMPLE_HTML)
        assert "pip install example-lib" in result

    def test_noise_stripped(self):
        result = extract_content(HTML_WITH_NOISE)
        assert "Real Content" in result
        assert "actual documentation content" in result
        # Nav, footer, script should be stripped
        assert "Page 1" not in result
        assert "Built with DocsFramework" not in result
        assert "tracking" not in result

    def test_table_preserved(self):
        result = extract_content(HTML_WITH_TABLE)
        assert "API Reference" in result
        # Table content should appear in some form
        assert "GET" in result
        assert "/users" in result

    def test_empty_html(self):
        result = extract_content(EMPTY_HTML)
        assert result == "" or len(result.strip()) == 0

    def test_empty_string(self):
        result = extract_content("")
        assert result == ""

    def test_none_safe(self):
        result = extract_content("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# extract_metadata tests
# ---------------------------------------------------------------------------

class TestExtractMetadata:
    def test_extracts_title(self):
        meta = extract_metadata(SIMPLE_HTML)
        assert meta["title"] == "Getting Started"

    def test_extracts_description(self):
        meta = extract_metadata(SIMPLE_HTML)
        assert meta["description"] == "Learn how to get started"

    def test_extracts_lang(self):
        meta = extract_metadata(SIMPLE_HTML)
        assert meta["lang"] == "en"

    def test_extracts_canonical(self):
        meta = extract_metadata(SIMPLE_HTML)
        assert meta["canonical_url"] == "https://example.com/docs/getting-started"

    def test_missing_metadata(self):
        meta = extract_metadata("<html><body><p>No meta</p></body></html>")
        assert meta["title"] is None or meta["title"] == ""
        assert meta["description"] is None
        assert meta["lang"] is None
        assert meta["canonical_url"] is None

    def test_h1_fallback_for_title(self):
        html = "<html><body><h1>My Page</h1><p>Content</p></body></html>"
        meta = extract_metadata(html)
        assert meta["title"] == "My Page"


# ---------------------------------------------------------------------------
# extract_section_path tests
# ---------------------------------------------------------------------------

class TestExtractSectionPath:
    def test_breadcrumb_extraction(self):
        path = extract_section_path(HTML_WITH_BREADCRUMBS)
        assert "Docs" in path
        assert "Guides" in path
        assert "Authentication" in path

    def test_no_breadcrumbs(self):
        path = extract_section_path(SIMPLE_HTML)
        assert path == []

    def test_empty_html(self):
        path = extract_section_path("")
        assert path == []


# ---------------------------------------------------------------------------
# DocsMarkdownConverter tests
# ---------------------------------------------------------------------------

class TestDocsMarkdownConverter:
    def test_code_block_language_extraction(self):
        from bs4 import BeautifulSoup
        html = '<pre><code class="language-python">print("hello")</code></pre>'
        soup = BeautifulSoup(html, "html.parser")
        converter = DocsMarkdownConverter()
        result = converter.convert_soup(soup)
        assert "```python" in result
        assert 'print("hello")' in result

    def test_warning_admonition(self):
        from bs4 import BeautifulSoup
        html = '<div class="warning"><p>Watch out!</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        converter = DocsMarkdownConverter()
        result = converter.convert_soup(soup)
        assert "Warning" in result
        assert "Watch out!" in result

    def test_note_admonition(self):
        from bs4 import BeautifulSoup
        html = '<div class="note"><p>Remember this.</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        converter = DocsMarkdownConverter()
        result = converter.convert_soup(soup)
        assert "Note" in result
        assert "Remember this." in result

    def test_nav_stripped(self):
        from bs4 import BeautifulSoup
        html = '<nav><a href="/">Home</a></nav><p>Content</p>'
        soup = BeautifulSoup(html, "html.parser")
        converter = DocsMarkdownConverter()
        result = converter.convert_soup(soup)
        assert "Home" not in result
        assert "Content" in result

    def test_footer_stripped(self):
        from bs4 import BeautifulSoup
        html = '<p>Content</p><footer>Copyright 2024</footer>'
        soup = BeautifulSoup(html, "html.parser")
        converter = DocsMarkdownConverter()
        result = converter.convert_soup(soup)
        assert "Copyright" not in result
        assert "Content" in result
