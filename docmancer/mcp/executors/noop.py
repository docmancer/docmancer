"""Tier-1 fallback executor: returns documentation snippets without making real calls."""
from __future__ import annotations

from typing import Any

from docmancer.mcp.executors.base import Executor, ExecutorResult


class NoopDocExecutor(Executor):
    def call(
        self,
        *,
        operation: dict[str, Any],
        args: dict[str, Any],
        auth_headers: dict[str, str],
        required_headers: dict[str, str],
        idempotency_key: str | None,
        idempotency_header: str | None,
        auth_params: dict[str, str] | None = None,
        auth_cookies: dict[str, str] | None = None,
    ) -> ExecutorResult:
        snippet = operation.get("doc_snippet") or operation.get("summary") or ""
        return ExecutorResult(
            ok=True,
            status="doc",
            body={
                "operation_id": operation.get("id"),
                "summary": operation.get("summary"),
                "doc": snippet,
                "examples": operation.get("examples", []),
                "note": "noop_doc executor: no live call was made; this is documentation only.",
            },
        )
