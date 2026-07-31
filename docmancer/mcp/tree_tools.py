"""MCP tool implementations for the tree-memory surface (checklist A.12).

SDK-free, like ``docmancer.mcp.tools``: every function here returns plain
Python data (dict / list[dict]) so it can be unit-tested without the ``mcp``
SDK, and ``docmancer.mcp.server.build_server`` wraps these with
``@server.tool``. This module is purely additive -- it does not change any
existing tool in ``docmancer.mcp.tools`` or ``docmancer.mcp.server``.

## Root resolution convention

Every tool accepts an optional ``project_path``. This chooses between two
roots, both distinct from every existing memory location on disk so a tree
root can never collide with the ``.md`` record files the legacy
``MemoryRecordStore``/``docmancer_memory_add`` path already writes:

- ``project_path`` given (project scope): ``<project_path>/.docmancer/tree``.
  This sits next to (not inside) the legacy record directory
  ``<project_path>/.docmancer/memory``, written by releases that still had a
  team scope. Same parent, different leaf, so nothing already written there
  is at risk.
- ``project_path`` omitted (global scope): ``<DOCMANCER_HOME>/tree``, where
  ``DOCMANCER_HOME`` follows the exact same env-var/default convention as
  ``docmancer.memory.records.MemoryRecordStore`` (``DOCMANCER_HOME`` or
  ``~/.docmancer``). That store's personal records live under
  ``<DOCMANCER_HOME>/memories``; the tree root lives under
  ``<DOCMANCER_HOME>/tree`` -- a sibling directory, never ``memories``
  itself, so the two storage generations cannot collide even though they
  share a parent.

Each call constructs its own ``TreeStore`` pinned to the resolved root.
Constructing the store is read-only and does not create a missing tree.
Mutation methods create only the parent directories needed for the requested
write.
"""
from __future__ import annotations

import os
from pathlib import Path

from docmancer.memory.tree.compiler import ContextRequest, compile_context, context_bundle_payload
from docmancer.memory.tree.errors import TreeError
from docmancer.memory.tree.parser import TreeMemoryFile
from docmancer.memory.tree.store import TreeStore

_DEFAULT_SEARCH_LIMIT = 8
_MAX_SEARCH_LIMIT = 50
_MAX_BODY_CHARS = 50_000


def _global_tree_root() -> Path:
    home = os.getenv("DOCMANCER_HOME")
    base = Path(home) if home else Path.home() / ".docmancer"
    return base / "tree"


