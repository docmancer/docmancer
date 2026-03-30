"""Tests for platform detection."""

from __future__ import annotations

from docmancer.connectors.fetchers.pipeline.detection import Platform, detect_platform


class TestDetectPlatform:
    def test_gitbook_via_generator(self):
        html = '<html><head><meta name="generator" content="GitBook"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.GITBOOK

    def test_gitbook_via_domain(self):
        html = "<html><body></body></html>"
        assert detect_platform(html, "https://myproject.gitbook.io/docs") == Platform.GITBOOK

    def test_gitbook_via_css_class(self):
        html = '<html><body><div class="gitbook-root">content</div></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.GITBOOK

    def test_mintlify_via_generator(self):
        html = '<html><head><meta name="generator" content="Mintlify"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.MINTLIFY

    def test_mintlify_via_domain(self):
        html = "<html><body></body></html>"
        assert detect_platform(html, "https://docs.example.mintlify.app") == Platform.MINTLIFY

    def test_mintlify_via_body_signal(self):
        html = '<html><body><script src="/mintlify-bundle.js"></script></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.MINTLIFY

    def test_docusaurus_via_generator(self):
        html = '<html><head><meta name="generator" content="Docusaurus v3.1"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.DOCUSAURUS

    def test_docusaurus_via_body_signal(self):
        html = '<html><body><script>var __docusaurus = {};</script></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.DOCUSAURUS

    def test_docusaurus_via_assets_path(self):
        html = '<html><body><link href="/_docusaurus/styles.css"></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.DOCUSAURUS

    def test_mkdocs_via_generator(self):
        html = '<html><head><meta name="generator" content="mkdocs-1.5"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.MKDOCS

    def test_mkdocs_via_css_classes(self):
        html = '<html><body><div class="md-content"><div class="md-typeset">text</div></div></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.MKDOCS

    def test_sphinx_via_generator(self):
        html = '<html><head><meta name="generator" content="Sphinx 7.2.6"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.SPHINX

    def test_sphinx_via_body_signal(self):
        html = '<html><body><div class="rst-content">text</div></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.SPHINX

    def test_readthedocs_via_header(self):
        html = "<html><body></body></html>"
        headers = {"X-RTD-Project": "myproject"}
        assert detect_platform(html, "https://myproject.readthedocs.io", headers) == Platform.READTHEDOCS

    def test_readthedocs_via_domain(self):
        html = "<html><body></body></html>"
        assert detect_platform(html, "https://myproject.readthedocs.io/en/latest") == Platform.READTHEDOCS

    def test_vitepress_via_generator(self):
        html = '<html><head><meta name="generator" content="VitePress"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.VITEPRESS

    def test_vitepress_via_body_signal(self):
        html = '<html><body><div id="VPContent" class="vp-doc">text</div></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.VITEPRESS

    def test_readme_io_via_header(self):
        html = "<html><body></body></html>"
        headers = {"x-readme-version": "3.0"}
        assert detect_platform(html, "https://docs.example.com", headers) == Platform.README_IO

    def test_readme_io_via_domain(self):
        html = "<html><body></body></html>"
        assert detect_platform(html, "https://docs.example.readme.io") == Platform.README_IO

    def test_readme_io_via_body_signal(self):
        html = '<html><body><div class="rm-Sidebar">nav</div></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.README_IO

    def test_nextjs_via_next_data(self):
        html = '<html><body><script id="__NEXT_DATA__">{}</script></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.NEXTJS

    def test_nextjs_via_next_assets(self):
        html = '<html><body><link href="/_next/static/chunks/main.js"></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.NEXTJS

    def test_generic_fallback(self):
        html = "<html><body><h1>Custom docs</h1><p>Content</p></body></html>"
        assert detect_platform(html, "https://docs.example.com") == Platform.GENERIC

    def test_empty_html(self):
        assert detect_platform("", "https://docs.example.com") == Platform.GENERIC

    def test_none_headers(self):
        html = '<html><head><meta name="generator" content="Docusaurus"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com", None) == Platform.DOCUSAURUS

    def test_generator_reversed_attributes(self):
        html = '<html><head><meta content="Sphinx 7.0" name="generator"></head><body></body></html>'
        assert detect_platform(html, "https://docs.example.com") == Platform.SPHINX
