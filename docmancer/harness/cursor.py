"""Cursor harness: global instructions, rules, and skills under ``~/.cursor``.

Harvests the global ``~/.cursor/AGENTS.md`` instructions plus rules under
``~/.cursor/rules`` and skills under ``~/.cursor/skills`` (``.md``/``.mdc``/
``.txt``). Cursor's global User Rules live in the app database, not a file, so
they are not indexable here. Degrades silently when any path is absent.
"""
from __future__ import annotations

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text


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
        for sub, kind in (("rules", "rules"), ("skills", "instructions")):
            d = base / sub
            if d.is_dir():
                sources.append(
                    HarnessSource(
                        harness=self.name,
                        root=d,
                        scope="global:cursor",
                        extra={"kind": kind},
                    )
                )
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        kind = source.extra.get("kind", "instructions")
        if source.root.is_file():
            text = read_text(source.root)
            if text is None:
                return []
            return [
                MemoryEntry(
                    self.name, source.scope, source.root.stem, text, str(source.root), {"kind": kind}
                )
            ]
        entries: list[MemoryEntry] = []
        for f in iter_text_files(source.root):
            text = read_text(f)
            if text is None:
                continue
            rel = f.relative_to(source.root)
            entries.append(
                MemoryEntry(
                    self.name,
                    source.scope,
                    str(rel.with_suffix("")),
                    text,
                    str(f),
                    {"kind": kind},
                )
            )
        return entries


__all__ = ["CursorHarness"]
