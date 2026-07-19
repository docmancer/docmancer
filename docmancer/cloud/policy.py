"""Local policy cache and acknowledgement records."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docmancer.cloud.config import CloudConfig


def acknowledge_policy(policy_id: str, version: str, *, root: str | Path) -> dict:
    value = {"policy_id": policy_id, "version": version, "acknowledged_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = CloudConfig(root).paths.root / "policy-ack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def apply_policy(value: dict, *, root: str | Path) -> dict:
    """Cache a metadata-only policy for local consumers and acknowledgement."""
    allowed = {"policy_id", "version", "redaction_patterns", "retention_days", "continuous_audit"}
    if set(value) - allowed:
        raise ValueError("policy contains unsupported fields")
    if not value.get("policy_id") or not value.get("version"):
        raise ValueError("policy identity and version are required")
    path = CloudConfig(root).paths.root / "policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return acknowledge_policy(str(value["policy_id"]), str(value["version"]), root=root)


__all__ = ["acknowledge_policy", "apply_policy"]
