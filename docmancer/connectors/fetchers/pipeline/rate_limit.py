"""Per-host rate limiting with jittered delays.

Enforces polite crawling behavior by tracking request timestamps per host
and sleeping between requests. Supports exponential backoff on 429/503.
"""

from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlparse


class RateLimiter:
    """Rate limiter that enforces delays between requests to the same host.

    Args:
        delay: Base delay in seconds between requests to the same host.
        jitter: Maximum additional random delay in seconds.
    """

    def __init__(self, delay: float = 0.5, jitter: float = 0.3):
        self._delay = delay
        self._jitter = jitter
        self._last_request: dict[str, float] = {}
        self._backoff_count: dict[str, int] = {}
        self._lock = threading.Lock()

    def _host_key(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def wait(self, url: str) -> None:
        """Wait the appropriate delay before making a request to this host.

        Args:
            url: The URL about to be requested.
        """
        host = self._host_key(url)
        while True:
            remaining = 0.0
            with self._lock:
                now = time.monotonic()
                last = self._last_request.get(host, 0.0)
                elapsed = now - last

                target_delay = self._delay + random.uniform(0, self._jitter)
                backoff = self._backoff_count.get(host, 0)
                if backoff > 0:
                    target_delay = min(target_delay * (2 ** backoff), 30.0)

                remaining = target_delay - elapsed
                if remaining <= 0:
                    self._last_request[host] = now
                    return
            time.sleep(remaining)

    def set_delay(self, delay: float) -> None:
        """Override the base delay (e.g. from robots.txt Crawl-delay)."""
        with self._lock:
            self._delay = delay

    def record_rate_limit(self, url: str) -> None:
        """Record that a request to this host was rate-limited (429/503).

        Increases the backoff multiplier for subsequent requests.
        """
        host = self._host_key(url)
        with self._lock:
            self._backoff_count[host] = self._backoff_count.get(host, 0) + 1

    def reset_backoff(self, url: str) -> None:
        """Reset the backoff counter for a host after a successful request."""
        host = self._host_key(url)
        with self._lock:
            self._backoff_count.pop(host, None)
