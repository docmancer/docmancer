"""Codex harness: memory under ``~/.codex/memories`` plus global AGENTS.md.

The Codex memory surface verified on a real machine is the markdown under
``~/.codex/memories/*.md`` (agent-written) and the global ``~/.codex/AGENTS.md``
(user-authored instructions). The structured ``memories_*.sqlite`` store is not
parsed in v1; markdown is the portable surface. Degrades silently when absent.
"""
from __future__ import annotations

from .base import Harness, HarnessSource, MemoryEntry, read_text


class CodexHarness(Harness):
    name = "codex"

    def discover(self) -> list[HarnessSource]:
        base = self.home / ".codex"
        if not base.is_dir():
            return []
        sources: list[HarnessSource] = []
        memories = base / "memories"
        if memories.is_dir():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=memories,
                    scope="global:codex",
                    extra={"kind": "agent-memory"},
                )
            )
        agents = base / "AGENTS.md"
        if agents.is_file():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=agents,
                    scope="global:codex",
                    extra={"kind": "instructions"},
                )
            )
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        kind = source.extra.get("kind", "agent-memory")
        entries: list[MemoryEntry] = []
        if source.root.is_dir():
            for md in sorted(source.root.glob("*.md")):
                text = read_text(md)
                if text is None:
                    continue
                entries.append(
                    MemoryEntry(self.name, source.scope, md.stem, text, str(md), {"kind": kind})
                )
        elif source.root.is_file():
            text = read_text(source.root)
            if text is not None:
                entries.append(
                    MemoryEntry(
                        self.name,
                        source.scope,
                        source.root.stem,
                        text,
                        str(source.root),
                        {"kind": kind},
                    )
                )
        return entries


__all__ = ["CodexHarness"]
