"""Context Compiler v1 tests (checklist A.9, A.10).

Includes a direct regression test for the Release 0 go/adjust/stop
finding: a naive word-overlap scorer let the product's own name pollute
rankings. This proves the IDF-weighted fix actually closes that gap using
the same reproduction scenario recorded in the Release 0 decision doc.
"""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree.compiler import ContextRequest, compile_context, fuse_scores
from docmancer.memory.tree.store import TreeStore


def test_mandatory_policy_survives_budget_and_relevance(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="policy.md", text="# Never commit env files\n\nNever commit .env files.\n", authority="mandatory", expect="absent")
    for i in range(5):
        store.write(relative_path=f"note-{i}.md", text=f"# Note {i}\n\nUnrelated spacing detail {i}.\n", expect="absent")

    bundle = compile_context(store.index, ContextRequest(task="design system spacing", token_budget=50))
    assert any(item.title == "Never commit env files" for item in bundle.mandatory_policies)


def test_authority_ordering_team_over_relevant_personal(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(
        relative_path="team-instruction.md",
        text="# Release pipeline\n\nAlways run migrations through the release pipeline.\n",
        authority="mandatory",
        expect="absent",
    )
    store.write(
        relative_path="personal-note.md",
        text="# Migration thoughts\n\nThe migration pipeline release process is worth reviewing again.\n",
        expect="absent",
    )
    bundle = compile_context(store.index, ContextRequest(task="migration pipeline release process"))
    all_items = bundle.mandatory_policies + bundle.curated_memory
    titles = [item.title for item in all_items]
    assert titles.index("Release pipeline") < titles.index("Migration thoughts")


def test_query_sensitive_selection(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="deploy.md", text="# Deploy\n\nDeploy through the release-patch script.\n", expect="absent")
    store.write(relative_path="design.md", text="# Design\n\nFollow the design system spacing scale.\n", expect="absent")

    deploy_bundle = compile_context(store.index, ContextRequest(task="How do I deploy a release?"))
    design_bundle = compile_context(store.index, ContextRequest(task="What is the design system spacing?"))

    deploy_titles = [item.title for item in deploy_bundle.curated_memory]
    design_titles = [item.title for item in design_bundle.curated_memory]
    # With only these two unrelated documents and no shared tokens, the
    # compiler excludes the irrelevant one entirely rather than merely
    # re-ranking it -- a stronger property than simple reordering.
    assert deploy_titles == ["Deploy"]
    assert design_titles == ["Design"]


def test_release_0_product_name_pollution_is_fixed(tmp_path: Path) -> None:
    """Reproduces the exact Release 0 finding: nearly every note mentions
    "docmancer" by name, and a naive word-overlap scorer let that pollute
    rankings. The IDF weighting must down-rank the ubiquitous term."""
    store = TreeStore(tmp_path / "memory")
    store.write(
        relative_path="retrieval-stack.md",
        text=(
            "# Default retrieval stack is local and offline\n\n"
            "Docmancer defaults to sqlite-vec plus the vendored model2vec "
            "potion-base-8M model, with no API key required.\n"
        ),
        expect="absent",
    )
    store.write(
        relative_path="release-process.md",
        text=(
            "# Release process uses a scripted patch bump\n\n"
            "Docmancer's release-patch-pypi.sh script owns the version "
            "bump and tag; never hand-edit the version.\n"
        ),
        expect="absent",
    )
    store.write(
        relative_path="mcp-surface.md",
        text="# MCP is the primary agent surface\n\nDocmancer exposes write_memory and search_memory over MCP.\n",
        expect="absent",
    )

    bundle = compile_context(
        store.index,
        ContextRequest(task="What retrieval stack does Docmancer use by default and why?"),
    )
    titles = [item.title for item in bundle.curated_memory]
    assert titles[0] == "Default retrieval stack is local and offline"
    # The unrelated release-process note must not out-rank or tie the
    # correct answer merely because both mention "docmancer".
    assert "Release process uses a scripted patch bump" not in titles[:1]


def test_bundle_stays_within_token_budget_when_mandatory_fits(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    for i in range(20):
        store.write(relative_path=f"note-{i}.md", text=f"# Note {i}\n\n" + ("word " * 200) + "\n", expect="absent")

    bundle = compile_context(store.index, ContextRequest(task="note", token_budget=100))
    assert bundle.token_estimate <= 100 + 1  # small rounding slack from the coarse estimator


def test_conflict_warnings_and_evidence_are_empty_by_default(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="a.md", text="# A\n\nBody.\n", expect="absent")
    bundle = compile_context(store.index, ContextRequest(task="a"))
    assert bundle.conflict_warnings == []
    assert bundle.relevant_evidence == []


def test_no_answer_state_when_nothing_clears_the_relevance_floor(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="a.md", text="# Deployment\n\nDeploy steps.\n", expect="absent")
    bundle = compile_context(store.index, ContextRequest(task="quantum thermodynamics"))
    assert bundle.curated_memory == []
    assert bundle.mandatory_policies == []


def test_fuse_scores_matches_the_documented_formula() -> None:
    assert fuse_scores(0.8, 0.2) == 0.8 + 0.3 * 0.2
    assert fuse_scores(0.0, 0.5) == 0.5


def test_retrieval_trace_exposes_bounded_native_scores_and_outcomes(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "tree")
    for index in range(25):
        topic = "railway deployment" if index == 0 else f"unrelated topic {index}"
        store.write(
            relative_path=f"notes/{index}.md",
            text=f"# Note {index}\n\n{topic}\n",
            expect="absent",
        )

    bundle = compile_context(
        store.index,
        ContextRequest(task="railway deployment", token_budget=1000),
    )

    trace = bundle.retrieval_trace
    assert trace.candidates_considered == 25
    assert len(trace.candidate_scores) == 20
    assert trace.candidate_scores_truncated == 5
    selected = trace.candidate_scores[0]
    assert selected.address.startswith("docmancer://memory/")
    assert selected.lexical_score > 0
    assert selected.lexical_normalized == 1.0
    assert 0 <= selected.dense_score <= 1
    assert selected.fused_score >= selected.lexical_normalized
    assert selected.selected is True
    assert selected.exclusion_reason is None
    assert any(score.exclusion_reason == "not_relevant" for score in trace.candidate_scores)
