"""Codex harness: memory under ``~/.codex/memories`` plus global AGENTS.md.

The Codex memory surface verified on a real machine is recursive markdown under
``~/.codex/memories`` (agent-written memory, rollout summaries, extensions, and
skills) plus the global ``~/.codex/AGENTS.md`` and ``~/.codex/AGENTS.override.md``
user-authored instructions. The structured ``memories_*.sqlite`` store is not
parsed in v1; markdown is the portable surface. Degrades silently when absent.
"""
from __future__ import annotations

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text

_MEMORY_SUFFIXES = {".md", ".markdown"}


class CodexHarness(Harness):
    name = "codex"

    def backup_adapter(self):
        from docmancer.backup.adapters import CodexBackupAdapter

        return CodexBackupAdapter(self.home)

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
        for name in ("AGENTS.md", "AGENTS.override.md"):
            agents = base / name
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
            for md in iter_text_files(source.root, _MEMORY_SUFFIXES):
                text = read_text(md)
                if text is None:
                    continue
                rel = md.relative_to(source.root)
                entries.append(
                    MemoryEntry(
                        self.name,
                        source.scope,
                        str(rel.with_suffix("")),
                        text,
                        str(md),
                        {"kind": kind},
                    )
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
