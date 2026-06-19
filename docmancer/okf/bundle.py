"""Write OKF bundles: concept files, a root ``index.md``, and an optional log."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .format import OKF_VERSION, dump_frontmatter

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Turn arbitrary text into a filesystem and URL safe slug."""
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or "untitled"


@dataclass
class OKFConcept:
    """A single OKF concept document.

    ``type`` is the only required OKF field. ``filename`` is the relative path
    within the bundle; when omitted it is derived from the title or type.
    """

    type: str
    body: str = ""
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = field(default_factory=list)
    timestamp: str | None = None
    extra: dict = field(default_factory=dict)
    filename: str | None = None

    def frontmatter(self) -> dict:
        fields: dict = {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "resource": self.resource,
            "tags": list(self.tags),
            "timestamp": self.timestamp,
        }
        fields.update(self.extra)
        return fields

    def to_markdown(self) -> str:
        return dump_frontmatter(self.frontmatter(), self.body)

    def default_slug(self) -> str:
        return slugify(self.title or self.type)


@dataclass
class BundleResult:
    root: Path
    concept_count: int
    files: list[Path]


def _assign_filenames(concepts: list[OKFConcept]) -> list[tuple[OKFConcept, str]]:
    """Resolve a unique ``.md`` filename for each concept, deduping collisions."""
    used: set[str] = set()
    assigned: list[tuple[OKFConcept, str]] = []
    for concept in concepts:
        name = concept.filename or f"{concept.default_slug()}.md"
        if not name.endswith(".md"):
            name += ".md"
        stem, suffix = name[:-3], ".md"
        candidate = name
        counter = 2
        while candidate in used:
            candidate = f"{stem}-{counter}{suffix}"
            counter += 1
        used.add(candidate)
        assigned.append((concept, candidate))
    return assigned


def _render_index(title: str | None, assigned: list[tuple[OKFConcept, str]]) -> str:
    lines = []
    for concept, name in assigned:
        label = concept.title or concept.type
        lines.append(f"- [{label}]({name})")
    body = (f"# {title}\n\n" if title else "") + "\n".join(lines) + "\n"
    return dump_frontmatter({"okf_version": OKF_VERSION, "title": title}, body)


def write_bundle(
    root: Path | str,
    concepts: list[OKFConcept],
    *,
    title: str | None = None,
    description: str | None = None,
    log_entries: list[str] | None = None,
) -> BundleResult:
    """Write ``concepts`` as an OKF bundle rooted at ``root``.

    Always writes a root ``index.md`` carrying ``okf_version``. Writes
    ``log.md`` when ``log_entries`` are provided.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    assigned = _assign_filenames(concepts)
    written: list[Path] = []
    for concept, name in assigned:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(concept.to_markdown(), encoding="utf-8")
        written.append(path)

    index_path = root / "index.md"
    index_path.write_text(_render_index(title, assigned), encoding="utf-8")
    written.append(index_path)

    # Per-directory index.md for every subdirectory holding concept files, with
    # links relative to that subdirectory.
    by_dir: dict[Path, list[tuple[OKFConcept, str]]] = {}
    for concept, name in assigned:
        parent = (root / name).parent
        if parent != root:
            by_dir.setdefault(parent, []).append((concept, Path(name).name))
    for directory, items in by_dir.items():
        sub_index = directory / "index.md"
        sub_title = directory.relative_to(root).as_posix()
        sub_index.write_text(_render_index(sub_title, items), encoding="utf-8")
        written.append(sub_index)

    if log_entries:
        log_path = root / "log.md"
        log_body = "# Log\n\n" + "\n".join(f"- {entry}" for entry in log_entries) + "\n"
        log_path.write_text(log_body, encoding="utf-8")
        written.append(log_path)

    return BundleResult(root=root, concept_count=len(assigned), files=written)
