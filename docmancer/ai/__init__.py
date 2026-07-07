"""Provider-backed memory intelligence for docmancer.

These features sit on top of the local-first memory harness. The default
drafting provider is OpenRouter, which requires ``OPENROUTER_API_KEY`` and
calls a hosted chat model to extract durable memory facts or produce
review-only consolidated drafts.
"""
from __future__ import annotations

MISSING_KEY_MESSAGE = (
    "needs OPENROUTER_API_KEY. Set it (export OPENROUTER_API_KEY=...) and retry."
)

__all__ = ["MISSING_KEY_MESSAGE"]
