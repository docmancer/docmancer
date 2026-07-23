"""Append-only local journal of canonical Markdown tree mutations."""
from __future__ import annotations

import difflib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DecisionJournal:
    def __init__(self, tree_root: str | Path) -> None:
        self.tree_root = Path(tree_root).expanduser().resolve()
        self.path = self.tree_root.parent / "state" / "decision-journal.jsonl"

    @staticmethod
    def diff(
        before: str,
        after: str,
        *,
        before_path: str | None,
        after_path: str | None,
    ) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=before_path or "/dev/null",
                tofile=after_path or "/dev/null",
                n=3,
            )
        )

    def append(
        self,
        *,
        file_id: str,
        revision_id: str,
        parent_revision_ids: list[str],
        operation: str,
        actor_surface: str,
        actor_harness: str | None,
        sources: list[str],
        before_path: str | None,
        after_path: str | None,
        before_hash: str | None,
        after_hash: str | None,
        before_body: str,
        after_body: str,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "file_id": file_id,
            "revision_id": revision_id,
            "parent_revision_ids": list(parent_revision_ids),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor_surface": actor_surface,
            "actor_harness": actor_harness,
            "sources": list(sources),
            "operation": operation,
            "before_path": before_path,
            "after_path": after_path,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "diff": self.diff(
                before_body,
                after_body,
                before_path=before_path,
                after_path=after_path,
            ),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def events(
        self,
        *,
        file_id: str | None = None,
        operation: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if file_id and row.get("file_id") != file_id:
                continue
            if operation and row.get("operation") != operation:
                continue
            rows.append(row)
        rows.sort(key=lambda row: (str(row.get("timestamp") or ""), str(row.get("event_id") or "")), reverse=True)
        return rows[: max(0, min(1000, int(limit)))]


__all__ = ["DecisionJournal"]
