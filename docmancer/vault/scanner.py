from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from docmancer.vault.manifest import (
    ContentKind,
    IndexState,
    ManifestEntry,
    SourceType,
    VaultManifest,
    _utc_now,
)

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg"}

_KIND_BY_DIR: dict[str, ContentKind] = {
    "raw": ContentKind.raw,
    "wiki": ContentKind.wiki,
    "outputs": ContentKind.output,
}

# Folder name heuristics for content kind inference (case-insensitive).
# Used when scan_dirs includes "." (whole-vault mode).
_FOLDER_KIND_HEURISTICS: dict[str, ContentKind] = {
    "raw": ContentKind.raw,
    "clippings": ContentKind.raw,
    "inbox": ContentKind.raw,
    "sources": ContentKind.raw,
    "wiki": ContentKind.wiki,
    "notes": ContentKind.wiki,
    "zettelkasten": ContentKind.wiki,
    "outputs": ContentKind.output,
    "reports": ContentKind.output,
    "slides": ContentKind.output,
    "assets": ContentKind.asset,
    "images": ContentKind.asset,
    "attachments": ContentKind.asset,
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg"}

# Directories to always skip during file discovery.
_SKIP_SCAN_DIRS = {".obsidian", ".docmancer", ".trash", ".git"}

_SOURCE_TYPE_BY_EXT: dict[str, SourceType] = {
    ".md": SourceType.markdown,
    ".txt": SourceType.local_file,
    ".pdf": SourceType.pdf,
    ".png": SourceType.image,
    ".jpg": SourceType.image,
    ".jpeg": SourceType.image,
    ".gif": SourceType.image,
    ".svg": SourceType.image,
}

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

_AUTO_GENERATED_FILES = {"_index.md", "_graph.md"}


def _sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_kind(relative_path: str) -> ContentKind:
    first_part = relative_path.split("/")[0] if "/" in relative_path else ""
    return _KIND_BY_DIR.get(first_part, ContentKind.asset)


def _infer_kind_flexible(
    relative_path: str,
    file_path: Path,
    frontmatter: dict,
) -> ContentKind:
    """Infer content kind using the priority chain for whole-vault mode.

    1. Explicit ``kind`` field in frontmatter
    2. Folder name heuristics (case-insensitive)
    3. Source URL presence in frontmatter → raw
    4. Image file extension → asset
    5. Default → raw
    """
    # 1. Explicit frontmatter kind
    fm_kind = frontmatter.get("kind")
    if isinstance(fm_kind, str):
        fm_kind_lower = fm_kind.strip().lower()
        try:
            return ContentKind(fm_kind_lower)
        except ValueError:
            pass

    # 2. Folder name heuristics
    parts = Path(relative_path).parts
    for part in parts[:-1]:  # skip the filename itself
        match = _FOLDER_KIND_HEURISTICS.get(part.lower())
        if match is not None:
            return match

    # 3. Source URL presence
    for key in ("source", "sources"):
        val = frontmatter.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            return ContentKind.raw
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    return ContentKind.raw

    # 4. Image extension
    if file_path.suffix.lower() in _IMAGE_EXTENSIONS:
        return ContentKind.asset

    # 5. Default
    return ContentKind.raw


def _infer_source_type(file_path: Path) -> SourceType:
    return _SOURCE_TYPE_BY_EXT.get(file_path.suffix.lower(), SourceType.local_file)


def _parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(content[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _manifest_metadata_for_file(file_path: Path) -> dict:
    metadata: dict = {}
    if file_path.suffix.lower() != ".md":
        return metadata
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return metadata

    frontmatter = _parse_frontmatter(content)
    title = frontmatter.get("title")
    if isinstance(title, str) and title.strip():
        metadata["title"] = title.strip()

    tags = frontmatter.get("tags")
    if isinstance(tags, list):
        metadata["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]

    # sources (plural, docmancer format) takes precedence over source (singular, Web Clipper)
    sources = frontmatter.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                metadata["source_url"] = source
                break
        for source in sources:
            if isinstance(source, str) and not source.startswith(("http://", "https://")):
                metadata["parent_ref"] = source
                break

    # Web Clipper uses singular "source" field
    if "source_url" not in metadata:
        source_singular = frontmatter.get("source")
        if isinstance(source_singular, str) and source_singular.startswith(("http://", "https://")):
            metadata["source_url"] = source_singular

    # Web Clipper extra fields
    extra: dict = {}
    author = frontmatter.get("author")
    if isinstance(author, str) and author.strip():
        extra["author"] = author.strip()
    published = frontmatter.get("published")
    if published is not None:
        extra["published"] = str(published)
    if extra:
        metadata["extra"] = extra

    # Web Clipper "created" field → added_at
    created = frontmatter.get("created")
    if created is not None:
        metadata["created_at"] = str(created)

    outbound_refs: list[str] = []
    for match in _WIKILINK_RE.finditer(content):
        target = match.group(1).strip()
        if target:
            outbound_refs.append(target)
    for _label, href in _MD_LINK_RE.findall(content):
        href = href.strip()
        if href and not href.startswith(("http://", "https://", "mailto:", "#")):
            outbound_refs.append(href)
    if outbound_refs:
        metadata["outbound_refs"] = list(dict.fromkeys(outbound_refs))

    if metadata.get("source_url"):
        metadata["canonical_source_url"] = metadata["source_url"]

    return metadata


@dataclass
class ScanResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0


def _should_skip_path(file_path: Path, vault_root: Path) -> bool:
    """Return True if the file is inside a directory that should be skipped."""
    try:
        relative = file_path.relative_to(vault_root)
    except ValueError:
        return True
    for part in relative.parts:
        if part in _SKIP_SCAN_DIRS or part.startswith("."):
            return True
    return False


def scan_vault(vault_root: Path, manifest: VaultManifest, scan_dirs: list[str]) -> ScanResult:
    """Walk scan_dirs under vault_root, reconcile with manifest, return summary."""
    result = ScanResult()
    seen_paths: set[str] = set()
    use_flexible_kind = "." in scan_dirs

    for dir_name in scan_dirs:
        scan_path = vault_root / dir_name
        if not scan_path.is_dir():
            continue
        for file_path in sorted(scan_path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                continue
            if file_path.name in _AUTO_GENERATED_FILES:
                continue
            # Skip hidden/internal directories
            if _should_skip_path(file_path, vault_root):
                continue
            relative = str(file_path.relative_to(vault_root))
            seen_paths.add(relative)
            content_hash = _sha256(file_path)
            existing = manifest.get_by_path(relative)
            metadata = _manifest_metadata_for_file(file_path)

            if use_flexible_kind:
                fm = _parse_frontmatter(
                    file_path.read_text(encoding="utf-8")
                ) if file_path.suffix.lower() == ".md" else {}
                kind = _infer_kind_flexible(relative, file_path, fm)
            else:
                kind = _infer_kind(relative)

            if existing is None:
                entry = ManifestEntry(
                    path=relative,
                    kind=kind,
                    source_type=_infer_source_type(file_path),
                    content_hash=content_hash,
                    index_state=IndexState.pending,
                    title=metadata.get("title"),
                    tags=metadata.get("tags", []),
                    source_url=metadata.get("source_url"),
                    canonical_source_url=metadata.get("canonical_source_url"),
                    parent_ref=metadata.get("parent_ref"),
                    outbound_refs=metadata.get("outbound_refs", []),
                    extra=metadata.get("extra", {}),
                    created_at=metadata.get("created_at"),
                )
                manifest.add(entry)
                result.added.append(relative)
            elif existing.content_hash != content_hash:
                manifest._entries[existing.id] = existing.model_copy(
                    update={
                        "content_hash": content_hash,
                        "index_state": IndexState.stale,
                        "updated_at": _utc_now(),
                        "title": metadata.get("title"),
                        "tags": metadata.get("tags", []),
                        "source_url": metadata.get("source_url", existing.source_url),
                        "canonical_source_url": metadata.get("canonical_source_url", existing.canonical_source_url),
                        "parent_ref": metadata.get("parent_ref"),
                        "outbound_refs": metadata.get("outbound_refs", []),
                    }
                )
                result.updated.append(relative)
            else:
                result.unchanged += 1

    # Remove entries whose files no longer exist on disk
    if use_flexible_kind:
        # In whole-vault mode, any tracked file not seen is removed
        for entry in manifest.all_entries():
            if entry.path not in seen_paths:
                manifest.remove(entry.id)
                result.removed.append(entry.path)
    else:
        tracked_roots = set(scan_dirs)
        for entry in manifest.all_entries():
            entry_root = Path(entry.path).parts[0] if Path(entry.path).parts else ""
            if entry_root in tracked_roots and entry.path not in seen_paths:
                manifest.remove(entry.id)
                result.removed.append(entry.path)

    return result
