import json

from docmancer.harness.claude_code import ClaudeCodeHarness
from docmancer.harness.codex import CodexHarness
from docmancer.harness.cursor import CursorHarness


def test_claude_code_discovers_and_harvests(tmp_path):
    home = tmp_path / "home"
    proj = home / ".claude" / "projects" / "-Users-x-my-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "note.md").write_text("We deploy on Railway.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/my-app"}) + "\n")

    h = ClaudeCodeHarness(home=home)
    sources = h.discover()
    assert len(sources) == 1
    assert sources[0].scope == "project:/Users/x/my-app"
    entries = [e for s in sources for e in h.harvest(s)]
    assert any("Railway" in e.content for e in entries)
    assert all(e.extra["kind"] == "agent-memory" for e in entries)


def test_claude_code_absent_returns_empty(tmp_path):
    assert ClaudeCodeHarness(home=tmp_path / "nope").discover() == []


def test_codex_memories_and_agents(tmp_path):
    home = tmp_path / "home"
    mem = home / ".codex" / "memories"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("Codex remembers the deploy target.\n")
    (home / ".codex" / "AGENTS.md").write_text("Global codex instructions.\n")

    h = CodexHarness(home=home)
    sources = h.discover()
    kinds = {s.extra.get("kind") for s in sources}
    assert kinds == {"agent-memory", "instructions"}
    entries = [e for s in sources for e in h.harvest(s)]
    assert any("Codex remembers" in e.content for e in entries)
    assert any(e.extra["kind"] == "instructions" for e in entries)


def test_codex_absent_returns_empty(tmp_path):
    assert CodexHarness(home=tmp_path / "nope").discover() == []


def test_cursor_agents_md(tmp_path):
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".cursor" / "AGENTS.md").write_text("Cursor global rules.\n")
    h = CursorHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    assert any("Cursor global rules" in e.content for e in entries)
    assert all(e.extra["kind"] == "instructions" for e in entries)


def test_skips_non_utf8_file(tmp_path):
    home = tmp_path / "home"
    mem = home / ".codex" / "memories"
    mem.mkdir(parents=True)
    (mem / "good.md").write_text("readable\n")
    (mem / "bad.md").write_bytes(b"\xff\xfe\x00\x01binary")
    h = CodexHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    titles = {e.title for e in entries}
    assert "good" in titles and "bad" not in titles
