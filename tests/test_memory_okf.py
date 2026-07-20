"""Canonical Markdown export and legacy OKF compatibility."""

from __future__ import annotations

import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.okf import OKF_VERSION, RESERVED_FILENAMES, parse_frontmatter
from docmancer.okf.validate import validate_bundle


def _plant(home, *, secret=False):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    body = "We deploy on Railway and use pnpm.\n"
    if secret:
        body += "api_key=supersecretvalue123456\n"
    (mem / "note.md").write_text(body)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _env(monkeypatch, tmp_path, *, secret=False):
    home = tmp_path / "home"
    _plant(home, secret=secret)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))


def test_export_writes_canonical_markdown_pack(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    added = CliRunner().invoke(cli, ["memory", "add", "We deploy on Railway and use pnpm."])
    assert added.exit_code == 0, added.output
    out = tmp_path / "personal-defaults.md"
    r = CliRunner().invoke(cli, ["memory", "export", "personal-defaults", "--output", str(out)])
    assert r.exit_code == 0, r.output
    body = out.read_text()
    assert "Personal defaults" in body
    assert "Railway" in body


def test_export_redacts_secrets(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, secret=True)
    added = CliRunner().invoke(cli, ["memory", "add", "api_key=supersecretvalue123456"])
    assert added.exit_code == 0, added.output
    out = tmp_path / "personal-defaults.md"
    exported = CliRunner().invoke(cli, ["memory", "export", "personal-defaults", "--output", str(out)])
    assert exported.exit_code == 0, exported.output
    assert "supersecretvalue123456" not in out.read_text()


def test_export_is_keyless(tmp_path, monkeypatch):
    # Export never calls a provider, so it must work with no API key set.
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    CliRunner().invoke(cli, ["memory", "add", "We use pnpm."])
    out = tmp_path / "personal-defaults.md"
    r = CliRunner().invoke(cli, ["memory", "export", "personal-defaults", "--output", str(out)])
    assert r.exit_code == 0, r.output


def test_okf_doctor_flags_bad_bundle(tmp_path):
    bad = tmp_path / "bad.okf"
    bad.mkdir()
    (bad / "concept.md").write_text("# no frontmatter\n\ntext\n")
    r = CliRunner().invoke(cli, ["okf", "doctor", str(bad)])
    assert r.exit_code == 1
    assert "error" in r.output.lower()


def _install_fake_consolidate(monkeypatch):
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection
    from docmancer.ai.openrouter_client import OpenRouterClient

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        return ConsolidatedMemoryDraft(
            title="Master Memory",
            summary="All of it.",
            sections=[ConsolidatedMemorySection(heading="Deploy", body="Railway, pnpm.")],
            source_paths=["/Users/x/app/CLAUDE.md"],
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(OpenRouterClient, "preflight", fake_preflight)
    monkeypatch.setattr(OpenRouterClient, "parse", fake_parse)


def test_consolidate_format_okf_writes_bundle(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    _install_fake_consolidate(monkeypatch)
    out = tmp_path / "draft.okf"
    r = CliRunner().invoke(
        cli, ["memory", "consolidate", "--provider", "openrouter", "--format", "okf", "--output", str(out), "--yes"]
    )
    assert r.exit_code == 0, r.output
    assert (out / "index.md").exists()
    fields, _ = parse_frontmatter((out / "index.md").read_text())
    assert fields.get("okf_version") == OKF_VERSION
    # A Deploy section concept exists and the bundle is conformant.
    blob = "\n".join(p.read_text() for p in out.rglob("*.md") if p.name not in RESERVED_FILENAMES)
    assert "Railway, pnpm" in blob
    assert [i for i in validate_bundle(out) if i.level == "error"] == []
