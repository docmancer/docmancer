#!/usr/bin/env python3
"""Run honest local-only LoCoMo and LongMemEval-S retrieval evaluations."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from docmancer import __version__
from docmancer.agent import DocmancerAgent
from docmancer.core.config import (
    DocmancerConfig,
    EmbeddingsConfig,
    IndexConfig,
    QueryConfig,
    RetrievalConfig,
    VectorStoreConfig,
)
from docmancer.core.models import Document
from docmancer.embeddings import get_embeddings_provider
from docmancer.retrieval.dispatch import RetrievalDispatcher
from docmancer.stores.base import get_vector_store


ROOT = Path(__file__).resolve().parent
DATASETS = json.loads((ROOT / "datasets.lock.json").read_text(encoding="utf-8"))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def session_text(turns: list[dict[str, Any]], date: str | None = None) -> str:
    lines = [f"Session date: {date}"] if date else []
    for turn in turns:
        speaker = str(turn.get("speaker") or turn.get("role") or "speaker").upper()
        content = str(turn.get("text") or turn.get("content") or "").strip()
        caption = str(turn.get("blip_caption") or "").strip()
        parts = [part for part in (content, f"Photo caption: {caption}" if caption else "") if part]
        lines.append(f"{speaker}: {' '.join(parts)}")
    return "\n".join(lines)


class LocalRetriever:
    def __init__(
        self,
        work: Path,
        embeddings: EmbeddingsConfig,
        provider,
    ) -> None:
        self.work = work
        config = DocmancerConfig(
            index=IndexConfig(db_path=str(work / "index.db"), extracted_dir=""),
            query=QueryConfig(default_limit=10, default_budget=100_000, default_expand=""),
            vector_store=VectorStoreConfig(
                provider="sqlite-vec",
                collection=f"public_benchmark_{embeddings.provider}_{embeddings.dimensions}",
                options={"db_path": str(work / "vectors.db")},
            ),
            embeddings=embeddings,
            # sqlite-vec stores dense vectors only. Queries still run the
            # shipping lexical+dense hybrid dispatcher below.
            retrieval=RetrievalConfig(default_mode="dense", expand=None, budget=100_000, limit=10),
        )
        self.config = config
        self.agent = DocmancerAgent(config=config)
        self.provider = provider

    def ingest(self, documents: list[Document]) -> float:
        started = time.perf_counter()
        self.agent.ingest_documents(
            documents,
            recreate=True,
            with_vectors=True,
            embeddings_provider=self.provider,
        )
        return (time.perf_counter() - started) * 1000

    def query(
        self,
        question: str,
        limit: int,
        *,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list, float]:
        vector = get_vector_store(
            self.config.vector_store,
            embeddings_dim=self.config.embeddings.dimensions,
        )
        dispatcher = RetrievalDispatcher(
            store=self.agent.store,
            config=self.config,
            vector_store=vector,
            provider=self.provider,
            collection=self.config.vector_store.collection
            or f"public_benchmark_{self.config.embeddings.provider}_{self.config.embeddings.dimensions}",
        )
        started = time.perf_counter()
        result = dispatcher.run(
            question,
            mode="hybrid",
            limit=limit,
            budget=100_000,
            filters=filters,
            allow_degraded=False,
        )
        return result.chunks, (time.perf_counter() - started) * 1000


def score_rows(rows: list[dict[str, Any]], ingest_ms: list[float], metadata: dict[str, Any]) -> dict[str, Any]:
    eligible = [row for row in rows if not row.get("excluded")]
    if not eligible:
        raise ValueError("the selected benchmark slice has no retrieval-evaluable cases")
    latencies = [float(row["latency_ms"]) for row in eligible]
    category: dict[str, dict[str, float]] = {}
    for name in sorted({str(row["category"]) for row in eligible}):
        selected = [row for row in eligible if str(row["category"]) == name]
        category[name] = {
            "cases": len(selected),
            "recall_at_1": sum(row["rank"] == 1 for row in selected) / len(selected),
            "recall_at_5": sum(bool(row["rank"] and row["rank"] <= 5) for row in selected) / len(selected),
            "mrr": statistics.mean(1 / row["rank"] if row["rank"] else 0 for row in selected),
        }
    report = {
        **metadata,
        "cases_total": len(rows),
        "cases_evaluated": len(eligible),
        "cases_excluded": len(rows) - len(eligible),
        "recall_at_1": sum(row["rank"] == 1 for row in eligible) / len(eligible),
        "recall_at_3": sum(bool(row["rank"] and row["rank"] <= 3) for row in eligible) / len(eligible),
        "recall_at_5": sum(bool(row["rank"] and row["rank"] <= 5) for row in eligible) / len(eligible),
        "mrr": statistics.mean(1 / row["rank"] if row["rank"] else 0 for row in eligible),
        "query_latency_ms": {
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
        },
        "ingestion_ms": {
            "total": round(sum(ingest_ms), 2),
            "p50": round(percentile(ingest_ms, 0.50), 2),
            "p95": round(percentile(ingest_ms, 0.95), 2),
        },
        "categories": category,
        "losses": [row for row in eligible if not row["rank"]],
        "results": rows,
    }
    if any("session_rank" in row for row in eligible):
        report["session_location"] = score_rank_field(eligible, "session_rank")
    non_adversarial = [row for row in eligible if str(row["category"]) != "5"]
    adversarial = [row for row in eligible if str(row["category"]) == "5"]
    report["non_adversarial"] = score_rank_field(non_adversarial, "rank") if non_adversarial else None
    report["adversarial"] = score_rank_field(adversarial, "rank") if adversarial else None
    return report


def score_rank_field(rows: list[dict[str, Any]], field: str) -> dict[str, float | int]:
    return {
        "cases": len(rows),
        "recall_at_1": sum(row.get(field) == 1 for row in rows) / len(rows),
        "recall_at_3": sum(bool(row.get(field) and row[field] <= 3) for row in rows) / len(rows),
        "recall_at_5": sum(bool(row.get(field) and row[field] <= 5) for row in rows) / len(rows),
        "mrr": statistics.mean(1 / row[field] if row.get(field) else 0 for row in rows),
    }


def _locomo_sessions(conversation: dict[str, Any]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    convo = conversation["conversation"]
    keys = sorted(
        (key for key in convo if key.startswith("session_") and not key.endswith("_date_time")),
        key=lambda value: int(value.split("_")[-1]),
    )
    return [(key, str(convo.get(f"{key}_date_time") or ""), convo[key]) for key in keys]


def _locomo_documents(
    conversation: dict[str, Any],
    mode: str,
    *,
    window_size: int = 5,
) -> tuple[list[Document], dict[str, str]]:
    sample = str(conversation["sample_id"])
    documents: list[Document] = []
    dialogue_to_session: dict[str, str] = {}
    for session_id, date, turns in _locomo_sessions(conversation):
        member_ids = [str(turn["dia_id"]) for turn in turns]
        dialogue_to_session.update({dialogue_id: session_id for dialogue_id in member_ids})
        if mode == "session":
            documents.append(
                Document(
                    source=f"locomo://{sample}/{session_id}",
                    content=session_text(turns, date),
                    metadata={
                        "benchmark_id": session_id,
                        "session_id": session_id,
                        "member_ids": member_ids,
                        "sample_id": sample,
                        "date": date,
                    },
                )
            )
            continue
        if mode == "window":
            radius = window_size // 2
            for index, turn in enumerate(turns):
                start = max(0, index - radius)
                end = min(len(turns), index + radius + 1)
                window_turns = turns[start:end]
                window_ids = [str(item["dia_id"]) for item in window_turns]
                documents.append(
                    Document(
                        source=f"locomo://{sample}/{session_id}/window-{index}",
                        content=session_text(window_turns, date),
                        metadata={
                            "benchmark_id": f"{session_id}:window:{index}",
                            "session_id": session_id,
                            "member_ids": window_ids,
                            "sample_id": sample,
                            "date": date,
                        },
                    )
                )
            continue
        if mode == "contextual-turn":
            radius = window_size // 2
            for index, turn in enumerate(turns):
                dialogue_id = str(turn["dia_id"])
                start = max(0, index - radius)
                end = min(len(turns), index + radius + 1)
                documents.append(
                    Document(
                        source=f"locomo://{sample}/{dialogue_id}",
                        content=session_text(turns[start:end], date),
                        metadata={
                            "benchmark_id": dialogue_id,
                            "session_id": session_id,
                            "member_ids": [dialogue_id],
                            "context_member_ids": [
                                str(item["dia_id"]) for item in turns[start:end]
                            ],
                            "sample_id": sample,
                            "date": date,
                        },
                    )
                )
            continue
        for turn in turns:
            dialogue_id = str(turn["dia_id"])
            documents.append(
                Document(
                    source=f"locomo://{sample}/{dialogue_id}",
                    content=session_text([turn], date),
                    metadata={
                        "benchmark_id": dialogue_id,
                        "session_id": session_id,
                        "member_ids": [dialogue_id],
                        "sample_id": sample,
                        "date": date,
                    },
                )
            )
    return documents, dialogue_to_session


def _rank_members(
    chunks: list,
    gold_ids: set[str],
    *,
    include_context: bool = False,
) -> int | None:
    return next(
        (
            position
            for position, chunk in enumerate(chunks, 1)
            if gold_ids
            & {
                str(value)
                for value in (
                    (chunk.metadata or {}).get(
                        "context_member_ids" if include_context else "member_ids"
                    )
                    or []
                )
            }
        ),
        None,
    )


def _rank_sessions(chunks: list, gold_sessions: set[str]) -> int | None:
    seen: set[str] = set()
    position = 0
    for chunk in chunks:
        session_id = str((chunk.metadata or {}).get("session_id") or "")
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        position += 1
        if session_id in gold_sessions:
            return position
    return None


def _collapse_overlapping_contexts(chunks: list, limit: int) -> list:
    """Keep the best-ranked candidate from each overlapping context region."""
    selected: list = []
    occupied: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        metadata = chunk.metadata or {}
        session_id = str(metadata.get("session_id") or "")
        context_ids = {
            str(value)
            for value in (
                metadata.get("context_member_ids")
                or metadata.get("member_ids")
                or []
            )
        }
        if context_ids and context_ids & occupied[session_id]:
            continue
        selected.append(chunk)
        occupied[session_id].update(context_ids)
        if len(selected) >= limit:
            break
    return selected


def run_locomo(
    dataset: Path,
    work_root: Path,
    cache: Path,
    limit: int | None,
    *,
    mode: str = "turn",
    window_size: int = 5,
    embeddings: EmbeddingsConfig | None = None,
) -> dict[str, Any]:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    embeddings = embeddings or benchmark_embeddings("local-default", cache)
    provider = get_embeddings_provider(embeddings)
    rows: list[dict[str, Any]] = []
    ingests: list[float] = []
    count = 0
    for conversation in data:
        if limit is not None and count >= limit:
            break
        sample = str(conversation["sample_id"])
        document_mode = (
            "contextual-turn"
            if mode in {"hierarchical", "hierarchical-window-dedup"}
            else "turn"
            if mode == "hierarchical-turn"
            else mode
        )
        documents, dialogue_to_session = _locomo_documents(
            conversation,
            document_mode,
            window_size=window_size,
        )
        with tempfile.TemporaryDirectory(prefix="docmancer-locomo-", dir=work_root) as directory:
            retriever = LocalRetriever(Path(directory), embeddings, provider)
            ingests.append(retriever.ingest(documents))
            session_retriever = None
            if mode.startswith("hierarchical"):
                session_documents, _ = _locomo_documents(conversation, "session")
                session_work = Path(directory) / "sessions"
                session_work.mkdir()
                session_retriever = LocalRetriever(session_work, embeddings, provider)
                ingests.append(session_retriever.ingest(session_documents))
            for qa in conversation["qa"]:
                if limit is not None and count >= limit:
                    break
                evidence = {str(value) for value in qa.get("evidence") or []}
                row = {
                    "id": f"{sample}:{count}",
                    "category": str(qa.get("category") or "unknown"),
                    "question": str(qa["question"]),
                    "answer": qa.get("answer"),
                    "gold_ids": sorted(evidence),
                }
                if not evidence:
                    row.update(excluded=True, exclusion_reason="no released retrieval evidence", rank=None, latency_ms=0)
                else:
                    gold_sessions = {
                        dialogue_to_session[dialogue_id]
                        for dialogue_id in evidence
                        if dialogue_id in dialogue_to_session
                    }
                    if mode.startswith("hierarchical") and session_retriever is not None:
                        session_chunks, session_latency = session_retriever.query(str(qa["question"]), 5)
                        selected_sessions = {
                            str((chunk.metadata or {}).get("session_id") or "")
                            for chunk in session_chunks
                        }
                        second_stage_limit = 50 if mode == "hierarchical-window-dedup" else 10
                        chunks, turn_latency = retriever.query(
                            str(qa["question"]),
                            second_stage_limit,
                            filters={"session_id": {"in": sorted(selected_sessions)}},
                        )
                        if mode == "hierarchical-window-dedup":
                            chunks = _collapse_overlapping_contexts(chunks, 10)
                        latency = session_latency + turn_latency
                        session_rank = _rank_sessions(session_chunks, gold_sessions)
                    else:
                        chunks, latency = retriever.query(str(qa["question"]), 10)
                        session_rank = _rank_sessions(chunks, gold_sessions)
                    ranked = [str((chunk.metadata or {}).get("benchmark_id") or "") for chunk in chunks]
                    row.update(
                        excluded=False,
                        rank=_rank_members(
                            chunks,
                            evidence,
                            include_context=mode == "hierarchical-window-dedup",
                        ),
                        session_rank=session_rank,
                        retrieved_ids=ranked,
                        retrieved_member_ids=[
                            [str(value) for value in ((chunk.metadata or {}).get("member_ids") or [])]
                            for chunk in chunks
                        ],
                        retrieved_context_member_ids=(
                            [
                                [
                                    str(value)
                                    for value in (
                                        (chunk.metadata or {}).get("context_member_ids")
                                        or []
                                    )
                                ]
                                for chunk in chunks
                            ]
                            if mode == "hierarchical-window-dedup"
                            else None
                        ),
                        latency_ms=round(latency, 2),
                    )
                rows.append(row)
                count += 1
                if count % 50 == 0:
                    print(f"LoCoMo progress: {count} questions", flush=True)
    metadata = report_metadata("locomo", dataset, embeddings)
    metadata.update(
        {
            "locomo_index_mode": mode,
            "window_size": (
                window_size
                if mode in {"window", "hierarchical", "hierarchical-window-dedup"}
                else None
            ),
            "metric_boundary": (
                "retrieval only; a hit requires a deduplicated retrieved window to contain a released gold dialogue ID"
                if mode == "hierarchical-window-dedup"
                else "retrieval only; a hit requires the retrieved document's scored member IDs to contain a released gold dialogue ID"
            ),
        }
    )
    return score_rows(rows, ingests, metadata)


def run_longmemeval(
    dataset: Path, work_root: Path, cache: Path, limit: int | None,
    checkpoint: Path,
    embeddings: EmbeddingsConfig | None = None,
) -> dict[str, Any]:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    embeddings = embeddings or benchmark_embeddings("local-default", cache)
    provider = get_embeddings_provider(embeddings)
    rows: list[dict[str, Any]] = []
    if checkpoint.is_file():
        rows = [
            json.loads(line)
            for line in checkpoint.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(f"Resuming LongMemEval-S after {len(rows)} checkpointed cases", flush=True)
    completed = {str(row["id"]) for row in rows}
    ingests: list[float] = [
        float(row["ingestion_ms"]) for row in rows if float(row.get("ingestion_ms") or 0) > 0
    ]
    for index, case in enumerate(data):
        if limit is not None and index >= limit:
            break
        question_id = str(case["question_id"])
        if question_id in completed:
            continue
        gold = {str(value) for value in case.get("answer_session_ids") or []}
        row = {
            "id": question_id,
            "category": "abstention" if question_id.endswith("_abs") else str(case["question_type"]),
            "question": str(case["question"]),
            "answer": case.get("answer"),
            "gold_ids": sorted(gold),
        }
        if question_id.endswith("_abs") or not gold:
            row.update(excluded=True, exclusion_reason="official retrieval evaluation excludes abstention", rank=None, latency_ms=0, ingestion_ms=0)
            rows.append(row)
            append_checkpoint(checkpoint, row)
            continue
        documents = [
            Document(
                source=f"longmemeval://{question_id}/{session_id}",
                content=session_text(turns, str(date)),
                metadata={"benchmark_id": str(session_id), "question_id": question_id, "date": str(date)},
            )
            for session_id, date, turns in zip(
                case["haystack_session_ids"],
                case["haystack_dates"],
                case["haystack_sessions"],
                strict=True,
            )
        ]
        with tempfile.TemporaryDirectory(prefix="docmancer-longmemeval-", dir=work_root) as directory:
            retriever = LocalRetriever(Path(directory), embeddings, provider)
            ingestion_ms = retriever.ingest(documents)
            ingests.append(ingestion_ms)
            chunks, latency = retriever.query(str(case["question"]), 10)
        ranked = [str((chunk.metadata or {}).get("benchmark_id") or "") for chunk in chunks]
        row.update(
            excluded=False,
            rank=next((position for position, item in enumerate(ranked, 1) if item in gold), None),
            retrieved_ids=ranked,
            latency_ms=round(latency, 2),
            ingestion_ms=round(ingestion_ms, 2),
        )
        rows.append(row)
        append_checkpoint(checkpoint, row)
        if len(rows) % 10 == 0:
            print(f"LongMemEval-S progress: {len(rows)} cases", flush=True)
    return score_rows(rows, ingests, report_metadata("longmemeval-s", dataset, embeddings))


def append_checkpoint(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def benchmark_embeddings(profile: str, cache: Path) -> EmbeddingsConfig:
    if profile == "fastembed-dense":
        return EmbeddingsConfig(
            provider="fastembed",
            model="BAAI/bge-base-en-v1.5",
            dimensions=768,
            cache=str(cache / "fastembed-dense"),
            batch_size=64,
        )
    return EmbeddingsConfig(
        provider="model2vec",
        model="minishlab/potion-base-8M",
        dimensions=256,
        cache=str(cache / "model2vec"),
        batch_size=64,
    )


def report_metadata(
    name: str,
    dataset: Path,
    embeddings: EmbeddingsConfig,
) -> dict[str, Any]:
    peak_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak_rss_mb = peak_rss / (1024 * 1024) if sys.platform == "darwin" else peak_rss / 1024
    return {
        "schema_version": 1,
        "benchmark": name,
        "configuration": (
            "pure-local-fastembed-dense-sqlite-vec-hybrid"
            if embeddings.provider == "fastembed"
            else "pure-local-model2vec-sqlite-vec-hybrid"
        ),
        "docmancer_version": __version__,
        "dataset_sha256": sha256(dataset),
        "dataset_expected_sha256": DATASETS[name]["sha256"],
        "dataset_source": DATASETS[name]["source"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "peak_rss_mb": round(peak_rss_mb, 2),
        },
        "embedding_provider": embeddings.provider,
        "embedding_model": (
            f"{embeddings.model} (local optional download)"
            if embeddings.provider == "fastembed"
            else f"{embeddings.model} (bundled)"
        ),
        "embedding_dimensions": embeddings.dimensions,
        "vector_store": "sqlite-vec",
        "retrieval": "hybrid lexical+dense reciprocal-rank fusion",
        "cache_state": (
            "downloaded local FastEmbed model warm after provider initialization; every corpus index is newly created"
            if embeddings.provider == "fastembed"
            else "bundled model warm after provider initialization; every corpus index is newly created"
        ),
        "reader_prompt": None,
        "judge_model": None,
        "curation_cost_usd": 0,
        "provider_calls": 0,
        "provider_cost_usd": 0,
        "metric_boundary": "retrieval only; a hit requires a released gold dialogue or session in the top k",
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = output.with_suffix(".md")
    summary.write_text(
        "\n".join(
            [
                f"# {report['benchmark']} local retrieval report",
                "",
                f"- Dataset SHA-256: `{report['dataset_sha256']}`",
                f"- Cases evaluated: {report['cases_evaluated']} of {report['cases_total']}",
                f"- Recall@1: {report['recall_at_1']:.2%}",
                f"- Recall@3: {report['recall_at_3']:.2%}",
                f"- Recall@5: {report['recall_at_5']:.2%}",
                f"- MRR: {report['mrr']:.4f}",
                f"- Query latency p50: {report['query_latency_ms']['p50']:.2f} ms",
                f"- Query latency p95: {report['query_latency_ms']['p95']:.2f} ms",
                f"- Corpus ingestion total: {report['ingestion_ms']['total']:.2f} ms",
                "- Provider calls: 0",
                "- Provider cost: $0",
                "",
                "This is a retrieval evaluation, not end-to-end answer accuracy. The generated JSON contains every query, rank, retrieved identifier, exclusion, and loss. Checked-in publication artifacts omit dataset question and answer text.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=["locomo", "longmemeval-s"])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--locomo-mode",
        choices=[
            "turn",
            "window",
            "session",
            "hierarchical",
            "hierarchical-turn",
            "hierarchical-window-dedup",
        ],
        default="turn",
        help="LoCoMo indexing and retrieval boundary.",
    )
    parser.add_argument("--window-size", type=int, choices=[3, 5], default=5)
    parser.add_argument(
        "--embedding-profile",
        choices=["local-default", "fastembed-dense"],
        default="local-default",
        help="Local embedding profile. FastEmbed is an optional dense-only sensitivity run.",
    )
    args = parser.parse_args()
    spec = DATASETS[args.benchmark]
    dataset = args.data_dir / spec["filename"]
    if not dataset.exists():
        raise SystemExit(f"missing {dataset}; run benchmarks/download.py first")
    actual = sha256(dataset)
    if actual != spec["sha256"]:
        raise SystemExit(f"dataset checksum mismatch: expected {spec['sha256']}, got {actual}")
    profile_suffix = "-fastembed-dense" if args.embedding_profile == "fastembed-dense" else ""
    default_name = (
        f"locomo-{args.locomo_mode}{profile_suffix}-local.json"
        if args.benchmark == "locomo"
        else f"{args.benchmark}{profile_suffix}-local.json"
    )
    output = args.output or ROOT / "results" / default_name
    cache = ROOT / ".cache" / "embeddings"
    work = ROOT / ".cache" / "work"
    work.mkdir(parents=True, exist_ok=True)
    embeddings = benchmark_embeddings(args.embedding_profile, cache)
    if args.benchmark == "locomo":
        report = run_locomo(
            dataset,
            work,
            cache,
            args.limit,
            mode=args.locomo_mode,
            window_size=args.window_size,
            embeddings=embeddings,
        )
    else:
        report = run_longmemeval(
            dataset,
            work,
            cache,
            args.limit,
            output.with_suffix(".partial.jsonl"),
            embeddings,
        )
    write_report(report, output)
    if args.benchmark == "longmemeval-s":
        output.with_suffix(".partial.jsonl").unlink(missing_ok=True)
    print(json.dumps({key: report[key] for key in ("benchmark", "cases_evaluated", "recall_at_1", "recall_at_3", "recall_at_5", "mrr", "query_latency_ms", "provider_cost_usd")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
