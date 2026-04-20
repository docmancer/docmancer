"""Backend protocol for docmancer bench.

A backend runs each question once via `run_question()` and returns both the
retrieval set it used and (optionally) the answer it generated from that
same set. This shape forbids hidden re-retrieval inside `answer()` so that
retrieval-vs-answer metrics stay comparable across backends.

RLM is the documented exception: it may iterate and retrieve multiple
times. Its `retrieved` field holds the union of chunks actually consulted
and its `raw` field holds the recursive trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, Set, runtime_checkable

from docmancer.core.models import RetrievedChunk


BackendCapability = Literal["retrieve", "answer", "cite"]


@dataclass
class SourceRef:
    source: str
    section_id: str | None = None


@dataclass
class LatencyBreakdown:
    retrieve_ms: float = 0.0
    answer_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class BenchQuestionResult:
    retrieved: list[RetrievedChunk]
    answer: str | None = None
    citations: list[SourceRef] = field(default_factory=list)
    prompt: str | None = None
    raw: dict = field(default_factory=dict)
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    status: Literal["ok", "timeout", "error"] = "ok"
    error: str | None = None


@dataclass
class CorpusHandle:
    """Opaque reference to the canonical corpus snapshot all backends prepare against."""

    db_path: str
    ingest_hash: str
    extracted_dir: str | None = None


@dataclass
class BackendConfig:
    k_retrieve: int = 10
    k_answer: int = 5
    timeout_s: float = 60.0
    extra: dict = field(default_factory=dict)


@runtime_checkable
class BenchBackend(Protocol):
    name: str
    capabilities: Set[BackendCapability]

    def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None: ...

    def run_question(self, question: str, *, k: int, timeout_s: float) -> BenchQuestionResult: ...

    def teardown(self) -> None: ...
