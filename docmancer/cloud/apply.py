"""Pull application, ancestry checks, and conflict capture."""
from __future__ import annotations

from pathlib import Path

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.envelope import open_envelope
from docmancer.cloud.outbox import CloudState
from docmancer.memory.records import MemoryRecordStore


def apply_payload(
    payload: dict,
    *,
    root: str | Path,
    state: CloudState | None = None,
    store: MemoryRecordStore | None = None,
) -> str:
    if int(payload.get("schema_version") or 1) == 2:
        if payload.get("object_kind") == "pack":
            from docmancer.memory.packs import ContextPackStore

            return ContextPackStore(root).apply_cloud_pack(payload)
        from docmancer.memory.graph import MemoryGraphStore

        return MemoryGraphStore(Path(root) / "memory.db").apply_cloud_object(payload)
    config = CloudConfig(root)
    sync_state = state or CloudState(config.paths.sync_state)
    record_store = store or MemoryRecordStore(root)
    project_path = None
    if payload["scope_kind"] in {"project", "team"}:
        project_path = config.path_for_project(payload["project_id"])
        if project_path is None:
            sync_state.add_conflict(
                record_ref=payload["record_id"], local_revision_id=None,
                remote_revision_id=payload["revision_id"], reason="unmapped_project", payload=payload,
            )
            return "deferred"
        sync_state.resolve_matching_conflict(
            record_ref=payload["record_id"], remote_revision_id=payload["revision_id"],
            reason="unmapped_project", resolution="project-linked",
        )
    existing = record_store.find_record(payload["record_id"], project_paths=[project_path] if project_path else None)
    revisions = record_store.revisions(payload["record_id"])
    local_head = revisions[-1] if revisions else None
    if (
        existing is None
        and local_head
        and bool(local_head.get("deleted"))
        and local_head.get("revision_id") not in payload["parent_revision_ids"]
    ):
        # A content-free local tombstone is authoritative over replayed or
        # concurrent live revisions. Only an explicit child of that tombstone
        # can restore the stable record identity.
        return "duplicate"
    if existing and existing.revision_id == payload["revision_id"]:
        record_store.append_revision(payload)
        return "duplicate"
    if existing and existing.revision_id not in payload["parent_revision_ids"]:
        sync_state.add_conflict(
            record_ref=payload["record_id"], local_revision_id=existing.revision_id,
            remote_revision_id=payload["revision_id"], reason="diverged_heads", payload=payload,
        )
        return "conflict"
    record_store.apply_revision(payload, project_path=project_path, existing=existing)
    return "applied"


def apply_envelopes(
    envelopes: list[dict], *, root: str | Path, workspace_key: bytes | dict[int, bytes],
    device_public_keys: dict[str, bytes], cursor: str | None = None,
) -> dict[str, int]:
    config = CloudConfig(root)
    state = CloudState(config.paths.sync_state)
    store = MemoryRecordStore(root)
    counts = {"applied": 0, "duplicate": 0, "conflict": 0, "deferred": 0}
    for envelope in envelopes:
        revision_ref = str(envelope["revision_ref"])
        if state.is_applied(revision_ref):
            counts["duplicate"] += 1
            continue
        device_id = str(envelope.get("created_by_device_id") or envelope.get("device_id") or "")
        public_key = device_public_keys.get(device_id)
        if public_key is None:
            raise ValueError(f"unknown cloud device: {device_id}")
        key = workspace_key.get(int(envelope.get("key_version") or 1)) if isinstance(workspace_key, dict) else workspace_key
        if key is None:
            raise ValueError(f"workspace key version {envelope.get('key_version')} is unavailable")
        payload = open_envelope(envelope, workspace_key=key, signing_public_key=public_key)
        outcome = apply_payload(payload, root=root, state=state, store=store)
        counts[outcome] += 1
        if outcome != "deferred":
            state.mark_applied(revision_ref)
    if counts["applied"]:
        from docmancer.memory import MemoryAgent

        base = Path(root)
        MemoryAgent(db_path=str(base / "memory.db"), home=base.parent).sync()
    if cursor is not None and not counts["deferred"]:
        state.set_meta("cursor", cursor)
    return counts


def resolve_conflict(conflict_id: int, strategy: str, *, root: str | Path, text: str | None = None) -> dict:
    """Create a merge revision that names both heads, then close a conflict."""
    from datetime import datetime, timezone
    from docmancer.cloud.serialize import build_record_payload
    from docmancer.cloud.lifecycle import enqueue_revision_if_enabled

    config = CloudConfig(root)
    state = CloudState(config.paths.sync_state)
    rows = [row for row in state.conflicts() if int(row["conflict_id"]) == int(conflict_id)]
    if not rows:
        raise ValueError("unresolved conflict not found")
    row = rows[0]
    remote = row["payload"]
    project_path = config.path_for_project(remote.get("project_id")) if remote["scope_kind"] in {"project", "team"} else None
    if remote["scope_kind"] in {"project", "team"} and project_path is None:
        raise ValueError(
            f"project {remote.get('project_id') or '<missing>'} is not linked to an existing local path; "
            "run `docmancer cloud link PATH --project-id PROJECT_ID` first"
        )
    store = MemoryRecordStore(root)
    local = store.find_record(remote["record_id"], project_paths=[project_path] if project_path else None)
    if local is None:
        if strategy not in {"keep-right", "manual"}:
            raise ValueError("the local conflict head no longer exists")
        local_text = ""
        local_revision = row.get("local_revision_id")
    else:
        local_text = local.text
        local_revision = local.revision_id
    remote_text = str(remote.get("text") or "")
    if strategy == "keep-left":
        merged_text = local_text
    elif strategy == "keep-right":
        merged_text = remote_text
    elif strategy == "keep-both":
        merged_text = local_text if local_text == remote_text else f"{local_text}\n\n{remote_text}".strip()
    elif strategy == "manual" and text:
        merged_text = text
    else:
        raise ValueError("manual conflict resolution requires replacement text")
    parents = sorted({value for value in (local_revision, remote["revision_id"]) if value})
    merged = build_record_payload(
        record_id=remote["record_id"], text=merged_text,
        memory_type=local.type if local else remote["memory_type"],
        tags=sorted(set((local.tags if local else []) + list(remote.get("tags") or []))),
        origin_kind="conflict-resolution", origin_harness="docmancer",
        scope_kind=remote["scope_kind"], project_id=remote.get("project_id"),
        created_at=local.created_at if local else remote["created_at"],
        updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        parent_revision_ids=parents,
    )
    store.apply_revision(merged, project_path=project_path, existing=local)
    enqueue_revision_if_enabled(merged, root=root)
    state.resolve_conflict(conflict_id, strategy)
    return merged


__all__ = ["apply_envelopes", "apply_payload", "resolve_conflict"]
