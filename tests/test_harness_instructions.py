import json

from docmancer.harness.instructions import InstructionsHarness


def test_harvests_repo_instruction_files(tmp_path):
    # A real repo with a CLAUDE.md, referenced by a Claude Code project session.
    repo = tmp_path / "code" / "my-app"
    repo.mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("This project uses pnpm and deploys on Railway.\n")
    proj = tmp_path / "home" / ".claude" / "projects" / "-Users-x-code-my-app"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": str(repo)}) + "\n")

    h = InstructionsHarness(home=tmp_path / "home")
    sources = h.discover()
    entries = [e for s in sources for e in h.harvest(s)]
    assert any("pnpm" in e.content for e in entries)
    assert all(e.extra.get("kind") == "instructions" for e in entries)


def test_harvests_cursor_rules(tmp_path):
    repo = tmp_path / "code" / "app2"
    rules = repo / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "style.md").write_text("Always use tabs.\n")
    proj = tmp_path / "home" / ".claude" / "projects" / "-Users-x-code-app2"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": str(repo)}) + "\n")

    h = InstructionsHarness(home=tmp_path / "home")
    entries = [e for s in h.discover() for e in h.harvest(s)]
    assert any("Always use tabs" in e.content for e in entries)


def test_skips_repo_that_no_longer_exists(tmp_path):
    proj = tmp_path / "home" / ".claude" / "projects" / "-Users-x-gone"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/gone-forever"}) + "\n")
    h = InstructionsHarness(home=tmp_path / "home")
    assert h.discover() == []
