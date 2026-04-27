"""Safety gating per spec 2.5 / D5."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GateResult:
    allowed: bool
    error_code: str | None = None
    message: str | None = None


def check(
    *,
    package: str,
    operation: dict[str, Any],
    allow_destructive: bool,
    has_credentials: bool,
    version: str | None = None,
) -> GateResult:
    safety = operation.get("safety", {}) or {}
    if safety.get("requires_auth") and not has_credentials:
        return GateResult(
            False,
            "missing_credentials",
            f"Operation {operation.get('id')} requires auth but no credential resolved.",
        )
    if safety.get("destructive") and not allow_destructive:
        spec = f"{package}@{version}" if version else package
        return GateResult(
            False,
            "destructive_call_blocked",
            (
                f"Tool for {operation.get('id')} is marked destructive. "
                f"Destructive calls are disabled for package {package}. "
                f"To enable: docmancer install-pack {spec} --allow-destructive, "
                f"then restart your agent."
            ),
        )
    return GateResult(True)
