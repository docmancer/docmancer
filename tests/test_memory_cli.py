import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _plant(home):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "note.md").write_text("We deploy on Railway.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    return tmp_path / "mem.db"


def test_scan_lists_harness(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "scan"])
    assert r.exit_code == 0
    assert "claude-code" in r.output


def test_sync_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sync", "--dry-run"])
    assert r.exit_code == 0
    assert "Would index" in r.output
    assert not db.exists()


def test_sync_then_query(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    s = CliRunner().invoke(cli, ["memory", "sync"])
    assert s.exit_code == 0, s.output
    q = CliRunner().invoke(cli, ["memory", "query", "where do we deploy"])
    assert q.exit_code == 0, q.output
    assert "Railway" in q.output


def test_sources_preview_lists_provenance(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sources", "--preview"])
    assert r.exit_code == 0, r.output
    assert "claude-code" in r.output
    assert "would index" in r.output
    assert "CLAUDE-CODE" in r.output  # grouped section header


def test_sources_json_and_filter(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sources", "--preview", "--json", "--agent", "claude-code"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data and all(row["agent"] == "claude-code" for row in data)
    assert "chars" in data[0] and "path" in data[0]


def test_sources_stored_index_after_sync(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    r = CliRunner().invoke(cli, ["memory", "sources"])
    assert r.exit_code == 0, r.output
    assert "files indexed" in r.output
    assert "claude-code" in r.output


def test_clear_removes_and_status_reports_empty(tmp_path, monkeypatch):
    db = _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    assert db.exists()
    c = CliRunner().invoke(cli, ["memory", "clear", "--yes"])
    assert c.exit_code == 0, c.output
    assert not db.exists()
    st = CliRunner().invoke(cli, ["memory", "status"])
    assert st.exit_code == 0
    assert "Exists: False" in st.output
