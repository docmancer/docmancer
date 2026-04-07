from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

logger = logging.getLogger(__name__)

_USER_AGENT = "docmancer/1.0 (+https://github.com/docmancer/docmancer)"
_FETCH_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_RETRYABLE_STATUSES = {403, 429, 503}

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


def _find_entry_by_source_url(manifest: VaultManifest, url: str) -> ManifestEntry | None:
    for entry in manifest.all_entries():
        if entry.source_url == url or entry.canonical_source_url == url:
            return entry
    return None


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
    metadata: dict[str, str | int | list[str]] = {
        "kind": entry.kind.value,
        "source_type": entry.source_type.value,
        "path": entry.path,
        "canonical_source": entry.canonical_source_url or "",
        "content_hash": entry.content_hash,
        "manifest_id": entry.id,
        "tags": list(entry.tags),
        "parent_ref": entry.parent_ref or "",
    }
    if suffix == ".md":
        content = file_path.read_text(encoding="utf-8")
        metadata["format"] = "markdown"
        metadata["content_type"] = "text/markdown"
        return Document(source=entry.path, content=content, metadata=metadata)
    if suffix == ".txt":
        content = file_path.read_text(encoding="utf-8")
        metadata["format"] = "text"
        metadata["content_type"] = "text/plain"
        return Document(source=entry.path, content=content, metadata=metadata)
    if suffix == ".pdf":
        content, pdf_metadata = _extract_pdf_content(file_path)
        if not content:
            return None
        metadata.update(pdf_metadata)
        metadata["format"] = "pdf"
        metadata["content_type"] = "application/pdf"
        return Document(source=entry.path, content=content, metadata=metadata)
    return None


