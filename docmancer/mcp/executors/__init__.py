"""Per-source executors. v1: http, noop_doc, python_import (opt-in)."""
from __future__ import annotations

from docmancer.mcp.executors.base import Executor, ExecutorResult
from docmancer.mcp.executors.http import HttpExecutor
from docmancer.mcp.executors.noop import NoopDocExecutor
from docmancer.mcp.executors.python_import import PythonImportExecutor


def get_executor(kind: str) -> Executor:
    if kind == "http":
        return HttpExecutor()
    if kind == "noop_doc":
        return NoopDocExecutor()
    if kind == "python_import":
        return PythonImportExecutor()
    raise ValueError(f"Unknown executor: {kind}")


__all__ = [
    "Executor", "ExecutorResult",
    "HttpExecutor", "NoopDocExecutor", "PythonImportExecutor",
    "get_executor",
]
