import logging
from unittest.mock import MagicMock

from docmancer.agent import DocmancerAgent
from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Document


def test_agent_default_creation():
    config = DocmancerConfig()
    agent = DocmancerAgent(config=config, _lazy_init=True)
    assert agent.config.embedding.provider == "fastembed"
    assert agent.config.vector_store.provider == "qdrant"


def test_agent_ingest_documents_uses_markdown_chunking_metadata() -> None:
    config = DocmancerConfig()
    config.ingestion.chunk_size = 40
    config.ingestion.chunk_overlap = 0

    agent = DocmancerAgent(config=config, _lazy_init=True)
    agent._dense_embedder = MagicMock()
    agent._sparse_embedder = MagicMock()
    agent._vector_store = MagicMock()

    agent._dense_embedder.embed.return_value = [[0.1]]
    agent._sparse_embedder.embed.return_value = [MagicMock()]
    agent._vector_store.upsert.return_value = 1

    count = agent.ingest_documents(
        [
            Document(
                source="https://docs.example.com/page",
                content="# Intro\n\nGitBook content.",
                metadata={"content_type": "text/markdown", "format": "markdown"},
            )
        ],
        recreate=True,
    )

    assert count == 1
    upsert_chunks = agent._vector_store.upsert.call_args.args[0]
    assert upsert_chunks[0].text.startswith("[# Intro]")
    assert agent._vector_store.upsert.call_args.kwargs["recreate"] is True


def test_ingest_preserves_recreate_until_non_empty_file(tmp_path) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("")
    non_empty = tmp_path / "real.md"
    non_empty.write_text("# Intro\n\nBody text.")

    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._dense_embedder = MagicMock()
    agent._sparse_embedder = MagicMock()
    agent._vector_store = MagicMock()

    agent._dense_embedder.embed.return_value = [[0.1]]
    agent._sparse_embedder.embed.return_value = [MagicMock()]
    agent._vector_store.upsert.return_value = 1

    count = agent.ingest(tmp_path, recreate=True)

    assert count == 1
    assert agent._vector_store.upsert.call_args.kwargs["recreate"] is True


def test_ingest_documents_persists_exact_document_content() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._dense_embedder = MagicMock()
    agent._sparse_embedder = MagicMock()
    agent._vector_store = MagicMock()

    agent._dense_embedder.embed.return_value = [[0.1]]
    agent._sparse_embedder.embed.return_value = [MagicMock()]
    agent._vector_store.upsert.return_value = 1

    document = Document(
        source="https://docs.example.com/page",
        content="# Heading\n\nOriginal body text.",
        metadata={"format": "markdown"},
    )

    agent.ingest_documents([document], recreate=True)

    agent._vector_store.upsert_document.assert_called_once_with(
        "https://docs.example.com/page",
        "# Heading\n\nOriginal body text.",
        recreate=True,
        docset_root=None,
    )


def test_ingest_documents_persists_docset_root_and_logs_progress(caplog) -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._dense_embedder = MagicMock()
    agent._sparse_embedder = MagicMock()
    agent._vector_store = MagicMock()

    agent._dense_embedder.embed.return_value = [[0.1]]
    agent._sparse_embedder.embed.return_value = [MagicMock()]
    agent._vector_store.upsert.return_value = 1

    document = Document(
        source="https://docs.example.com/page",
        content="# Heading\n\nOriginal body text.",
        metadata={"format": "markdown", "docset_root": "https://docs.example.com"},
    )

    with caplog.at_level(logging.INFO):
        agent.ingest_documents([document], recreate=True)

    agent._vector_store.upsert_document.assert_called_once_with(
        "https://docs.example.com/page",
        "# Heading\n\nOriginal body text.",
        recreate=True,
        docset_root="https://docs.example.com",
    )
    assert "Chunking https://docs.example.com..." in caplog.text
    assert "Embedding 1 chunks from https://docs.example.com..." in caplog.text
    assert "Processed 1/1 documents" in caplog.text


def test_ingest_url_logs_post_fetch_summary(caplog) -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._dense_embedder = MagicMock()
    agent._sparse_embedder = MagicMock()
    agent._vector_store = MagicMock()
    agent._get_fetcher = MagicMock()
    fetcher = MagicMock()
    fetcher.fetch.return_value = [
        Document(source="https://docs.example.com/page", content="# Hi", metadata={"format": "markdown"})
    ]
    agent._get_fetcher.return_value = fetcher
    agent._dense_embedder.embed.return_value = [[0.1]]
    agent._sparse_embedder.embed.return_value = [MagicMock()]
    agent._vector_store.upsert.return_value = 1

    with caplog.at_level(logging.INFO):
        agent.ingest_url("https://docs.example.com")

    assert "Fetched 1 document(s); starting ingest" in caplog.text


def test_get_document_returns_exact_content() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._vector_store = MagicMock()
    agent._vector_store.get_document_content.return_value = "Exact stored text"

    result = agent.get_document("docs/intro.md")

    assert result == "Exact stored text"
    agent._vector_store.get_document_content.assert_called_once_with("docs/intro.md")


def test_remove_source_prefers_docset_then_source() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._vector_store = MagicMock()
    agent._vector_store.delete_docset.return_value = True

    result = agent.remove_source("https://docs.example.com")

    assert result == (True, "docset")
    agent._vector_store.delete_docset.assert_called_once_with("https://docs.example.com")
    agent._vector_store.delete_source.assert_not_called()


def test_remove_source_falls_back_to_exact_source() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._vector_store = MagicMock()
    agent._vector_store.delete_docset.return_value = False
    agent._vector_store.delete_source.return_value = True

    result = agent.remove_source("https://docs.example.com/page")

    assert result == (True, "source")
    agent._vector_store.delete_docset.assert_called_once_with("https://docs.example.com/page")
    agent._vector_store.delete_source.assert_called_once_with("https://docs.example.com/page")


def test_remove_all_sources_deletes_entire_store() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._vector_store = MagicMock()
    agent._vector_store.delete_all.return_value = True

    result = agent.remove_all_sources()

    assert result is True
    agent._vector_store.delete_all.assert_called_once_with()
