"""`docmancer memory export --format okf` and `docmancer okf doctor`."""

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


def test_export_writes_conformant_okf_bundle(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "memory.okf"
    r = CliRunner().invoke(cli, ["memory", "export", "--output", str(out)])
    assert r.exit_code == 0, r.output

    index = out / "index.md"
    assert index.exists()
    fields, _ = parse_frontmatter(index.read_text())
    assert fields.get("okf_version") == OKF_VERSION

    # At least one concept file with a non-empty type was written.
    concept_files = [p for p in out.rglob("*.md") if p.name not in RESERVED_FILENAMES]
    assert concept_files
    cfields, cbody = parse_frontmatter(concept_files[0].read_text())
    assert cfields.get("type")
    assert "Railway" in cbody

    # The bundle is conformant.
    errors = [i for i in validate_bundle(out) if i.level == "error"]
    assert errors == []


def test_export_redacts_secrets(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, secret=True)
    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "memory.okf"
    CliRunner().invoke(cli, ["memory", "export", "--output", str(out)])
    blob = "\n".join(p.read_text() for p in out.rglob("*.md"))
    assert "supersecretvalue123456" not in blob


def test_export_is_keyless(tmp_path, monkeypatch):
    # Export never calls a provider, so it must work with no API key set.
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "memory.okf"
    r = CliRunner().invoke(cli, ["memory", "export", "--output", str(out)])
    assert r.exit_code == 0, r.output


def test_okf_doctor_reports_clean_bundle(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "memory.okf"
    CliRunner().invoke(cli, ["memory", "export", "--output", str(out)])
    r = CliRunner().invoke(cli, ["okf", "doctor", str(out)])
    assert r.exit_code == 0, r.output
    assert "conformant" in r.output.lower() or "no errors" in r.output.lower()


def test_okf_doctor_flags_bad_bundle(tmp_path):
    bad = tmp_path / "bad.okf"
    bad.mkdir()
    (bad / "concept.md").write_text("# no frontmatter\n\ntext\n")
    r = CliRunner().invoke(cli, ["okf", "doctor", str(bad)])
    assert r.exit_code == 1
    assert "error" in r.output.lower()


def _install_fake_consolidate(monkeypatch):
    from docmancer.ai.agent_cli_client import AgentCliClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        return ConsolidatedMemoryDraft(
            title="Master Memory",
            summary="All of it.",
            sections=[ConsolidatedMemorySection(heading="Deploy", body="Railway, pnpm.")],
            source_paths=["/Users/x/app/CLAUDE.md"],
        )

    monkeypatch.setattr(AgentCliClient, "preflight", fake_preflight)
    monkeypatch.setattr(AgentCliClient, "parse", fake_parse)


def test_consolidate_format_okf_writes_bundle(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    _install_fake_consolidate(monkeypatch)
    out = tmp_path / "draft.okf"
    r = CliRunner().invoke(
        cli, ["memory", "consolidate", "--provider", "claude", "--format", "okf", "--output", str(out), "--yes"]
    )
    assert r.exit_code == 0, r.output
    assert (out / "index.md").exists()
    fields, _ = parse_frontmatter((out / "index.md").read_text())
    assert fields.get("okf_version") == OKF_VERSION
    # A Deploy section concept exists and the bundle is conformant.
    blob = "\n".join(p.read_text() for p in out.rglob("*.md") if p.name not in RESERVED_FILENAMES)
    assert "Railway, pnpm" in blob
    assert [i for i in validate_bundle(out) if i.level == "error"] == []
