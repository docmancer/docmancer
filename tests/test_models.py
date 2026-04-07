from docmancer.core.models import Document, Chunk, RetrievedChunk


def test_document_creation():
    doc = Document(source="test.md", content="Hello world", metadata={"type": "md"})
    assert doc.source == "test.md"
    assert doc.content == "Hello world"


def test_chunk_creation():
    chunk = Chunk(text="Some text", source="test.md", chunk_index=0, metadata={})
    assert chunk.text == "Some text"


def test_retrieved_chunk_creation():
    rc = RetrievedChunk(source="test.md", chunk_index=0, text="Some text", score=0.95)
    assert rc.score == 0.95


def test_retrieved_chunk_has_vault_name():
    chunk = RetrievedChunk(
        source="raw/doc.md",
        chunk_index=0,
        text="hello",
        score=0.9,
        vault_name="my-vault",
    )
    assert chunk.vault_name == "my-vault"


def test_retrieved_chunk_vault_name_defaults_none():
    chunk = RetrievedChunk(source="raw/doc.md", chunk_index=0, text="hello", score=0.9)
    assert chunk.vault_name is None
