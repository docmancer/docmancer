"""Redirect pattern learning for skipping known redirect chains.

Observes HTTP redirects during fetching and learns prefix-replacement
patterns.  Once a pattern is confirmed (by default after 3 matching
observations), it rewrites future URLs so the fetcher can request the
final destination directly — turning a 302→301→200 chain into a single 200.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


class RedirectTracker:
    """Learns URL redirect patterns to skip redirect chains.

    After observing *min_observations* redirects that share the same
    prefix-replacement rule, the tracker promotes the rule and applies it
    to unseen URLs via :meth:`predict_final_url`.

    Args:
        min_observations: Number of matching redirects required before a
            pattern is considered learned.  Default ``3``.
    """

    def __init__(self, min_observations: int = 3) -> None:
        self._min_observations = min_observations
        # candidate pattern -> observation count
        self._candidates: dict[tuple[str, str], int] = {}
        # promoted patterns, ordered by most observations first
        self._learned: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_redirect(self, original: str, final: str) -> None:
        """Record an observed redirect and update pattern candidates.

        Args:
            original: The URL that was requested.
            final: The URL that was ultimately served (after redirects).
        """
        pattern = self._extract_pattern(original, final)
        if pattern is None:
            return

        if pattern in dict(self._learned):
            return  # already promoted

        count = self._candidates.get(pattern, 0) + 1
        self._candidates[pattern] = count

        if count >= self._min_observations:
            self._learned.append(pattern)
            del self._candidates[pattern]
            logger.info(
                "Learned redirect pattern: %s -> %s (after %d observations)",
                pattern[0],
                pattern[1],
                count,
            )

    def predict_final_url(self, url: str) -> str | None:
        """Apply learned patterns to predict the final redirect target.

        Returns:
            The predicted final URL, or ``None`` if no pattern matches.
        """
        for original_prefix, replacement_prefix in self._learned:
            if url.startswith(original_prefix):
                return replacement_prefix + url[len(original_prefix):]
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pattern(original: str, final: str) -> tuple[str, str] | None:
        """Derive a prefix-replacement pattern from a single redirect.

        Returns a ``(original_prefix, replacement_prefix)`` tuple, or
        ``None`` if the redirect is not a clean prefix replacement (e.g.
        cross-domain, query-string-based, or path rearrangement).
        """
        orig_parsed = urlparse(original)
        final_parsed = urlparse(final)

        # Must share scheme and netloc.
        if orig_parsed.scheme != final_parsed.scheme:
            return None
        if orig_parsed.netloc.lower() != final_parsed.netloc.lower():
            return None

        orig_segments = [s for s in orig_parsed.path.split("/") if s]
        final_segments = [s for s in final_parsed.path.split("/") if s]

        # Find longest common prefix of segments.
        prefix_len = 0
        for a, b in zip(orig_segments, final_segments):
            if a == b:
                prefix_len += 1
            else:
                break

        # Find longest common suffix of segments (from the non-prefix remainder).
        orig_rest = orig_segments[prefix_len:]
        final_rest = final_segments[prefix_len:]

        suffix_len = 0
        for a, b in zip(reversed(orig_rest), reversed(final_rest)):
            if a == b:
                suffix_len += 1
            else:
                break

        # The differing middle segments.
        orig_mid = orig_rest[: len(orig_rest) - suffix_len] if suffix_len else orig_rest
        final_mid = final_rest[: len(final_rest) - suffix_len] if suffix_len else final_rest

        if not orig_mid and not final_mid:
            # No difference — not a redirect pattern we care about.
            return None

        # Build prefix strings up to (and including) the differing middle.
        base = f"{orig_parsed.scheme}://{orig_parsed.netloc}"
        common_prefix_path = "/".join(orig_segments[:prefix_len])

        orig_prefix = f"{base}/{common_prefix_path}/{'/'.join(orig_mid)}".rstrip("/")
        final_prefix = f"{base}/{common_prefix_path}"
        if final_mid:
            final_prefix = f"{final_prefix}/{'/'.join(final_mid)}"
        final_prefix = final_prefix.rstrip("/")

        return (orig_prefix, final_prefix)
