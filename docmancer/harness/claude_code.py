"""Claude Code harness: agent memory and instructions under ``~/.claude``.

Harvests three surfaces:

- agent memory under ``~/.claude/projects/<slug>/memory`` (recursive),
- global user instructions ``~/.claude/CLAUDE.md`` and enterprise
  ``/Library/Application Support/ClaudeCode/CLAUDE.md`` when present,
- global rules under ``~/.claude/rules``.

Degrades silently when any path is absent.
"""
from __future__ import annotations

from pathlib import Path

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text
from .paths import project_path_for_slug_dir


class ClaudeCodeHarness(Harness):
    name = "claude-code"

    def backup_adapter(self):
        from docmancer.backup.adapters import ClaudeCodeBackupAdapter

        return ClaudeCodeBackupAdapter(self.home)

    def discover(self) -> list[HarnessSource]:
        sources: list[HarnessSource] = []
        base = self.home / ".claude" / "projects"
        if base.is_dir():
            for proj in sorted(base.iterdir()):
                if not proj.is_dir():
                    continue
                memory_dir = proj / "memory"
                if not memory_dir.is_dir():
                    continue
                scope = f"project:{project_path_for_slug_dir(proj)}"
                sources.append(
                    HarnessSource(
                        harness=self.name,
                        root=memory_dir,
                        scope=scope,
                        extra={"kind": "agent-memory"},
                    )
                )

        global_claude = self.home / ".claude" / "CLAUDE.md"
        if global_claude.is_file():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=global_claude,
                    scope="global:claude-code",
                    extra={"kind": "instructions"},
                )
            )
        enterprise = Path("/Library/Application Support/ClaudeCode/CLAUDE.md")
        if enterprise.is_file():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=enterprise,
                    scope="global:claude-code",
                    extra={"kind": "instructions"},
                )
            )
        rules = self.home / ".claude" / "rules"
        if rules.is_dir():
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=rules,
                    scope="global:claude-code",
                    extra={"kind": "rules"},
                )
            )
        return sources

    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        kind = source.extra.get("kind", "agent-memory")
        entries: list[MemoryEntry] = []
        if source.root.is_dir():
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


__all__ = ["ClaudeCodeHarness"]
