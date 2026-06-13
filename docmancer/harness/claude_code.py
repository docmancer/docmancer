"""Claude Code harness: agent memory under ``~/.claude/projects/*/memory``."""
from __future__ import annotations

from .base import Harness, HarnessSource, MemoryEntry, read_text
from .paths import project_path_for_slug_dir


class ClaudeCodeHarness(Harness):
    name = "claude-code"

    def discover(self) -> list[HarnessSource]:
        base = self.home / ".claude" / "projects"
        if not base.is_dir():
            return []
        sources: list[HarnessSource] = []
        for proj in sorted(base.iterdir()):
            if not proj.is_dir():
                continue
            memory_dir = proj / "memory"
            if not memory_dir.is_dir():
                continue
            scope = f"project:{project_path_for_slug_dir(proj)}"
            sources.append(HarnessSource(harness=self.name, root=memory_dir, scope=scope))
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for md in sorted(source.root.glob("*.md")):
            text = read_text(md)
            if text is None:
                continue
            entries.append(
                MemoryEntry(
                    harness=self.name,
                    scope=source.scope,
                    title=md.stem,
                    content=text,
                    path=str(md),
                    extra={"kind": "agent-memory"},
                )
            )
        return entries


__all__ = ["ClaudeCodeHarness"]
