from docmancer.memory.projections import (
    build_context_projection,
    render_context_projection,
    write_context_baseline,
)


def _manifest():
    return {
        "revision_id": "rev_1",
        "scope": {"project_id": "project-1"},
        "conflicts": [],
        "topics": [
            {
                "cluster_id": "ctx_1",
                "synthesized": False,
                "body": "Railway is the recorded deployment target.",
                "source_addresses": ["memory://atom/a1"],
            }
        ],
    }


def test_projection_keeps_generated_topics_separate_from_curated_memory():
    projection = build_context_projection(
        _manifest(),
        {
            "mandatory_policies": [],
            "curated_memory": [
                {
                    "address": "docmancer://memory/one",
                    "excerpt": "Run a smoke test.",
                }
            ],
            "conflict_warnings": [],
        },
        target_agent="codex",
        token_budget=2_000,
    )

    assert projection.curated_memory[0]["excerpt"] == "Run a smoke test."
    assert projection.topic_summaries[0]["cluster_id"] == "ctx_1"
    assert "topic_summaries" in projection.to_dict()


def test_mandatory_overflow_evicts_advisory_before_policy():
    projection = build_context_projection(
        _manifest(),
        {
            "mandatory_policies": [{"excerpt": "M" * 1_000}],
            "curated_memory": [{"excerpt": "advisory"}],
            "conflict_warnings": [],
        },
        target_agent="codex",
        token_budget=100,
    )

    assert projection.mandatory_overflow is True
    assert len(projection.mandatory_policies) == 1
    assert len(projection.curated_memory) == 0
    assert projection.omitted["curated_memory"] == 1


def test_baseline_render_is_byte_idempotent(tmp_path):
    projection = build_context_projection(
        _manifest(),
        {
            "mandatory_policies": [],
            "curated_memory": [],
            "conflict_warnings": [],
        },
        target_agent="codex",
        token_budget=2_000,
    )

    first = write_context_baseline(projection, project_id="project-1", home=tmp_path)
    before = (tmp_path / ".docmancer" / "baselines" / "codex" / "project-1.md").read_bytes()
    second = write_context_baseline(projection, project_id="project-1", home=tmp_path)

    assert first["changed"] is True
    assert second["changed"] is False
    assert render_context_projection(projection).encode() == before
