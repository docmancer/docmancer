"""Top-level retrieval dispatcher.

Takes a query plus the configured mode (``lexical``, ``dense``, ``sparse``,
``hybrid``) and returns a unified ranked list. For multi-signal modes,
candidate lists are fused with RRF and resolved back to FTS5-flavoured
``RetrievedChunk`` objects so the rest of the agent sees a stable shape.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .fusion import reciprocal_rank_fusion, weighted_rrf

if TYPE_CHECKING:
    from docmancer.core.config import DocmancerConfig
    from docmancer.core.models import RetrievedChunk
    from docmancer.core.sqlite_store import SQLiteStore
    from docmancer.embeddings.base import EmbeddingsProvider
    from docmancer.stores.base import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    chunks: list[Any] = field(default_factory=list)
    contributions: dict[Any, dict[str, int]] = field(default_factory=dict)
    mode_used: str = "lexical"
    candidate_counts: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


class HybridRetrievalError(RuntimeError):
    """Raised when one or more non-lexical retrievers fail in strict mode."""

    def __init__(self, failures: dict[str, str]) -> None:
        self.failures = dict(failures)
        parts = "; ".join(f"{src}: {msg}" for src, msg in failures.items())
        super().__init__(
            f"hybrid retrieval failed in {len(failures)} source(s): {parts}. "
            f"Pass --allow-degraded to fall back to the remaining signals, or "
            f"run `docmancer doctor` to diagnose."
        )


class RetrievalDispatcher:
    """Coordinator for lexical / dense / sparse / hybrid retrieval."""

    def __init__(
        self,
        *,
        store: "SQLiteStore",
        config: "DocmancerConfig",
        vector_store: "VectorStore | None" = None,
        provider: "EmbeddingsProvider | None" = None,
        collection: str | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.vector_store = vector_store
        self.provider = provider
        self.collection = collection
        self._auto_hierarchical_cache: bool | None = None

    def run(
        self,
        query: str,
        *,
        mode: str | None = None,
        limit: int | None = None,
        budget: int | None = None,
        expand: str | None = None,
        filters: dict | None = None,
        allow_degraded: bool = False,
    ) -> DispatchResult:
        configured_mode = getattr(getattr(self.config, "retrieval", None), "default_mode", None)
        effective_mode = (
            mode
            or (configured_mode if isinstance(configured_mode, str) else None)
            or "lexical"
        ).lower()
        limit = limit or self.config.query.default_limit
        budget = budget or self.config.query.default_budget
        per_source_limit = max(limit * 3, 20)

        # Query-aware routing: first matching router merges its filters into
        # the dispatcher's filters for this call (e.g. ``status_code=LIVE``,
        # ``international_class=030``).
        merged_filters = self._apply_router(query, filters)

        # Effective expand: per-call > retrieval.expand > query.default_expand.
        retrieval_expand = (
            expand
            or getattr(self.config.retrieval, "expand", None)
            or self.config.query.default_expand
        )

        if effective_mode == "lexical" or self.vector_store is None or self.provider is None:
            chunks = self.store.query(query, limit=limit, budget=budget, expand=retrieval_expand)
            return DispatchResult(
                chunks=chunks,
                contributions={c.metadata.get("section_id"): {"lexical": idx + 1} for idx, c in enumerate(chunks) if c.metadata.get("section_id") is not None},
                mode_used="lexical",
                candidate_counts={"lexical": len(chunks)},
            )

        hierarchical = getattr(self.config.retrieval, "hierarchical", None)
        if hierarchical is not None and self._hierarchical_active(hierarchical):
            return self._run_hierarchical(
                query=query,
                mode=effective_mode,
                limit=limit,
                budget=budget,
                filters=merged_filters,
                expand=retrieval_expand,
                allow_degraded=allow_degraded,
            )

        ready_failure = self._vector_readiness_failure(effective_mode)
        if ready_failure and not allow_degraded:
            raise HybridRetrievalError(ready_failure)

        candidate_lists, raw_counts, failures = self._fan_out(
            query=query,
            mode=effective_mode,
            per_source_limit=per_source_limit,
            filters=merged_filters,
        )

        if failures and effective_mode != "lexical" and not allow_degraded:
            raise HybridRetrievalError(failures)

        if not candidate_lists:
            if ready_failure and allow_degraded:
                raw_counts.update({source: 0 for source in ready_failure})
                failures.update(ready_failure)
            chunks = self.store.query(query, limit=limit, budget=budget, expand=retrieval_expand)
            return DispatchResult(
                chunks=chunks,
                mode_used="lexical-fallback",
                candidate_counts=raw_counts,
                failures=failures,
            )

        fusion_method = self.config.retrieval.fusion.method or "rrf"
        k_rrf = int(self.config.retrieval.fusion.rrf_k or 60)
        weights = dict(self.config.retrieval.fusion.weights or {})

        if fusion_method == "weighted_rrf" and weights:
            ranked = weighted_rrf(candidate_lists, weights=weights, k_rrf=k_rrf)
        else:
            ranked = reciprocal_rank_fusion(candidate_lists, k_rrf=k_rrf)

        section_ids = self._top_section_ids(ranked, limit=limit)
        contributions = {sid: dict(c) for hid, _s, c in ranked for sid in [int(hid)] if sid in section_ids}
        relevance_scores = self._relevance_scores(candidate_lists)
        fusion_scores = {int(hid): float(score) for hid, score, _c in ranked}

        # Neighbor expansion in hybrid mode: pull adjacent section ids before
        # hydrate. Lexical mode handles this inside ``SQLiteStore.query``;
        # we replicate the effect here so hybrid hits feel as well-cited.
        if (retrieval_expand or "").lower() in {"adjacent", "page"}:
            section_ids = self._expand_section_ids(
                section_ids,
                mode=retrieval_expand,
                budget_cap=limit * 3,
                scores=relevance_scores,
            )

        chunks = self._hydrate(
            section_ids,
            budget=budget,
            scores=relevance_scores,
            fusion_scores=fusion_scores,
        )
        return DispatchResult(
            chunks=chunks,
            contributions=contributions,
            mode_used=effective_mode,
            candidate_counts=raw_counts,
            failures=failures,
        )

    def _hierarchical_active(self, hcfg: Any) -> bool:
        """Decide whether to run the two-stage hierarchical pass for this call.

        Explicit ``enabled=True`` always wins. Otherwise, when ``auto`` is
        on, fall back to a corpus-size heuristic: enable when the index
        contains at least ``auto_min_documents`` distinct documents. Below
        that threshold the extra round-trip costs latency without gaining
        recall (you'd select every document anyway).
        """
        if getattr(hcfg, "enabled", False):
            return True
        if not getattr(hcfg, "auto", False):
            return False
        if self._auto_hierarchical_cache is not None:
            return self._auto_hierarchical_cache
        threshold = int(getattr(hcfg, "auto_min_documents", 10))
        try:
            distinct = int(self.store.distinct_document_count())
        except Exception:
            distinct = 0
        active = distinct >= threshold
        self._auto_hierarchical_cache = active
        if active:
            logger.debug(
                "hierarchical retrieval auto-enabled (%d distinct documents >= %d)",
                distinct,
                threshold,
            )
        return active

    def _vector_readiness_failure(self, mode: str) -> dict[str, str]:
        if mode == "lexical" or self.vector_store is None or not self.collection:
            return {}
        count_fn = getattr(self.vector_store, "count", None)
        if not callable(count_fn):
            return {}
        try:
            points = int(count_fn(self.collection))
        except Exception as exc:
            return {"vector": f"{type(exc).__name__}: {exc}"}
        if points <= 0:
            return {"vector": f"collection {self.collection!r} has no indexed vectors"}
        return {}

    # ------------------ hierarchical retrieval ------------------

    def _run_hierarchical(
        self,
        *,
        query: str,
        mode: str,
        limit: int,
        budget: int,
        filters: dict | None,
        expand: str | None,
        allow_degraded: bool = False,
    ) -> DispatchResult:
        """Two-stage retrieval: top documents first, then top sections inside them."""
        hcfg = self.config.retrieval.hierarchical
        candidate_pool = int(hcfg.candidate_pool)
        ready_failure = self._vector_readiness_failure(mode)
        if ready_failure and not allow_degraded:
            raise HybridRetrievalError(ready_failure)

        # Stage 1: cast a wide net and aggregate by document_title_hash.
        stage1_candidates, stage1_counts, stage1_failures = self._fan_out(
            query=query,
            mode=mode,
            per_source_limit=candidate_pool,
            filters=filters,
        )
        if stage1_failures and mode != "lexical" and not allow_degraded:
            raise HybridRetrievalError(stage1_failures)
        if not stage1_candidates:
            chunks = self.store.query(query, limit=limit, budget=budget, expand=expand)
            return DispatchResult(
                chunks=chunks,
                mode_used="lexical-fallback",
                candidate_counts=stage1_counts,
                failures=stage1_failures,
            )

        doc_scores: dict[str, float] = {}
        for source, shaped in stage1_candidates.items():
            payload_lookup = self._payload_lookup_for(source, shaped)
            for rank, hit in enumerate(shaped, start=1):
                sid = int(hit["id"])
                doc_hash = payload_lookup.get(sid, "")
                if not doc_hash:
                    continue
                doc_scores[doc_hash] = doc_scores.get(doc_hash, 0.0) + 1.0 / (60 + rank)

        if not doc_scores:
            # No payloads carry document_title_hash (e.g. mixed corpus where
            # only some loaders set it). Fall through to a flat fusion.
            return self._fuse_and_hydrate(stage1_candidates, limit=limit, budget=budget, expand=expand, counts=stage1_counts, mode=mode)

        top_docs = [h for h, _ in sorted(doc_scores.items(), key=lambda kv: kv[1], reverse=True)[: hcfg.documents_limit]]

        # Stage 2: re-retrieve dense + sparse filtered to those documents.
        stage2_filters = dict(filters or {})
        stage2_filters["document_title_hash"] = {"in": top_docs}
        stage2_candidates, stage2_counts, stage2_failures = self._fan_out(
            query=query,
            mode=mode,
            per_source_limit=max(limit * 3, hcfg.sections_per_document * hcfg.documents_limit),
            filters=stage2_filters,
        )
        if stage2_failures and mode != "lexical" and not allow_degraded:
            raise HybridRetrievalError(stage2_failures)
        if not stage2_candidates:
            return self._fuse_and_hydrate(stage1_candidates, limit=limit, budget=budget, expand=expand, counts=stage1_counts, mode=mode)
        return self._fuse_and_hydrate(
            stage2_candidates,
            limit=limit,
            budget=budget,
            expand=expand,
            counts={**stage1_counts, **{f"{k}.stage2": v for k, v in stage2_counts.items()}},
            mode=f"{mode}/hierarchical",
        )

    def _fuse_and_hydrate(
        self,
        candidate_lists: dict[str, list[Any]],
        *,
        limit: int,
        budget: int,
        expand: str | None,
        counts: dict[str, int],
        mode: str,
    ) -> DispatchResult:
        k_rrf = int(self.config.retrieval.fusion.rrf_k or 60)
        ranked = reciprocal_rank_fusion(candidate_lists, k_rrf=k_rrf)
        section_ids = self._top_section_ids(ranked, limit=limit)
        contributions = {sid: dict(c) for hid, _s, c in ranked for sid in [int(hid)] if sid in section_ids}
        relevance_scores = self._relevance_scores(candidate_lists)
        fusion_scores = {int(hid): float(score) for hid, score, _c in ranked}
        if (expand or "").lower() in {"adjacent", "page"}:
            section_ids = self._expand_section_ids(
                section_ids,
                mode=expand,
                budget_cap=limit * 3,
                scores=relevance_scores,
            )
        chunks = self._hydrate(
            section_ids,
            budget=budget,
            scores=relevance_scores,
            fusion_scores=fusion_scores,
        )
        return DispatchResult(
            chunks=chunks,
            contributions=contributions,
            mode_used=mode,
            candidate_counts=counts,
        )

    # ------------------ helpers ------------------

    def _apply_router(self, query: str, filters: dict | None) -> dict | None:
        """Walk ``retrieval.routers``; merge the first match's filters into ``filters``."""
        import re as _re

        routers = list(getattr(self.config.retrieval, "routers", []) or [])
        if not routers:
            return filters
        for router in routers:
            pattern = getattr(router, "match", "") or ""
            if not pattern:
                continue
            try:
                if _re.search(pattern, query, _re.IGNORECASE):
                    merged = dict(filters or {})
                    for k, v in (router.filters or {}).items():
                        merged[k] = v
                    logger.debug("router matched: %s", getattr(router, "description", None) or pattern)
                    return merged
            except _re.error:
                logger.warning("invalid router regex skipped: %r", pattern)
                continue
        return filters

    def _top_section_ids(self, ranked, *, limit: int) -> list[int]:
        section_ids: list[int] = []
        for hit_id, _score, _contrib in ranked:
            try:
                section_ids.append(int(hit_id))
            except (TypeError, ValueError):
                continue
            if len(section_ids) >= limit:
                break
        return section_ids

    @staticmethod
    def _relevance_scores(candidate_lists: dict[str, list[Any]]) -> dict[int, float]:
        """Preserve real signal strength separately from rank-only RRF.

        RRF decides ordering, but cannot say whether the nearest candidate is
        actually relevant. The public chunk score is the strongest normalized
        retrieval signal for that section. The raw fused score remains in
        metadata for diagnostics.
        """
        signals: dict[int, dict[str, float]] = {}
        for source, hits in candidate_lists.items():
            for hit in hits:
                try:
                    section_id = int(hit["id"] if isinstance(hit, dict) else hit.id)
                    raw = float(hit.get("score", 0.0) if isinstance(hit, dict) else hit.score)
                except (AttributeError, KeyError, TypeError, ValueError):
                    continue
                normalized = max(0.0, min(1.0, raw))
                signals.setdefault(section_id, {})[source] = max(
                    signals.get(section_id, {}).get(source, 0.0),
                    normalized,
                )
        scores: dict[int, float] = {}
        for section_id, section_signals in signals.items():
            lexical = section_signals.get("lexical")
            dense_raw = section_signals.get("dense")
            sparse = section_signals.get("sparse")
            # Static embeddings have a non-zero nearest-neighbour baseline.
            # Map the observed 0.40 noise floor to zero confidence while
            # preserving the upper end of cosine similarity.
            dense = (
                max(0.0, min(1.0, (dense_raw - 0.40) / 0.60))
                if dense_raw is not None
                else None
            )
            semantic = max(value for value in (dense, sparse) if value is not None) if any(
                value is not None for value in (dense, sparse)
            ) else None
            if lexical is not None and semantic is not None:
                score = (lexical + semantic) / 2.0
            elif lexical is not None:
                score = lexical
            else:
                score = semantic or 0.0
            scores[section_id] = round(max(0.0, min(1.0, score)), 6)
        return scores

    def _expand_section_ids(
        self,
        section_ids: list[int],
        *,
        mode: str,
        budget_cap: int,
        scores: dict[int, float] | None = None,
    ) -> list[int]:
        """Add adjacent or full-page section ids while preserving order."""
        if not section_ids or not hasattr(self.store, "adjacent_section_ids"):
            return section_ids
        seen: set[int] = set(section_ids)
        out: list[int] = list(section_ids)
        for sid in list(section_ids):
            try:
                neighbors = self.store.adjacent_section_ids(int(sid), mode=mode)
            except Exception:
                continue
            for nid in neighbors:
                if nid in seen:
                    continue
                seen.add(nid)
                if scores is not None and nid not in scores:
                    scores[nid] = float(scores.get(int(sid), 0.0))
                out.append(nid)
                if len(out) >= budget_cap:
                    return out
        return out

    def _payload_lookup_for(self, source: str, shaped: list[dict]) -> dict[int, str]:
        """Return ``{section_id: document_title_hash}`` from this round's hits.

        Vector hits carry the hash in their payload; lexical hits don't, so
        we cross-walk the surviving section ids through SQLite for those.
        """
        out: dict[int, str] = {}
        if source == "lexical" and hasattr(self.store, "document_title_hashes_for"):
            try:
                out.update(self.store.document_title_hashes_for([int(h["id"]) for h in shaped]))
            except Exception:
                pass
            return out
        # For dense/sparse, the dispatcher only stores ``id`` + ``score`` in
        # ``shaped``; the underlying payloads have already been discarded.
        # We re-fetch payloads via SQLite metadata which mirrors the same
        # document_title_hash.
        if hasattr(self.store, "document_title_hashes_for"):
            try:
                out.update(self.store.document_title_hashes_for([int(h["id"]) for h in shaped]))
            except Exception:
                pass
        return out

    # ------------------ helpers ------------------

    def _fan_out(
        self,
        *,
        query: str,
        mode: str,
        per_source_limit: int,
        filters: dict | None,
    ) -> tuple[dict[str, list[Any]], dict[str, int], dict[str, str]]:
        from .dense import dense_search
        from .lexical import lexical_search
        from .sparse import sparse_search

        tasks: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            if mode == "hybrid":
                tasks["lexical"] = ex.submit(
                    lexical_search, self.store, query, limit=per_source_limit, budget=10_000
                )
                tasks["dense"] = ex.submit(
                    dense_search,
                    vector_store=self.vector_store,
                    provider=self.provider,
                    collection=self.collection,
                    query=query,
                    limit=per_source_limit,
                    filters=filters,
                )
                # Only schedule sparse when the backend advertises it. Dense-only
                # stores (sqlite-vec) set supports_sparse=False, so hybrid runs
                # as lexical + dense rather than failing on an unsupported call.
                if getattr(self.vector_store, "supports_sparse", False):
                    tasks["sparse"] = ex.submit(
                        sparse_search,
                        vector_store=self.vector_store,
                        provider=self.provider,
                        collection=self.collection,
                        query=query,
                        limit=per_source_limit,
                        filters=filters,
                    )
            elif mode == "dense":
                tasks["dense"] = ex.submit(
                    dense_search,
                    vector_store=self.vector_store,
                    provider=self.provider,
                    collection=self.collection,
                    query=query,
                    limit=per_source_limit,
                    filters=filters,
                )
            elif mode == "sparse":
                tasks["sparse"] = ex.submit(
                    sparse_search,
                    vector_store=self.vector_store,
                    provider=self.provider,
                    collection=self.collection,
                    query=query,
                    limit=per_source_limit,
                    filters=filters,
                )
            else:
                return {}, {}, {}

            candidate_lists: dict[str, list[Any]] = {}
            counts: dict[str, int] = {}
            failures: dict[str, str] = {}
            for source, fut in tasks.items():
                try:
                    hits = fut.result()
                except Exception as exc:
                    logger.warning("retrieval source %s failed: %s", source, exc)
                    failures[source] = f"{type(exc).__name__}: {exc}"
                    hits = []
                if not hits:
                    counts[source] = 0
                    continue
                shaped = _shape_for_fusion(source, hits)
                if shaped:
                    candidate_lists[source] = shaped
                    counts[source] = len(shaped)
        return candidate_lists, counts, failures

    def _hydrate(
        self,
        section_ids: list[int],
        *,
        budget: int,
        scores: dict[int, float] | None = None,
        fusion_scores: dict[int, float] | None = None,
    ) -> list:
        if not section_ids:
            return []
        from inspect import Parameter, signature

        fetch = self.store.fetch_sections_by_id
        try:
            parameters = signature(fetch).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_extra_keywords = any(
            parameter.kind == Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        supports_scores = accepts_extra_keywords or (
            "scores" in parameters and "fusion_scores" in parameters
        )
        if supports_scores:
            return self.store.fetch_sections_by_id(
                section_ids,
                budget=budget,
                scores=scores,
                fusion_scores=fusion_scores,
            )
        # Compatibility for third-party stores implementing the older
        # hydration protocol without score maps.
        chunks = fetch(section_ids, budget=budget)
        for chunk in chunks:
            section_id = int((chunk.metadata or {}).get("section_id") or 0)
            if section_id in (scores or {}):
                chunk.score = float(scores[section_id])
        return chunks


def _shape_for_fusion(source: str, hits: list[Any]) -> list[dict]:
    """Reduce heterogeneous hit shapes to ``[{"id": <section_id>, ...}, ...]``."""
    shaped: list[dict] = []
    for hit in hits:
        if source == "lexical":
            section_id = (hit.metadata or {}).get("section_id") if hasattr(hit, "metadata") else None
            if section_id is None:
                continue
            shaped.append({"id": int(section_id), "score": float(getattr(hit, "score", 0.0))})
        else:
            try:
                section_id = int(hit.id)
            except (TypeError, ValueError):
                section_id = (hit.payload or {}).get("section_id")
                if section_id is None:
                    continue
                section_id = int(section_id)
            shaped.append({"id": section_id, "score": float(getattr(hit, "score", 0.0))})
    return shaped


def dispatch_query(
    *,
    store: "SQLiteStore",
    config: "DocmancerConfig",
    vector_store: "VectorStore | None",
    provider: "EmbeddingsProvider | None",
    collection: str | None,
    query: str,
    mode: str | None = None,
    limit: int | None = None,
    budget: int | None = None,
    expand: str | None = None,
    filters: dict | None = None,
    allow_degraded: bool = False,
) -> DispatchResult:
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=vector_store,
        provider=provider,
        collection=collection,
    )
    return dispatcher.run(
        query,
        mode=mode,
        limit=limit,
        budget=budget,
        expand=expand,
        filters=filters,
        allow_degraded=allow_degraded,
    )
