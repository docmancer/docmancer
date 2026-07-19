from docmancer.harness.base import MemoryEntry
from docmancer.memory.audit import audit_secrets


def test_audit_helper_groups_masked_findings_by_severity():
    entries = [
        MemoryEntry(
            harness="codex",
            scope="global:codex",
            title="Memory",
            content="token=supersecretvalue123",
            path="/tmp/memory.md",
        )
    ]

    report = audit_secrets(entries)

    assert report["unique_secret_count"] == 1
    assert report["finding_count"] == 1
    assert report["by_severity"]["medium"]
    occurrence = report["findings"][0]["occurrences"][0]
    assert "supersecretvalue123" not in occurrence["masked_excerpt"]
    assert occurrence["source_path"] == "/tmp/memory.md"
