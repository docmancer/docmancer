"""Section 24: append behavior of calls.jsonl."""
import json

from docmancer.mcp import logging as mcp_logging


def test_log_appends_multiple_entries(tmp_path):
    log_path = tmp_path / "calls.jsonl"
    for i in range(3):
        mcp_logging.log_call(
            tool=f"t{i}", args={"x": i},
            status=200, latency_ms=10 + i, log_path=log_path,
        )
    lines = log_path.read_text().splitlines()
    assert len(lines) == 3
    entries = [json.loads(line) for line in lines]
    assert [e["tool"] for e in entries] == ["t0", "t1", "t2"]


def test_log_creates_parent_dir(tmp_path):
    log_path = tmp_path / "nested" / "calls.jsonl"
    mcp_logging.log_call(
        tool="t", args={}, status=200, latency_ms=1, log_path=log_path,
    )
    assert log_path.exists()
