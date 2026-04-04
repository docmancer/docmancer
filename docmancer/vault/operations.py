from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from docmancer.connectors.fetchers.pipeline.extraction import (
    extract_content,
    extract_metadata,
)
from docmancer.core.config import DocmancerConfig, VaultConfig
from docmancer.core.models import Document
from docmancer.core.html_utils import looks_like_html
from docmancer.vault.manifest import (
    ContentKind,
    IndexState,
    ManifestEntry,
    SourceType,
    VaultManifest,
)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_vault_config(vault_root: Path) -> DocmancerConfig:
    config_path = vault_root / "docmancer.yaml"
    if config_path.exists():
        return DocmancerConfig.from_yaml(config_path)
    return DocmancerConfig()


def _document_for_entry(vault_root: Path, entry: ManifestEntry) -> Document | None:
    file_path = vault_root / entry.path
    if not file_path.exists():
        return None
    suffix = file_path.suffix.lower()
    if suffix not in {".md", ".txt"}:
        return None
    content = file_path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    if suffix == ".md":
        metadata["format"] = "markdown"
        metadata["content_type"] = "text/markdown"
    return Document(source=entry.path, content=content, metadata=metadata)


def sync_vault_index(
    vault_root: Path,
    manifest: VaultManifest,
    *,
    added_paths: list[str] | None = None,
    updated_paths: list[str] | None = None,
    removed_paths: list[str] | None = None,
) -> None:
    added_paths = added_paths or []
    updated_paths = updated_paths or []
    removed_paths = removed_paths or []

    if not added_paths and not updated_paths and not removed_paths:
        return

    from docmancer.agent import DocmancerAgent

    agent = DocmancerAgent(config=_load_vault_config(vault_root))

    for source in [*removed_paths, *updated_paths]:
        agent.remove_source(source)

    docs_to_index: list[Document] = []
    entry_ids_to_mark_indexed: list[str] = []
    entry_ids_to_mark_failed: list[str] = []

    for path in [*added_paths, *updated_paths]:
        entry = manifest.get_by_path(path)
        if entry is None:
            continue
        document = _document_for_entry(vault_root, entry)
        if document is None:
            continue
        docs_to_index.append(document)
        entry_ids_to_mark_indexed.append(entry.id)

    if not docs_to_index:
        return

    try:
        agent.ingest_documents(docs_to_index, recreate=False)
    except Exception:
        entry_ids_to_mark_failed = entry_ids_to_mark_indexed[:]
        entry_ids_to_mark_indexed = []
        raise
    finally:
        for entry_id in entry_ids_to_mark_indexed:
            manifest.set_index_state(entry_id, IndexState.indexed)
        for entry_id in entry_ids_to_mark_failed:
            manifest.set_index_state(entry_id, IndexState.failed)


def init_vault(directory: Path) -> Path:
    """Scaffold a vault project. Returns path to created docmancer.yaml."""
    directory.mkdir(parents=True, exist_ok=True)
    for subdir in ("raw", "wiki", "outputs", ".docmancer"):
        (directory / subdir).mkdir(exist_ok=True)

    config_path = directory / "docmancer.yaml"
    if config_path.exists():
        return config_path

    config = DocmancerConfig(vault=VaultConfig())
    data = config.model_dump(exclude_none=False)
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    manifest_path = directory / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.save()

    # Auto-register in local vault registry
    try:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        vault_name = directory.name
        registry.register(vault_name, directory, config_path)
    except Exception:
        pass  # Registry is optional; don't fail init if it errors

    return config_path


def add_url(vault_root: Path, url: str) -> ManifestEntry:
    """Fetch a single web page into raw/ with provenance tracking."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        raw_html = resp.text

    if looks_like_html(raw_html):
        content = extract_content(raw_html, url=url)
        meta = extract_metadata(raw_html)
    else:
        content = raw_html
        meta = {}

    if not content or not content.strip():
        raise ValueError(f"No content could be extracted from {url}")

    title = meta.get("title") or ""
    parsed = urlparse(url)
    slug = parsed.path.strip("/").replace("/", "_") or "index"
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", slug)
    filename = f"{slug}.md"

    raw_dir = vault_root / "raw"
    raw_dir.mkdir(exist_ok=True)
    dest = raw_dir / filename

    counter = 1
    while dest.exists():
        dest = raw_dir / f"{slug}_{counter}.md"
        counter += 1

    now_iso = datetime.now(timezone.utc).isoformat()
    fm_title = title if title else slug.replace("_", " ").title()
    frontmatter = (
        f"---\n"
        f"title: {fm_title}\n"
        f"tags: []\n"
        f"sources: [{url}]\n"
        f"created: {now_iso}\n"
        f"updated: {now_iso}\n"
        f"---\n\n"
    )
    content_with_fm = frontmatter + content
    dest.write_text(content_with_fm, encoding="utf-8")

    content_hash_val = _content_hash(content_with_fm)
    relative_path = str(dest.relative_to(vault_root))

    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    entry = ManifestEntry(
        path=relative_path,
        kind=ContentKind.raw,
        source_type=SourceType.web,
        content_hash=content_hash_val,
        index_state=IndexState.pending,
        source_url=url,
        title=title if title else None,
        extra={"fetched_at": datetime.now(timezone.utc).isoformat()},
    )
    manifest.add(entry)
    try:
        sync_vault_index(vault_root, manifest, added_paths=[relative_path])
    finally:
        manifest.save()
    return manifest.get_by_id(entry.id) or entry


def inspect_entry(vault_root: Path, id_or_path: str) -> ManifestEntry | None:
    """Look up a manifest entry by ID or relative path."""
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    entry = manifest.get_by_id(id_or_path)
    if entry is not None:
        return entry
    return manifest.get_by_path(id_or_path)


def search_vault(vault_root: Path, query: str, kind: str | None = None, limit: int = 10) -> list[dict]:
    """Search vault manifest by keyword matching against path, title, tags.

    Returns list of dicts with: path, kind, source_type, title, score, preview.
    """
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    query_lower = query.lower()
    results = []

    for entry in manifest.all_entries():
        if kind and entry.kind.value != kind:
            continue

        # Simple keyword relevance scoring
        score = 0.0
        searchable = f"{entry.path} {entry.title or ''} {' '.join(entry.tags)}".lower()

        for term in query_lower.split():
            if term in searchable:
                score += 1.0
            if entry.title and term in entry.title.lower():
                score += 0.5  # boost title matches
            if term in entry.path.lower():
                score += 0.3  # boost path matches

        if score > 0:
            # Read preview from file
            preview = ""
            file_path = vault_root / entry.path
            if file_path.exists() and file_path.suffix.lower() in {".md", ".txt"}:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    preview = content[:200].replace("\n", " ").strip()
                except Exception:
                    pass

            results.append({
                "path": entry.path,
                "kind": entry.kind.value,
                "source_type": entry.source_type.value,
                "title": entry.title,
                "score": score,
                "preview": preview,
                "id": entry.id,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]
