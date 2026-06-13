"""Repo-level instruction harvest (surface widening).

Even users without agent auto-memory almost always have ``CLAUDE.md`` /
``AGENTS.md`` / ``.cursor/rules`` in their repositories. We recover each repo's
real path from the Claude Code session files and harvest those instruction
files so the indexed count is rarely zero. Entries are tagged
``kind="instructions"``.
"""
from __future__ import annotations

from pathlib import Path

from .base import Harness, HarnessSource, MemoryEntry, read_text
from .paths import project_path_for_slug_dir

_REPO_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")


class InstructionsHarness(Harness):
    name = "instructions"

    def discover(self) -> list[HarnessSource]:
        base = self.home / ".claude" / "projects"
        if not base.is_dir():
            return []
        seen: set[str] = set()
        sources: list[HarnessSource] = []
        for proj in sorted(base.iterdir()):
            if not proj.is_dir():
                continue
            repo = project_path_for_slug_dir(proj)
            if not repo or repo in seen:
                continue
            seen.add(repo)
            repo_path = Path(repo)
            if not repo_path.is_dir():
                continue
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=repo_path,
                    scope=f"project:{repo}",
                    extra={"kind": "instructions"},
                )
            )
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        repo = source.root
        entries: list[MemoryEntry] = []
        for rel in _REPO_INSTRUCTION_FILES:
            f = repo / rel
            if f.is_file():
                text = read_text(f)
                if text is not None:
                    entries.append(
                        MemoryEntry(self.name, source.scope, rel, text, str(f), {"kind": "instructions"})
                    )
        rules_dir = repo / ".cursor" / "rules"
        if rules_dir.is_dir():
            for rule in sorted(rules_dir.glob("*")):
                if not rule.is_file():
                    continue
                text = read_text(rule)
                if text is None:
                    continue
                entries.append(
                    MemoryEntry(
                        self.name,
                        source.scope,
                        f".cursor/rules/{rule.name}",
                        text,
                        str(rule),
                        {"kind": "instructions"},
                    )
                )
        return entries


__all__ = ["InstructionsHarness"]
