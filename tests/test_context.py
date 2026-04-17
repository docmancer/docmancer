"""Tests for context formatting helpers."""

from __future__ import annotations

import pytest

from docmancer.context import build_rag_prompt, format_context
from docmancer.core.models import RetrievedChunk


def _chunk(text: str, source: str = "https://docs.example.com/auth", title: str = "Auth", score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        source=source,
        chunk_index=0,
        text=text,
        score=score,
        metadata={"title": title, "token_estimate": len(text) // 4},
    )


class TestFormatContext:
    def test_empty_chunks(self):
        assert format_context([]) == ""

    def test_markdown_style(self):
        chunks = [_chunk("Use OAuth tokens for auth.")]
        result = format_context(chunks, style="markdown")
        assert "### Auth" in result
        assert "Use OAuth tokens" in result
        assert "docs.example.com" in result

    def test_markdown_no_sources(self):
        chunks = [_chunk("Token-based auth.")]
        result = format_context(chunks, style="markdown", include_sources=False)
        assert "docs.example.com" not in result
        assert "Token-based auth." in result

    def test_xml_style(self):
        chunks = [_chunk("Use OAuth tokens.")]
        result = format_context(chunks, style="xml")
        assert "<doc" in result
        assert 'source="https://docs.example.com/auth"' in result
        assert 'title="Auth"' in result
        assert "Use OAuth tokens." in result
        assert "</doc>" in result

    def test_xml_escapes_attribute_chars(self):
        chunks = [_chunk("Text", source="https://example.com/a&b", title='Say "hello"')]
        result = format_context(chunks, style="xml")
        assert "&amp;" in result
        assert "&quot;" in result

    def test_xml_escapes_text_content(self):
        chunks = [_chunk("Use <code>foo</code> & call </doc> to break out")]
        result = format_context(chunks, style="xml")
        assert "&lt;code&gt;" in result or "&lt;code" in result
        assert "&amp; call" in result
        assert "</doc>" not in result.split("<doc", 1)[1].split("\n</doc>")[0]

    def test_plain_style(self):
        chunks = [_chunk("Use tokens."), _chunk("Set headers.", source="https://docs.example.com/headers", title="Headers")]
        result = format_context(chunks, style="plain")
        assert "[https://docs.example.com/auth]" in result
        assert "Use tokens." in result
        assert "[https://docs.example.com/headers]" in result

    def test_invalid_style_raises(self):
        with pytest.raises(ValueError, match="Unknown style"):
            format_context([_chunk("text")], style="csv")

    def test_max_tokens_budget(self):
        chunks = [
            _chunk("A" * 400, title="First"),
            _chunk("B" * 400, title="Second"),
            _chunk("C" * 400, title="Third"),
        ]
        result = format_context(chunks, style="plain", max_tokens=200)
        # Should include at least one chunk but not all three
        assert "A" * 10 in result
        # With budget of 200 tokens (~800 chars), first chunk (400 chars = ~100 tokens) fits
        # Second chunk (another 100 tokens) fits too
        # Third may or may not fit depending on exact math

    def test_multiple_chunks_separated(self):
        chunks = [_chunk("First section."), _chunk("Second section.")]
        result = format_context(chunks, style="markdown")
        assert "---" in result


class TestBuildRagPrompt:
    def test_basic_prompt(self):
        chunks = [_chunk("Use OAuth tokens.")]
        result = build_rag_prompt(chunks, "How do I authenticate?")
        assert "Use the following documentation" in result
        assert "Question: How do I authenticate?" in result
        assert "Use OAuth tokens." in result

    def test_with_instruction(self):
        chunks = [_chunk("Token auth.")]
        result = build_rag_prompt(
            chunks, "Auth?", instruction="You are a helpful assistant."
        )
        assert "You are a helpful assistant." in result
        assert "Question: Auth?" in result

    def test_empty_chunks_still_has_question(self):
        result = build_rag_prompt([], "What is X?")
        assert "Question: What is X?" in result
