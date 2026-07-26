"""Unified task recall across curated memory and indexed agent evidence."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Callable

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
    token_budget: int = 4000,
    limit: int = 12,
    scope: str | None = None,
    evidence_budget: int | None = None,
    include_history: bool = False,
    refresh: bool = True,
    agent_name: str = "unknown",
    surface: str = "library",
    integration_mode: str = "direct",
    answer: bool | None = None,
    answer_client=None,
    answer_mode: str = "normal",
    on_delta: Callable[[str], None] | None = None,
) -> dict:
    """Return one bounded context bundle from the two local memory corpora.

    Indexed evidence recall defaults to global (every indexed project plus
    global memory). It is scoped to one project only when the caller passes an
    explicit ``project_path`` or ``scope="project"``. Evidence is also
    guaranteed a floor of the token budget so curated tree memory cannot crowd
    it out; ``evidence_budget`` overrides that floor.
    """
    from docmancer.memory import MemoryAgent

    project = resolve_project_root(project_path)
    resolved_tree = Path(tree_root).expanduser().resolve() if tree_root is not None else tree_paths(project)[0]

    # Reserve a share of the budget for indexed evidence up front, then compile
    # curated memory against only the remainder. This guarantees evidence its
    # floor (cross-project recall lives in the evidence corpus). Evidence never
    # pushes the bundle past token_budget: when curated content already fills the
    # budget, `remaining` is zero and no evidence is added. The one documented
    # exception is mandatory policy: compile_context always includes it even when
    # it alone exceeds token_budget, so the bundle can exceed budget only then.
    # The result reports `within_budget` so callers can see when that happened.
    reserve = token_budget // 2 if evidence_budget is None else max(0, evidence_budget)
    reserve = min(reserve, token_budget)
    curated_budget = max(0, token_budget - reserve)
    request = ContextRequest(
        task=task,
        project_path=str(project),
        token_budget=curated_budget,
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

    curated_tokens = bundle.token_estimate
    remaining = max(0, token_budget - curated_tokens)
    start_remaining = remaining

    # Default to global recall across every indexed project. Only scope to one
    # project when the caller explicitly asked, via project_path or
    # scope="project".
    scoped = project_path is not None or scope == "project"
    query_project = project if scoped else None

    chunks = []
    if remaining:
        try:
            chunks = agent.query(
                task,
                limit=limit,
                project_path=query_project,
                scope=scope,
                include_history=include_history,
            )
        except Exception:  # noqa: BLE001 - an absent recall index leaves tree recall usable
            chunks = []

    evidence: list[EvidenceReference] = []
    evidence_debug: list[dict] = []
    truncated = 0
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        excerpt = str(chunk.text or "").strip()
        cost = _token_estimate(excerpt)
        if cost > remaining:
            # Do not stop: a smaller lower-ranked chunk may still fit, which
            # keeps coverage higher than an early break would. Count what was
            # dropped so a missing fact is visible rather than silent.
            truncated += 1
            continue
        remaining -= cost
        source = str(metadata.get("source_path") or chunk.source or "")
        evidence.append(
            EvidenceReference(
                address=source,
                title=str(metadata.get("title") or Path(source).name or "Indexed evidence"),
                excerpt=excerpt,
                # Carried so the answer path can date claims, name the agent that
                # recorded them, and apply a relevance floor. Previously these
                # existed only in the debug payload and were dropped.
                recorded_at=str(metadata.get("timestamp") or ""),
                harness=str(metadata.get("harness") or ""),
                score=float(chunk.score or 0.0),
                rank=len(evidence) + 1,
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
    evidence_used = start_remaining - remaining
    bundle.token_estimate = curated_tokens + evidence_used
    # The bundle exceeds budget only when mandatory policy overflows it; evidence
    # is bounded above by `remaining`, which is zero once curated content fills
    # the budget.
    within_budget = bundle.token_estimate <= token_budget
    result = {
        "task": task,
        "project_path": str(project),
        "scoped_to_project": scoped,
        "mandatory_policies": [asdict(item) for item in bundle.mandatory_policies],
        "curated_memory": [asdict(item) for item in bundle.curated_memory],
        "relevant_evidence": [asdict(item) for item in evidence],
        "conflict_warnings": [asdict(item) for item in bundle.conflict_warnings],
        "evidence_truncated": truncated,
        "within_budget": within_budget,
        "mandatory_overflow": (not within_budget),
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
        "answer": None,
    }
    if answer is None:
        if answer_client is not None:
            answer = True
        else:
            try:
                from docmancer.ai.providers.factory import provider_status

                provider_id = agent.config.providers.default_llm
                answer = provider_status(
                    provider_id,
                    config=agent.config.providers,
                )["key_state"] in {"stored", "from_env", "override", "not_required"}
            except Exception:
                answer = False
    if answer:
        client = answer_client
        if client is None:
            try:
                from docmancer.ai.providers.factory import provider_client

                client = provider_client(
                    agent.config.providers.default_llm,
                    config=agent.config.providers,
                )
            except Exception:
                client = None
        if client is not None:
            from docmancer.ai.answer import generate_answer

            try:
                from docmancer.ai.provider_protocol import options_for_role

                result["answer"] = generate_answer(
                    result,
                    task,
                    client=client,
                    mode=answer_mode,
                    options=options_for_role(
                        "ask", agent.config.providers, mode=answer_mode
                    ),
                    on_delta=on_delta,
                ).to_dict()
            except Exception as exc:  # noqa: BLE001
                # Degradation matrix (spec 7.5): losing the provider must cost
                # the prose, never the cited evidence bundle. A timeout, a
                # stopped local endpoint, or a rate limit previously raised out
                # of ask() and the user got nothing at all, which is worse than
                # the keyless path they would have had without a provider.
                result["answer"] = None
                result["answer_unavailable"] = (
                    f"The answer provider failed ({type(exc).__name__}). "
                    "The cited evidence bundle below is unaffected."
                )
        else:
            result["answer_unavailable"] = (
                "No answer provider is configured. The cited evidence bundle is still available."
            )
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
