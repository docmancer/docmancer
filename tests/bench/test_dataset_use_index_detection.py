from __future__ import annotations

from pathlib import Path

from docmancer.bench.cli import _corpus_fully_indexed


def test_corpus_fully_indexed_requires_all_supported_files(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    a = corpus / "a.md"
    b = corpus / "nested" / "b.md"
    b.parent.mkdir()
    a.write_text("# A\n", encoding="utf-8")
    b.write_text("# B\n", encoding="utf-8")

    assert not _corpus_fully_indexed(corpus, [str(a)])
    assert _corpus_fully_indexed(corpus, [str(a), str(b)])


def test_corpus_fully_indexed_normalizes_windows_separators(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = corpus / "newsletters" / "foo.md"
    doc.parent.mkdir()
    doc.write_text("# Foo\n", encoding="utf-8")

    windows_style = str(doc).replace("/", "\\")
    assert _corpus_fully_indexed(corpus, [windows_style])
