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
    )


def test_get_document_returns_exact_content() -> None:
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    agent._vector_store = MagicMock()
    agent._vector_store.get_document_content.return_value = "Exact stored text"

    result = agent.get_document("docs/intro.md")

    assert result == "Exact stored text"
    agent._vector_store.get_document_content.assert_called_once_with("docs/intro.md")
