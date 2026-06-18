"""Mistral-backed memory intelligence for docmancer.

These features are key-gated extras on top of the local-first memory harness.
They require ``MISTRAL_API_KEY`` and call the official ``mistralai`` client to
extract durable memory facts and produce review-only consolidated drafts. The
default local ``docmancer memory`` commands never touch this package.
"""
from __future__ import annotations

MISSING_KEY_MESSAGE = (
    "needs MISTRAL_API_KEY. Set it (export MISTRAL_API_KEY=...) and retry."
)

__all__ = ["MISSING_KEY_MESSAGE"]
