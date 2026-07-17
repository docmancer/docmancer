"""`docmancer memory apply`: managed-block writes, backup, idempotency, remove."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from docmancer.cli.__main__ import cli

BEGIN = "<!-- docmancer:memory:begin"
END = "<!-- docmancer:memory:end -->"


def _draft(tmp_path):
    d = tmp_path / "draft.md"
    d.write_text("# Master Memory\n\nWe deploy on Railway.\n")
    return d


def test_apply_to_output_creates_block(tmp_path):
    draft = _draft(tmp_path)
    target = tmp_path / "AGENTS.md"
    r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--yes"])
    assert r.exit_code == 0, r.output
    text = target.read_text()
    assert BEGIN in text and END in text
    assert "We deploy on Railway." in text


def test_apply_preserves_surrounding_content_and_is_idempotent(tmp_path):
    draft = _draft(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("# My own notes\n\nKeep me.\n")
    runner = CliRunner()
    r1 = runner.invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--yes"])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--yes"])
    assert r2.exit_code == 0, r2.output
    text = target.read_text()
    assert "Keep me." in text
    assert text.count(BEGIN) == 1  # block replaced, not duplicated
    # A timestamped backup is written.
    assert any(p.name.startswith("AGENTS.md.docmancer-bak-") for p in tmp_path.iterdir())


def test_apply_dry_run_writes_nothing(tmp_path):
    draft = _draft(tmp_path)
    target = tmp_path / "AGENTS.md"
    r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert not target.exists()


def test_apply_print_only_writes_nothing(tmp_path):
    draft = _draft(tmp_path)
    target = tmp_path / "AGENTS.md"
    r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--print"])
    assert r.exit_code == 0, r.output
    assert BEGIN in r.output
    assert not target.exists()


def test_apply_remove_strips_only_block(tmp_path):
    draft = _draft(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("# Mine\n\nKeep.\n")
    runner = CliRunner()
    runner.invoke(cli, ["memory", "apply", "--from", str(draft), "--output", str(target), "--yes"])
    r = runner.invoke(cli, ["memory", "apply", "--remove", "--output", str(target), "--yes"])
    assert r.exit_code == 0, r.output
    text = target.read_text()
    assert BEGIN not in text
    assert "Keep." in text


def test_apply_requires_target(tmp_path):
    draft = _draft(tmp_path)
    r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--yes"])
    assert r.exit_code == 2
    assert "Specify a target" in r.output


def test_apply_without_from_uses_default_draft(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem():
        target = Path("AGENTS.md")
        r = runner.invoke(cli, ["memory", "apply", "--output", str(target), "--yes"])
        assert r.exit_code == 2
        assert "memory sync" in r.output
        assert not target.exists()


def test_apply_without_from_renders_atomic_memory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    mem = home / ".claude" / "projects" / "-Users-x-app" / "memory"
    mem.mkdir(parents=True)
    (mem / "note.md").write_text("- We deploy on Railway.\n")
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    target = tmp_path / "AGENTS.md"

    sync = CliRunner().invoke(cli, ["memory", "sync"])
    assert sync.exit_code == 0, sync.output
    r = CliRunner().invoke(cli, ["memory", "apply", "--output", str(target), "--yes"])

    assert r.exit_code == 0, r.output
    text = target.read_text()
    assert BEGIN in text
    assert "docmancer atomic memory" in text
    assert "We deploy on Railway." in text


def test_apply_agent_target_resolves_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(tmp_path / "home"))
    draft = _draft(tmp_path)
    r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--agent", "codex", "--yes"])
    assert r.exit_code == 0, r.output
    target = tmp_path / "home" / ".codex" / "AGENTS.md"
    assert target.exists()
    assert BEGIN in target.read_text()


def test_apply_new_agent_targets_resolve_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(tmp_path / "home"))
    draft = _draft(tmp_path)
    expected = {
        "gemini": tmp_path / "home" / ".gemini" / "GEMINI.md",
        "opencode": tmp_path / "home" / ".config" / "opencode" / "AGENTS.md",
        "github-copilot": tmp_path / "home" / ".copilot" / "copilot-instructions.md",
        "cline": tmp_path / "home" / ".cline" / "AGENTS.md",
    }
    for agent, target in expected.items():
        r = CliRunner().invoke(cli, ["memory", "apply", "--from", str(draft), "--agent", agent, "--yes"])
        assert r.exit_code == 0, r.output
        assert target.exists()
        assert BEGIN in target.read_text()
