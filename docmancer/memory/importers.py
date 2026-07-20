"""One-shot importers for user-owned conversation account exports."""
from __future__ import annotations

import json
from pathlib import Path

from docmancer.harness.base import MemoryEntry
from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import AtomicMemoryEntry, extract_atoms


def _message_text(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_message_text(item))
        return output
    if not isinstance(value, dict):
        return []
    output = []
    for key in ("text", "content", "parts", "message"):
        if key in value:
            output.extend(_message_text(value[key]))
    return output


def _chatgpt_conversation(item: dict) -> tuple[str, list[str]]:
    title = str(item.get("title") or "Imported ChatGPT conversation")
    messages = []
    mapping = item.get("mapping") or {}
    if isinstance(mapping, dict):
        nodes = sorted(
            (node for node in mapping.values() if isinstance(node, dict)),
            key=lambda node: float((node.get("message") or {}).get("create_time") or 0),
        )
        for node in nodes:
            message = node.get("message") or {}
            role = str((message.get("author") or {}).get("role") or "")
            if role in {"user", "assistant"}:
                messages.extend(_message_text(message.get("content")))
    return title, messages


def _claude_conversation(item: dict) -> tuple[str, list[str]]:
    title = str(item.get("name") or item.get("title") or "Imported Claude conversation")
    messages = []
    for message in item.get("chat_messages") or item.get("messages") or []:
        if isinstance(message, dict) and str(message.get("sender") or message.get("role") or "") in {
            "human", "assistant", "user",
        }:
            messages.extend(_message_text(message.get("text") or message.get("content")))
    return title, messages


def conversation_atoms(
    path: str | Path,
    *,
    source: str = "auto",
    scope_kind: str = "global",
    project_path: str | Path | None = None,
) -> list[AtomicMemoryEntry]:
    export_path = Path(path).expanduser()
    data = json.loads(export_path.read_text(encoding="utf-8"))
    conversations = data if isinstance(data, list) else data.get("conversations", [])
    if not isinstance(conversations, list):
        raise ValueError("conversation export must contain a JSON array")
    detected = source
    if source == "auto":
        first = next((item for item in conversations if isinstance(item, dict)), {})
        detected = "chatgpt" if "mapping" in first else "claude"
    if detected not in {"chatgpt", "claude"}:
        raise ValueError("source must be auto, chatgpt, or claude")
    parser = _chatgpt_conversation if detected == "chatgpt" else _claude_conversation
    scope = "global:docmancer" if scope_kind == "global" else f"{scope_kind}:{Path(project_path or Path.cwd()).resolve()}"
    output: list[AtomicMemoryEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(conversations):
        if not isinstance(item, dict):
            continue
        title, messages = parser(item)
        content = "\n\n".join(redact_secrets(message) for message in messages if message.strip())
        entry = MemoryEntry(
            harness=f"{detected}-export",
            scope=scope,
            title=title,
            content=content,
            path=f"conversation-export://{detected}/{index}",
            extra={"kind": "conversation-import"},
        )
        for atom in extract_atoms(entry):
            if atom.content_hash in seen:
                continue
            seen.add(atom.content_hash)
            output.append(atom)
    return output


__all__ = ["conversation_atoms"]
