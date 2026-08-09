"""Read-only sizing for the next encrypted Personal Sync upload."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, opaque_ref
from docmancer.cloud.envelope import build_envelope
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.serialize import build_graph_payload, canonicalize
from docmancer.cloud.sync import (
    _MAX_ENVELOPE_BYTES,
    _PUSH_BATCH_BYTES,
    _PUSH_BATCH_SIZE,
    _push_batches,
    encoded_request_bytes,
)
from docmancer.cloud.tree_sync import MACHINE_TREE_ID, plan_tree_root

DEFAULT_SERVICE_BATCH_BYTES = 8_000_000
DEFAULT_BACKUP_QUOTA_BYTES = 1_000_000_000


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _record_payloads(root: Path, projects: dict[str, Path]) -> list[dict]:
    from docmancer.memory.records import MemoryRecordStore

    store = MemoryRecordStore(root)
    project_paths = list(projects.values())
    path_ids = {str(path.resolve()): project_id for project_id, path in projects.items()}
    payloads: list[dict] = []
    seen: set[str] = set()
    for record in store.records(project_paths=project_paths):
        for revision in store.revisions(record.record_id):
            revision_id = str(revision.get("revision_id") or "")
            if revision_id and revision_id not in seen:
                payloads.append(revision)
                seen.add(revision_id)

        # Old record files may not have been migrated into the immutable
        # revision log yet. Mirror that migration in memory only.
        if record.scope_kind == "project" and not record.project_id:
            record.project_id = path_ids.get(str(Path(record.project_path or "").resolve()))
            record.revision_id = ""
        current = record.to_revision_payload()
        if current["revision_id"] not in seen:
            payloads.append(current)
            seen.add(current["revision_id"])
    return payloads


def _graph_payloads(root: Path) -> list[dict]:
    from docmancer.memory.graph import MemoryGraphStore

    db_path = root / "memory.db"
    if not db_path.is_file():
        return []
    graph = MemoryGraphStore(db_path)
    return [build_graph_payload(**item) for item in graph.cloud_objects()]


def _tree_payloads(root: Path, projects: dict[str, Path]) -> list[dict]:
    payloads = plan_tree_root(
        root / "tree",
        project_id=MACHINE_TREE_ID,
        root=root,
    )
    for project_id, project_path in projects.items():
        payloads.extend(
            plan_tree_root(
                project_path / ".docmancer" / "tree",
                project_id=project_id,
                root=root,
            )
        )
    return payloads


def _new_envelopes(
    payloads: Iterable[dict],
    *,
    known_refs: set[str],
    workspace_id: str,
    device_id: str,
    workspace_key: bytes,
    signing_private_key: bytes,
    key_version: int,
) -> tuple[list[dict], dict[str, dict[str, int]], int]:
    envelopes: list[dict] = []
    by_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"envelopes": 0, "plaintext_bytes": 0, "encrypted_envelope_bytes": 0}
    )
    plaintext_bytes = 0
    for payload in payloads:
        revision_ref = opaque_ref(
            str(payload["revision_id"]),
            workspace_key,
            workspace_id=workspace_id,
            kind="revision",
        )
        if revision_ref in known_refs:
            continue
        known_refs.add(revision_ref)
        envelope = build_envelope(
            payload,
            workspace_id=workspace_id,
            device_id=device_id,
            workspace_key=workspace_key,
            signing_private_key=signing_private_key,
            key_version=key_version,
        )
        kind = str(envelope["kind"])
        plain_size = len(canonicalize(payload))
        envelope_size = _json_bytes(envelope)
        by_kind[kind]["envelopes"] += 1
        by_kind[kind]["plaintext_bytes"] += plain_size
        by_kind[kind]["encrypted_envelope_bytes"] += envelope_size
        plaintext_bytes += plain_size
        envelopes.append(envelope)
    return envelopes, dict(by_kind), plaintext_bytes


def _upload_batches(envelopes: list[dict], *, cursor: int) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for offset in range(0, len(envelopes), _PUSH_BATCH_SIZE):
        pending = envelopes[offset : offset + _PUSH_BATCH_SIZE]
        groups: dict[int, list[dict]] = {}
        for envelope in pending:
            version = int(envelope.get("protocol_version") or 1)
            groups.setdefault(version, []).append(envelope)
        for version, group in sorted(groups.items()):
            for batch in _push_batches(group, cursor=cursor, protocol_version=version):
                result.append(
                    {
                        "protocol_version": version,
                        "envelopes": len(batch),
                        "bytes": encoded_request_bytes(
                            batch,
                            cursor=cursor,
                            protocol_version=version,
                        ),
                    }
                )
    return result


def estimate_sync(
    *,
    root: str | Path,
    keystore: KeyStore,
    entitlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate the next encrypted upload without queueing or sending data."""
    root_path = Path(root).expanduser().resolve()
    config = CloudConfig(root_path)
    account = config.account()
    workspace = config.workspace()
    if not config.enabled() or workspace is None:
        raise ValueError("cloud sync is not configured; run `docmancer cloud connect`")

    account_id = str(account.get("account_id") or "")
    device_id = str(account.get("device_id") or "")
    workspace_id, metadata = workspace
    key_version = int(metadata.get("key_version") or 1)
    workspace_key = (
        keystore.workspace_key(account_id, workspace_id, key_version)
        or keystore.workspace_key(account_id, workspace_id)
    )
    signing_private = keystore.get(account_id, "device-signing-private")
    if not workspace_key or not signing_private:
        raise ValueError("workspace encryption keys are unavailable on this device")

    projects: dict[str, Path] = {}
    for project_id in config.workspaces().get("projects", {}):
        mapping = config.mapping_status(str(project_id))
        if mapping["state"] == "mapped":
            projects[str(project_id)] = Path(mapping["paths"][0])

    state = CloudState(config.paths.sync_state)
    existing = state.pending_all()
    payloads = [
        *_record_payloads(root_path, projects),
        *_graph_payloads(root_path),
        *_tree_payloads(root_path, projects),
    ]
    new, by_kind, plaintext_bytes = _new_envelopes(
        payloads,
        known_refs=state.known_revision_refs(),
        workspace_id=workspace_id,
        device_id=device_id,
        workspace_key=workspace_key,
        signing_private_key=signing_private,
        key_version=key_version,
    )
    # New rows share a transaction timestamp when a real sync queues them, so
    # revision-ref order is the closest deterministic preview of upload order.
    new.sort(key=lambda row: str(row["revision_ref"]))
    envelopes = [*existing, *new]
    cursor = int(state.get_meta("cursor") or 0)
    batches = _upload_batches(envelopes, cursor=cursor)

    remote = dict(entitlement or {})
    remote_limits = remote.get("limits") if isinstance(remote.get("limits"), dict) else {}
    max_envelope_bytes = int(remote_limits.get("max_envelope_bytes") or _MAX_ENVELOPE_BYTES)
    service_batch_bytes = int(
        remote_limits.get("max_batch_bytes") or DEFAULT_SERVICE_BATCH_BYTES
    )
    max_batch_count = int(remote_limits.get("max_batch_count") or _PUSH_BATCH_SIZE)
    sync_storage_bytes = remote_limits.get("sync_storage_bytes")
    backup_storage_bytes = int(
        remote_limits.get("backup_storage_bytes") or DEFAULT_BACKUP_QUOTA_BYTES
    )

    envelope_sizes = [_json_bytes(envelope) for envelope in envelopes]
    ciphertext_bytes = sum(
        len(b64decode(str(envelope.get("ciphertext") or ""))) for envelope in envelopes
    )
    issues: list[str] = []
    oversized = sum(size > max_envelope_bytes for size in envelope_sizes)
    if oversized:
        issues.append(
            f"{oversized} encrypted envelope(s) exceed the service envelope limit"
        )
    oversized_batches = sum(batch["bytes"] > service_batch_bytes for batch in batches)
    if oversized_batches:
        issues.append(
            f"{oversized_batches} upload request(s) exceed the service request limit"
        )
    overcount_batches = sum(batch["envelopes"] > max_batch_count for batch in batches)
    if overcount_batches:
        issues.append(
            f"{overcount_batches} upload request(s) exceed the service envelope-count limit"
        )
    if not bool(remote.get("can_push", True)):
        issues.append("the current plan does not allow uploads")

    return {
        "workspace_id": workspace_id,
        "plan": {
            "key": str(remote.get("plan_key") or "sync"),
            "status": str(remote.get("status") or "unknown"),
            "can_push": bool(remote.get("can_push", True)),
            "can_pull": bool(remote.get("can_pull", True)),
        },
        "estimate": {
            "existing_queued_envelopes": len(existing),
            "new_envelopes": len(new),
            "total_envelopes": len(envelopes),
            "new_plaintext_bytes": plaintext_bytes,
            "encrypted_ciphertext_bytes": ciphertext_bytes,
            "encrypted_envelope_bytes": sum(envelope_sizes),
            "upload_request_bytes": sum(batch["bytes"] for batch in batches),
            "upload_batches": len(batches),
            "largest_envelope_bytes": max(envelope_sizes, default=0),
        },
        "limits": {
            "source": "service" if remote_limits else "client_defaults",
            "sync_storage_bytes": sync_storage_bytes,
            "max_envelope_bytes": max_envelope_bytes,
            "max_batch_bytes": service_batch_bytes,
            "max_batch_count": max_batch_count,
            "client_batch_target_bytes": _PUSH_BATCH_BYTES,
            "backup_storage_bytes": backup_storage_bytes,
        },
        "by_kind": by_kind,
        "batches": batches,
        "fits_limits": not issues,
        "issues": issues,
        "read_only": True,
    }


__all__ = ["estimate_sync"]
