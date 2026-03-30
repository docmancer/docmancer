"""Tests for redirect pattern learning."""

from __future__ import annotations

from docmancer.connectors.fetchers.pipeline.redirect import RedirectTracker


class TestRedirectTracker:
    """Unit tests for RedirectTracker pattern learning."""

    def test_no_prediction_without_observations(self):
        tracker = RedirectTracker()
        assert tracker.predict_final_url("https://example.com/docs/v7/api/toast") is None

    def test_no_prediction_below_threshold(self):
        tracker = RedirectTracker(min_observations=3)
        tracker.record_redirect(
            "https://example.com/docs/v7/api/toast",
            "https://example.com/docs/api/toast",
        )
        tracker.record_redirect(
            "https://example.com/docs/v7/api/button",
            "https://example.com/docs/api/button",
        )
        # Only 2 observations, need 3.
        assert tracker.predict_final_url("https://example.com/docs/v7/api/card") is None

    def test_prediction_after_threshold(self):
        tracker = RedirectTracker(min_observations=3)
        tracker.record_redirect(
            "https://example.com/docs/v7/api/toast",
            "https://example.com/docs/api/toast",
        )
        tracker.record_redirect(
            "https://example.com/docs/v7/api/button",
            "https://example.com/docs/api/button",
        )
        tracker.record_redirect(
            "https://example.com/docs/v7/api/card",
            "https://example.com/docs/api/card",
        )
        predicted = tracker.predict_final_url("https://example.com/docs/v7/api/toolbar")
        assert predicted == "https://example.com/docs/api/toolbar"

    def test_prediction_nested_path(self):
        tracker = RedirectTracker(min_observations=2)
        tracker.record_redirect(
            "https://example.com/docs/v7/cli/commands/build",
            "https://example.com/docs/cli/commands/build",
        )
        tracker.record_redirect(
            "https://example.com/docs/v7/cli/commands/serve",
            "https://example.com/docs/cli/commands/serve",
        )
        predicted = tracker.predict_final_url("https://example.com/docs/v7/cli/commands/start")
        assert predicted == "https://example.com/docs/cli/commands/start"

    def test_multiple_patterns(self):
        tracker = RedirectTracker(min_observations=2)
        # Pattern 1: /v7/ -> /
        tracker.record_redirect(
            "https://example.com/docs/v7/a",
            "https://example.com/docs/a",
        )
        tracker.record_redirect(
            "https://example.com/docs/v7/b",
            "https://example.com/docs/b",
        )
        # Pattern 2: /old/ -> /new/
        tracker.record_redirect(
            "https://example.com/docs/old/x",
            "https://example.com/docs/new/x",
        )
        tracker.record_redirect(
            "https://example.com/docs/old/y",
            "https://example.com/docs/new/y",
        )

        assert tracker.predict_final_url("https://example.com/docs/v7/c") == "https://example.com/docs/c"
        assert tracker.predict_final_url("https://example.com/docs/old/z") == "https://example.com/docs/new/z"

    def test_cross_domain_redirect_ignored(self):
        tracker = RedirectTracker(min_observations=1)
        tracker.record_redirect(
            "https://old.example.com/docs/page",
            "https://new.example.com/docs/page",
        )
        assert tracker.predict_final_url("https://old.example.com/docs/other") is None

    def test_custom_threshold(self):
        tracker = RedirectTracker(min_observations=1)
        tracker.record_redirect(
            "https://example.com/docs/v7/a",
            "https://example.com/docs/a",
        )
        # Should learn after just 1 observation.
        assert tracker.predict_final_url("https://example.com/docs/v7/b") == "https://example.com/docs/b"

    def test_unmatched_url_returns_none(self):
        tracker = RedirectTracker(min_observations=1)
        tracker.record_redirect(
            "https://example.com/docs/v7/a",
            "https://example.com/docs/a",
        )
        # Different base path — should not match.
        assert tracker.predict_final_url("https://example.com/api/v7/a") is None

    def test_identical_urls_no_pattern(self):
        tracker = RedirectTracker(min_observations=1)
        # No actual redirect difference.
        tracker.record_redirect(
            "https://example.com/docs/a",
            "https://example.com/docs/a",
        )
        assert tracker.predict_final_url("https://example.com/docs/b") is None

    def test_scheme_mismatch_ignored(self):
        tracker = RedirectTracker(min_observations=1)
        tracker.record_redirect(
            "http://example.com/docs/v7/a",
            "https://example.com/docs/a",
        )
        assert tracker.predict_final_url("http://example.com/docs/v7/b") is None
