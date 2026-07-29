"""Cost and resilience guarantees for the Context build.

A real build on a laptop-wide corpus fanned 7,181 atoms into 634 sequential
provider calls, ran for 27 minutes, then lost everything to one TLS error.
"""
from __future__ import annotations

import ssl
import threading
import time
from types import SimpleNamespace

import pytest

from docmancer.memory.context_engine import (
    ContextSource,
    DedupGroup,
    cluster_topics,
    _complete_with_retry,
    _is_transcript_noise,
    _is_transient_provider_error,
)


def _atom(source_path: str, source_title: str = "Memory", text: str = ""):
    return SimpleNamespace(source_path=source_path, source_title=source_title, text=text)


class TestTranscriptFiltering:
    """42% of the paid input was raw session transcript."""

    @pytest.mark.parametrize(
        "title",
        [
            "Raw Memories > Thread `019f45f3-26e1-7f31` > Task 2",
            "Task Group: Bonzo Stage A interest-rate recovery",
            "Rollout context: something",
            "task_outcome: done",
        ],
    )
    def test_transcript_material_is_excluded(self, title):
        assert _is_transcript_noise(_atom("/Users/x/.codex/memories/MEMORY.md", title))

    @pytest.mark.parametrize(
        "title",
        ["Project Memory", "Security & Privacy", "Deploy runbook"],
    )
    def test_durable_material_is_kept(self, title):
        assert not _is_transcript_noise(_atom("/Users/x/repo/CLAUDE.md", title))

    def test_marker_matching_is_case_insensitive(self):
        assert _is_transcript_noise(_atom("/x", "RAW MEMORIES > THREAD abc"))

    def test_transcript_marker_in_atom_text_is_excluded(self):
        assert _is_transcript_noise(
            _atom(
                "/Users/x/.codex/memories/MEMORY.md",
                "Project Memory",
                "Task Group: release review > running commentary",
            )
        )

    def test_missing_fields_do_not_crash(self):
        assert not _is_transcript_noise(SimpleNamespace(source_path=None, source_title=None))


class TestTransientErrorClassification:
    def test_the_error_that_killed_the_real_run_is_transient(self):
        exc = ssl.SSLError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac")
        assert _is_transient_provider_error(exc)

    @pytest.mark.parametrize(
        "exc",
        [ConnectionError("connection reset by peer"), TimeoutError("timed out")],
    )
    def test_transport_faults_are_transient(self, exc):
        assert _is_transient_provider_error(exc)

    def test_named_httpx_style_errors_are_transient(self):
        assert _is_transient_provider_error(type("ReadTimeout", (Exception,), {})("slow"))

    @pytest.mark.parametrize(
        "message",
        ["invalid api key", "model not found", "content policy refusal"],
    )
    def test_permanent_failures_are_not_retried(self, message):
        """Retrying these only multiplies the bill."""
        assert not _is_transient_provider_error(ValueError(message))


class TestRetry:
    def test_a_transient_failure_is_retried_and_succeeds(self, monkeypatch):
        monkeypatch.setattr(
            "docmancer.memory.context_engine.CONTEXT_PROVIDER_BACKOFF_SECONDS", 0.0
        )
        calls = []

        class _Client:
            def complete_text(self, messages, options):
                calls.append(1)
                if len(calls) < 3:
                    raise ssl.SSLError("bad record mac")
                return SimpleNamespace(text="done", cost_usd=0.01)

        result = _complete_with_retry(_Client(), [], None)
        assert result.text == "done"
        assert len(calls) == 3

    def test_a_permanent_failure_fails_immediately(self):
        calls = []

        class _Client:
            def complete_text(self, messages, options):
                calls.append(1)
                raise ValueError("invalid api key")

        with pytest.raises(ValueError):
            _complete_with_retry(_Client(), [], None)
        assert len(calls) == 1, "a permanent error must not be retried"

    def test_retries_are_bounded(self, monkeypatch):
        monkeypatch.setattr(
            "docmancer.memory.context_engine.CONTEXT_PROVIDER_BACKOFF_SECONDS", 0.0
        )
        calls = []

        class _Client:
            def complete_text(self, messages, options):
                calls.append(1)
                raise ssl.SSLError("bad record mac")

        with pytest.raises(ssl.SSLError):
            _complete_with_retry(_Client(), [], None)
        assert len(calls) == 4


