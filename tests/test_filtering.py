"""Tests for URL filtering, normalization, and content deduplication."""

from __future__ import annotations

from docmancer.connectors.fetchers.pipeline.filtering import (
    ContentDeduplicator,
    _infer_scope_path,
    infer_docset_root,
    is_docs_url,
    normalize_url,
    resolve_url,
)


# ---------------------------------------------------------------------------
# normalize_url tests
# ---------------------------------------------------------------------------

class TestNormalizeUrl:
    def test_strips_fragment(self):
        url = normalize_url("https://example.com/docs/page#section")
        assert "#" not in url

    def test_strips_trailing_slash(self):
        url = normalize_url("https://example.com/docs/page/")
        assert not url.endswith("/")

    def test_keeps_root_slash(self):
        url = normalize_url("https://example.com/")
        assert url.endswith("/")

    def test_strips_tracking_params(self):
        url = normalize_url("https://example.com/page?utm_source=twitter&valid=1")
        assert "utm_source" not in url
        assert "valid=1" in url

    def test_lowercases_scheme_and_host(self):
        url = normalize_url("HTTPS://EXAMPLE.COM/Docs/Page")
        assert url.startswith("https://example.com")

    def test_idempotent(self):
        url = "https://example.com/docs/page"
        assert normalize_url(normalize_url(url)) == normalize_url(url)

    def test_handles_no_query(self):
        url = normalize_url("https://example.com/docs")
        assert "?" not in url


class TestInferDocsetRoot:
    def test_docs_subdomain_collapses_to_host(self):
        assert infer_docset_root("https://docs.railway.com/cli/deploy") == "https://docs.railway.com"

    def test_docs_path_collapses_to_docs_root(self):
        assert infer_docset_root("https://ionicframework.com/docs/v7/api/button") == "https://ionicframework.com/docs"

    def test_llms_full_strips_suffix(self):
        assert infer_docset_root("https://docs.polymarket.com/llms-full.txt") == "https://docs.polymarket.com"

    def test_non_url_returns_none(self):
        assert infer_docset_root("./docs/intro.md") is None


# ---------------------------------------------------------------------------
# is_docs_url tests
# ---------------------------------------------------------------------------

class TestInferScopePath:
    def test_shallow_path_unchanged(self):
        assert _infer_scope_path("/docs") == "/docs"
        assert _infer_scope_path("/docs/getting-started") == "/docs/getting-started"

    def test_deep_path_with_root_hint_widens(self):
        # /docs/ai/overview -> /docs/ai (root hint "docs" + one child "ai")
        assert _infer_scope_path("/docs/ai/overview") == "/docs/ai"

    def test_deeper_path_with_root_hint(self):
        # /docs/ai/overview/install -> /docs/ai
        assert _infer_scope_path("/docs/ai/overview/install") == "/docs/ai"

    def test_reference_root_hint(self):
        assert _infer_scope_path("/reference/api/v1/users") == "/reference/api/v1"

    def test_no_root_hint_strips_leaf(self):
        # No recognized segment, so strip the leaf
        assert _infer_scope_path("/a/b/c/d") == "/a/b/c"

    def test_api_root_hint(self):
        assert _infer_scope_path("/api/v2/endpoints/auth") == "/api/v2"


