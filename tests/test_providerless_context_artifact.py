"""No-key, no-network acceptance test for the T013 providerless Context artifact."""
from __future__ import annotations

import socket

import httpx
import pytest

from docmancer.memory.tree.providerless_context import (
    ClusterMember,
    ConflictEntry,
    ConflictSide,
    ProviderlessCluster,
    render_providerless_cluster,
)


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt at a network call fails loudly instead of silently succeeding."""
    calls = {"count": 0}

    def _blocked(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("network access attempted during a providerless render")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(httpx.Client, "__init__", _blocked)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", _blocked)
    return calls


def _fixture_cluster() -> ProviderlessCluster:
    members = (
        ClusterMember(
            record_id="rec_1",
            path="decisions/vector-store.md",
            harness="claude-code",
            recorded_at="2026-05-02",
            text="sqlite-vec was chosen because it needs no daemon.",
        ),
        ClusterMember(
            record_id="rec_2",
            path="decisions/vector-store-note.md",
            harness="codex",
            recorded_at="2026-05-03",
            text="sqlite-vec avoids a daemon dependency, matching the local-first goal.",
        ),
    )
    return ProviderlessCluster(
        cluster_id="cluster_vector_store",
        topic_label="Vector store choice",
        members=members,
        duplicate_counts={"rec_1": 3},
        collapsed_sources={"rec_1": ("cursor:decisions/vector-store.md", "gemini:decisions/vector-store.md")},
        conflicts=(
            ConflictEntry(
                description="whether FastEmbed is required",
                sides=(
                    ConflictSide(
                        claim="FastEmbed is required for retrieval.",
                        date="2026-04-01",
                        source="claude-code",
                        record_id="rec_3",
                    ),
                    ConflictSide(
                        claim="FastEmbed is optional; model2vec is the default.",
                        date="2026-05-02",
                        source="codex",
                        record_id="rec_4",
                    ),
                ),
            ),
        ),
    )


def test_render_makes_zero_provider_calls(no_network):
    render_providerless_cluster(_fixture_cluster())
    assert no_network["count"] == 0


def test_render_output_is_non_empty(no_network):
    output = render_providerless_cluster(_fixture_cluster())
    assert output.strip()
    assert no_network["count"] == 0


def test_every_body_line_traces_to_a_member_record_or_a_structural_label(no_network):
    cluster = _fixture_cluster()
    output = render_providerless_cluster(cluster)

    member_text_fragments = set()
    for member in cluster.members:
        member_text_fragments.add(member.path)
        member_text_fragments.add(member.harness)
        member_text_fragments.add(member.recorded_at)
        member_text_fragments.update(member.text.split("\n"))
    for conflict in cluster.conflicts:
        member_text_fragments.add(conflict.description)
        for side in conflict.sides:
            member_text_fragments.add(side.claim)
            member_text_fragments.add(side.date)
            member_text_fragments.add(side.source)
            member_text_fragments.add(side.record_id)

    structural_prefixes = ("# ", "## ", "Source:", "Duplicates:", "Conflict:", "- ")

    for line in output.splitlines():
        if not line.strip():
            continue
        if line.startswith(structural_prefixes):
            continue
        assert line.strip() in member_text_fragments, f"unattributed line in providerless render: {line!r}"

    assert no_network["count"] == 0
