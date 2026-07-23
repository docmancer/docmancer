"""Context Compiler v1 (checklist A.9) and local retrieval (checklist A.10).

Implements the minimal ``ContextRequest``/``ContextBundle`` contract from
plan section 6 and checklist "Minimal Context Compiler contract": only the
fields that section requires, ``conflict_warnings`` empty unless an
explicit eligible conflict is already detectable, and a bounded
``retrieval_trace``.

## Fixing the Release 0 finding

The Release 0 go/adjust/stop decision
(docs/memory-harness/2026-07-22-release-0-go-adjust-stop-decision.md) found
that a raw word-overlap relevance count treats the product's own name as a
relevance signal, since nearly every note mentions "docmancer" and that
inflates irrelevant matches. This module fixes it with a corpus-relative
inverse document frequency weight: a token that appears in most of the
eligible documents (like a product name, or any other ubiquitous word)
contributes almost nothing to a match score, while a token that appears in
only one or two documents is a strong signal. This directly implements the
plan section A.10 requirement without hand-maintaining a stopword list of
domain-specific ubiquitous terms.

When `docmancer reindex` has created the local tree chunk index, the compiler
fuses Model2Vec and lexical scores. If the disposable dense index is absent or
unavailable, it falls back to lexical retrieval without making canonical
memory unavailable.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from docmancer.memory.tree.addressing import AddressIndex
from docmancer.memory.tree.contracts import MANDATORY_AUTHORITY
from docmancer.memory.tree.parser import TreeMemoryFile

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Checklist A.10: "Implement stopword and punctuation stripping where it
# improves recall without damaging commands." Punctuation stripping is
# already handled by _TOKEN_RE. This is a small, fixed English function-word
# list -- not a per-domain/product-name list (that would just reintroduce
# the Release 0 finding in a different shape) -- so an overlap-only match on
# a bare function word like "the" can never by itself make an unrelated
# document eligible.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "with", "is",
    "are", "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "for", "as", "at", "by", "from", "it", "its", "not", "but",
    "how", "what", "why", "when", "who", "which", "will", "can", "do",
    "does", "did", "has", "have", "had",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall((text or "").casefold())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _document_text(entry: TreeMemoryFile) -> str:
    return entry.body + " " + entry.title + " " + " ".join(entry.tags)


def build_idf(corpus: list[TreeMemoryFile]) -> dict[str, float]:
    """Corpus-relative inverse document frequency. A token present in every
    document (like the product's own name) scores near zero; a token
    present in one document out of many scores highest."""
    doc_count = len(corpus) or 1
    frequency: dict[str, int] = {}
    for entry in corpus:
        for token in _tokens(_document_text(entry)):
            frequency[token] = frequency.get(token, 0) + 1
    # No additive floor: a token present in every document (a stopword, or
    # the product's own name) must be able to reach exactly zero weight,
    # not just "near zero" -- otherwise it can still tip an unrelated
    # document just over the relevance floor below.
    return {token: math.log((doc_count + 1) / (df + 1)) for token, df in frequency.items()}


def lexical_score(entry: TreeMemoryFile, query_tokens: set[str], idf: dict[str, float]) -> float:
    doc_tokens = _tokens(_document_text(entry))
    shared = query_tokens & doc_tokens
    return sum(idf.get(token, 0.0) for token in shared)


def fuse_scores(vector_score: float, fts_score: float) -> float:
    """Plan section 6.1's documented fusion formula. Scores are expected
    pre-normalised to [0, 1] by the caller; this function does not clamp."""
    return max(vector_score, fts_score) + 0.3 * min(vector_score, fts_score)


def _estimate_tokens(text: str) -> int:
    # Coarse, deterministic estimate (~4 chars/token). Good enough for a
    # budget-compliance check; not a claim of exact model tokenization.
    return max(1, len(text) // 4)


@dataclass
class ContextItem:
    address: str
    title: str
    excerpt: str
    authority: str
    source_type: str
    token_estimate: int


@dataclass
class EvidenceReference:
    address: str
    title: str
    excerpt: str


@dataclass
class ConflictWarning:
    left_address: str
    right_address: str
    reason: str


@dataclass
class RetrievalTrace:
    channel: str
    query_tokens: list[str]
    candidates_considered: int
    excluded_over_budget: int


@dataclass
class ContextRequest:
    task: str = ""
    project_path: str | None = None
    project_id: str | None = None
    agent: str = "unknown"
    session_id: str | None = None
    token_budget: int = 2000
    requested_domains: list[str] = field(default_factory=list)


@dataclass
class ContextBundle:
    mandatory_policies: list[ContextItem]
    curated_memory: list[ContextItem]
    relevant_evidence: list[EvidenceReference]
    conflict_warnings: list[ConflictWarning]
    token_estimate: int
    index_revision: str
    generated_at: str
    retrieval_trace: RetrievalTrace


def compile_context(index: AddressIndex, request: ContextRequest) -> ContextBundle:
    """One Context Compiler used by every surface (CLI `context`, MCP
    `build_context`, hooks, projections) -- see plan section 6."""
    from docmancer.memory.tree.parser import now_iso

    corpus = [entry for entry in index.entries() if entry.status == "active" and entry.type != "context"]
    query_tokens = _tokens(request.task)
    idf = build_idf(corpus)
    vector_scores: dict[str, float] = {}
    dense_available = False
    dense_index = None
    try:
        from docmancer.memory.tree.dense_index import TreeDenseIndex

        if TreeDenseIndex.exists(index.root):
            dense_index = TreeDenseIndex(index.root)
            dense_index.sync(corpus)
            vector_scores = dense_index.search(request.task, limit=max(50, len(corpus)))
            dense_available = True
    except Exception:
        vector_scores = {}
    finally:
        if dense_index is not None:
            dense_index.close()

    # Inclusion and ranking are deliberately decoupled. IDF-weighted score
    # orders results (a term ubiquitous across the corpus, like the
    # product's own name, contributes little). But raw token overlap alone
    # decides whether an item is eligible at all. Gating inclusion on the
    # IDF score would fail the plan's core activation moment: in a
    # brand-new or single-document tree, every token trivially has
    # document-frequency equal to the corpus size, so its IDF is exactly
    # zero -- the very first decision ever written would then be
    # unrecallable purely because there is nothing yet to contrast it
    # against. Overlap-based inclusion has no such failure mode.
    lexical = {entry.memory_id: lexical_score(entry, query_tokens, idf) for entry in corpus}
    lexical_max = max(lexical.values(), default=0.0)
    scored = []
    for entry in corpus:
        lexical_normalized = lexical[entry.memory_id] / lexical_max if lexical_max > 0 else 0.0
        vector_score = vector_scores.get(entry.memory_id, 0.0)
        overlap = len(query_tokens & _tokens(_document_text(entry)))
        scored.append((entry, fuse_scores(vector_score, lexical_normalized), overlap, vector_score))
    scored.sort(key=lambda row: (0 if row[0].authority == MANDATORY_AUTHORITY else 1, -row[1]))

    mandatory_items: list[ContextItem] = []
    curated_items: list[ContextItem] = []
    used_tokens = 0
    excluded_over_budget = 0
    for entry, score, overlap, vector_score in scored:
        is_mandatory = entry.authority == MANDATORY_AUTHORITY
        if not is_mandatory and query_tokens and overlap <= 0 and vector_score < 0.35:
            continue
        item = ContextItem(
            address=entry.address,
            title=entry.title,
            excerpt=entry.body.strip()[:280],
            authority=entry.authority,
            source_type=entry.curation_origin,
            token_estimate=_estimate_tokens(entry.body),
        )
        if is_mandatory:
            # Mandatory policy is retained even if it alone exceeds the
            # budget (plan section 6, checklist "mandatory-policy overflow").
            mandatory_items.append(item)
            used_tokens += item.token_estimate
            continue
        if used_tokens + item.token_estimate > request.token_budget:
            excluded_over_budget += 1
            continue
        curated_items.append(item)
        used_tokens += item.token_estimate

    return ContextBundle(
        mandatory_policies=mandatory_items,
        curated_memory=curated_items,
        relevant_evidence=[],
        conflict_warnings=[],
        token_estimate=used_tokens,
        index_revision=str(len(corpus)),
        generated_at=now_iso(),
        retrieval_trace=RetrievalTrace(
            channel="hybrid-model2vec-lexical" if dense_available else "lexical-idf",
            query_tokens=sorted(query_tokens),
            candidates_considered=len(corpus),
            excluded_over_budget=excluded_over_budget,
        ),
    )
