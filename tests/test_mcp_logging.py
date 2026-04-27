import json

from docmancer.mcp import logging as mcp_logging


def test_log_redacts_values(tmp_path):
    log_path = tmp_path / "calls.jsonl"
    mcp_logging.log_call(
        tool="t", args={"limit": 3, "secret": "abc"},
        status=200, latency_ms=100, idempotency_key="k", log_path=log_path,
    )
    entry = json.loads(log_path.read_text().strip())
    assert entry["arg_keys"] == ["limit", "secret"]
    assert "secret" not in json.dumps(entry).replace("\"secret\"", "")
    assert "abc" not in log_path.read_text()
    assert entry["idempotency_key"] == "k"
