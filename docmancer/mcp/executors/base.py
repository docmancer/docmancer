from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExecutorResult:
    ok: bool
    status: int | str
    body: Any
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class Executor(Protocol):
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
    ) -> ExecutorResult: ...
