"""External agent harnesses (data-driven).

These cover coding agents docmancer can read memory/instructions/rules from even
when it does not yet install skills to them. Each agent is described by a list
of global locations (files or directories, relative to home); the generic
:class:`ExternalHarness` discovers whichever exist and harvests them. Directories
are scanned recursively for text files; single files are read directly so
extensionless dotfiles (for example ``.goosehints``) are still picked up.

Adding a new agent is a one-line spec edit, never new control flow. Paths are
the canonical researched locations; divergent variants are listed as separate
locations and indexed only when present.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Harness, HarnessSource, MemoryEntry, iter_text_files, read_text


@dataclass(frozen=True)
class ExternalLocation:
    relpath: str  # relative to home
    kind: str  # "agent-memory" | "instructions" | "rules"


@dataclass(frozen=True)
class ExternalSpec:
    name: str
    locations: tuple[ExternalLocation, ...]


def _loc(relpath: str, kind: str) -> ExternalLocation:
    return ExternalLocation(relpath, kind)


EXTERNAL_SPECS: tuple[ExternalSpec, ...] = (
    ExternalSpec("opencode", (
        _loc(".config/opencode/AGENTS.md", "instructions"),
        _loc(".config/opencode/skills", "instructions"),
    )),
    ExternalSpec("crush", (
        _loc(".config/crush/CRUSH.md", "instructions"),
        _loc(".config/crush/skills", "instructions"),
    )),
    ExternalSpec("goose", (
        _loc(".config/goose/.goosehints", "instructions"),
        _loc(".config/goose/skills", "instructions"),
    )),
    ExternalSpec("qwen", (
        _loc(".qwen/QWEN.md", "instructions"),
        _loc(".qwen/skills", "instructions"),
        _loc(".qwen/projects", "agent-memory"),
        _loc(".qwen/memories", "agent-memory"),
    )),
    ExternalSpec("continue", (
        _loc(".continue/rules", "rules"),
        _loc(".continue/skills", "instructions"),
    )),
    ExternalSpec("cline", (
        _loc("Documents/Cline/Rules", "rules"),
        _loc("Cline/Rules", "rules"),
        _loc(".agents/AGENTS.md", "instructions"),
    )),
    ExternalSpec("windsurf", (
        _loc(".codeium/windsurf/global_rules.md", "rules"),
        _loc(".codeium/windsurf/memories", "agent-memory"),
        _loc(".codeium/windsurf/global_workflows", "instructions"),
        _loc(".codeium/windsurf/skills", "instructions"),
    )),
    ExternalSpec("openclaw", (
        _loc(".openclaw/workspace/AGENTS.md", "instructions"),
        _loc(".openclaw/workspace/SOUL.md", "instructions"),
        _loc(".openclaw/workspace/IDENTITY.md", "instructions"),
        _loc(".openclaw/workspace/USER.md", "instructions"),
        _loc(".openclaw/workspace/TOOLS.md", "instructions"),
        _loc(".openclaw/workspace/MEMORY.md", "agent-memory"),
        _loc(".openclaw/workspace/memory", "agent-memory"),
    )),
    ExternalSpec("hermes", (
        _loc(".hermes/SOUL.md", "instructions"),
        _loc(".hermes/memories", "agent-memory"),
    )),
    ExternalSpec("gemini", (
        _loc(".gemini/GEMINI.md", "instructions"),
        _loc(".gemini/skills", "instructions"),
    )),
    ExternalSpec("github-copilot", (
        _loc(".copilot/copilot-instructions.md", "instructions"),
        _loc("Library/Application Support/Code/User/prompts", "instructions"),
    )),
    ExternalSpec("roo", (
        _loc(".roo/rules", "rules"),
    )),
    ExternalSpec("zed", (
        _loc(".config/zed/AGENTS.md", "instructions"),
    )),
)


class ExternalHarness(Harness):
    """Generic harness driven by an :class:`ExternalSpec`."""

    def __init__(self, home=None, *, spec: ExternalSpec) -> None:
        super().__init__(home)
        self.spec = spec
        self.name = spec.name

    def discover(self) -> list[HarnessSource]:
        sources: list[HarnessSource] = []
        for loc in self.spec.locations:
            path = self.home / loc.relpath
            if path.is_dir() or path.is_file():
                sources.append(
                    HarnessSource(
                        harness=self.name,
                        root=path,
                        scope=f"global:{self.name}",
                        extra={"kind": loc.kind},
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


def external_harnesses(home=None) -> list[Harness]:
    return [ExternalHarness(home, spec=spec) for spec in EXTERNAL_SPECS]


__all__ = ["ExternalHarness", "ExternalSpec", "ExternalLocation", "EXTERNAL_SPECS", "external_harnesses"]
