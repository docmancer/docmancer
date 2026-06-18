"""Registry of all known harnesses.

Combines the four first-class harnesses (Claude Code, Codex, Cursor, repo
Instructions) with the data-driven external agents, then applies optional
:class:`docmancer.core.config.DiscoveryConfig` overrides: harnesses named in
``discovery.disabled`` are dropped, and ``discovery.extra_sources`` become a
synthetic ``custom`` harness so a new agent can be covered without a release.
"""
from __future__ import annotations

from pathlib import Path

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text
from .claude_code import ClaudeCodeHarness
from .codex import CodexHarness
from .cursor import CursorHarness
from .external import external_harnesses
from .instructions import InstructionsHarness

_HARNESS_CLASSES = [
    ClaudeCodeHarness,
    CodexHarness,
    CursorHarness,
    InstructionsHarness,
]


class CustomHarness(Harness):
    """Harvests user-declared ``discovery.extra_sources`` paths."""

    name = "custom"

    def __init__(self, home: Path | None = None, *, sources=()) -> None:
        super().__init__(home)
        self._specs = list(sources)

    def discover(self) -> list[HarnessSource]:
        out: list[HarnessSource] = []
        for spec in self._specs:
            path = Path(spec.path).expanduser()
            if not path.is_absolute():
                path = self.home / spec.path
            if path.is_dir() or path.is_file():
                out.append(
                    HarnessSource(
                        harness=spec.harness or "custom",
                        root=path,
                        scope=spec.scope or f"global:{spec.harness or 'custom'}",
                        extra={"kind": spec.kind or "instructions"},
                    )
                )
        return out

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        kind = source.extra.get("kind", "instructions")
        harness = source.harness
        if source.root.is_file():
            text = read_text(source.root)
            if text is None:
                return []
            return [MemoryEntry(harness, source.scope, source.root.stem, text, str(source.root), {"kind": kind})]
        entries: list[MemoryEntry] = []
        for f in iter_text_files(source.root):
            text = read_text(f)
            if text is None:
                continue
            rel = f.relative_to(source.root)
            entries.append(
                MemoryEntry(harness, source.scope, str(rel.with_suffix("")), text, str(f), {"kind": kind})
            )
        return entries


def all_harnesses(home: Path | None = None, config=None) -> list[Harness]:
    harnesses: list[Harness] = [cls(home) for cls in _HARNESS_CLASSES]
    harnesses.extend(external_harnesses(home))

    discovery = getattr(config, "discovery", None)
    disabled = {d.lower() for d in getattr(discovery, "disabled", []) or []}
    if disabled:
        harnesses = [h for h in harnesses if h.name.lower() not in disabled]

    extra = getattr(discovery, "extra_sources", []) or []
    if extra:
        harnesses.append(CustomHarness(home, sources=extra))
    return harnesses


__all__ = ["all_harnesses", "CustomHarness"]
