"""Tests for DocmancerClient convenience wrapper."""

from __future__ import annotations

import tempfile
from pathlib import Path

from docmancer.client import DocmancerClient
from docmancer.core.models import Document


class TestDocmancerClient:
    def _make_client(self, tmp_path: Path) -> DocmancerClient:
        db_path = str(tmp_path / "test.db")
        return DocmancerClient(db_path=db_path)

    def test_add_and_get_context(self, tmp_path):
        client = self._make_client(tmp_path)
        # Ingest a local markdown file
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Auth\n\nUse OAuth tokens for authentication.\n\n# API\n\nCall /api/v1 endpoint.")
        client.add(str(md_file))

        context = client.get_context("authentication")
        assert "OAuth" in context or "Auth" in context

    def test_add_and_get_chunks(self, tmp_path):
        client = self._make_client(tmp_path)
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Setup\n\nInstall with pip install example.")
        client.add(str(md_file))

        chunks = client.get_chunks("install")
        assert len(chunks) >= 1
        assert any("pip install" in c.text for c in chunks)

    def test_list_and_remove_sources(self, tmp_path):
        client = self._make_client(tmp_path)
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Test\n\nContent here.")
        client.add(str(md_file))

        sources = client.list_sources()
        assert len(sources) >= 1

        for source in sources:
            assert client.remove(source) is True

        assert client.list_sources() == []

    def test_custom_style(self, tmp_path):
        client = DocmancerClient(
            db_path=str(tmp_path / "test.db"),
            style="xml",
        )
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Guide\n\nFollow these steps.")
        client.add(str(md_file))

        context = client.get_context("steps")
        assert "<doc" in context

    def test_style_override(self, tmp_path):
        client = self._make_client(tmp_path)
        md_file = tmp_path / "docs.md"
        md_file.write_text("# Guide\n\nFollow steps.")
        client.add(str(md_file))

        context = client.get_context("steps", style="xml")
        assert "<doc" in context
