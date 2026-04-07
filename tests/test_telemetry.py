import json
from unittest.mock import MagicMock, patch

from docmancer.core.config import DocmancerConfig, TelemetryConfig
from docmancer.telemetry.tracer import QueryTrace, Span, format_trace_for_terminal


def test_span_timing():
    span = Span(name="test")
    import time
    time.sleep(0.01)
    span.stop()
    assert span.duration_ms > 0
    assert span.duration_ms < 1000  # sanity


def test_span_to_dict():
    span = Span(name="embed", metadata={"model": "bge"})
    span.end_time = span.start_time + 0.05  # 50ms
    d = span.to_dict()
    assert d["name"] == "embed"
    assert d["duration_ms"] == 50.0
    assert d["metadata"]["model"] == "bge"


def test_query_trace_spans():
    trace = QueryTrace(query_text="test query")
    s1 = trace.start_span("dense_embed")
    s1.end_time = s1.start_time + 0.01
    s2 = trace.start_span("sparse_embed")
    s2.end_time = s2.start_time + 0.005
    assert len(trace.spans) == 2
    assert trace.total_duration_ms > 0


def test_query_trace_to_json():
    trace = QueryTrace(query_text="hello")
    s = trace.start_span("test")
    s.end_time = s.start_time + 0.01
    trace.results = [{"source": "doc.md", "score": 0.95, "text": "hello world"}]
    j = json.loads(trace.to_json())
    assert j["query"] == "hello"
    assert len(j["spans"]) == 1
    assert len(j["results"]) == 1


def test_query_trace_save(tmp_path):
    trace = QueryTrace(query_text="save test")
    s = trace.start_span("x")
    s.stop()
    path = trace.save(tmp_path / "traces")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["query"] == "save test"


def test_format_trace_for_terminal():
    trace = QueryTrace(query_text="format test")
    s = trace.start_span("dense_embed")
    s.end_time = s.start_time + 0.025
    trace.results = [{"source": "a.md", "score": 0.9, "text": "some text here"}]
    output = format_trace_for_terminal(trace)
    assert "format test" in output
    assert "dense_embed" in output
    assert "25.0ms" in output
    assert "a.md" in output


# ---------------------------------------------------------------------------
# Langfuse sink tests
# ---------------------------------------------------------------------------


def test_try_send_skips_when_telemetry_disabled():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=False))
    try_send_to_langfuse(MagicMock(), config)


def test_try_send_skips_when_no_telemetry_config():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    try_send_to_langfuse(MagicMock(), DocmancerConfig())


def test_try_send_skips_when_provider_not_langfuse():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=True, provider="other"))
    try_send_to_langfuse(MagicMock(), config)


def test_try_send_handles_missing_langfuse_package():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    import docmancer.telemetry.langfuse_sink as sink_mod
    sink_mod._WARNED_MISSING_KEYS = False
    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=True, provider="langfuse"))
    try_send_to_langfuse(MagicMock(), config)
