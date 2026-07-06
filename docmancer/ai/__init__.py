"""Cloud-backed memory intelligence for docmancer.

These features are key-gated extras on top of the local-first memory harness.
They require ``OPENROUTER_API_KEY`` by default and call a hosted chat model to
extract durable memory facts and produce review-only consolidated drafts. The
default local ``docmancer memory`` commands never touch this package.
"""
from __future__ import annotations

MISSING_KEY_MESSAGE = (
    "needs OPENROUTER_API_KEY. Set it (export OPENROUTER_API_KEY=...) and retry."
)

__all__ = ["MISSING_KEY_MESSAGE"]
