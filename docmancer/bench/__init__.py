"""docmancer bench: local retrieval + reasoning benchmarking harness.

Compares FTS (stable core), Qdrant vector (experimental, [vector] extra),
and RLM (experimental, [rlm] extra) backends on the same corpus and
question set with reproducible local artifacts.
"""

from docmancer.bench.dataset import BenchDataset, BenchQuestion, load_dataset
from docmancer.bench.backends.base import (
    BackendCapability,
    BenchBackend,
    BenchQuestionResult,
    LatencyBreakdown,
    SourceRef,
)

__all__ = [
    "BenchDataset",
    "BenchQuestion",
    "load_dataset",
    "BenchBackend",
    "BenchQuestionResult",
    "LatencyBreakdown",
    "SourceRef",
    "BackendCapability",
]
