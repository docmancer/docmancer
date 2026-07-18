"""MCP tool implementations (SDK-free).

Each function returns plain Python data so it can be unit-tested without the
``mcp`` SDK. ``server.py`` wraps these with FastMCP. Search tools touch only
local indexes; cloud tools run privacy filtering and require OPENROUTER_API_KEY.

Outputs are capped by a character budget so a tool call never floods the agent.
"""
from __future__ import annotations

import os

_DEFAULT_LIMIT = 8
_CHAR_BUDGET = 6000


def _truncate(text: str, budget: int = _CHAR_BUDGET) -> str:
    if len(text) <= budget:
        return text
    return text[:budget] + "\n... [truncated]"


def memory_search(query: str, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Search the local memory index. Returns source-attributed excerpts."""
    from docmancer.cli.ui import display_path
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    chunks = agent.query(query, limit=limit)
    out = []
    for c in chunks:
        meta = c.metadata or {}
        out.append(
            {
                "score": round(float(c.score), 4),
                "scope": meta.get("scope", ""),
                "kind": meta.get("kind", ""),
                "title": meta.get("title", ""),
                "source_path": meta.get("source_path", ""),
                "display_path": display_path(meta.get("source_path", "")),
                "excerpt": _truncate(c.text, 1200),
            }
        )
    return out


def docs_search(query: str, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Search the local docs index. Returns source-attributed excerpts."""
    from docmancer.cli.commands import _load_config

    config = _load_config(None)
    from docmancer.agent import DocmancerAgent
    from docmancer.retrieval.dispatch import RetrievalDispatcher
    from docmancer.embeddings import get_embeddings_provider
    from docmancer.stores.base import get_vector_store

    agent = DocmancerAgent(config=config)
    try:
        vector_store = get_vector_store(config.vector_store, embeddings_dim=config.embeddings.dimensions)
        provider = get_embeddings_provider(config.embeddings)
    except Exception:  # noqa: BLE001 - degrade to lexical
        vector_store, provider = None, None
    dispatcher = RetrievalDispatcher(
        store=agent.store,
        config=config,
        vector_store=vector_store,
        provider=provider,
        collection=agent._vector_collection_name(),
    )
    result = dispatcher.run(query, mode=config.retrieval.default_mode, limit=limit, allow_degraded=True)
    out = []
    for c in result.chunks:
        meta = c.metadata or {}
        out.append(
            {
                "score": round(float(c.score), 4),
                "source": meta.get("source", ""),
                "title": meta.get("title", meta.get("document_title", "")),
                "excerpt": _truncate(c.text, 1200),
            }
        )
    return out


def memory_status() -> dict:
    from docmancer.cli.ui import display_path
    from docmancer.memory import MemoryAgent

    status = MemoryAgent().status()
    status["display_path"] = display_path(status.get("db_path", ""))
    return status


def sources_list(agent: str | None = None, scope: str | None = None, kind: str | None = None) -> list[dict]:
    from docmancer.cli.ui import display_path
    from docmancer.memory import MemoryAgent

    rows = MemoryAgent().sources()
    if agent:
        rows = [r for r in rows if r["agent"].lower() == agent.lower()]
    if scope:
        rows = [r for r in rows if r["scope"].startswith(scope.lower())]
    if kind:
        rows = [r for r in rows if r["type"].lower() == kind.lower()]
    rows = [dict(r, display_path=display_path(r.get("path", ""))) for r in rows]
    return rows


def memory_add(
    text: str,
    *,
    scope: str = "global",
    project_path: str | None = None,
    memory_type: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    from docmancer.memory import MemoryAgent

    record, indexed = MemoryAgent().add_record(
        text,
        scope_kind=scope,
        project_path=project_path,
        memory_type=memory_type,
        tags=tags or [],
        origin="mcp",
    )
    return {
        "record_id": record.record_id,
        "scope": record.scope,
        "type": record.type,
        "source_path": record.source_path,
        "indexed": indexed,
    }


def memory_list(
    *,
    scope: str | None = None,
    memory_type: str | None = None,
    origin: str | None = None,
    limit: int = 100,
) -> list[dict]:
    from docmancer.memory import MemoryAgent

    atoms = MemoryAgent().indexed_atoms()
    if scope:
        atoms = [atom for atom in atoms if atom.scope_kind == scope]
    if memory_type:
        atoms = [atom for atom in atoms if atom.type == memory_type]
    if origin:
        atoms = [atom for atom in atoms if atom.origin == origin]
    return [
        {
            "id": atom.record_id or atom.atom_id,
            "atom_id": atom.atom_id,
            "record_id": atom.record_id,
            "text": _truncate(atom.text, 1200),
            "type": atom.type,
            "scope": atom.scope,
            "origin": atom.origin,
            "source_path": atom.source_path,
        }
        for atom in atoms[: max(0, limit)]
    ]


def memory_show(identifier: str) -> dict:
    from docmancer.memory import MemoryAgent

    atom = MemoryAgent().find_atom(identifier)
    if atom is None:
        return {"error": "memory id is missing or ambiguous"}
    return {
        "id": atom.record_id or atom.atom_id,
        "atom_id": atom.atom_id,
        "record_id": atom.record_id,
        "text": atom.text,
        "type": atom.type,
        "scope": atom.scope,
        "origin": atom.origin,
        "tags": atom.tags,
        "source_path": atom.source_path,
        "merged_from": atom.merged_from,
    }


def memory_forget(identifier: str, *, confirm: bool = False) -> dict:
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    atom = agent.find_atom(identifier)
    if atom is None:
        return {"error": "memory id is missing or ambiguous"}
    if not confirm:
        return {
            "requires_confirmation": True,
            "id": atom.record_id or atom.atom_id,
            "text": _truncate(atom.text, 500),
            "action": "remove owned record" if atom.record_id else "suppress harvested atom",
        }
    try:
        forgotten = agent.forget(identifier)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"forgotten": True, "id": forgotten.record_id or forgotten.atom_id}


def memory_promote(identifier: str, *, project_path: str, confirm: bool = False) -> dict:
    from pathlib import Path
    from docmancer.memory import MemoryAgent

    project = Path(project_path).expanduser().resolve()
    agent = MemoryAgent()
    atom = agent.find_atom(identifier)
    if atom is None:
        return {"error": "memory id is missing or ambiguous"}
    if not confirm:
        return {
            "requires_confirmation": True,
            "id": atom.record_id or atom.atom_id,
            "text": _truncate(atom.text, 500),
            "destination": str(project / ".docmancer" / "memory"),
        }
    try:
        record, indexed = agent.promote(identifier, project_path=project)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"promoted": True, "record_id": record.record_id, "source_path": record.source_path, "indexed": indexed}


