"""Non-authoritative local entitlement cache."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docmancer.cloud.config import CloudConfig


def cache_entitlement(value: dict, *, root: str | Path) -> dict:
    payload = dict(value)
    payload["cached_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = CloudConfig(root).paths.entitlement_cache
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def read_entitlement(*, root: str | Path) -> dict:
    path = CloudConfig(root).paths.entitlement_cache
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown"}
    return value if isinstance(value, dict) else {"state": "unknown"}


def remote_transfer_allowed(value: dict) -> bool:
    return value.get("state") in {"active", "trial", "grace"}


__all__ = ["cache_entitlement", "read_entitlement", "remote_transfer_allowed"]
