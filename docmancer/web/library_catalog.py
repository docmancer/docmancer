"""Disposable SQLite summary catalog for the local human Library."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from docmancer.core.sqlite import connect


class LibraryCatalog:
    """Index lightweight list metadata while canonical content stays elsewhere."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_records (
                    corpus TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT '',
                    agent TEXT NOT NULL DEFAULT '',
                    project_label TEXT NOT NULL DEFAULT '',
                    scope_label TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    source_count INTEGER NOT NULL DEFAULT 0,
                    section_count INTEGER NOT NULL DEFAULT 0,
                    content_fingerprint TEXT NOT NULL DEFAULT '',
                    detail_key TEXT NOT NULL,
                    PRIMARY KEY (corpus, record_id)
                );
                CREATE INDEX IF NOT EXISTS library_records_order
                    ON library_records (corpus, updated_at DESC, title, record_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS library_records_fts USING fts5(
                    corpus UNINDEXED,
                    record_id UNINDEXED,
                    title,
                    summary,
                    kind,
                    agent,
                    project_label,
                    scope_label
                );
                CREATE TABLE IF NOT EXISTS library_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def replace(self, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
        rows = list(records)
        indexed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM library_records")
            connection.execute("DELETE FROM library_records_fts")
            for row in rows:
                values = (
                    str(row.get("corpus") or ""),
                    str(row.get("record_id") or ""),
                    str(row.get("title") or "Untitled"),
                    str(row.get("summary") or ""),
                    str(row.get("kind") or ""),
                    str(row.get("agent") or ""),
                    str(row.get("project_label") or ""),
                    str(row.get("scope_label") or ""),
                    str(row.get("updated_at") or ""),
                    int(row.get("source_count") or 0),
                    int(row.get("section_count") or 0),
                    str(row.get("content_fingerprint") or ""),
                    str(row.get("detail_key") or row.get("record_id") or ""),
                )
                connection.execute(
                    """
                    INSERT INTO library_records (
                        corpus, record_id, title, summary, kind, agent,
                        project_label, scope_label, updated_at, source_count,
                        section_count, content_fingerprint, detail_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                connection.execute(
                    """
                    INSERT INTO library_records_fts (
                        corpus, record_id, title, summary, kind, agent,
                        project_label, scope_label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values[:8],
                )
            connection.execute(
                "INSERT OR REPLACE INTO library_meta (key, value) VALUES ('last_indexed_at', ?)",
                (indexed_at,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO library_meta (key, value) VALUES ('record_count', ?)",
                (str(len(rows)),),
            )
        return {"records": len(rows), "last_indexed_at": indexed_at}

    @staticmethod
    def _query_digest(corpus: str, query: str) -> str:
        return hashlib.sha256(f"{corpus}\0{query}".encode()).hexdigest()[:12]

    @classmethod
    def _encode_cursor(cls, offset: int, corpus: str, query: str) -> str:
        payload = json.dumps(
            {"offset": offset, "query": cls._query_digest(corpus, query)},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def _decode_cursor(cls, cursor: str | None, corpus: str, query: str) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded).decode())
            if value.get("query") != cls._query_digest(corpus, query):
                raise ValueError("cursor does not match the current Library query")
            return max(0, int(value.get("offset") or 0))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid Library cursor") from exc

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = [token.replace('"', "") for token in query.split() if token.replace('"', "")]
        return " AND ".join(f'"{token}"*' for token in tokens)

    def list(
        self,
        *,
        corpus: str,
        query: str = "",
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        limit = max(1, min(100, int(limit)))
        query = query.strip()
        offset = self._decode_cursor(cursor, corpus, query)
        parameters: list[Any] = [corpus]
        join = ""
        where = "WHERE records.corpus = ?"
        if query:
            join = (
                "JOIN library_records_fts "
                "ON library_records_fts.corpus = records.corpus "
                "AND library_records_fts.record_id = records.record_id"
            )
            where += " AND library_records_fts MATCH ?"
            parameters.append(self._fts_query(query))
        parameters.extend([limit + 1, offset])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT records.*
                FROM library_records AS records
                {join}
                {where}
                ORDER BY records.updated_at DESC, records.title, records.record_id
                LIMIT ? OFFSET ?
                """,
                parameters,
            ).fetchall()
            last_indexed = connection.execute(
                "SELECT value FROM library_meta WHERE key = 'last_indexed_at'"
            ).fetchone()
        has_more = len(rows) > limit
        visible = rows[:limit]
        return {
            "items": [dict(row) for row in visible],
            "next_cursor": self._encode_cursor(offset + limit, corpus, query) if has_more else None,
            "last_indexed_at": last_indexed["value"] if last_indexed else None,
        }

    def detail_key(self, corpus: str, record_id: str) -> str | None:
        row = self.record(corpus, record_id)
        return str(row["detail_key"]) if row else None

    def record(self, corpus: str, record_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_records WHERE corpus = ? AND record_id = ?",
                (corpus, record_id),
            ).fetchone()
        return dict(row) if row else None

    def has_records(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM library_records LIMIT 1").fetchone()
        return row is not None


__all__ = ["LibraryCatalog"]
