from docmancer.core.models import RetrievedChunk


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
    chunk = RetrievedChunk(
        source="raw/doc.md",
        chunk_index=0,
        text="hello",
        score=0.9,
    )
    assert chunk.vault_name is None
