"""Hook-time memory recall for Claude Code and Codex.

This module is intentionally small and avoids importing the main CLI/provider
stack at import time. Hook commands run synchronously in the user's agent loop,
so slow or noisy failure is worse than returning no context.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOOK_LIMIT = 3
DEFAULT_HOOK_MAX_CHARS = 2_000
DEFAULT_HOOK_THRESHOLD = 0.01
DEFAULT_HOOK_TIMEOUT_MS = 1_000
_MAX_SEEN_FINGERPRINTS = 200


@dataclass(frozen=True)
class HookPayload:
    agent: str
    event: str
    session_id: str
    cwd: str
    prompt: str


def hook_timeout_ms() -> int:
    raw = os.environ.get("DOCMANCER_HOOK_TIMEOUT_MS", "").strip()
    if not raw:
        return DEFAULT_HOOK_TIMEOUT_MS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_HOOK_TIMEOUT_MS


def parse_hook_payload(raw: str, *, agent: str = "auto") -> HookPayload | None:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    event = str(data.get("hook_event_name") or data.get("hookEventName") or "")
    session_id = str(data.get("session_id") or data.get("sessionId") or "")
    cwd = str(data.get("cwd") or data.get("workspace_dir") or data.get("project_dir") or "")
    prompt = str(data.get("prompt") or data.get("user_prompt") or data.get("userPrompt") or "")

    if not event:
        return None
    if agent == "auto":
        # Codex payloads include model/permission_mode fields. Claude payloads
        # do not need detection for output formatting, but a stable label helps
        # tests and future diagnostics.
        agent = "codex" if "permission_mode" in data or "turn_id" in data else "claude-code"

    return HookPayload(agent=agent, event=event, session_id=session_id, cwd=cwd, prompt=prompt)


def _cache_root() -> Path:
    home = os.environ.get("DOCMANCER_HOME")
    base = Path(home) if home else Path.home() / ".docmancer"
    return base / "hook-cache"


def _session_cache_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return _cache_root() / f"{digest}.json"


def _load_seen(session_id: str) -> list[str]:
    path = _session_cache_path(session_id)
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - hook cache must never break recall
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def _save_seen(session_id: str, seen: list[str]) -> None:
    path = _session_cache_path(session_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen[-_MAX_SEEN_FINGERPRINTS:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - hook cache is best effort
        return


def _fingerprint(chunk) -> str:
    meta = chunk.metadata or {}
    source = str(meta.get("source_path") or chunk.source or "")
    text = " ".join((chunk.text or "").split())
    return hashlib.sha256(f"{source}\n{text[:500]}".encode("utf-8")).hexdigest()


def _one_line(text: str, *, max_len: int = 320) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def _short_source(path: str) -> str:
    if not path:
        return "unknown source"
    try:
        from docmancer.cli.ui import display_path

        return display_path(path)
    except Exception:  # noqa: BLE001 - hooks must stay best effort
        home = str(Path.home())
        if path.startswith(home):
            return "~" + path[len(home):]
        return path


def _format_context(chunks: list[Any], *, max_chars: int) -> str:
    lines = ["Relevant docmancer atomic memories:"]
    for chunk in chunks:
        meta = chunk.metadata or {}
        kind = meta.get("memory_type") or meta.get("kind") or "memory"
        scope = meta.get("scope") or "unknown scope"
        harness = meta.get("harness") or str(chunk.source or "").split(":", 1)[0] or "agent"
        source_path = _short_source(str(meta.get("source_path") or chunk.source or ""))
        excerpt = _one_line(chunk.text or "")
        lines.append(f"- {excerpt} Source: {harness}, {kind}, {scope}, {source_path}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def build_hook_context(
    payload: HookPayload,
    *,
    limit: int = DEFAULT_HOOK_LIMIT,
    max_chars: int = DEFAULT_HOOK_MAX_CHARS,
    threshold: float = DEFAULT_HOOK_THRESHOLD,
) -> str:
    if payload.event not in {"SessionStart", "UserPromptSubmit"}:
        return ""
    query = payload.prompt.strip()
    if not query and payload.event == "SessionStart":
        query = f"project context {payload.cwd}".strip()
    if not query:
        return ""

    from docmancer.memory import MemoryAgent

    chunks = MemoryAgent().query(
        query,
        limit=max(limit * 3, limit),
        mode="hybrid",
        project_path=payload.cwd or None,
    )
    if not chunks:
        return ""
    if max(float(getattr(chunk, "score", 0.0) or 0.0) for chunk in chunks) < threshold:
        return ""

    should_dedupe = payload.event == "UserPromptSubmit"
    seen_order = _load_seen(payload.session_id) if should_dedupe else []
    seen = set(seen_order)
    selected = []
    for chunk in chunks:
        if float(getattr(chunk, "score", 0.0) or 0.0) < threshold:
            continue
        fp = _fingerprint(chunk)
        if should_dedupe and fp in seen:
            continue
        selected.append(chunk)
        if should_dedupe:
            seen.add(fp)
            seen_order.append(fp)
        if len(selected) >= limit:
            break
    if not selected:
        return ""
    if should_dedupe:
        _save_seen(payload.session_id, seen_order)
    return _format_context(selected, max_chars=max_chars)


def hook_output(event: str, context: str) -> str:
    if not context.strip():
        return ""
    # Claude Code and Codex both accept this hook-specific additional-context
    # envelope for prompt and session hooks.
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        },
        ensure_ascii=False,
    )


__all__ = [
    "DEFAULT_HOOK_LIMIT",
    "DEFAULT_HOOK_MAX_CHARS",
    "DEFAULT_HOOK_THRESHOLD",
    "DEFAULT_HOOK_TIMEOUT_MS",
    "HookPayload",
    "build_hook_context",
    "hook_output",
    "hook_timeout_ms",
    "parse_hook_payload",
]
