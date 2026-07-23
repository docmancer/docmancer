"""Project-aware discovery for optional Markdown harvesting."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from docmancer.harness.base import discover_harnesses

logger = logging.getLogger(__name__)

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdc"}


@dataclass(frozen=True)
class ProjectHarvestSource:
    root: Path
    harness: str
    scope: str
    files: tuple[Path, ...] = ()


def discover_project_harvest_sources(
    project_path: str | Path,
    *,
    home: Path | None = None,
    config=None,
) -> list[ProjectHarvestSource]:
    """Return registered harness sources scoped to exactly one project."""
    project = Path(project_path).expanduser().resolve()
    selected: list[ProjectHarvestSource] = []
    seen: set[Path] = set()
    for harness in discover_harnesses(home=home, config=config):
        try:
            sources = harness.discover()
        except Exception as exc:  # noqa: BLE001
            logger.debug("harness %s discovery failed during harvest: %s", harness.name, exc)
            continue
        for source in sources:
            kind, separator, value = source.scope.partition(":")
            if kind != "project" or not separator:
                continue
            try:
                source_project = Path(value).expanduser().resolve()
            except OSError:
                continue
            root = source.root.expanduser().resolve()
            if source_project == project and root not in seen and root.exists():
                try:
                    entries = harness.harvest(source)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("harness %s harvest failed during source selection: %s", harness.name, exc)
                    continue
                files = tuple(
                    sorted({
                        Path(entry.path).expanduser().resolve()
                        for entry in entries
                        if Path(entry.path).suffix.lower() in MARKDOWN_SUFFIXES
                        and Path(entry.path).expanduser().is_file()
                    })
                )
                if not files:
                    continue
                seen.add(root)
                selected.append(
                    ProjectHarvestSource(
                        root=root,
                        harness=source.harness,
                        scope=source.scope,
                        files=files,
                    )
                )
    return sorted(selected, key=lambda item: (item.harness, str(item.root)))


def markdown_files(sources: list[Path] | tuple[Path, ...], *, limit: int = 500) -> list[Path]:
    """Expand explicit files/directories into a bounded, de-duplicated list."""
    files: list[Path] = []
    for source in sources:
        source = source.expanduser()
        if source.is_file() and source.suffix.lower() in MARKDOWN_SUFFIXES:
            files.append(source)
        elif source.is_dir():
            files.extend(
                path for path in source.rglob("*")
                if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES
            )
    return sorted(dict.fromkeys(path.resolve() for path in files))[:limit]


__all__ = [
    "MARKDOWN_SUFFIXES",
    "ProjectHarvestSource",
    "discover_project_harvest_sources",
    "markdown_files",
]
