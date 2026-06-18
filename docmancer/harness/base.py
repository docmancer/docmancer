"""Harness discovery abstractions.

A *harness* is a coding agent (Claude Code, Codex, Cursor) that writes memory
or working-context files to disk. Each harness exposes :meth:`Harness.discover`
(find sources on this machine) and :meth:`Harness.harvest` (read a source into
``MemoryEntry`` objects). Entries carry a ``kind`` in ``extra`` so callers can
tell genuine agent-written memory (``agent-memory``) from user-authored
instructions (``instructions``).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docmancer.core.models import Document

logger = logging.getLogger(__name__)


def default_home() -> Path:
    """Home directory for harness discovery.

    Honours ``DOCMANCER_HARNESS_HOME`` so tests (and users with a relocated
    home) can point discovery at an isolated tree.
    """
    override = os.getenv("DOCMANCER_HARNESS_HOME")
    return Path(override).expanduser() if override else Path.home()


def read_text(path: Path) -> str | None:
    """Read a UTF-8 text file, returning None for unreadable/binary files."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# Markdown/text extensions indexed across harnesses.
TEXT_SUFFIXES = {".md", ".markdown", ".mdc", ".txt"}

# Directories never worth walking into for memory/instruction files.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".DS_Store"}


def iter_text_files(
    root: Path,
    suffixes: "set[str] | None" = None,
    *,
    skip_dirs: "set[str] | None" = None,
):
    """Yield text files under ``root`` recursively, skipping noise directories.

    Sorted for deterministic output. ``suffixes`` defaults to
    :data:`TEXT_SUFFIXES`; matching is case-insensitive.
    """
    suffixes = TEXT_SUFFIXES if suffixes is None else suffixes
    skip_dirs = SKIP_DIRS if skip_dirs is None else skip_dirs
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if any(part in skip_dirs for part in path.relative_to(root).parts):
            continue
        yield path


@dataclass
class HarnessSource:
    """A discovered location (a directory or file) a harness can harvest."""

    harness: str
    root: Path
    scope: str
    extra: dict = field(default_factory=dict)


@dataclass
class MemoryEntry:
    """One harvested memory or instruction file."""

    harness: str
    scope: str
    title: str
    content: str
    path: str
    extra: dict = field(default_factory=dict)

    def to_document(self) -> "Document":
        from docmancer.core.models import Document

        metadata = {
            "harness": self.harness,
            "scope": self.scope,
            "title": self.title,
            "source_path": self.path,
            "kind": self.extra.get("kind", "agent-memory"),
        }
        for key, value in self.extra.items():
            metadata.setdefault(key, value)
        return Document(source=f"{self.harness}:{self.path}", content=self.content, metadata=metadata)


class Harness(ABC):
    """Base class for a discoverable coding-agent harness."""

    name: str = "harness"

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home) if home is not None else default_home()

    @abstractmethod
    def discover(self) -> list[HarnessSource]:
        """Return the sources present on this machine (``[]`` when absent)."""

    @abstractmethod
    def harvest(self, source: HarnessSource) -> list[MemoryEntry]:
        """Read a source into memory entries (skipping unreadable files)."""


def discover_harnesses(home: Path | None = None, config=None) -> list[Harness]:
    from .registry import all_harnesses

    return all_harnesses(home, config=config)


def harvest_all(home: Path | None = None, config=None) -> list[MemoryEntry]:
    """Discover and harvest every registered harness into one flat list.

    ``config`` is an optional :class:`docmancer.core.config.DiscoveryConfig`
    used to disable harnesses or add custom source paths.
    """
    entries: list[MemoryEntry] = []
    for harness in discover_harnesses(home, config=config):
        try:
            sources = harness.discover()
        except Exception as exc:  # noqa: BLE001 - one bad harness must not abort the rest
            logger.debug("harness %s discover failed: %s", harness.name, exc)
            continue
        for source in sources:
            try:
                entries.extend(harness.harvest(source))
            except Exception as exc:  # noqa: BLE001
                logger.debug("harness %s harvest failed for %s: %s", harness.name, source.root, exc)
    return entries


__all__ = [
    "HarnessSource",
    "MemoryEntry",
    "Harness",
    "default_home",
    "read_text",
    "iter_text_files",
    "TEXT_SUFFIXES",
    "SKIP_DIRS",
    "discover_harnesses",
    "harvest_all",
]
