"""Cursor harness: global ``~/.cursor/AGENTS.md`` instructions.

The project-rules layout under ``~/.cursor/projects`` is still unverified, so
v1 harvests only the reliably-present global ``AGENTS.md``. Degrades silently
when absent.
"""
from __future__ import annotations

from .base import Harness, HarnessSource, MemoryEntry, read_text


class CursorHarness(Harness):
    name = "cursor"

    def discover(self) -> list[HarnessSource]:
        base = self.home / ".cursor"
        if not base.is_dir():
            return []
        sources: list[HarnessSource] = []
        agents = base / "AGENTS.md"
        if agents.is_file():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=agents,
                    scope="global:cursor",
                    extra={"kind": "instructions"},
                )
            )
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        text = read_text(source.root)
        if text is None:
            return []
        return [
            MemoryEntry(
                self.name,
                source.scope,
                source.root.stem,
                text,
                str(source.root),
                {"kind": source.extra.get("kind", "instructions")},
            )
        ]


__all__ = ["CursorHarness"]
