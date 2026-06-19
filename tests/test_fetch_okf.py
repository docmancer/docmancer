"""`docmancer fetch --format okf` writes an OKF bundle instead of bare .md."""

from __future__ import annotations

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.core.models import Document
from docmancer.okf import OKF_VERSION, parse_frontmatter
from docmancer.okf.validate import validate_bundle


def _fake_docs():
    return [
        Document(source="https://docs.example.com/api/auth", content="# Auth\n\nHow to auth.", metadata={"title": "Auth"}),
        Document(source="https://docs.example.com/guide", content="# Guide\n\nGuide body.", metadata={}),
    ]


def _patch_fetcher(monkeypatch):
    import docmancer.connectors.fetchers.gitbook as gb

    class FakeFetcher:
        def fetch(self, url):
            return _fake_docs()

    monkeypatch.setattr(gb, "GitBookFetcher", FakeFetcher)


def test_fetch_okf_writes_conformant_bundle(tmp_path, monkeypatch):
    _patch_fetcher(monkeypatch)
    out = tmp_path / "docs.okf"
    r = CliRunner().invoke(
        cli, ["fetch", "https://docs.example.com", "--format", "okf", "--output", str(out)]
    )
    assert r.exit_code == 0, r.output

    index = out / "index.md"
    assert index.exists()
    fields, _ = parse_frontmatter(index.read_text())
    assert fields.get("okf_version") == OKF_VERSION

    auth = out / "api-auth.md"
    assert auth.exists()
    cfields, cbody = parse_frontmatter(auth.read_text())
    assert cfields["type"] == "Documentation Page"
    assert cfields["resource"] == "https://docs.example.com/api/auth"
    assert "How to auth" in cbody

    assert [i for i in validate_bundle(out) if i.level == "error"] == []


def test_fetch_default_still_writes_plain_markdown(tmp_path, monkeypatch):
    _patch_fetcher(monkeypatch)
    out = tmp_path / "plain"
    r = CliRunner().invoke(cli, ["fetch", "https://docs.example.com", "--output", str(out)])
    assert r.exit_code == 0, r.output
    # No frontmatter, no okf_version: default behavior is unchanged.
    assert not (out / "index.md").exists() or "okf_version" not in (out / "index.md").read_text()
    files = list(out.glob("*.md"))
    assert files
    assert "---\ntype:" not in files[0].read_text()
