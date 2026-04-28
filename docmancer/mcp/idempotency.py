"""Idempotency-key generation and reuse per spec 2.8.1 / 2.8.6 / D17."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from docmancer.mcp import paths

EXPLICIT_KEY_ARG = "_docmancer_idempotency_key"
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h matches the most common API idempotency window


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or paths.idempotency_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            fingerprint TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    return conn


def _fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    scrubbed = {k: v for k, v in args.items() if k != EXPLICIT_KEY_ARG}
    payload = tool_name + "|" + json.dumps(scrubbed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def get_or_create_key(
    tool_name: str,
    args: dict[str, Any],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    db_path: Path | None = None,
    now: float | None = None,
) -> tuple[str, bool]:
    """Return (idempotency_key, was_reused).

    Resolution order: explicit `_docmancer_idempotency_key` arg, then SQLite
    fingerprint cache, then a fresh UUID4.
    """
    explicit = args.get(EXPLICIT_KEY_ARG)
    if isinstance(explicit, str) and explicit:
        return explicit, True

    fp = _fingerprint(tool_name, args)
    now = int(now if now is not None else time.time())
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT key, expires_at FROM idempotency_keys WHERE fingerprint = ?",
            (fp,),
        ).fetchone()
        if row and row[1] > now:
            return row[0], True
        new_key = str(uuid.uuid4())
        conn.execute(
            "INSERT OR REPLACE INTO idempotency_keys "
            "(fingerprint, key, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (fp, new_key, now, now + ttl_seconds),
        )
        conn.commit()
        return new_key, False
    finally:
        conn.close()
