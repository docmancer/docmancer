"""Idempotent migration of 0.7.x durable records into Protocol v1 lineage."""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.records import MemoryRecordStore, RECORD_SCHEMA_VERSION


def migrate_records(*, root: str | Path, project_paths=None) -> dict[str, int]:
    store = MemoryRecordStore(root)
    counts = {"records": 0, "revisions_added": 0, "files_updated": 0}
    for record in store.records(project_paths=project_paths):
        counts["records"] += 1
        assigned_project_id = record.scope_kind == "project" and not record.project_id
        if assigned_project_id:
            record.project_id = store.cloud.ensure_project(record.project_path)
            record.revision_id = ""
        payload = record.to_revision_payload()
        record.revision_id = payload["revision_id"]
        if store.append_revision(payload):
            counts["revisions_added"] += 1
        if assigned_project_id or record.schema_version < RECORD_SCHEMA_VERSION:
            record.schema_version = RECORD_SCHEMA_VERSION
            store._write_record(Path(record.source_path), record)
            counts["files_updated"] += 1
    return counts


__all__ = ["migrate_records"]