class TestIsDocsUrl:
    def test_same_domain_in_scope(self):
        assert is_docs_url("https://example.com/docs/page", "https://example.com/docs")

    def test_different_domain_out_of_scope(self):
        assert not is_docs_url("https://other.com/docs", "https://example.com/docs")

    def test_parent_path_out_of_scope(self):
        assert not is_docs_url("https://example.com/blog/post", "https://example.com/docs")

    def test_blocklist_blog(self):
        assert not is_docs_url("https://example.com/blog/post", "https://example.com")

    def test_blocklist_login(self):
        assert not is_docs_url("https://example.com/login", "https://example.com")

    def test_blocklist_pricing(self):
        assert not is_docs_url("https://example.com/pricing", "https://example.com")

    def test_blocklist_file_extensions(self):
        assert not is_docs_url("https://example.com/file.pdf", "https://example.com")
        assert not is_docs_url("https://example.com/image.png", "https://example.com")

    def test_blocklist_print_pages(self):
        assert not is_docs_url("https://example.com/docs/page?print", "https://example.com/docs")

    def test_allows_valid_doc_pages(self):
        base = "https://example.com/docs"
        assert is_docs_url("https://example.com/docs/getting-started", base)
        assert is_docs_url("https://example.com/docs/api/reference", base)
        assert is_docs_url("https://example.com/docs/guides/auth/oauth", base)

    def test_deep_base_url_widens_scope(self):
        """A deep base URL like /docs/ai/overview should include sibling paths."""
        base = "https://pydantic.dev/docs/ai/overview"
        assert is_docs_url("https://pydantic.dev/docs/ai/overview/", base)
        assert is_docs_url("https://pydantic.dev/docs/ai/advanced-features/input/", base)
        assert is_docs_url("https://pydantic.dev/docs/ai/api/models/anthropic/", base)
        # Outside the /docs/ai section
        assert not is_docs_url("https://pydantic.dev/docs/concepts/models/", base)
        assert not is_docs_url("https://pydantic.dev/blog/post/", base)

    def test_root_base_allows_docs_paths(self):
        base = "https://example.com"
        assert is_docs_url("https://example.com/docs/page", base)
        assert is_docs_url("https://example.com/api/reference", base)

    def test_non_http_scheme_rejected(self):
        assert not is_docs_url("ftp://example.com/docs", "https://example.com")
        assert not is_docs_url("mailto:user@example.com", "https://example.com")

    def test_search_blocked(self):
        assert not is_docs_url("https://example.com/search?q=test", "https://example.com")


# ---------------------------------------------------------------------------
# resolve_url tests
# ---------------------------------------------------------------------------

class TestResolveUrl:
    def test_absolute_url_unchanged(self):
        assert resolve_url("https://example.com/page", "https://example.com") == "https://example.com/page"

    def test_relative_url_resolved(self):
        result = resolve_url("/docs/page", "https://example.com/docs/")
        assert result == "https://example.com/docs/page"

    def test_relative_path_resolved(self):
        result = resolve_url("page", "https://example.com/docs/")
        assert result == "https://example.com/docs/page"


# ---------------------------------------------------------------------------
# ContentDeduplicator tests
# ---------------------------------------------------------------------------

class TestContentDeduplicator:
    def test_first_content_is_not_duplicate(self):
        dedup = ContentDeduplicator()
        assert not dedup.is_content_duplicate("Hello world")

    def test_same_content_is_duplicate(self):
        dedup = ContentDeduplicator()
        dedup.is_content_duplicate("Hello world")
        assert dedup.is_content_duplicate("Hello world")

    def test_different_content_not_duplicate(self):
        dedup = ContentDeduplicator()
        dedup.is_content_duplicate("Hello world")
        assert not dedup.is_content_duplicate("Goodbye world")

    def test_whitespace_normalized(self):
        dedup = ContentDeduplicator()
        dedup.is_content_duplicate("Hello   world")
        assert dedup.is_content_duplicate("Hello world")

    def test_case_normalized(self):
        dedup = ContentDeduplicator()
        dedup.is_content_duplicate("Hello World")
        assert dedup.is_content_duplicate("hello world")

    def test_url_dedup_first_not_duplicate(self):
        dedup = ContentDeduplicator()
        assert not dedup.is_url_duplicate("https://example.com/page")

    def test_url_dedup_same_url(self):
        dedup = ContentDeduplicator()
        dedup.is_url_duplicate("https://example.com/page")
        assert dedup.is_url_duplicate("https://example.com/page")

    def test_url_dedup_with_fragment(self):
        dedup = ContentDeduplicator()
        dedup.is_url_duplicate("https://example.com/page")
        assert dedup.is_url_duplicate("https://example.com/page#section")

    def test_url_dedup_trailing_slash(self):
        dedup = ContentDeduplicator()
        dedup.is_url_duplicate("https://example.com/page")
        assert dedup.is_url_duplicate("https://example.com/page/")

    def test_reset_clears_state(self):
        dedup = ContentDeduplicator()
        dedup.is_content_duplicate("Hello")
        dedup.is_url_duplicate("https://example.com")
        dedup.reset()
        assert not dedup.is_content_duplicate("Hello")
        assert not dedup.is_url_duplicate("https://example.com")

    def test_content_hash_deterministic(self):
        h1 = ContentDeduplicator.content_hash("hello world")
        h2 = ContentDeduplicator.content_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest
