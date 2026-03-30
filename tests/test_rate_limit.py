"""Tests for rate limiter."""

from __future__ import annotations

import time

from docmancer.connectors.fetchers.pipeline.rate_limit import RateLimiter


class TestRateLimiter:
    def test_first_request_no_wait(self):
        limiter = RateLimiter(delay=1.0, jitter=0.0)
        start = time.monotonic()
        limiter.wait("https://example.com/page1")
        elapsed = time.monotonic() - start
        # First request should have minimal delay
        assert elapsed < 0.1

    def test_second_request_waits(self):
        limiter = RateLimiter(delay=0.2, jitter=0.0)
        limiter.wait("https://example.com/page1")
        start = time.monotonic()
        limiter.wait("https://example.com/page2")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.15  # Should wait ~0.2s

    def test_different_hosts_independent(self):
        limiter = RateLimiter(delay=0.5, jitter=0.0)
        limiter.wait("https://example.com/page1")
        start = time.monotonic()
        limiter.wait("https://other.com/page1")
        elapsed = time.monotonic() - start
        # Different host, should not wait
        assert elapsed < 0.1

    def test_set_delay(self):
        limiter = RateLimiter(delay=0.1, jitter=0.0)
        limiter.set_delay(0.3)
        limiter.wait("https://example.com/page1")
        start = time.monotonic()
        limiter.wait("https://example.com/page2")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.25

    def test_backoff_increases_delay(self):
        limiter = RateLimiter(delay=0.1, jitter=0.0)
        limiter.record_rate_limit("https://example.com/page")
        limiter.wait("https://example.com/page1")
        start = time.monotonic()
        limiter.wait("https://example.com/page2")
        elapsed = time.monotonic() - start
        # With backoff=1, delay should be 0.1 * 2^1 = 0.2
        assert elapsed >= 0.15

    def test_reset_backoff(self):
        limiter = RateLimiter(delay=0.1, jitter=0.0)
        limiter.record_rate_limit("https://example.com/page")
        limiter.reset_backoff("https://example.com/page")
        limiter.wait("https://example.com/page1")
        start = time.monotonic()
        limiter.wait("https://example.com/page2")
        elapsed = time.monotonic() - start
        # Back to base delay after reset
        assert elapsed < 0.2
