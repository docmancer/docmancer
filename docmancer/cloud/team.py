"""Git team-memory import and reviewable export helpers."""
from __future__ import annotations

from pathlib import Path

from docmancer.memory import MemoryAgent
from docmancer.memory.records import MemoryRecordStore


def import_from_git(project: str | Path) -> dict:
    root = Path(project).expanduser().resolve()
    if not (root / ".git").exists():
        raise ValueError("team import requires a Git repository root")
    agent = MemoryAgent()
    agent._extra_project_paths.add(str(root))
    records = [record for record in agent.records.records(project_paths=[root]) if record.scope_kind == "team"]
    indexed = agent.sync()
    return {"records": len(records), "indexed_atoms": indexed, "project": str(root)}


def export_to_git(project: str | Path, *, dry_run: bool = True) -> dict:
    root = Path(project).expanduser().resolve()
    if not (root / ".git").exists():
        raise ValueError("team export requires a Git repository root")
    store = MemoryRecordStore()
    records = [record for record in store.records(project_paths=[root]) if record.scope_kind == "team"]
    destination = root / ".docmancer" / "memory"
    preview = [{"record_id": record.record_id, "source": record.source_path, "destination": str(destination / Path(record.source_path).name)} for record in records]
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        for record in records:
            target = destination / Path(record.source_path).name
            if Path(record.source_path).resolve() != target.resolve():
                store._write_record(target, record)
    return {"dry_run": dry_run, "records": preview, "destination": str(destination), "staged": False, "committed": False}


__all__ = ["export_to_git", "import_from_git"]
