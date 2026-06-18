"""Repo-level instruction and rule harvest (surface widening).

Even users without agent auto-memory almost always have ``CLAUDE.md`` /
``AGENTS.md`` / ``GEMINI.md`` and rule directories in their repositories. We
recover each repo's real path from every agent that records it (Claude Code,
Cursor, Gemini, Codex sessions) and harvest those instruction files and rule
directories, so the indexed count is rarely zero. Entries are tagged
``kind="instructions"`` or ``kind="rules"``.
"""
from __future__ import annotations

from pathlib import Path

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text
from .paths import discover_project_roots

# Single instruction files, relative to a repo root.
_REPO_INSTRUCTION_FILES = (
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    "GEMINI.md",
    "QWEN.md",
    "CRUSH.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    "CONVENTIONS.md",
    ".rules",
)

# Rule directories, relative to a repo root. Scanned recursively.
_REPO_RULE_DIRS = (
    ".claude/rules",
    ".cursor/rules",
    ".continue/rules",
    ".clinerules",
    ".windsurf/rules",
    ".windsurf/workflows",
    ".devin/rules",
)

_RULE_SUFFIXES = {".md", ".markdown", ".mdc", ".txt", ".yaml", ".yml"}


class InstructionsHarness(Harness):
    name = "instructions"

    def discover(self) -> list[HarnessSource]:
        sources: list[HarnessSource] = []
        for repo in discover_project_roots(self.home):
            sources.append(
                HarnessSource(
                    harness=self.name,
                    root=Path(repo),
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
        # Legacy single-file .clinerules is handled above only when it is a file;
        # the dir form is handled by the rule-dir loop below.
        for rel in _REPO_RULE_DIRS:
            rules_dir = repo / rel
            if not rules_dir.is_dir():
                continue
            for rule in iter_text_files(rules_dir, _RULE_SUFFIXES):
                text = read_text(rule)
                if text is None:
                    continue
                rule_rel = rule.relative_to(repo)
                entries.append(
                    MemoryEntry(
                        self.name,
                        source.scope,
                        str(rule_rel),
                        text,
                        str(rule),
                        {"kind": "rules"},
                    )
                )
        return entries


__all__ = ["InstructionsHarness"]
