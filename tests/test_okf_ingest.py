"""Ingesting an OKF bundle: reserved files skipped, frontmatter lifted."""
from __future__ import annotations

from pathlib import Path

from docmancer.connectors.parsers.markdown import MarkdownLoader
from docmancer.okf import is_okf_bundle
from docmancer.okf.bundle import OKFConcept, write_bundle


def test_markdown_loader_lifts_okf_frontmatter(tmp_path: Path):
    f = tmp_path / "c.md"
    f.write_text(
        "---\ntype: Decision\ntitle: Pick Railway\ntags:\n- infra\nresource: /p/CLAUDE.md\n"
        "timestamp: '2026-06-19T00:00:00Z'\n---\nBody.\n"
    )
    doc = MarkdownLoader().load(f)
    assert doc.metadata["title"] == "Pick Railway"
    assert doc.metadata["okf_type"] == "Decision"
    assert doc.metadata["tags"] == ["infra"]
    assert doc.metadata["resource"] == "/p/CLAUDE.md"
    assert doc.metadata["timestamp"] == "2026-06-19T00:00:00Z"


def test_markdown_loader_ignores_non_okf_markdown(tmp_path: Path):
    f = tmp_path / "plain.md"
    f.write_text("# Heading\n\nNo frontmatter.\n")
    doc = MarkdownLoader().load(f)
    assert "okf_type" not in doc.metadata


def test_is_okf_bundle_detects_root_index_version(tmp_path: Path):
    bundle = tmp_path / "b.okf"
    write_bundle(bundle, [OKFConcept(type="Decision", title="A", body="b")], title="t")
    assert is_okf_bundle(bundle) is True
    # A plain directory of markdown is not an OKF bundle.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.md").write_text("# a\n")
    assert is_okf_bundle(plain) is False


def test_ingest_skips_reserved_files_in_bundle(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli

    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    bundle = tmp_path / "b.okf"
    write_bundle(
        bundle,
        [OKFConcept(type="Decision", title="Pick Railway", body="Railwaydeploys here.")],
        title="memory",
        log_entries=["2026-06-19: Logsentinel9999 created the bundle"],
    )
    config = tmp_path / "docmancer.yaml"
    config.write_text(f"index:\n  db_path: {tmp_path / 'd.db'}\n")
    runner = CliRunner()

    r = runner.invoke(
        cli, ["docs", "add", str(bundle), "--recreate", "--no-vectors", "--config", str(config)]
    )
    assert r.exit_code == 0, r.output

    # The concept content is searchable.
    hit = runner.invoke(cli, ["docs", "query", "Railwaydeploys", "--config", str(config)])
    assert hit.exit_code == 0, hit.output
    assert "Railwaydeploys" in hit.output

    # The reserved log.md was not indexed: text unique to it is unfindable.
    miss = runner.invoke(cli, ["docs", "query", "Logsentinel9999", "--config", str(config)])
    assert miss.exit_code == 1
