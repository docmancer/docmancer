"""Local context-delivery receipts and agent integration matrix."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENTS = (
    "claude-code",
    "claude-desktop",
    "codex",
    "codex-app",
    "codex-desktop",
    "cursor",
    "gemini",
    "opencode",
    "cline",
    "windsurf",
    "continue",
    "github-copilot",
)


def inspect_hook_status(project_path: str | Path | None = None) -> list[dict]:
    locations = [
        ("claude-code", "user", Path.home() / ".claude" / "settings.json"),
        ("codex", "user", Path.home() / ".codex" / "hooks.json"),
    ]
    if project_path is not None:
        project = Path(project_path).expanduser().resolve()
        locations.extend(
            [
                ("claude-code", "project", project / ".claude" / "settings.json"),
                ("codex", "project", project / ".codex" / "hooks.json"),
            ]
        )
    rows = []
    for agent, scope, path in locations:
        data: dict[str, Any] = {}
        error = None
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError) as exc:
                error = str(exc)
        blob = json.dumps(data, sort_keys=True)
        hooks = data.get("hooks") if isinstance(data, dict) else {}
        rows.append(
            {
                "agent": agent,
                "scope": scope,
                "path": str(path),
                "exists": path.is_file(),
                "recall": "memory hook-context" in blob or "session-baseline" in blob,
                "capture": "memory capture-hook" in blob,
                "events": sorted(str(event) for event in hooks) if isinstance(hooks, dict) else [],
                "error": error,
            }
        )
    return rows


def _state_path(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / ".docmancer" / "state" / "delivery.json"


def _stable_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        key: bundle.get(key)
        for key in (
            "mandatory_policies",
            "curated_memory",
            "relevant_evidence",
            "conflict_warnings",
            "token_estimate",
            "token_budget",
            "index_revision",
        )
    }


def bundle_hash(bundle: dict[str, Any]) -> str:
    encoded = json.dumps(_stable_bundle(bundle), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def record_delivery(
    project_path: str | Path,
    *,
    agent: str,
    surface: str,
    integration_mode: str,
    bundle: dict[str, Any],
    task: str | None = None,
) -> dict[str, Any]:
    path = _state_path(project_path)
    state: dict[str, Any] = {"schema_version": 1, "agents": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError):
            pass
    agents = state.setdefault("agents", {})
    row = {
        "agent": agent,
        "surface": surface,
        "integration_mode": integration_mode,
        "last_successful_recall": datetime.now(timezone.utc).isoformat(),
        "tree_revision": str(bundle.get("index_revision") or ""),
        "bundle_hash": bundle_hash(bundle),
        "token_estimate": int(bundle.get("token_estimate") or 0),
        "item_count": sum(
            len(bundle.get(key) or [])
            for key in ("mandatory_policies", "curated_memory", "relevant_evidence")
        ),
        "task_hash": hashlib.sha256((task or "").encode("utf-8")).hexdigest()[:16] if task else None,
    }
    agents[agent] = row
    state["updated_at"] = row["last_successful_recall"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return row


def delivery_matrix(
    project_path: str | Path,
    *,
    hook_rows: list[dict] | None = None,
    projections: dict[str, str] | None = None,
) -> list[dict]:
    path = _state_path(project_path)
    state: dict[str, Any] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    receipts = state.get("agents") if isinstance(state.get("agents"), dict) else {}
    projections = projections or {}
    hook_by_agent: dict[str, list[dict]] = {}
    for row in hook_rows or []:
        hook_by_agent.setdefault(str(row.get("agent") or ""), []).append(row)

    matrix = []
    for agent in AGENTS:
        hooks = hook_by_agent.get(agent, [])
        recall_hook = any(bool(row.get("recall")) for row in hooks)
        projection = projections.get(agent)
        receipt = receipts.get(agent) if isinstance(receipts.get(agent), dict) else {}
        mode = "hook" if recall_hook else "managed-projection" if projection else "skill-or-cli"
        matrix.append(
            {
                "agent": agent,
                "integration_mode": mode,
                "hook_status": "installed" if recall_hook else "not-installed",
                "hook_scopes": sorted(str(row.get("scope") or "") for row in hooks if row.get("recall")),
                "projection_path": projection,
                "last_successful_recall": receipt.get("last_successful_recall"),
                "tree_revision": receipt.get("tree_revision"),
                "bundle_hash": receipt.get("bundle_hash"),
                "surface": receipt.get("surface"),
                "item_count": receipt.get("item_count"),
                "status": "delivered" if receipt.get("bundle_hash") else "not-observed",
            }
        )
    return matrix


__all__ = [
    "AGENTS",
    "bundle_hash",
    "delivery_matrix",
    "inspect_hook_status",
    "record_delivery",
]
