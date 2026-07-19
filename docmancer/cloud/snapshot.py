"""Client-produced encrypted snapshots of live local record heads."""
from __future__ import annotations

import json
from pathlib import Path

from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt
from docmancer.cloud.serialize import canonicalize
from docmancer.memory.records import MemoryRecordStore


def build_snapshot(*, root: str | Path, workspace_id: str, workspace_key: bytes, cursor: str | None = None, project_paths=None) -> dict:
    store = MemoryRecordStore(root)
    heads = [record.to_revision_payload() for record in store.records(project_paths=project_paths)]
    tombstones = []
    revisions_dir = store.personal_dir / ".revisions"
    if revisions_dir.is_dir():
        for path in revisions_dir.glob("*.jsonl"):
            rows = store.revisions(path.stem)
            if rows and rows[-1].get("deleted"):
                tombstones.append(rows[-1])
    payload = {"version": 1, "workspace_id": workspace_id, "cursor": cursor, "heads": heads, "tombstones": tombstones}
    nonce, ciphertext = encrypt(canonicalize(payload), workspace_key, aad=workspace_id.encode("utf-8"))
    return {"version": 1, "workspace_id": workspace_id, "cursor": cursor, "nonce": b64encode(nonce), "ciphertext": b64encode(ciphertext)}


def open_snapshot(snapshot: dict, *, workspace_key: bytes) -> dict:
    workspace_id = str(snapshot["workspace_id"])
    value = decrypt(b64decode(snapshot["ciphertext"]), workspace_key, nonce=b64decode(snapshot["nonce"]), aad=workspace_id.encode("utf-8"))
    payload = json.loads(value)
    if payload.get("workspace_id") != workspace_id:
        raise ValueError("snapshot workspace mismatch")
    return payload


def apply_snapshot(snapshot: dict, *, root: str | Path, workspace_key: bytes) -> dict:
    from docmancer.cloud.apply import apply_payload
    from docmancer.cloud.config import CloudConfig
    from docmancer.cloud.outbox import CloudState

    payload = open_snapshot(snapshot, workspace_key=workspace_key)
    counts = {"applied": 0, "duplicate": 0, "conflict": 0}
    for revision in list(payload.get("heads") or []) + list(payload.get("tombstones") or []):
        outcome = apply_payload(revision, root=root)
        counts[outcome] += 1
    if counts["applied"]:
        from docmancer.memory import MemoryAgent

        base = Path(root)
        MemoryAgent(db_path=str(base / "memory.db"), home=base.parent).sync()
    if payload.get("cursor") is not None:
        CloudState(CloudConfig(root).paths.sync_state).set_meta("cursor", str(payload["cursor"]))
    return counts


__all__ = ["apply_snapshot", "build_snapshot", "open_snapshot"]
