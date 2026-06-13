import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    # Plant a Claude Code memory file in the isolated home.
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "2026-03-28.md").write_text("We deploy on Railway.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")
    # Isolate everything that touches the real home.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    return home


def test_setup_indexes_memory(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["setup", "--agent", "codex", "--index-memory"])
    assert r.exit_code == 0, r.output
    assert "Indexed" in r.output
    q = CliRunner().invoke(cli, ["memory", "query", "where do we deploy"])
    assert q.exit_code == 0, q.output
    assert "Railway" in q.output


def test_setup_dry_run_previews_only(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["setup", "--agent", "codex", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "Would index" in r.output
    assert not (tmp_path / "mem.db").exists()


def test_setup_no_index_memory_skips(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["setup", "--agent", "codex", "--no-index-memory"])
    assert r.exit_code == 0, r.output
    assert "Indexed" not in r.output
    assert not (tmp_path / "mem.db").exists()
