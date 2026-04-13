from unittest.mock import MagicMock

from docmancer.agent import DocmancerAgent
from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Document


def _config(tmp_path):
    config = DocmancerConfig()
    config.index.db_path = str(tmp_path / "docmancer.db")
    config.index.extracted_dir = str(tmp_path / "extracted")
    return config


def test_agent_default_creation():
    agent = DocmancerAgent(config=DocmancerConfig(), _lazy_init=True)
    assert agent.config.index.provider == "sqlite"
    assert agent.config.query.default_budget == 2400


def test_ingest_documents_indexes_sections_and_extracts_files(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))

    count = agent.ingest_documents(
        [
            Document(
                source="https://docs.example.com/page",
                content="# Intro\n\nGitBook content.\n\n## Auth\n\nUse tokens.",
                metadata={"format": "markdown", "docset_root": "https://docs.example.com"},
            )
        ],
        recreate=True,
    )

    assert count == 2
    stats = agent.collection_stats()
    assert stats["sources_count"] == 1
    assert stats["sections_count"] == 2
    assert list((tmp_path / "extracted").glob("*.md"))
    assert list((tmp_path / "extracted").glob("*.json"))


def test_query_returns_context_pack_metadata(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    agent.ingest_documents(
        [
            Document(
                source="docs/auth.md",
                content="# Auth\n\nAuthenticate with OAuth tokens.\n\n## Refresh\n\nRefresh tokens before expiry.",
                metadata={"format": "markdown"},
            )
        ],
        recreate=True,
    )

    results = agent.query("OAuth tokens", budget=1200)

    assert results
    assert results[0].source == "docs/auth.md"
    assert results[0].metadata["docmancer_tokens"] > 0
    assert results[0].metadata["raw_tokens"] > 0
    assert "savings_percent" in results[0].metadata


def test_query_falls_back_to_or_when_all_terms_do_not_match_one_section(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    agent.ingest_documents(
        [
            Document(
                source="docs/terminal-moto.md",
                content=(
                    "# Process MOTO payments\n\n"
                    "Use Stripe Terminal to process MOTO payments.\n\n"
                    "## Android\n\n"
                    "Set a non-null MotoConfiguration on the CollectPaymentIntentConfiguration."
                ),
                metadata={"format": "markdown"},
            )
        ],
        recreate=True,
    )

    results = agent.query("How do I process MOTO payments on Android with Kotlin", budget=1200)

    assert results
    assert results[0].source == "docs/terminal-moto.md"


def test_ingest_reads_markdown_directory(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "auth.md").write_text("# Auth\n\nToken docs.", encoding="utf-8")

    agent = DocmancerAgent(config=_config(tmp_path))
    count = agent.ingest(docs, recreate=True)

    assert count == 1
    assert agent.list_sources()


def test_ingest_url_logs_post_fetch_summary(caplog, tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    fetcher = MagicMock()
    fetcher.fetch.return_value = [
        Document(source="https://docs.example.com/page", content="# Hi", metadata={"format": "markdown"})
    ]
    agent._get_fetcher = MagicMock(return_value=fetcher)

    agent.ingest_url("https://docs.example.com")

    assert "https://docs.example.com/page" in agent.list_sources()


def test_get_document_returns_exact_content(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    agent.ingest_documents([Document(source="docs/intro.md", content="# Intro\n\nExact stored text")], recreate=True)

    assert agent.get_document("docs/intro.md") == "# Intro\n\nExact stored text"


def test_remove_source_prefers_docset_then_source(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    agent.ingest_documents(
        [
            Document(
                source="https://docs.example.com/page",
                content="# Intro\n\nBody",
                metadata={"docset_root": "https://docs.example.com"},
            )
        ],
        recreate=True,
    )

    assert agent.remove_source("https://docs.example.com") == (True, "docset")
    assert agent.list_sources() == []


def test_remove_all_sources_deletes_entire_store(tmp_path):
    agent = DocmancerAgent(config=_config(tmp_path))
    agent.ingest_documents([Document(source="docs/intro.md", content="# Intro\n\nBody")], recreate=True)

    assert agent.remove_all_sources() is True
    assert agent.collection_stats()["sources_count"] == 0
