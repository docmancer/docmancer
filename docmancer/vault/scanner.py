from __future__ import annotations

import hashlib
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


def _sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_kind(relative_path: str) -> ContentKind:
    first_part = relative_path.split("/")[0] if "/" in relative_path else ""
    return _KIND_BY_DIR.get(first_part, ContentKind.asset)


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

    sources = frontmatter.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                metadata["source_url"] = source
                break

    return metadata


@dataclass
class ScanResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0


def scan_vault(vault_root: Path, manifest: VaultManifest, scan_dirs: list[str]) -> ScanResult:
    """Walk scan_dirs under vault_root, reconcile with manifest, return summary."""
    result = ScanResult()
    seen_paths: set[str] = set()

    for dir_name in scan_dirs:
        scan_path = vault_root / dir_name
        if not scan_path.is_dir():
            continue
        for file_path in sorted(scan_path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                continue
            relative = str(file_path.relative_to(vault_root))
            seen_paths.add(relative)
            content_hash = _sha256(file_path)
            existing = manifest.get_by_path(relative)
            metadata = _manifest_metadata_for_file(file_path)

            if existing is None:
                entry = ManifestEntry(
                    path=relative,
                    kind=_infer_kind(relative),
                    source_type=_infer_source_type(file_path),
                    content_hash=content_hash,
                    index_state=IndexState.pending,
                    title=metadata.get("title"),
                    tags=metadata.get("tags", []),
                    source_url=metadata.get("source_url"),
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
                    }
                )
                result.updated.append(relative)
            else:
                result.unchanged += 1

    # Remove entries whose files no longer exist on disk
    tracked_roots = set(scan_dirs)
    for entry in manifest.all_entries():
        entry_root = Path(entry.path).parts[0] if Path(entry.path).parts else ""
        if entry_root in tracked_roots and entry.path not in seen_paths:
            manifest.remove(entry.id)
            result.removed.append(entry.path)

    return result
