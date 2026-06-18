"""Exhaustive discovery: recursive harvest, global instructions, external agents."""
from __future__ import annotations

import json

from docmancer.harness import harvest_all
from docmancer.harness.claude_code import ClaudeCodeHarness
from docmancer.harness.codex import CodexHarness
from docmancer.harness.cursor import CursorHarness
from docmancer.harness.external import external_harnesses
from docmancer.harness.instructions import InstructionsHarness
from docmancer.harness.registry import all_harnesses


def test_codex_harvests_recursively(tmp_path):
    home = tmp_path / "home"
    nested = home / ".codex" / "memories" / "rollouts" / "2026"
    nested.mkdir(parents=True)
    (nested / "summary.md").write_text("Deep nested codex memory.\n")
    (home / ".codex" / "memories" / "top.markdown").write_text("Top-level memory.\n")
    h = CodexHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    contents = " ".join(e.content for e in entries)
    assert "Deep nested" in contents and "Top-level" in contents
    # Title preserves the relative path so nested files are distinguishable.
    assert any("rollouts/2026/summary" in e.title for e in entries)


def test_codex_reads_agents_override(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "AGENTS.md").write_text("base\n")
    (home / ".codex" / "AGENTS.override.md").write_text("override wins\n")
    h = CodexHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    assert any("override wins" in e.content for e in entries)


def test_claude_code_global_instructions_and_rules(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("Global user instructions.\n")
    rules = home / ".claude" / "rules"
    rules.mkdir()
    (rules / "py.md").write_text("Always type-hint.\n")
    h = ClaudeCodeHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    kinds = {e.extra["kind"] for e in entries}
    assert "instructions" in kinds and "rules" in kinds
    assert any("Global user instructions" in e.content for e in entries)
    assert any("Always type-hint" in e.content for e in entries)


def test_cursor_rules_and_skills(tmp_path):
    home = tmp_path / "home"
    rules = home / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "style.mdc").write_text("Use tabs.\n")
    skills = home / ".cursor" / "skills" / "x"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("A cursor skill.\n")
    h = CursorHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    contents = " ".join(e.content for e in entries)
    assert "Use tabs" in contents and "A cursor skill" in contents


def test_external_gemini_and_opencode(tmp_path):
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "GEMINI.md").write_text("Gemini global memory.\n")
    oc = home / ".config" / "opencode"
    oc.mkdir(parents=True)
    (oc / "AGENTS.md").write_text("OpenCode instructions.\n")
    entries = []
    for h in external_harnesses(home=home):
        for s in h.discover():
            entries.extend(h.harvest(s))
    by_agent = {e.harness for e in entries}
    assert "gemini" in by_agent and "opencode" in by_agent
    assert any("Gemini global memory" in e.content for e in entries)


def test_instructions_multisource_project_roots(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "code" / "viacodex"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("Repo agents instructions.\n")
    # Only a Codex session references this repo (not Claude).
    sessions = home / ".codex" / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (sessions / "s.jsonl").write_text(json.dumps({"cwd": str(repo)}) + "\n")
    h = InstructionsHarness(home=home)
    entries = [e for s in h.discover() for e in h.harvest(s)]
    assert any("Repo agents instructions" in e.content for e in entries)


def test_registry_honors_disabled_and_extra_sources(tmp_path):
    from docmancer.core.config import DiscoveryConfig, DiscoveryExtraSource, DocmancerConfig

    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "GEMINI.md").write_text("gemini\n")
    custom_file = tmp_path / "notes" / "playbook.md"
    custom_file.parent.mkdir(parents=True)
    custom_file.write_text("Custom playbook.\n")

    config = DocmancerConfig(
        discovery=DiscoveryConfig(
            disabled=["gemini"],
            extra_sources=[DiscoveryExtraSource(harness="notebook", path=str(custom_file), kind="instructions")],
        )
    )
    names = {h.name for h in all_harnesses(home, config=config)}
    assert "gemini" not in names
    entries = harvest_all(home, config=config)
    assert any(e.harness == "notebook" and "Custom playbook" in e.content for e in entries)
    assert all(e.harness != "gemini" for e in entries)
