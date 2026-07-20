"""Best-effort local lifecycle capture for Claude Code and Codex."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docmancer.harness.base import MemoryEntry
from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import extract_atoms


MAX_CAPTURE_INPUT_CHARS = 16_000
MAX_CAPTURE_ATOMS = 8
_DURABLE_TYPES = {"decision", "preference", "constraint", "workflow", "warning", "fact", "command"}


def _strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            out.extend(_strings(item))
    elif isinstance(value, dict):
        for key in ("text", "content", "message", "output_text", "last_assistant_message"):
            if key in value:
                out.extend(_strings(value[key]))
    return out


def transcript_tail(path: str | None) -> str:
    if not path:
        return ""
    transcript = Path(path).expanduser()
    if not transcript.is_file():
        return ""
    try:
        with transcript.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - 128_000))
            raw = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""
    candidates: list[str] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = str(item.get("role") or (item.get("message") or {}).get("role") or "").lower()
        item_type = str(item.get("type") or "").lower()
        if role == "assistant" or item_type in {"agent_message", "assistant", "response_item"}:
            candidates.extend(_strings(item))
    return candidates[-1] if candidates else ""


def capture_text(payload: dict) -> str:
    if payload.get("background_tasks") or payload.get("session_crons"):
        return ""
    for key in ("compact_summary", "last_assistant_message", "last_agent_message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:MAX_CAPTURE_INPUT_CHARS]
    return transcript_tail(payload.get("transcript_path"))[:MAX_CAPTURE_INPUT_CHARS]


def capture_candidates(payload: dict, *, agent: str) -> list[dict]:
    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
    supported = {
        "claude-code": {"PostCompact", "SessionEnd"},
        "codex": {"PreCompact", "Stop"},
    }
    if event not in supported.get(agent, set()):
        return []
    text = " ".join(redact_secrets(capture_text(payload)).split()).strip()
    if len(text) < 40:
        return []
    lowered = text.lower()
    if lowered in {"done", "completed", "no changes", "nothing to report"}:
        return []
    cwd = str(payload.get("cwd") or "")
    entry = MemoryEntry(
        harness="docmancer-capture",
        scope=f"project:{cwd}" if cwd else "global:docmancer",
        title=f"{agent} {event}",
        content=text,
        path=f"capture://{agent}/{payload.get('session_id') or 'unknown'}/{event}",
        extra={"kind": "captured-memory"},
    )
    atoms = [atom for atom in extract_atoms(entry) if atom.type in _DURABLE_TYPES]
    seen: set[str] = set()
    out: list[dict] = []
    for atom in atoms:
        if atom.content_hash in seen:
            continue
        seen.add(atom.content_hash)
        out.append({"text": atom.text, "type": atom.type, "tags": atom.tags})
        if len(out) >= MAX_CAPTURE_ATOMS:
            break
    return out


def capture_payload(payload: dict, *, agent: str) -> tuple[int, bool]:
    from docmancer.memory import MemoryAgent, SyncInProgressError
    from docmancer.memory.records import normalize_memory_text

    candidates = capture_candidates(payload, agent=agent)
    if not candidates:
        return 0, False
    memory = MemoryAgent()
    if not memory.config.capture.allows(agent):
        return 0, False
    cwd = payload.get("cwd") or None
    project_paths = [cwd] if cwd else None
    existing_texts = {normalize_memory_text(atom.text) for atom in memory.indexed_atoms()}
    existing_texts.update(
        normalize_memory_text(record.text)
        for record in memory.records.records(project_paths=project_paths)
    )
    created = 0
    created_records = []
    session_id = str(payload.get("session_id") or "") or None
    for candidate in candidates:
        normalized = normalize_memory_text(candidate["text"])
        if normalized in existing_texts:
            continue
        record, _ = memory.add_record(
            candidate["text"],
            scope_kind="project" if cwd else "global",
            project_path=cwd,
            memory_type=candidate["type"],
            tags=candidate["tags"],
            origin="capture",
            session_id=session_id,
            sync_index=False,
        )
        created_records.append(record)
        existing_texts.add(normalized)
        created += 1
    if not created:
        return 0, False
    try:
        memory.index_records(created_records)
        return created, True
    except SyncInProgressError:
        return created, False


__all__ = ["capture_candidates", "capture_payload", "capture_text", "transcript_tail"]
