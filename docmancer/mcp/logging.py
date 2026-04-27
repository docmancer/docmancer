"""Append-only call log per spec 2.5 / Section 24. Values redacted."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from docmancer.mcp import paths


def log_call(
    *,
    tool: str,
    args: dict[str, Any],
    status: int | str,
    latency_ms: int,
    idempotency_key: str | None = None,
    log_path: Path | None = None,
) -> None:
    log_path = log_path or paths.calls_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": int(time.time()),
        "tool": tool,
        "arg_keys": sorted(args.keys()),
        "status": status,
        "latency_ms": latency_ms,
        "idempotency_key": idempotency_key,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