class TestConcurrency:
    def test_provider_renders_overlap_and_keep_their_cluster_mapping(self):
        """Independent provider batches must overlap and retain topic mapping."""
        from docmancer.memory.context_engine import ContextEngine

        clusters = [SimpleNamespace(cluster_id=f"c{i}") for i in range(8)]
        active = 0
        peak = 0
        lock = threading.Lock()

        def render(batch, *, client, mode):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {
                cluster.cluster_id: (
                    f"body-{cluster.cluster_id}",
                    True,
                    0.01,
                    False,
                )
                for cluster in batch
            }

        engine = ContextEngine.__new__(ContextEngine)
        engine.distillation = SimpleNamespace(max_concurrency=8)
        engine._last_render_stats = {}
        engine._cluster_batches = lambda pending: [[cluster] for cluster in pending]
        engine._cluster_cache_path = lambda cluster, client, mode: (
            cluster.cluster_id,
            SimpleNamespace(),
        )
        engine._load_json = lambda *_args: None
        engine._render_provider_batch = render

        rendered = engine._render_clusters(clusters, client=object(), mode="normal")

        assert peak > 1, "provider calls ran one at a time"
        assert set(rendered) == {c.cluster_id for c in clusters}
        assert rendered["c3"][0] == "body-c3", "results must stay matched to their cluster"

    def test_without_a_provider_the_work_stays_sequential(self):
        from docmancer.memory.context_engine import ContextEngine

        clusters = [SimpleNamespace(cluster_id=f"c{i}") for i in range(4)]
        engine = ContextEngine.__new__(ContextEngine)
        engine._render_cluster = lambda cluster, *, client, mode: (
            f"local-{cluster.cluster_id}", False, None, False
        )

        rendered = engine._render_clusters(clusters, client=None, mode="normal")

        assert rendered["c0"][0] == "local-c0"
        assert len(rendered) == 4

    def test_topics_are_batched_before_provider_calls(self):
        from docmancer.memory.context_engine import ContextEngine
        from docmancer.memory.tree.providerless_context import ProviderlessCluster

        clusters = [
            SimpleNamespace(
                cluster_id=f"c{i}",
                topic_label=f"Topic {i}",
                sources=[],
            )
            for i in range(64)
        ]
        engine = ContextEngine.__new__(ContextEngine)
        engine.distillation = SimpleNamespace(
            topics_per_request=8,
            max_input_tokens=12_000,
        )
        engine._providerless_cluster = lambda cluster: ProviderlessCluster(
            cluster_id=cluster.cluster_id,
            topic_label=cluster.topic_label,
            members=(),
        )

        batches = engine._cluster_batches(clusters)

        assert len(batches) == 8
        assert all(len(batch) == 8 for batch in batches)


def _source(address: str, text: str, title: str = "Topic") -> ContextSource:
    return ContextSource(
        address=address,
        content_hash=address,
        text=text,
        title=title,
        path=f"/{address}.md",
        harness="codex",
        recorded_at="2026-07-29T00:00:00+00:00",
        scope="project",
        authority="agent-memory",
    )


class TestStableClustering:
    def test_cluster_id_survives_label_and_minor_membership_change(self):
        original = [
            DedupGroup(_source("docmancer://a", "Qdrant indexing vectors quickly.", "Index")),
            DedupGroup(_source("docmancer://b", "Qdrant vector indexing batches.", "Index")),
        ]
        first = cluster_topics(original)
        assert len(first) == 1
        previous = [
            {
                "cluster_id": first[0].cluster_id,
                "member_addresses": [source.address for source in first[0].sources],
            }
        ]
        changed = original + [
            DedupGroup(_source("docmancer://c", "Qdrant vector indexing throughput.", "Scale"))
        ]

        second = cluster_topics(changed, previous=previous)

        assert len(second) == 1
        assert second[0].cluster_id == first[0].cluster_id

    def test_oversized_components_keep_hard_member_bound(self):
        groups = [
            DedupGroup(
                _source(
                    f"docmancer://{index}",
                    f"shared retrieval indexing topic group {index % 3}",
                )
            )
            for index in range(30)
        ]

        clusters = cluster_topics(groups, threshold=0.05, max_members=7)

        assert sum(len(cluster.groups) for cluster in clusters) == 30
        assert max(len(cluster.groups) for cluster in clusters) <= 7
