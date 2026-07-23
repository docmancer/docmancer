from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location("public_benchmark", ROOT / "benchmarks" / "run_retrieval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_text_preserves_date_roles_and_content():
    module = load_runner()
    rendered = module.session_text(
        [{"role": "user", "content": "I deploy on Railway."}, {"role": "assistant", "content": "Noted."}],
        "2026-07-23",
    )
    assert rendered == "Session date: 2026-07-23\nUSER: I deploy on Railway.\nASSISTANT: Noted."


def test_session_text_preserves_caption_when_turn_also_has_text():
    module = load_runner()
    rendered = module.session_text(
        [{"speaker": "nate", "text": "Check out this pic!", "blip_caption": "A red kayak on a lake"}]
    )
    assert rendered == "NATE: Check out this pic! Photo caption: A red kayak on a lake"


def test_dataset_lock_has_reproducible_public_sources():
    locked = json.loads((ROOT / "benchmarks" / "datasets.lock.json").read_text(encoding="utf-8"))
    assert set(locked) == {"locomo", "longmemeval-s"}
    for row in locked.values():
        assert row["source"].startswith("https://")
        assert len(row["sha256"]) == 64


def test_score_rows_reports_losses_categories_and_latency():
    module = load_runner()
    report = module.score_rows(
        [
            {"category": "one", "rank": 1, "latency_ms": 10, "excluded": False},
            {"category": "one", "rank": None, "latency_ms": 20, "excluded": False},
            {"category": "none", "rank": None, "latency_ms": 0, "excluded": True},
        ],
        [100],
        {"benchmark": "fixture"},
    )
    assert report["cases_evaluated"] == 2
    assert report["cases_excluded"] == 1
    assert report["recall_at_1"] == 0.5
    assert report["recall_at_5"] == 0.5
    assert len(report["losses"]) == 1
    assert report["non_adversarial"]["cases"] == 2
    assert report["adversarial"] is None


def test_locomo_context_units_keep_member_ids_and_session_identity():
    module = load_runner()
    conversation = {
        "sample_id": "sample",
        "conversation": {
            "session_1": [
                {"dia_id": "D1:1", "speaker": "a", "text": "Trek stories."},
                {"dia_id": "D1:2", "speaker": "b", "text": "I visited a travel agency."},
                {"dia_id": "D1:3", "speaker": "a", "text": "Great."},
            ],
            "session_1_date_time": "2026-01-01",
        },
    }
    windows, mapping = module._locomo_documents(conversation, "window", window_size=3)
    sessions, _ = module._locomo_documents(conversation, "session")

    assert mapping == {"D1:1": "session_1", "D1:2": "session_1", "D1:3": "session_1"}
    assert windows[1].metadata["member_ids"] == ["D1:1", "D1:2", "D1:3"]
    assert sessions[0].metadata["member_ids"] == ["D1:1", "D1:2", "D1:3"]
    assert sessions[0].metadata["session_id"] == "session_1"


def test_score_rows_reports_session_location_and_adversarial_boundary():
    module = load_runner()
    report = module.score_rows(
        [
            {"category": "4", "rank": None, "session_rank": 1, "latency_ms": 10, "excluded": False},
            {"category": "5", "rank": 1, "session_rank": 1, "latency_ms": 20, "excluded": False},
        ],
        [100],
        {"benchmark": "fixture"},
    )
    assert report["session_location"]["recall_at_1"] == 1.0
    assert report["non_adversarial"]["recall_at_1"] == 0.0
    assert report["adversarial"]["recall_at_1"] == 1.0


def test_session_rank_deduplicates_retrieved_turns_from_the_same_session():
    module = load_runner()

    class Chunk:
        def __init__(self, session_id):
            self.metadata = {"session_id": session_id}

    chunks = [Chunk("session_1"), Chunk("session_1"), Chunk("session_2")]
    assert module._rank_sessions(chunks, {"session_2"}) == 2


def test_context_overlap_collapse_keeps_highest_ranked_non_overlapping_units():
    module = load_runner()

    class Chunk:
        def __init__(self, benchmark_id, session_id, context_ids):
            self.metadata = {
                "benchmark_id": benchmark_id,
                "session_id": session_id,
                "context_member_ids": context_ids,
            }

    chunks = [
        Chunk("center-2", "session_1", ["turn-1", "turn-2", "turn-3"]),
        Chunk("center-3", "session_1", ["turn-2", "turn-3", "turn-4"]),
        Chunk("center-8", "session_1", ["turn-7", "turn-8", "turn-9"]),
        Chunk("center-2", "session_2", ["turn-1", "turn-2", "turn-3"]),
    ]

    collapsed = module._collapse_overlapping_contexts(chunks, 10)

    assert [chunk.metadata["benchmark_id"] for chunk in collapsed] == [
        "center-2",
        "center-8",
        "center-2",
    ]


def test_contextual_scoring_can_credit_gold_inside_a_retrieved_window():
    module = load_runner()

    class Chunk:
        metadata = {
            "member_ids": ["center-turn"],
            "context_member_ids": ["before-turn", "center-turn", "gold-turn"],
        }

    assert module._rank_members([Chunk()], {"gold-turn"}) is None
    assert module._rank_members([Chunk()], {"gold-turn"}, include_context=True) == 1


def test_benchmark_embedding_profiles_are_explicit_and_local(tmp_path):
    module = load_runner()
    default = module.benchmark_embeddings("local-default", tmp_path)
    heavy = module.benchmark_embeddings("fastembed-dense", tmp_path)

    assert (default.provider, default.model, default.dimensions) == (
        "model2vec",
        "minishlab/potion-base-8M",
        256,
    )
    assert (heavy.provider, heavy.model, heavy.dimensions) == (
        "fastembed",
        "BAAI/bge-base-en-v1.5",
        768,
    )
