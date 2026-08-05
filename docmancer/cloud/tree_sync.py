"""Canonical Markdown tree revision queueing and safe local application."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.lifecycle import enqueue_revisions_if_enabled
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.serialize import build_tree_payload
from docmancer.memory.tree.parser import parse_tree_file
from docmancer.memory.tree.store import TreeStore, _atomic_write, _unlink_durable

MACHINE_TREE_ID = "prj_machine"


def payload_for_file(path: Path, *, tree_root: Path, project_id: str, parent: str | None = None) -> dict:
    entry = parse_tree_file(path)
    if entry is None:
        raise ValueError(f"unreadable tree file: {path.name}")
    relative = path.resolve().relative_to(tree_root.resolve()).as_posix()
    return build_tree_payload(
        object_kind="tree_file",
        file_id=entry.memory_id,
        project_id=project_id,
        relative_path=relative,
        markdown=path.read_text(encoding="utf-8"),
        metadata={
            "title": entry.title,
            "scope": entry.scope,
            "authority": entry.authority,
            "status": entry.status,
            "tags": entry.tags,
            "sources": entry.sources,
            "generated": False,
            "publication_state": "local",
        },
        updated_at=entry.updated_at,
        parent_revision_ids=[parent] if parent else entry.parent_revision_ids,
    )


def _queue_tree_root(
    tree_root: Path,
    *,
    project_id: str,
    root: str | Path,
    keystore=None,
) -> dict[str, int]:
    config = CloudConfig(root)
    state = CloudState(config.paths.sync_state)
    prior = state.tree_heads(project_id)
    current: dict[str, dict] = {}
    payloads: list[dict] = []
    if tree_root.is_dir():
        for path in sorted(tree_root.rglob("*.md")):
            entry = parse_tree_file(path)
            if entry is None:
                continue
            previous = prior.get(entry.memory_id)
            payload = payload_for_file(
                path,
                tree_root=tree_root,
                project_id=project_id,
                parent=str(previous["revision_id"]) if previous and not previous["deleted"] else None,
            )
            current[entry.memory_id] = payload
            if previous is None or previous["revision_id"] != payload["revision_id"]:
                payloads.append(payload)
    for file_id, previous in prior.items():
        if file_id in current or bool(previous["deleted"]):
            continue
        payloads.append(
            build_tree_payload(
                object_kind="tree_file",
                file_id=file_id,
                project_id=project_id,
                relative_path=str(previous["relative_path"]),
                markdown="",
                metadata={"publication_state": "deleted"},
                updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                parent_revision_ids=[str(previous["revision_id"])],
                deleted=True,
            )
        )
    queued = enqueue_revisions_if_enabled(payloads, root=root, keystore=keystore)
    state.set_tree_heads(
        {
            "project_id": project_id,
            "file_id": payload["file_id"],
            "revision_id": payload["revision_id"],
            "relative_path": payload["relative_path"],
            "deleted": payload["deleted"],
        }
        for payload in payloads
    )
    return {"changed": len(payloads), "queued": queued}


def queue_machine_tree_changes(
    *, root: str | Path, keystore=None,
) -> dict[str, int]:
    """Queue the exact machine-wide canonical Markdown tree."""
    return _queue_tree_root(
        Path(root).expanduser().resolve() / "tree",
        project_id=MACHINE_TREE_ID,
        root=root,
        keystore=keystore,
    )


def queue_tree_changes(
    project_path: str | Path, *, root: str | Path, keystore=None,
) -> dict[str, int]:
    project = Path(project_path).expanduser().resolve()
    return _queue_tree_root(
        project / ".docmancer" / "tree",
        project_id=CloudConfig(root).ensure_project(project),
        root=root,
        keystore=keystore,
    )


def apply_tree_payload(payload: dict, *, root: str | Path, state: CloudState) -> str:
    config = CloudConfig(root)
    if payload["project_id"] == MACHINE_TREE_ID:
        tree_root = Path(root).expanduser().resolve() / "tree"
    else:
        mapping = config.mapping_status(payload["project_id"])
        if mapping["state"] != "mapped":
            state.add_conflict(
                record_ref=payload["file_id"],
                local_revision_id=None,
                remote_revision_id=payload["revision_id"],
                reason=f"project_mapping_{mapping['state']}",
                payload=payload,
            )
            return "deferred"
        project = Path(mapping["paths"][0])
        tree_root = project / ".docmancer" / "tree"
    store = TreeStore(tree_root)
    store.index.rebuild()
    address = f"docmancer://memory/{payload['file_id']}"
    try:
        existing = store.read(address)
    except Exception:
        existing = None
    if existing and existing.revision_id == payload["revision_id"]:
        return "duplicate"
    if existing and existing.revision_id not in payload["parent_revision_ids"]:
        state.add_conflict(
            record_ref=payload["file_id"],
            local_revision_id=existing.revision_id,
            remote_revision_id=payload["revision_id"],
            reason="tree_diverged_heads",
            payload=payload,
        )
        return "conflict"
    if payload["deleted"]:
        if existing is None:
            outcome = "duplicate"
        else:
            _unlink_durable(existing.path)
            store.index.note_delete(existing.memory_id)
            outcome = "applied"
    else:
        target = store.index.resolve_target(payload["relative_path"])
        if target.exists() and (existing is None or target.resolve() != existing.path.resolve()):
            state.add_conflict(
                record_ref=payload["file_id"],
                local_revision_id=None,
                remote_revision_id=payload["revision_id"],
                reason="tree_path_collision",
                payload=payload,
            )
            return "conflict"
        if hashlib.sha256(payload["markdown"].encode()).hexdigest() != payload["content_hash"]:
            raise ValueError("tree payload changed after validation")
        _atomic_write(target, payload["markdown"].encode("utf-8"))
        if existing and existing.path.resolve() != target.resolve():
            _unlink_durable(existing.path)
        store.index.rebuild()
        outcome = "applied"
    state.set_tree_head(
        project_id=payload["project_id"],
        file_id=payload["file_id"],
        revision_id=payload["revision_id"],
        relative_path=payload["relative_path"],
        deleted=payload["deleted"],
    )
    return outcome


__all__ = [
    "MACHINE_TREE_ID",
    "apply_tree_payload",
    "payload_for_file",
    "queue_machine_tree_changes",
    "queue_tree_changes",
]
