from __future__ import annotations

from docmancer.core.html_utils import clean_html, looks_like_html


class TestCleanHtmlBlockStripping:
    def test_strips_script_content(self):
        html = '<p>Hello</p><script>var x = 1; console.log(x);</script><p>World</p>'
        result = clean_html(html)
        assert "var x" not in result
        assert "console.log" not in result
        assert "Hello" in result
        assert "World" in result

    def test_strips_style_content(self):
        html = '<p>Hello</p><style>:root { --color: red; } .foo { display: none; }</style><p>World</p>'
        result = clean_html(html)
        assert "--color" not in result
        assert "display" not in result
        assert "Hello" in result
        assert "World" in result

    def test_strips_head_content(self):
        html = '<head><title>Page Title</title><meta charset="utf-8"></head><body><p>Content</p></body>'
        result = clean_html(html)
        assert "Page Title" not in result
        assert "Content" in result

    def test_strips_nav_footer_header(self):
        html = (
            '<header>Site Header</header>'
            '<nav>Menu Item 1 | Menu Item 2</nav>'
            '<main><p>Real content here</p></main>'
            '<footer>Copyright 2024</footer>'
        )
        result = clean_html(html)
        assert "Menu Item" not in result
        assert "Copyright" not in result
        assert "Site Header" not in result
        assert "Real content here" in result

    def test_preserves_plain_markdown(self):
        md = "# Title\n\nSome paragraph text.\n\n- item 1\n- item 2\n"
        assert clean_html(md) == md

    def test_preserves_inline_html_text(self):
        html = "Some <b>bold</b> and <em>italic</em> text"
        result = clean_html(html)
        assert "bold" in result
        assert "italic" in result
        assert "<b>" not in result

    def test_strips_noscript_content(self):
        html = '<p>Hello</p><noscript><img src="track.gif"></noscript><p>World</p>'
        result = clean_html(html)
        assert "track.gif" not in result
        assert "Hello" in result

    def test_strips_multiline_style_block(self):
        html = (
            '<style>\n'
            '  :root {\n'
            '    --fds-color-primary: #1877f2;\n'
            '    --spacing-lg: 24px;\n'
            '  }\n'
            '</style>\n'
            '<p>Actual content</p>'
        )
        result = clean_html(html)
        assert "fds-color" not in result
        assert "spacing-lg" not in result
        assert "Actual content" in result


class TestLooksLikeHtml:
    def test_doctype(self):
        assert looks_like_html("<!DOCTYPE html><html><head></head><body></body></html>")

    def test_html_tag(self):
        assert looks_like_html("<html><head></head><body>Content</body></html>")

    def test_head_tag(self):
        assert looks_like_html("  \n  <head><title>Hi</title></head><body></body>")

    def test_markdown_returns_false(self):
        assert not looks_like_html("# Title\n\nSome text with **bold**.")

    def test_inline_html_returns_false(self):
        assert not looks_like_html("Some <b>bold</b> and a <table><tr><td>cell</td></tr></table>")

    def test_empty_string(self):
        assert not looks_like_html("")