# --- Optional cloud-backed tools (require OPENROUTER_API_KEY) ----------------


def _blocked_by_recursion() -> dict | None:
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        return {"error": "docmancer MCP memory drafting is disabled inside docmancer subprocesses"}
    return None


def _redacted_entries(limit: int):
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    return [agent.privacy.clean(e) for e in agent.preview()][:limit]


def memory_consolidate_draft(query: str | None = None, limit: int = 60) -> dict:
    """Cloud: produce a review-only consolidated memory draft via OpenRouter."""
    from docmancer.ai.memory_features import consolidate_memory
    from docmancer.ai.openrouter_client import OpenRouterClient, openrouter_api_key

    blocked = _blocked_by_recursion()
    if blocked:
        return blocked
    if not openrouter_api_key():
        return {"error": "OPENROUTER_API_KEY is not set"}
    entries = _redacted_entries(limit)
    if not entries:
        return {"error": "no memory entries"}
    payload = [
        {"scope": e.scope, "title": e.title, "source_path": e.path, "text": e.content}
        for e in entries
    ]
    try:
        client = OpenRouterClient()
        return consolidate_memory(payload, instruction=query, client=client).model_dump()
    except Exception as exc:  # noqa: BLE001 - return an error payload, never raise to the client
        return {"error": f"OpenRouter consolidate failed: {exc}"}


__all__ = [
    "memory_search",
    "docs_search",
    "memory_status",
    "sources_list",
    "memory_consolidate_draft",
]