def _project_tree_root(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / ".docmancer" / "tree"


def _resolve_root(project_path: str | None) -> Path:
    if project_path:
        return _project_tree_root(project_path)
    return _global_tree_root()


def _store_for(project_path: str | None = None) -> TreeStore:
    return TreeStore(_resolve_root(project_path))


def _error_payload(exc: TreeError) -> dict:
    """Structured, agent-recoverable error (checklist A.13). Never raised
    up through FastMCP -- every tool below catches ``TreeError`` and
    returns this shape instead."""
    payload: dict = {
        "error": str(exc),
        "error_type": type(exc).__name__,
        "likely_cause": exc.likely_cause,
        "retry_safe": exc.retry_safe,
    }
    next_action = getattr(exc, "next_action", None)
    if next_action:
        payload["next_action"] = next_action
    candidates = getattr(exc, "candidates", None)
    if candidates:
        payload["candidates"] = candidates
    return payload


def _entry_payload(entry: TreeMemoryFile) -> dict:
    return {
        "address": entry.address,
        "title": entry.title,
        "type": entry.type,
        "scope": entry.scope,
        "authority": entry.authority,
        "project_id": entry.project_id,
        "status": entry.status,
        "tags": entry.tags,
        "sources": entry.sources,
        "content_hash": entry.content_hash,
        "revision_id": entry.revision_id,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "body": entry.body,
    }


def write_memory(
    relative_path: str,
    text: str,
    *,
    memory_type: str = "fact",
    scope: str = "global",
    authority: str = "advisory",
    project_id: str | None = None,
    project_path: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    status: str = "active",
    curation_origin: str = "deliberate_write",
    expect: str | None = "absent",
) -> dict:
    """Create or update one curated memory file. MUTATING.

    ``expect`` is ``"absent"`` (default, create-only -- fails with
    ``AlreadyExistsError`` if ``relative_path`` already has a file),
    ``None`` (also create-only), or the current ``content_hash`` of an
    existing file (guarded update -- fails with ``StaleWriteError`` if the
    file changed since that hash was read). ``project_path`` pins the
    write to that project's tree root; omit it for the global root. On
    success, returns the stable address, content hash, and revision id an
    agent should keep for a follow-up ``edit_memory``/``move_memory`` call.
    """
    try:
        store = _store_for(project_path)
        entry = store.write(
            relative_path=relative_path,
            text=text,
            memory_type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id,
            sources=sources,
            status=status,
            tags=tags,
            curation_origin=curation_origin,
            expect=expect,
            actor_surface="mcp",
        )
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    payload["indexed"] = True
    payload["safe_next_action"] = (
        f"To update this memory later, call edit_memory(address={entry.address!r}, "
        f"expected_hash={entry.content_hash!r})."
    )
    return payload


def read_memory(address: str, *, project_path: str | None = None) -> dict:
    """Read one memory file by stable address (``docmancer://memory/<id>``),
    relative path, or exact title. READ-ONLY -- never mutates the tree.

    On an ambiguous title/path match, returns a structured error whose
    ``candidates`` list every matching address; retry with one of those.
    """
    try:
        store = _store_for(project_path)
        entry = store.read(address)
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    if len(payload["body"]) > _MAX_BODY_CHARS:
        payload["body"] = payload["body"][:_MAX_BODY_CHARS]
        payload["truncated"] = True
        payload["next_action"] = "Open the canonical file locally or narrow the requested memory."
    return payload


def edit_memory(
    address: str,
    text: str,
    *,
    expected_hash: str,
    project_path: str | None = None,
) -> dict:
    """Replace the body of one memory file, preserving all other
    frontmatter (type, scope, authority, tags, sources, ...). MUTATING.

    ``expected_hash`` must be the file's current ``content_hash`` (from a
    prior ``read_memory``/``write_memory`` call). A stale hash fails with
    a structured ``StaleWriteError`` payload naming the safe next call:
    re-read the address and retry with the fresh hash.

    Automatically reconciled files (the canonical sections) carry a generated
    zone that is rewritten on every sync. An edit that changes that zone fails
    with a ``generated_zone_readonly`` payload naming ``pin_memory`` instead,
    because the edit would otherwise be silently discarded on the next sync.
    """
    from docmancer.memory.tree.zones import ZoneViolation, guard_zoned_write

    try:
        store = _store_for(project_path)
        existing = store.read(address)
        guard_zoned_write(existing.body, text, address=address)
        entry = store.edit(address, text=text, expected_hash=expected_hash, actor_surface="mcp")
    except ZoneViolation as exc:
        payload = exc.payload()
        payload["recovery"] = (
            f"Call pin_memory(section={exc.address.removesuffix('.md')!r}, text=...) "
            "to add a note that survives reconciliation."
        )
        return payload
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    payload["edited"] = True
    return payload


def _reconciler():
    from docmancer.memory import MemoryAgent
    from docmancer.memory.laptop import LaptopMemoryReconciler

    return LaptopMemoryReconciler(MemoryAgent())


def canonical_memory(*, section: str | None = None) -> dict:
    """Read the machine-wide canonical memory: what Docmancer has reconciled
    about this user across every agent and project. READ-ONLY.

    Without ``section``, returns the status of all sections. With ``section``
    (``about``, ``preferences``, ``working-principles``, ``active-projects``),
    returns that section split into its ``pinned`` and ``generated`` zones.
    """
    try:
        reconciler = _reconciler()
        return reconciler.read_section(section) if section else reconciler.status()
    except ValueError as exc:
        return {"ok": False, "error": "unknown_section", "message": str(exc)}


def pin_memory(section: str, text: str) -> dict:
    """Add one durable line to a canonical section's pinned zone. MUTATING.

    The pinned zone is the only part of a canonical section that survives
    reconciliation. Use this instead of ``edit_memory`` for anything that
    should persist: a correction, a standing preference, a fact the automatic
    reconciler got wrong or omitted.

    ``section`` is one of ``about``, ``preferences``, ``working-principles``,
    or ``active-projects``.
    """
    try:
        return {"ok": True, **_reconciler().pin(section, text)}
    except ValueError as exc:
        return {"ok": False, "error": "pin_failed", "message": str(exc)}


def unpin_memory(section: str, text: str) -> dict:
    """Remove pinned lines in ``section`` containing ``text``. MUTATING.

    Matching is a case-insensitive substring test. Fails without changing
    anything when nothing matches.
    """
    try:
        return {"ok": True, **_reconciler().unpin(section, text)}
    except ValueError as exc:
        return {"ok": False, "error": "unpin_failed", "message": str(exc)}


def move_memory(
    address: str,
    new_relative_path: str,
    *,
    expected_hash: str,
    project_path: str | None = None,
) -> dict:
    """Move or rename one memory file to ``new_relative_path`` inside the
    same tree root, preserving its stable address (memory_id survives the
    move). MUTATING -- and DESTRUCTIVE at the old path: the old path stops
    resolving once the move succeeds, so any citation held by a caller
    must switch to the returned stable address, not the old path.

    Requires the file's current ``content_hash`` in ``expected_hash``;
    fails safely (no partial move) if it is stale or if the destination
    already has a file.
    """
    try:
        store = _store_for(project_path)
        entry = store.move(
            address,
            new_relative_path,
            expected_hash=expected_hash,
            actor_surface="mcp",
        )
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    payload["moved"] = True
    return payload


def search_memory(
    query: str,
    *,
    limit: int = _DEFAULT_SEARCH_LIMIT,
    project_path: str | None = None,
) -> list[dict]:
    """Lexical search over one tree's active memory (mandatory policy plus
    query-relevant curated memory). READ-ONLY.

    Returns ``[]`` -- not an error -- when nothing is relevant or the tree
    is empty; callers should treat an empty list as "no memory found for
    this task", not as a failure to retry.
    """
    try:
        store = _store_for(project_path)
        request = ContextRequest(task=query, project_path=project_path, token_budget=10_000)
        bundle = compile_context(store.index, request)
    except TreeError as exc:
        return [_error_payload(exc)]
    items = list(bundle.mandatory_policies) + list(bundle.curated_memory)
    return [
        {
            "address": item.address,
            "title": item.title,
            "excerpt": item.excerpt,
            "authority": item.authority,
            "source_type": item.source_type,
        }
        for item in items[: min(_MAX_SEARCH_LIMIT, max(0, limit))]
    ]


def duplicate_memory(
    address: str,
    new_relative_path: str,
    *,
    expected_hash: str,
    project_path: str | None = None,
) -> dict:
    """Duplicate a memory file under a new stable identity. MUTATING."""
    try:
        entry = _store_for(project_path).duplicate(
            address,
            new_relative_path,
            expected_hash=expected_hash,
            actor_surface="mcp",
        )
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    payload["duplicated"] = True
    return payload


def trash_memory(address: str, *, expected_hash: str, project_path: str | None = None) -> dict:
    """Move one memory file to recoverable trash. DESTRUCTIVE but reversible."""
    try:
        token = _store_for(project_path).trash(address, expected_hash=expected_hash, actor_surface="mcp")
    except TreeError as exc:
        return _error_payload(exc)
    return {"trashed": True, "restore_token": token}


def restore_memory(restore_token: str, *, project_path: str | None = None) -> dict:
    """Restore one previously trashed memory file. MUTATING."""
    try:
        entry = _store_for(project_path).restore(restore_token, actor_surface="mcp")
    except TreeError as exc:
        return _error_payload(exc)
    payload = _entry_payload(entry)
    payload["restored"] = True
    return payload


def build_context(
    task: str,
    *,
    project_path: str | None = None,
    project_id: str | None = None,
    agent: str = "unknown",
    session_id: str | None = None,
    token_budget: int = 2000,
    requested_domains: list[str] | None = None,
) -> dict:
    """Compile task-relevant context: the same ``compile_context`` operation
    CLI ``context`` uses, over the tree pinned by ``project_path`` (or the
    global tree when omitted). READ-ONLY.

    ``project_path`` here only *selects which tree root* this MCP process
    reads from; it is not a way to escape the server's own root pin --
    ``TreeStore``/``AddressIndex`` still refuse any path outside that
    resolved root. Returns an empty ``mandatory_policies``/
    ``curated_memory`` bundle (not an error) when the tree has no relevant
    or mandatory memory yet.
    """
    try:
        store = _store_for(project_path)
        request = ContextRequest(
            task=task,
            project_path=project_path,
            project_id=project_id,
            agent=agent,
            session_id=session_id,
            token_budget=token_budget,
            requested_domains=requested_domains or [],
        )
        bundle = compile_context(store.index, request)
    except TreeError as exc:
        return _error_payload(exc)
    return context_bundle_payload(bundle)


def ask_memory(
    task: str,
    *,
    project_path: str | None = None,
    token_budget: int = 4000,
    limit: int = 12,
    include_history: bool = False,
    agent: str = "mcp-client",
    answer: bool = False,
    mode: str = "normal",
) -> dict:
    """Recall curated memory plus supporting indexed agent evidence."""
    from docmancer.memory.ask import ask

    return ask(
        task,
        project_path=project_path,
        tree_root=_resolve_root(project_path),
        token_budget=token_budget,
        limit=limit,
        include_history=include_history,
        agent_name=agent,
        surface="mcp",
        integration_mode="mcp",
        answer=answer,
        answer_mode=mode,
    )


def common_memory(*, project_path: str | None = None) -> list[dict]:
    """Return recurring memory across independent local agent harnesses."""
    from docmancer.memory import MemoryAgent

    return MemoryAgent().common_memory(project_path=project_path)


def context_delivery(*, project_path: str | None = None) -> list[dict]:
    """Return the local integration and latest-delivery matrix."""
    from docmancer.memory.delivery import delivery_matrix, inspect_hook_status
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

    project = Path(project_path).expanduser().resolve() if project_path else Path.cwd().resolve()
    projections = {
        agent: str(projection_path(agent))
        for agent in PROJECTION_TARGETS
        if projection_path(agent).is_file()
    }
    return delivery_matrix(
        project,
        hook_rows=inspect_hook_status(project),
        projections=projections,
    )


def context_status(*, project_path: str | None = None) -> dict:
    """Read the current Context revision and freshness. Never mutates it."""
    from docmancer.memory.context_engine import ContextEngine

    project = Path(project_path).expanduser().resolve() if project_path else Path.cwd().resolve()
    latest = ContextEngine(project).latest()
    if latest is None:
        return {"available": False}
    return {
        "available": True,
        "revision_id": latest.get("revision_id"),
        "parent_revision_id": latest.get("parent_revision_id"),
        "scope": latest.get("scope"),
        "clusters": latest.get("clusters") or [],
        "freshness": latest.get("freshness") or {},
        "cost_estimate": latest.get("cost_estimate") or {},
        "excluded": latest.get("excluded") or [],
    }


def context_projection(
    *,
    agent: str,
    project_path: str | None = None,
    token_budget: int = 2_000,
) -> dict:
    """Render a current projection in memory without refreshing or writing it."""
    from docmancer.memory.context_engine import ContextEngine
    from docmancer.memory.projections import (
        build_context_projection,
        render_context_projection,
    )

    project = Path(project_path).expanduser().resolve() if project_path else Path.cwd().resolve()
    engine = ContextEngine(project)
    latest = engine.latest()
    if latest is None:
        return {"available": False}
    bundle = context_bundle_payload(
        compile_context(
            _store_for(str(project)).index,
            ContextRequest(
                task="session baseline",
                project_path=str(project),
                agent=agent,
                token_budget=token_budget,
            ),
        )
    )
    projection = build_context_projection(
        latest,
        bundle,
        target_agent=agent,
        token_budget=token_budget,
    )
    return {
        "available": True,
        "projection": projection.to_dict(),
        "rendered": render_context_projection(projection),
    }


def decision_timeline(
    *,
    project_path: str | None = None,
    file_id: str | None = None,
    operation: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return append-only canonical tree mutation events."""
    from docmancer.memory.tree.journal import DecisionJournal

    return DecisionJournal(_resolve_root(project_path)).events(
        file_id=file_id,
        operation=operation,
        limit=limit,
    )


__all__ = [
    "write_memory",
    "read_memory",
    "edit_memory",
    "move_memory",
    "duplicate_memory",
    "trash_memory",
    "restore_memory",
    "search_memory",
    "ask_memory",
    "build_context",
    "common_memory",
    "context_delivery",
    "context_projection",
    "context_status",
    "decision_timeline",
]
