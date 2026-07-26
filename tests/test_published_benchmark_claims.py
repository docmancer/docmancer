"""Lock in the honesty claims published benchmark results depend on (T006).

`docs/docmancer-overview.md` and the public benchmark READMEs assert that these
runs make no provider calls, cost nothing, use no LLM judge or reader, and that
published artifacts never carry dataset question/answer text. These are
regression tests for those specific claims, not general retrieval tests.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_retrieval():
    return _load("public_benchmark_claims", "benchmarks/run_retrieval.py")


def _publish():
    return _load("public_benchmark_publish", "benchmarks/publish.py")


def test_retrieval_run_makes_zero_provider_calls_and_costs_nothing(tmp_path):
    module = _run_retrieval()
    dataset = tmp_path / "locomo10.json"
    dataset.write_bytes(b"{}")
    embeddings = module.benchmark_embeddings("local-default", tmp_path)
    # `locomo` is looked up in DATASETS for its expected hash; the fixture
    # dataset content will not match, which is fine, that field is not asserted.
    module.DATASETS["locomo"] = {"sha256": module.sha256(dataset), "source": "https://example.invalid/locomo10.json"}
    report = module.report_metadata("locomo", dataset, embeddings)
    assert report["provider_calls"] == 0
    assert report["provider_cost_usd"] == 0
    assert report["curation_cost_usd"] == 0


def test_retrieval_run_uses_no_judge_model_or_reader_prompt(tmp_path):
    module = _run_retrieval()
    dataset = tmp_path / "locomo10.json"
    dataset.write_bytes(b"{}")
    embeddings = module.benchmark_embeddings("local-default", tmp_path)
    module.DATASETS["locomo"] = {"sha256": module.sha256(dataset), "source": "https://example.invalid/locomo10.json"}
    report = module.report_metadata("locomo", dataset, embeddings)
    assert report["judge_model"] is None
    assert report["reader_prompt"] is None
    assert report["metric_boundary"] == "retrieval only; a hit requires a released gold dialogue or session in the top k"


def test_publish_strips_question_and_answer_from_every_row(tmp_path):
    module = _publish()
    source = tmp_path / "source.json"
    destination = tmp_path / "published.json"
    source.write_text(
        json.dumps({
            "benchmark": "fixture",
            "cases_evaluated": 2,
            "results": [
                {"case_id": "1", "question": "what port?", "answer": "8080", "rank": 1, "excluded": False},
                {"case_id": "2", "question": "why sqlite-vec?", "answer": "no daemon", "rank": None, "excluded": False},
            ],
        }),
        encoding="utf-8",
    )

    report = module.publish(source, destination)

    for row in report["results"]:
        assert "question" not in row
        assert "answer" not in row
    published = json.loads(destination.read_text(encoding="utf-8"))
    for row in published["results"]:
        assert "question" not in row
        assert "answer" not in row
    assert "publication_note" in report


def test_publish_preserves_non_private_fields(tmp_path):
    module = _publish()
    source = tmp_path / "source.json"
    destination = tmp_path / "published.json"
    source.write_text(
        json.dumps({
            "benchmark": "fixture",
            "cases_evaluated": 1,
            "results": [{"case_id": "1", "question": "q", "answer": "a", "rank": 1, "excluded": False}],
        }),
        encoding="utf-8",
    )
    report = module.publish(source, destination)
    assert report["results"][0]["case_id"] == "1"
    assert report["results"][0]["rank"] == 1
