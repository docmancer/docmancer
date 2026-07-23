"""Unified task recall across curated memory and indexed agent evidence."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from docmancer.memory.tree.compiler import (
    ContextRequest,
    EvidenceReference,
    compile_context,
)
from docmancer.memory.tree.project import resolve_project_root, tree_paths
from docmancer.memory.tree.store import TreeStore


def _token_estimate(text: str) -> int:
    return max(1, len(text or "") // 4)


def ask(
    task: str,
    *,
    project_path: str | Path | None = None,
    tree_root: str | Path | None = None,
    token_budget: int = 2000,
    limit: int = 8,
    scope: str | None = None,
    include_history: bool = False,
    refresh: bool = True,
    agent_name: str = "unknown",
    surface: str = "library",
    integration_mode: str = "direct",
) -> dict:
    """Return one bounded context bundle from the two local memory corpora."""
    from docmancer.memory import MemoryAgent

    project = resolve_project_root(project_path)
    resolved_tree = Path(tree_root).expanduser().resolve() if tree_root is not None else tree_paths(project)[0]
    request = ContextRequest(
        task=task,
        project_path=str(project),
        token_budget=token_budget,
    )
    bundle = compile_context(TreeStore(resolved_tree).index, request)

    agent = MemoryAgent()
    refresh_error = None
    refreshed = False
    if refresh:
        try:
            refreshed = agent.refresh_if_changed()
        except Exception as exc:  # noqa: BLE001 - recall uses the last valid index
            refresh_error = str(exc)

    remaining = max(0, token_budget - bundle.token_estimate)
    chunks = []
    if remaining:
        try:
            chunks = agent.query(
                task,
                limit=limit,
                project_path=project if project_path is not None or tree_root is None else None,
                scope=scope,
                include_history=include_history,
            )
        except Exception:  # noqa: BLE001 - an absent recall index leaves tree recall usable
            chunks = []

    evidence: list[EvidenceReference] = []
    evidence_debug: list[dict] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        excerpt = str(chunk.text or "").strip()
        cost = _token_estimate(excerpt)
        if cost > remaining:
            continue
        remaining -= cost
        source = str(metadata.get("source_path") or chunk.source or "")
        evidence.append(
            EvidenceReference(
                address=source,
                title=str(metadata.get("title") or Path(source).name or "Indexed evidence"),
                excerpt=excerpt,
            )
        )
        evidence_debug.append(
            {
                "address": source,
                "score": float(chunk.score or 0.0),
                "metadata": metadata,
            }
        )

    bundle.relevant_evidence = evidence
    bundle.token_estimate = token_budget - remaining
    result = {
        "task": task,
        "project_path": str(project),
        "mandatory_policies": [asdict(item) for item in bundle.mandatory_policies],
        "curated_memory": [asdict(item) for item in bundle.curated_memory],
        "relevant_evidence": [asdict(item) for item in evidence],
        "conflict_warnings": [asdict(item) for item in bundle.conflict_warnings],
        "token_estimate": bundle.token_estimate,
        "token_budget": token_budget,
        "index_revision": bundle.index_revision,
        "generated_at": bundle.generated_at,
        "retrieval_trace": asdict(bundle.retrieval_trace),
        "refresh": {
            "refreshed": refreshed,
            "error": refresh_error,
        },
        "debug_evidence": evidence_debug,
    }
    if (project / ".docmancer").exists():
        try:
            from docmancer.memory.delivery import record_delivery

            record_delivery(
                project,
                agent=agent_name,
                surface=surface,
                integration_mode=integration_mode,
                bundle=result,
                task=task,
            )
        except OSError:
            pass
    return result


__all__ = ["ask"]
