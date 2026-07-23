"""Durable ciphertext outbox, cursors, applied refs, and conflict state."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class CloudState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS outbox (
                    revision_ref TEXT PRIMARY KEY, envelope_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS applied (revision_ref TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS published (revision_ref TEXT PRIMARY KEY, published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS idempotency (
                    operation TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS conflicts (
                    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, record_ref TEXT NOT NULL,
                    local_revision_id TEXT, remote_revision_id TEXT NOT NULL,
                    reason TEXT NOT NULL, payload_json TEXT NOT NULL,
                    resolved_at TEXT, resolution TEXT,
                    UNIQUE(record_ref, remote_revision_id)
                );
                CREATE TABLE IF NOT EXISTS tree_heads (
                    project_id TEXT NOT NULL, file_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(project_id, file_id)
                );
            """)

    def enqueue(self, envelope: dict[str, Any]) -> bool:
        return bool(self.enqueue_many([envelope]))

    def enqueue_many(self, envelopes: Iterable[dict[str, Any]]) -> int:
        """Queue encrypted envelopes in one transaction, excluding published refs."""
        queued = 0
        with self._connect() as conn:
            for envelope in envelopes:
                revision_ref = str(envelope["revision_ref"])
                value = json.dumps(envelope, separators=(",", ":"), sort_keys=True)
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO outbox (revision_ref, envelope_json)
                       SELECT ?, ? WHERE NOT EXISTS (
                         SELECT 1 FROM published WHERE revision_ref = ?
                       )""",
                    (revision_ref, value, revision_ref),
                )
                queued += int(cursor.rowcount == 1)
        return queued

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT envelope_json FROM outbox ORDER BY created_at, revision_ref LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def known_revision_refs(self) -> set[str]:
        """Return locally queued or server-acknowledged revision references."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT revision_ref FROM outbox UNION SELECT revision_ref FROM published"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def acknowledge(self, revision_refs: list[str]) -> None:
        if not revision_refs:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO published (revision_ref) VALUES (?)",
                [(value,) for value in revision_refs],
            )
            conn.executemany(
                "DELETE FROM outbox WHERE revision_ref = ?",
                [(value,) for value in revision_refs],
            )

    def mark_failed(self, revision_ref: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE outbox SET attempts = attempts + 1, last_error = ? WHERE revision_ref = ?", (error[:1000], revision_ref))

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def idempotency_key(self, operation: str) -> str:
        import uuid

        with self._connect() as conn:
            row = conn.execute("SELECT idempotency_key FROM idempotency WHERE operation=?", (operation,)).fetchone()
            if row:
                return str(row[0])
            value = str(uuid.uuid4())
            conn.execute("INSERT INTO idempotency (operation, idempotency_key) VALUES (?, ?)", (operation, value))
            return value

    def clear_idempotency_key(self, operation: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM idempotency WHERE operation=?", (operation,))

    def mark_applied(self, revision_ref: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO applied (revision_ref) VALUES (?)", (revision_ref,))

    def is_applied(self, revision_ref: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM applied WHERE revision_ref = ?", (revision_ref,)).fetchone() is not None

    def add_conflict(self, *, record_ref: str, local_revision_id: str | None, remote_revision_id: str, reason: str, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conflicts (record_ref, local_revision_id, remote_revision_id, reason, payload_json) VALUES (?, ?, ?, ?, ?)",
                (record_ref, local_revision_id, remote_revision_id, reason, json.dumps(payload, sort_keys=True)),
            )

    def conflicts(self, *, unresolved_only: bool = True) -> list[dict]:
        where = "WHERE resolved_at IS NULL" if unresolved_only else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM conflicts {where} ORDER BY conflict_id").fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def resolve_conflict(self, conflict_id: int, resolution: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE conflicts SET resolved_at=CURRENT_TIMESTAMP, resolution=? WHERE conflict_id=?", (resolution, conflict_id))

    def resolve_matching_conflict(
        self, *, record_ref: str, remote_revision_id: str, reason: str, resolution: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conflicts SET resolved_at=CURRENT_TIMESTAMP, resolution=? "
                "WHERE record_ref=? AND remote_revision_id=? AND reason=? AND resolved_at IS NULL",
                (resolution, record_ref, remote_revision_id, reason),
            )

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            pending = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
            conflicts = conn.execute("SELECT COUNT(*) FROM conflicts WHERE resolved_at IS NULL").fetchone()[0]
        return {"pending": pending, "conflicts": conflicts, "cursor": self.get_meta("cursor")}

    def tree_heads(self, project_id: str) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tree_heads WHERE project_id=? ORDER BY file_id",
                (str(project_id),),
            ).fetchall()
        return {str(row["file_id"]): dict(row) for row in rows}

    def set_tree_head(
        self, *, project_id: str, file_id: str, revision_id: str,
        relative_path: str, deleted: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO tree_heads(project_id,file_id,revision_id,relative_path,deleted)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(project_id,file_id) DO UPDATE SET
                     revision_id=excluded.revision_id,
                     relative_path=excluded.relative_path,
                     deleted=excluded.deleted""",
                (project_id, file_id, revision_id, relative_path, int(deleted)),
            )


__all__ = ["CloudState"]
