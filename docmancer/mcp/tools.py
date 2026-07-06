"""MCP tool implementations (SDK-free).

Each function returns plain Python data so it can be unit-tested without the
``mcp`` SDK. ``server.py`` wraps these with FastMCP. Search tools touch only
local indexes; cloud tools run privacy filtering and require OPENROUTER_API_KEY.

Outputs are capped by a character budget so a tool call never floods the agent.
"""
from __future__ import annotations

_DEFAULT_LIMIT = 8
_CHAR_BUDGET = 6000


def _truncate(text: str, budget: int = _CHAR_BUDGET) -> str:
    if len(text) <= budget:
        return text
    return text[:budget] + "\n... [truncated]"


def memory_search(query: str, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Search the local memory index. Returns source-attributed excerpts."""
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
    from docmancer.memory import MemoryAgent

    return MemoryAgent().status()


def sources_list(agent: str | None = None, scope: str | None = None, kind: str | None = None) -> list[dict]:
    from docmancer.memory import MemoryAgent

    rows = MemoryAgent().sources()
    if agent:
        rows = [r for r in rows if r["agent"].lower() == agent.lower()]
    if scope:
        rows = [r for r in rows if r["scope"].startswith(scope.lower())]
    if kind:
        rows = [r for r in rows if r["type"].lower() == kind.lower()]
    return rows


# --- Optional cloud-backed tools (require OPENROUTER_API_KEY) ----------------


def _redacted_entries(limit: int):
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    return [agent.privacy.clean(e) for e in agent.preview()][:limit]


def memory_extract(limit: int = 30) -> dict:
    """Cloud: extract durable memory facts via OpenRouter."""
    from docmancer.ai.memory_features import extract_memory_facts
    from docmancer.ai.openrouter_client import OpenRouterClient, openrouter_api_key

    if not openrouter_api_key():
        return {"error": "OPENROUTER_API_KEY is not set"}
    entries = _redacted_entries(limit)
    if not entries:
        return {"facts": []}
    combined = "\n\n".join(f"### {e.title}\n{e.content}" for e in entries)
    try:
        client = OpenRouterClient()
        return extract_memory_facts(combined, {"entries": len(entries)}, client=client).model_dump()
    except Exception as exc:  # noqa: BLE001 - return an error payload, never raise to the client
        return {"error": f"OpenRouter extract failed: {exc}"}


def memory_consolidate_draft(query: str | None = None, limit: int = 60) -> dict:
    """Cloud: produce a review-only consolidated memory draft via OpenRouter."""
    from docmancer.ai.memory_features import consolidate_memory
    from docmancer.ai.openrouter_client import OpenRouterClient, openrouter_api_key

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
    "memory_extract",
    "memory_consolidate_draft",
]
