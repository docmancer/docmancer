"""Mistral OCR: client method, loader, and `ingest --ocr mistral`."""
from __future__ import annotations

import sys
import types

import pytest


def _install_fake_ocr(monkeypatch, capture: dict):
    class FakePage:
        def __init__(self, markdown):
            self.markdown = markdown

    class FakeOcrResp:
        def __init__(self, pages):
            self.pages = pages

    class FakeOcr:
        def process(self, *, model, document, **kwargs):
            capture["model"] = model
            capture["document"] = document
            return FakeOcrResp([FakePage("# Page 1\n\nOcrsentinel42 body."), FakePage("Page 2 tail.")])

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.ocr = FakeOcr()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def test_client_ocr_concatenates_page_markdown(tmp_path, monkeypatch):
    capture: dict = {}
    _install_fake_ocr(monkeypatch, capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake bytes")

    from docmancer.ai.mistral_client import MistralClient

    text = MistralClient().ocr_file(pdf)
    assert "Ocrsentinel42" in text
    assert "Page 2 tail" in text
    # A PDF is sent as a base64 document_url data URI.
    assert capture["document"]["type"] == "document_url"
    assert capture["document"]["document_url"].startswith("data:application/pdf;base64,")


def test_ocr_loader_returns_markdown_document(tmp_path, monkeypatch):
    capture: dict = {}
    _install_fake_ocr(monkeypatch, capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    from docmancer.connectors.parsers.mistral_ocr import MistralOCRLoader

    doc = MistralOCRLoader().load(pdf)
    assert "Ocrsentinel42" in doc.content
    assert doc.metadata.get("ocr") == "mistral"


def test_ingest_with_ocr_indexes_extracted_markdown(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli

    capture: dict = {}
    _install_fake_ocr(monkeypatch, capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    config = tmp_path / "docmancer.yaml"
    config.write_text(f"index:\n  db_path: {tmp_path / 'd.db'}\n")

    runner = CliRunner()
    r = runner.invoke(
        cli, ["ingest", str(pdf), "--ocr", "mistral", "--no-vectors", "--config", str(config)]
    )
    assert r.exit_code == 0, r.output
    hit = runner.invoke(cli, ["query", "Ocrsentinel42", "--config", str(config)])
    assert hit.exit_code == 0, hit.output
    assert "Ocrsentinel42" in hit.output


def test_ingest_ocr_requires_key(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli

    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    config = tmp_path / "docmancer.yaml"
    config.write_text(f"index:\n  db_path: {tmp_path / 'd.db'}\n")

    r = CliRunner().invoke(
        cli, ["ingest", str(pdf), "--ocr", "mistral", "--no-vectors", "--config", str(config)]
    )
    assert r.exit_code == 2
    assert "MISTRAL_API_KEY" in r.output
