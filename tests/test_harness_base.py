from docmancer.harness.base import MemoryEntry


def test_to_document_shape_and_kind():
    entry = MemoryEntry(
        harness="claude-code",
        scope="project:/x/app",
        title="note",
        content="we deploy on Railway",
        path="/x/app/memory/note.md",
        extra={"kind": "agent-memory"},
    )
    doc = entry.to_document()
    assert doc.content == "we deploy on Railway"
    assert doc.source == "claude-code:/x/app/memory/note.md"
    assert doc.metadata["kind"] == "agent-memory"
    assert doc.metadata["scope"] == "project:/x/app"
    assert doc.metadata["harness"] == "claude-code"
    assert doc.metadata["title"] == "note"


def test_kind_defaults_to_agent_memory_when_absent():
    entry = MemoryEntry("codex", "global:codex", "t", "x", "/p.md")
    assert entry.to_document().metadata["kind"] == "agent-memory"