def _extract_pdf_content(file_path: Path) -> tuple[str, dict[str, int]]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(file_path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        if pages:
            return "\n\n".join(pages), {"page_count": len(reader.pages)}
    except Exception:
        pass

    raw_text = file_path.read_bytes().decode("latin-1", errors="ignore")
    normalized = re.sub(r"\s+", " ", raw_text).strip()
    if any(ch.isalpha() for ch in normalized):
        return normalized, {}
    return "", {}


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
            if entry.source_type == SourceType.pdf:
                entry_ids_to_mark_failed.append(entry.id)
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


def init_vault(directory: Path, name: str | None = None) -> Path:
    """Scaffold a vault project. Returns path to created docmancer.yaml.

    If *name* is provided it is used as the vault's registry name,
    otherwise the directory basename is used.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for subdir in ("raw", "wiki", "outputs", "assets", ".docmancer"):
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
        vault_name = name or directory.resolve().name
        registry.register(vault_name, directory, config_path)
    except Exception:
        pass  # Registry is optional; don't fail init if it errors

    return config_path


def init_obsidian_vault(directory: Path, name: str | None = None) -> Path:
    """Scaffold a vault inside an existing Obsidian vault directory.

    Unlike *init_vault*, this does **not** create ``raw/``, ``wiki/``,
    ``outputs/`` or ``assets/`` directories.  Instead it configures
    ``scan_dirs: ["."]`` so the entire Obsidian vault is indexed.

    Returns path to the created ``docmancer.yaml``.
    """
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".docmancer").mkdir(exist_ok=True)

    config_path = directory / "docmancer.yaml"
    if config_path.exists():
        return config_path

    vault_cfg = VaultConfig(
        scan_dirs=["."],
        scan_cooldown_seconds=30,
    )
    config = DocmancerConfig(vault=vault_cfg)
    data = config.model_dump(exclude_none=False)
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    manifest_path = directory / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.save()

    # Hide .docmancer from Obsidian's search / graph
    from docmancer.vault.obsidian import update_obsidian_ignore
    update_obsidian_ignore(directory)

    # Auto-register in local vault registry
    try:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        vault_name = name or directory.name
        registry.register(vault_name, directory, config_path)
    except Exception:
        pass  # Registry is optional

    return config_path


_SKIP_DIRS = {"raw", "wiki", "outputs", "assets", ".docmancer"}


def open_vault(directory: Path, name: str | None = None) -> tuple[Path, int]:
    """Adopt an existing folder as a vault by symlinking files into raw/.

    Creates the vault scaffold (via *init_vault*), discovers supported files
    outside the managed directories, and creates relative symlinks inside
    ``raw/`` that preserve the original directory structure.

    Returns ``(config_path, symlinks_created)``.
    """
    from docmancer.vault.scanner import _SUPPORTED_EXTENSIONS

    directory = directory.resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory does not exist: {directory}")

    config_path = init_vault(directory, name=name)
    raw_dir = directory / "raw"

    symlinks_created = 0
    for file_path in sorted(directory.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue

        # Skip dot-directories and docmancer-managed directories
        try:
            relative = file_path.relative_to(directory)
        except ValueError:
            continue
        parts = relative.parts
        if any(p.startswith(".") for p in parts):
            continue
        if parts[0] in _SKIP_DIRS:
            continue

        # Build the symlink target inside raw/
        symlink_path = raw_dir / relative
        if symlink_path.exists() or symlink_path.is_symlink():
            continue

        symlink_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute a relative path from the symlink location back to the original
        target = Path("../" * len(relative.parts)) / relative
        symlink_path.symlink_to(target)
        symlinks_created += 1

    return config_path, symlinks_created


def _fetch_url(url: str, browser: bool = False) -> str:
    """Fetch URL with progressive fallback: headers -> retry -> Playwright."""
    with httpx.Client(timeout=30, follow_redirects=True, headers=_FETCH_HEADERS) as client:
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.text
        first_status = resp.status_code

    # Retry once for retryable statuses (some WAFs unblock on second attempt)
    if first_status in _RETRYABLE_STATUSES:
        logger.debug("GET %s returned %d, retrying", url, first_status)
        with httpx.Client(timeout=30, follow_redirects=True, headers=_FETCH_HEADERS) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text

    # Browser fallback for retryable statuses when --browser is set
    if browser and first_status in _RETRYABLE_STATUSES:
        logger.debug("Retrying %s via Playwright browser renderer", url)
        try:
            from docmancer.connectors.fetchers.pipeline.browser import BrowserRenderer
            renderer = BrowserRenderer()
            html = renderer.render(url)
            if html:
                return html
        except ImportError:
            raise ImportError(
                "Playwright is not installed. Install it with:\n"
                "  pip install docmancer[browser]\n"
                "  playwright install chromium"
            )

    hint = ""
    if not browser and first_status == 403:
        hint = " This site may require JavaScript rendering. Try: docmancer vault add-url --browser <url>"
    msg = f"Client error '{first_status}' for url '{url}'.{hint}"
    raise httpx.HTTPStatusError(message=msg, request=resp.request, response=resp)


def add_url(vault_root: Path, url: str, browser: bool = False) -> ManifestEntry:
    """Fetch a single web page into raw/ with provenance tracking."""
    raw_html = _fetch_url(url, browser=browser)

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
    content_hash_val = _content_hash(content_with_fm)

    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    existing_entry = _find_entry_by_source_url(manifest, url)

    if existing_entry is not None:
        existing_path = vault_root / existing_entry.path
        if existing_path.exists() and existing_path != dest:
            existing_path.unlink()
        dest = vault_root / existing_entry.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        relative_path = existing_entry.path
    else:
        relative_path = str(dest.relative_to(vault_root))

    dest.write_text(content_with_fm, encoding="utf-8")

    if existing_entry is not None:
        entry = existing_entry.model_copy(
            update={
                "path": relative_path,
                "kind": ContentKind.raw,
                "source_type": SourceType.web,
                "content_hash": content_hash_val,
                "index_state": IndexState.pending,
                "source_url": url,
                "canonical_source_url": url,
                "title": title if title else None,
                "fetched_at": now_iso,
                "updated_at": now_iso,
                "outbound_refs": [],
                "extra": {"fetched_at": now_iso},
            }
        )
        manifest._entries[entry.id] = entry
        updated_paths = [relative_path]
        added_paths: list[str] = []
    else:
        entry = ManifestEntry(
            path=relative_path,
            kind=ContentKind.raw,
            source_type=SourceType.web,
            content_hash=content_hash_val,
            index_state=IndexState.pending,
            source_url=url,
            canonical_source_url=url,
            title=title if title else None,
            created_at=now_iso,
            fetched_at=now_iso,
            outbound_refs=[],
            extra={"fetched_at": now_iso},
        )
        manifest.add(entry)
        updated_paths = []
        added_paths = [relative_path]
    try:
        sync_vault_index(vault_root, manifest, added_paths=added_paths, updated_paths=updated_paths)
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


def cross_vault_query(
    query_text: str,
    vault_names: list[str] | None = None,
    tag: str | None = None,
    limit: int = 10,
) -> list:
    """Query across multiple registered vaults, merging results by score.

    If *vault_names* is None and *tag* is None, queries all registered vaults.
    If *tag* is provided, only vaults with that tag are queried.
    Populates vault_name on each RetrievedChunk for provenance.
    """
    from docmancer.agent import DocmancerAgent
    from docmancer.core.config import DocmancerConfig
    from docmancer.vault.registry import VaultRegistry

    registry = VaultRegistry()
    if tag:
        all_vaults = registry.list_vaults_by_tag(tag)
    else:
        all_vaults = registry.list_vaults()

    if vault_names:
        all_vaults = [v for v in all_vaults if v["name"] in vault_names]

    if not all_vaults:
        return []

    all_results = []
    for vault in all_vaults:
        vault_root = Path(vault["root_path"])
        config_path = vault_root / "docmancer.yaml"
        if not config_path.exists():
            continue
        try:
            config = DocmancerConfig.from_yaml(config_path)
            agent = DocmancerAgent(config=config)
            results = agent.query(query_text, limit=limit)
            for chunk in results:
                chunk.vault_name = vault["name"]
            all_results.extend(results)
        except Exception:
            continue

    all_results.sort(key=lambda c: c.score, reverse=True)
    return all_results[:limit]


def search_vault(vault_root: Path, query: str, kind: str | None = None, limit: int = 10) -> list[dict]:
    """Search vault manifest by keyword matching against path, title, tags.

    Returns list of dicts with: path, kind, source_type, title, score, preview.
    """
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    query_lower = query.lower()
    terms = [term for term in query_lower.split() if term]
    results = []

    for entry in manifest.all_entries():
        if kind and entry.kind.value != kind:
            continue

        # Simple keyword relevance scoring
        score = 0.0
        searchable = f"{entry.path} {entry.title or ''} {' '.join(entry.tags)}".lower()
        body = ""
        preview = ""
        file_path = vault_root / entry.path
        if file_path.exists() and file_path.suffix.lower() in {".md", ".txt", ".pdf"}:
            try:
                raw_content = file_path.read_text(encoding="utf-8", errors="ignore")
                body = raw_content.lower()
                preview = raw_content[:200].replace("\n", " ").strip()
            except Exception:
                body = ""

        for term in terms:
            if term in searchable:
                score += 1.0
            if entry.title and term in entry.title.lower():
                score += 0.5  # boost title matches
            if term in entry.path.lower():
                score += 0.3  # boost path matches
            if body and term in body:
                score += 0.2

        if score > 0:
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
