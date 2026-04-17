"""Tests for AsyncDocmancerAgent."""

from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.async_agent import AsyncDocmancerAgent
from docmancer.core.config import DocmancerConfig, IndexConfig
from docmancer.core.models import Document


def _make_config(tmp_path: Path) -> DocmancerConfig:
    return DocmancerConfig(index=IndexConfig(db_path=str(tmp_path / "test.db")))


@pytest.fixture
def agent(tmp_path):
    return AsyncDocmancerAgent(config=_make_config(tmp_path))


class TestAsyncAgent:
    async def test_ingest_documents_and_query(self, agent, tmp_path):
        docs = [
            Document(
                source="https://docs.example.com/auth",
                content="# Authentication\n\nUse OAuth tokens to authenticate.",
                metadata={"format": "markdown"},
            )
        ]
        count = await agent.ingest_documents(docs)
        assert count >= 1

        results = await agent.query("authentication")
        assert len(results) >= 1
        assert any("OAuth" in r.text for r in results)

    async def test_ingest_local_path(self, agent, tmp_path):
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Setup\n\nInstall with pip.")
        count = await agent.ingest(str(md_file))
        assert count >= 1

    async def test_query_context(self, agent, tmp_path):
        docs = [
            Document(
                source="https://docs.example.com/api",
                content="# API Reference\n\nCall /api/v1/users for user data.",
                metadata={"format": "markdown"},
            )
        ]
        await agent.ingest_documents(docs)
        context = await agent.query_context("user data", style="xml")
        assert "<doc" in context

    async def test_list_sources(self, agent, tmp_path):
        docs = [
            Document(
                source="https://docs.example.com/test",
                content="# Test\n\nContent.",
                metadata={},
            )
        ]
        await agent.ingest_documents(docs)
        sources = await agent.list_sources()
        assert "https://docs.example.com/test" in sources

    async def test_collection_stats(self, agent):
        stats = await agent.collection_stats()
        assert "sources_count" in stats
        assert "sections_count" in stats
