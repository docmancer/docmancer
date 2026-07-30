"""Durable local Ask history, deliberately separate from memory evidence."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_EXPLICIT_MACHINE_MUTATION_RE = re.compile(
    r"\b(?:remember|save|update|edit|move|duplicate|delete|remove|forget|trash|restore)\b"
    r".*\b(?:shared memory|canonical memory|machine[- ]wide|global(?:ly)?|all memory files)\b",
    re.IGNORECASE | re.DOTALL,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def _title(text: str) -> str:
    single_line = " ".join(text.split())
    if not single_line:
        return "New conversation"
    return single_line if len(single_line) <= 58 else f"{single_line[:57].rstrip()}…"


class AskHistoryStore:
    """Store workbench conversations without making them memory sources."""

    def __init__(self, path: str | Path, *, project_id: str, project_label: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.project_id = project_id
        self.project_label = project_label
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ask_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    project_label TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    last_message_preview TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS ask_conversations_project_updated_idx
                    ON ask_conversations(project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS ask_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL
                        REFERENCES ask_conversations(conversation_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('pending', 'complete', 'failed')),
                    provider TEXT,
                    model TEXT,
                    token_estimate INTEGER,
                    cost_usd REAL,
                    index_revision TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ask_messages_conversation_created_idx
                    ON ask_messages(conversation_id, created_at, message_id);

                CREATE TABLE IF NOT EXISTS ask_actions (
                    action_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL
                        REFERENCES ask_conversations(conversation_id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL
                        REFERENCES ask_messages(message_id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ask_actions_message_idx
                    ON ask_actions(message_id);
                CREATE INDEX IF NOT EXISTS ask_actions_target_status_idx
                    ON ask_actions(conversation_id, target, status);
                """
            )

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("conversation id is invalid")
        return value

    def create_conversation(self) -> dict[str, Any]:
        conversation_id = _identifier("chat")
        stamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ask_conversations(
                    conversation_id, project_id, project_label, title,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    conversation_id,
                    self.project_id,
                    self.project_label,
                    "New conversation",
                    stamp,
                    stamp,
                ),
            )
        return self.get_conversation(conversation_id, include_messages=False) or {}

    def list_conversations(self, *, limit: int = 60) -> list[dict[str, Any]]:
        bounded = min(max(int(limit), 1), 200)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ask_conversations
                WHERE project_id=?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (self.project_id, bounded),
            ).fetchall()
        return [self._conversation(row) for row in rows]

    def get_conversation(
        self,
        conversation_id: str,
        *,
        include_messages: bool = True,
    ) -> dict[str, Any] | None:
        identifier = self._validate_id(conversation_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM ask_conversations
                WHERE conversation_id=? AND project_id=?
                """,
                (identifier, self.project_id),
            ).fetchone()
            if row is None:
                return None
            result = self._conversation(row)
            if include_messages:
                messages = connection.execute(
                    """
                    SELECT * FROM ask_messages
                    WHERE conversation_id=?
                    ORDER BY rowid
                    """,
                    (identifier,),
                ).fetchall()
                actions = connection.execute(
                    """
                    SELECT * FROM ask_actions
                    WHERE conversation_id=?
                    ORDER BY rowid
                    """,
                    (identifier,),
                ).fetchall()
                by_message = {
                    str(action["message_id"]): self._action(action)
                    for action in actions
                }
                result["messages"] = [
                    {
                        **self._message(message),
                        "action": by_message.get(str(message["message_id"])),
                    }
                    for message in messages
                ]
        return result

    def recent_messages(self, conversation_id: str, *, limit: int = 6) -> list[dict[str, str]]:
        identifier = self._validate_id(conversation_id)
        bounded = max(1, min(int(limit), 20))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content FROM ask_messages
                WHERE conversation_id=? AND status='complete'
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (identifier, bounded),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def pending_action_context(self, conversation_id: str) -> dict[str, Any]:
        """Return the unfinished action thread, if the last action turn needs input."""
        identifier = self._validate_id(conversation_id)
        with self._connect() as connection:
            pending = connection.execute(
                """
                SELECT * FROM ask_actions
                WHERE conversation_id=? AND status='pending'
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (identifier,),
            ).fetchone()
            assistant = connection.execute(
                """
                SELECT metadata_json FROM ask_messages
                WHERE conversation_id=? AND role='assistant' AND status='complete'
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (identifier,),
            ).fetchone()
            recent_users = connection.execute(
                """
                SELECT content FROM ask_messages
                WHERE conversation_id=? AND role='user' AND status='complete'
                ORDER BY rowid DESC
                LIMIT 20
                """,
                (identifier,),
            ).fetchall()
        result: dict[str, Any] = {
            "pending_action": self._action(pending) if pending is not None else None,
            "clarification_request": None,
            "clarification_count": 0,
        }
        if assistant is None:
            return result
        try:
            metadata = json.loads(str(assistant["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            return result
        if metadata.get("action_kind") in {"clarification", "unavailable"}:
            request = str(metadata.get("action_request") or "").strip()
            if not request and metadata.get("action_kind") == "unavailable":
                request = next(
                    (
                        str(row["content"]).strip()
                        for row in recent_users
                        if _EXPLICIT_MACHINE_MUTATION_RE.search(str(row["content"]))
                    ),
                    "",
                )
            result["clarification_request"] = request or None
            result["clarification_count"] = int(metadata.get("action_clarification_count") or 1)
        return result

    def begin_exchange(self, conversation_id: str, task: str) -> tuple[str, str]:
        identifier = self._validate_id(conversation_id)
        task = task.strip()
        if not task:
            raise ValueError("task is required")
        user_id = _identifier("msg")
        assistant_id = _identifier("msg")
        stamp = _now()
        with self._connect() as connection:
            conversation = connection.execute(
                """
                SELECT title, message_count FROM ask_conversations
                WHERE conversation_id=? AND project_id=?
                """,
                (identifier, self.project_id),
            ).fetchone()
            if conversation is None:
                raise KeyError("conversation not found")
            connection.execute(
                """
                INSERT INTO ask_messages(
                    message_id, conversation_id, role, content, status,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (user_id, identifier, "user", task, "complete", stamp, stamp),
            )
            connection.execute(
                """
                INSERT INTO ask_messages(
                    message_id, conversation_id, role, content, status,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (assistant_id, identifier, "assistant", "", "pending", stamp, stamp),
            )
            first_message = int(conversation["message_count"]) == 0
            connection.execute(
                """
                UPDATE ask_conversations
                SET title=?, updated_at=?, message_count=message_count+2,
                    last_message_preview=?
                WHERE conversation_id=?
                """,
                (
                    _title(task) if first_message else str(conversation["title"]),
                    stamp,
                    _title(task),
                    identifier,
                ),
            )
        return user_id, assistant_id

    def complete_answer(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        status: str = "complete",
    ) -> None:
        identifier = self._validate_id(conversation_id)
        if status not in {"complete", "failed"}:
            raise ValueError("answer status must be complete or failed")
        details = dict(metadata or {})
        stamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE ask_messages
                SET content=?, status=?, provider=?, model=?, token_estimate=?,
                    cost_usd=?, index_revision=?, metadata_json=?, updated_at=?
                WHERE message_id=? AND conversation_id=? AND role='assistant'
                """,
                (
                    content,
                    status,
                    details.get("provider"),
                    details.get("model"),
                    details.get("token_estimate"),
                    details.get("cost_usd"),
                    details.get("index_revision"),
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    stamp,
                    message_id,
                    identifier,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("answer message not found")
            connection.execute(
                """
                UPDATE ask_conversations
                SET updated_at=?, last_message_preview=?
                WHERE conversation_id=? AND project_id=?
                """,
                (stamp, _title(content), identifier, self.project_id),
            )

    def save_action(
        self,
        conversation_id: str,
        message_id: str,
        proposal: dict[str, Any],
    ) -> dict[str, Any]:
        from docmancer.memory.actions import new_action_id

        identifier = self._validate_id(conversation_id)
        action_id = str(proposal.get("id") or new_action_id())
        self._validate_id(action_id)
        target = str(proposal.get("address") or proposal.get("restore_token") or proposal.get("path") or "")
        stamp = _now()
        payload = {**proposal, "id": action_id, "status": "pending", "created_at": stamp}
        with self._connect() as connection:
            message = connection.execute(
                """
                SELECT message_id FROM ask_messages
                WHERE message_id=? AND conversation_id=? AND role='assistant'
                """,
                (message_id, identifier),
            ).fetchone()
            if message is None:
                raise KeyError("assistant message not found")
            connection.execute(
                """
                UPDATE ask_actions
                SET status='superseded', resolved_at=?
                WHERE conversation_id=? AND target=? AND status='pending'
                """,
                (stamp, identifier, target),
            )
            connection.execute(
                """
                INSERT INTO ask_actions(
                    action_id, conversation_id, message_id, project_id,
                    operation, scope, target, status, proposal_json,
                    result_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    action_id,
                    identifier,
                    message_id,
                    self.project_id,
                    str(proposal["operation"]),
                    str(proposal["scope"]),
                    target,
                    "pending",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    "{}",
                    stamp,
                ),
            )
        return payload

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        identifier = self._validate_id(action_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM ask_actions
                WHERE action_id=? AND project_id=?
                """,
                (identifier, self.project_id),
            ).fetchone()
        return self._action(row) if row is not None else None

    def resolve_action(
        self,
        action_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from docmancer.memory.actions import ACTION_STATUSES

        if status not in ACTION_STATUSES or status == "pending":
            raise ValueError("action status is invalid")
        identifier = self._validate_id(action_id)
        stamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE ask_actions
                SET status=?, result_json=?, resolved_at=?
                WHERE action_id=? AND project_id=? AND status='pending'
                """,
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False, sort_keys=True),
                    stamp,
                    identifier,
                    self.project_id,
                ),
            )
            if cursor.rowcount != 1:
                existing = connection.execute(
                    "SELECT status FROM ask_actions WHERE action_id=? AND project_id=?",
                    (identifier, self.project_id),
                ).fetchone()
                if existing is None:
                    raise KeyError("memory action not found")
                raise ValueError(f"memory action is already {existing['status']}")
        action = self.get_action(identifier)
        assert action is not None
        return action

    def delete_conversation(self, conversation_id: str) -> bool:
        identifier = self._validate_id(conversation_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM ask_conversations
                WHERE conversation_id=? AND project_id=?
                """,
                (identifier, self.project_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _conversation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["conversation_id"]),
            "title": str(row["title"]),
            "project_id": str(row["project_id"]),
            "project_label": str(row["project_label"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "message_count": int(row["message_count"]),
            "preview": str(row["last_message_preview"]),
        }

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        return {
            "id": str(row["message_id"]),
            "conversation_id": str(row["conversation_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "status": str(row["status"]),
            "provider": row["provider"],
            "model": row["model"],
            "token_estimate": row["token_estimate"],
            "cost_usd": row["cost_usd"],
            "index_revision": row["index_revision"],
            "evidence": metadata.get("evidence") or [],
            "metadata": metadata,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _action(row: sqlite3.Row) -> dict[str, Any]:
        try:
            proposal = json.loads(str(row["proposal_json"] or "{}"))
        except json.JSONDecodeError:
            proposal = {}
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except json.JSONDecodeError:
            result = {}
        return {
            **proposal,
            "id": str(row["action_id"]),
            "operation": str(row["operation"]),
            "scope": str(row["scope"]),
            "target": str(row["target"]),
            "status": str(row["status"]),
            "result": result,
            "created_at": str(row["created_at"]),
            "resolved_at": row["resolved_at"],
        }


__all__ = ["AskHistoryStore"]
