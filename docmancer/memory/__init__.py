"""Local memory agent: index and recall coding-agent memory on this machine.

``MemoryAgent`` harvests harness memory and instruction files (Claude Code,
Codex, Cursor) through :mod:`docmancer.harness`, applies the privacy filter,
indexes everything into dedicated local SQLite + sqlite-vec files, and
answers queries through the real hybrid (lexical + dense) dispatcher.

Sync and recall do not upload anything. The memory index uses its own
collection, separate from any docs index.
"""
from __future__ import annotations

import logging
import os
import json
import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from docmancer.harness import default_home, harvest_all
from docmancer.harness.privacy import PrivacyFilter
from docmancer.memory.atomic import AtomicMemoryEntry, extract_atoms, merge_atoms
from docmancer.memory.hooks import DEFAULT_HOOK_THRESHOLD as DEFAULT_MEMORY_RELEVANCE_THRESHOLD
from docmancer.memory.records import MemoryRecord, MemoryRecordStore, normalize_memory_text

if TYPE_CHECKING:
    from docmancer.core.config import DocmancerConfig
    from docmancer.core.models import RetrievedChunk
    from docmancer.harness.base import MemoryEntry

logger = logging.getLogger(__name__)

_MEMORY_COLLECTION = "docmancer_memory"

# Bump when extraction logic changes so stale cached atoms are not reused.
_ATOM_CACHE_VERSION = 2
MEMORY_SCHEMA_VERSION = 2
_SCHEMA_META_TABLE = "docmancer_memory_meta"
_DEFAULT_SYNC_LOCK_TIMEOUT = 10.0


class SyncInProgressError(RuntimeError):
    """Raised when another Docmancer process is rebuilding the memory index."""


class SchemaMismatchError(RuntimeError):
    """Raised when the local memory index uses an incompatible projection."""


def sync_lock_path(db_path: str) -> Path:
    return Path(db_path).parent / "sync.lock"


def _read_schema_meta(db_path: str) -> dict[str, str]:
    if not Path(db_path).exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(f"SELECT key, value FROM {_SCHEMA_META_TABLE}").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


def _write_schema_meta(db_path: str, meta: dict[str, str]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_SCHEMA_META_TABLE} "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.executemany(
            f"INSERT INTO {_SCHEMA_META_TABLE} (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, str(value)) for key, value in meta.items()],
        )


def default_memory_db() -> str:
    home = os.getenv("DOCMANCER_HOME")
    base = Path(home) if home else Path.home() / ".docmancer"
    return str(base / "memory.db")


class MemoryAgent:
    def __init__(
        self,
        *,
        db_path: str | None = None,
        home: str | Path | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        config: "DocmancerConfig | None" = None,
    ) -> None:
        self.home = Path(home) if home is not None else default_home()
        self.db_path = str(db_path or os.getenv("DOCMANCER_MEMORY_DB") or default_memory_db())
        self.privacy = PrivacyFilter(include=list(include or []), exclude=list(exclude or []))
        self._last_sync_stats: dict = {}
        self.config = config or self._build_config()
        record_root = Path(self.db_path).parent
        self.records = MemoryRecordStore(record_root)
        self._extra_project_paths: set[str] = set()
        from docmancer.agent import DocmancerAgent

        # Lazy: constructing the store would create the SQLite file, so defer
        # it until an operation that actually reads or writes the index. This
        # keeps preview()/status()/dry-run from materialising an empty index.
        self._agent = DocmancerAgent(config=self.config, _lazy_init=True)

    def _build_config(self) -> "DocmancerConfig":
        from docmancer.core.config import DocmancerConfig, IndexConfig, VectorStoreConfig

        db = Path(self.db_path)
        db.parent.mkdir(parents=True, exist_ok=True)
        # Co-locate the sqlite-vec store next to the index so the two never
        # diverge across runs (a fresh vec store beside a populated index is
        # the silent "0 indexed vectors" trap).
        vec_db = str(db.with_name(db.stem + "-vec.db"))
        return DocmancerConfig(
            index=IndexConfig(db_path=str(db)),
            vector_store=VectorStoreConfig(
                provider="sqlite-vec",
                collection=_MEMORY_COLLECTION,
                options={"db_path": vec_db},
            ),
            discovery=self._load_user_discovery(),
        )

    def _load_user_discovery(self):
        """Read only the ``discovery`` block from the user's docmancer.yaml.

        The memory index keeps its own isolated config, but discovery tuning
        (disabled harnesses, custom paths) should still take effect from the
        user's config file. Looked up under ``<home>/.docmancer/docmancer.yaml``
        so it stays test-isolated. Anything missing falls back to defaults.
        """
        from docmancer.core.config import DiscoveryConfig

        try:
            import yaml as _yaml

            cfg_path = self.home / ".docmancer" / "docmancer.yaml"
            if not cfg_path.is_file():
                return DiscoveryConfig()
            data = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            block = data.get("discovery")
            return DiscoveryConfig(**block) if isinstance(block, dict) else DiscoveryConfig()
        except Exception:  # noqa: BLE001 - never let config parsing break discovery
            return DiscoveryConfig()

    # ------------------------------------------------------------------
    # Harvest / index
    # ------------------------------------------------------------------

    def preview(self) -> list["MemoryEntry"]:
        """Return the entries that WOULD be indexed (post-filter), no writes."""
        return [e for e in harvest_all(self.home, config=self.config) if self.privacy.allows(e)]

    def atom_preview(self) -> list[AtomicMemoryEntry]:
        """Return atomic records that WOULD be indexed, no writes."""
        entries = self.preview()
        atoms = self._atoms_from_entries(entries, merge=False)
        atoms.extend(record.to_atom() for record in self.records.records(project_paths=self._project_paths(entries)))
        atoms = [atom for atom in atoms if not self.records.is_forgotten(atom)]
        return self._merge_all(atoms)

    def sync(self, *, recreate: bool = False, progress_callback=None) -> int:
        """Harvest, filter, redact, extract atoms, and index them."""
        progress = progress_callback or (lambda _stage, _detail="": None)
        progress("lock", "Waiting for the local sync lock")
        with self._sync_lock():
            progress("harvest", "Discovering memory and instruction files")
            entries = self.preview()
            progress("redact", f"Redacting and extracting {len(entries):,} source file(s)")
            cleaned_entries = [self.privacy.clean(e) for e in entries]
            atoms = self._atoms_from_entries_cached(cleaned_entries, recreate=recreate, merge=False)
            atoms.extend(
                record.to_atom()
                for record in self.records.records(project_paths=self._project_paths(cleaned_entries))
            )
            atoms = [atom for atom in atoms if not self.records.is_forgotten(atom)]
            progress("merge", f"Deduplicating {len(atoms):,} extracted memory atoms")
            atoms = self._merge_all(atoms)
            self._last_sync_stats["atoms_after_merge"] = len(atoms)
            # Memory is a dedicated index, so every sync rebuilds the atom projection
            # from harvested sources. This prevents stale atom records after source
            # files are edited or removed.
            self._drop_vectors()
            self._clear_embedding_bookkeeping()
            progress("index", f"Rebuilding the local search index with {len(atoms):,} memory atoms")
            if not atoms:
                self._agent.store.add_documents([], recreate=True)
            else:
                docs = [atom.to_document() for atom in atoms]
                self._agent.ingest_documents(docs, recreate=True, with_vectors=True)
            progress("finalize", "Writing provenance and schema metadata")
            self._write_source_snapshot(cleaned_entries, atoms)
            self._stamp_schema()
            progress("done", f"Indexed {len(atoms):,} memory atoms")
            return len(atoms)

    @contextmanager
    def _sync_lock(self):
        from filelock import FileLock, Timeout

        timeout = float(os.getenv("DOCMANCER_SYNC_LOCK_TIMEOUT", _DEFAULT_SYNC_LOCK_TIMEOUT))
        lock = FileLock(str(sync_lock_path(self.db_path)), timeout=timeout)
        try:
            lock.acquire()
        except Timeout as exc:
            raise SyncInProgressError(
                "another Docmancer sync is in progress; wait for it to finish, then retry"
            ) from exc
        try:
            yield
        finally:
            lock.release()

    def _stamp_schema(self) -> None:
        emb = self.config.embeddings
        _write_schema_meta(
            self.db_path,
            {
                "schema_version": str(MEMORY_SCHEMA_VERSION),
                "memory_layer": "atomic",
                "embeddings_provider": str(emb.provider or ""),
                "embeddings_model": str(emb.model or ""),
                "embeddings_dim": str(emb.dimensions or 0),
            },
        )

    def validate_schema(self) -> None:
        meta = _read_schema_meta(self.db_path)
        if not meta:
            return
        if meta.get("schema_version") != str(MEMORY_SCHEMA_VERSION) or meta.get("memory_layer") != "atomic":
            raise SchemaMismatchError(
                "this memory index predates memory atoms; run `docmancer memory sync --recreate`"
            )

    def _atoms_from_entries(
        self,
        entries: list["MemoryEntry"],
        *,
        already_clean: bool = False,
        merge: bool = True,
    ) -> list[AtomicMemoryEntry]:
        atoms: list[AtomicMemoryEntry] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in entries:
            clean_entry = entry if already_clean else self.privacy.clean(entry)
            for atom in extract_atoms(clean_entry):
                key = (atom.scope, atom.source_path, atom.content_hash)
                if key in seen:
                    continue
                seen.add(key)
                atoms.append(atom)
        if merge and len(atoms) > 1:
            embed = self._embed_fn()
            if embed is not None:
                atoms = merge_atoms(atoms, embed_texts=embed)
        return atoms

    def _embed_fn(self):
        """Return the local embedding function, or None if unavailable.

        Cross-agent merge needs vectors; if the embeddings backend cannot load
        we skip merge rather than fail the sync.
        """
        try:
            from docmancer.embeddings import get_embeddings_provider

            provider = get_embeddings_provider(self.config.embeddings)
            return provider.embed
        except Exception as exc:  # noqa: BLE001 - degrade to unmerged atoms
            logger.debug("merge embeddings unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Incremental extraction cache
    # ------------------------------------------------------------------

    def _atom_cache_path(self) -> Path:
        db = Path(self.db_path)
        return db.with_name(db.stem + "-atom-cache.json")

    def _load_atom_cache(self) -> dict[str, list[dict]]:
        path = self._atom_cache_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken cache just means full re-extract
            return {}
        if not isinstance(data, dict) or data.get("version") != _ATOM_CACHE_VERSION:
            return {}
        sources = data.get("sources")
        return sources if isinstance(sources, dict) else {}

    def _save_atom_cache(self, cache: dict[str, list[dict]]) -> None:
        path = self._atom_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _ATOM_CACHE_VERSION, "sources": cache}
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - cache is best effort
            logger.debug("could not write atom cache: %s", exc)

    @staticmethod
    def _cache_key(path: str, content: str) -> str:
        digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
        return f"{path}\n{digest}"

    def _atoms_from_entries_cached(
        self,
        entries: list["MemoryEntry"],
        *,
        recreate: bool = False,
        merge: bool = True,
    ) -> list[AtomicMemoryEntry]:
        """Extract atoms, reusing cached per-source atoms for unchanged files.

        Only sources whose content changed since the last sync are re-extracted;
        unchanged sources reuse their cached atoms keyed by content hash. The
        rebuilt cache holds only sources present this run, so deleted or edited
        files drop out. Cross-agent merge still runs globally over the combined
        atom set, since a merge cluster can span several sources.
        """
        old_cache: dict[str, list[dict]] = {} if recreate else self._load_atom_cache()
        new_cache: dict[str, list[dict]] = {}
        raw_atoms: list[AtomicMemoryEntry] = []
        seen: set[tuple[str, str, str]] = set()
        reused_sources = 0
        extracted_sources = 0
        for entry in entries:  # entries are already privacy-cleaned
            key = self._cache_key(entry.path, entry.content or "")
            cached = old_cache.get(key)
            if cached is not None:
                entry_atoms = [AtomicMemoryEntry(**record) for record in cached]
                reused_sources += 1
            else:
                entry_atoms = extract_atoms(entry)
                extracted_sources += 1
            new_cache[key] = [asdict(atom) for atom in entry_atoms]
            for atom in entry_atoms:
                dedupe = (atom.scope, atom.source_path, atom.content_hash)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                raw_atoms.append(atom)

        self._save_atom_cache(new_cache)

        pre_merge = len(raw_atoms)
        if merge and pre_merge > 1:
            embed = self._embed_fn()
            if embed is not None:
                raw_atoms = merge_atoms(raw_atoms, embed_texts=embed)
        self._last_sync_stats = {
            "sources_total": len(entries),
            "sources_reused": reused_sources,
            "sources_extracted": extracted_sources,
            "atoms_before_merge": pre_merge,
            "atoms_after_merge": len(raw_atoms),
            "duplicates_merged": pre_merge - len(raw_atoms),
            "cross_agent_atoms": sum(1 for atom in raw_atoms if atom.source_count > 1),
        }
        return raw_atoms

    def _merge_all(self, atoms: list[AtomicMemoryEntry]) -> list[AtomicMemoryEntry]:
        if len(atoms) <= 1:
            return atoms
        embed = self._embed_fn()
        return merge_atoms(atoms, embed_texts=embed) if embed is not None else atoms

    def index_records(self, records: list[MemoryRecord]) -> int:
        """Incrementally index newly persisted records without harvesting all sources."""
        atoms = [record.to_atom() for record in records]
        atoms = [atom for atom in atoms if not self.records.is_forgotten(atom)]
        if not atoms:
            return 0
        with self._sync_lock():
            self._agent.ingest_documents(
                [atom.to_document() for atom in atoms],
                recreate=False,
                with_vectors=True,
            )
            self._stamp_schema()
        return len(atoms)

    def _project_paths(self, entries: list["MemoryEntry"] | None = None) -> list[str]:
        paths: set[str] = set(self._extra_project_paths)
        for entry in entries or []:
            prefix, _, value = (entry.scope or "").partition(":")
            if prefix == "project" and value:
                paths.add(str(Path(value).expanduser().resolve()))
        cwd = Path.cwd().resolve()
        for candidate in [cwd, *cwd.parents]:
            if (candidate / ".git").exists():
                paths.add(str(candidate))
                break
        return sorted(paths)

    def last_sync_stats(self) -> dict:
        return dict(getattr(self, "_last_sync_stats", {}) or {})

    def _drop_vectors(self) -> None:
        """Best-effort removal of the memory vector collection and its metadata."""
        collection = self._agent._vector_collection_name()
        try:
            from docmancer.stores.base import get_vector_store

            vs = get_vector_store(
                self.config.vector_store, embeddings_dim=self.config.embeddings.dimensions
            )
            try:
                vs.delete_collection(collection)
            except Exception:  # noqa: BLE001 - missing collection is success, not failure
                pass
            close = getattr(vs, "close", None)
            if callable(close):
                close()
        except Exception as exc:  # noqa: BLE001 - vector store may be unavailable
            logger.debug("could not drop memory vectors: %s", exc)
        try:
            from docmancer.core import index_meta

            index_meta.drop(collection)
        except Exception:  # noqa: BLE001
            pass

    def _clear_embedding_bookkeeping(self) -> None:
        """Clear embedding_upserts for the memory collection, best effort."""
        try:
            collection = self._agent._vector_collection_name()
            self._agent.store.clear_embedding_upserts(collection)
        except Exception as exc:  # noqa: BLE001 - bookkeeping cleanup is best effort
            logger.debug("could not clear embedding bookkeeping: %s", exc)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        *,
        limit: int | None = None,
        budget: int | None = None,
        mode: str = "hybrid",
        allow_degraded: bool = True,
        project_path: str | Path | None = None,
        scope: str | None = None,
        min_score: float | None = DEFAULT_MEMORY_RELEVANCE_THRESHOLD,
    ) -> list["RetrievedChunk"]:
        from docmancer.retrieval.dispatch import RetrievalDispatcher

        self.validate_schema()

        vector_store, provider = self._build_retrieval_backends()
        dispatcher = RetrievalDispatcher(
            store=self._agent.store,
            config=self.config,
            vector_store=vector_store,
            provider=provider,
            collection=self._agent._vector_collection_name(),
        )
        requested_limit = limit or self.config.query.default_limit
        # Retrieve a wider pool before applying confidence and project filters.
        # RRF orders candidates, while the final public score measures whether
        # they are relevant enough to show at all.
        search_limit = requested_limit * 4
        result = dispatcher.run(text, mode=mode, limit=search_limit, budget=budget, allow_degraded=allow_degraded)
        chunks = result.chunks
        if min_score is not None:
            chunks = [chunk for chunk in chunks if float(chunk.score or 0.0) >= min_score]
        if scope:
            chunks = [chunk for chunk in chunks if str((chunk.metadata or {}).get("scope_kind") or (chunk.metadata or {}).get("scope", "").split(":", 1)[0]) == scope]
        if project_path:
            project = Path(project_path).expanduser().resolve()

            def bucket(chunk):
                meta = chunk.metadata or {}
                kind = str(meta.get("scope_kind") or str(meta.get("scope", "")).split(":", 1)[0])
                raw = meta.get("project_path")
                if kind in {"project", "team"} and raw:
                    try:
                        memory_project = Path(str(raw)).expanduser().resolve()
                        if project == memory_project or memory_project in project.parents:
                            return 0 if kind == "project" else 1
                    except OSError:
                        pass
                    return 9
                return 2 if kind == "global" else 9

            chunks = [chunk for chunk in chunks if bucket(chunk) < 9]
            chunks.sort(key=lambda chunk: (bucket(chunk), -float(chunk.score or 0.0)))
        else:
            chunks.sort(key=lambda chunk: -float(chunk.score or 0.0))

        # Distinct durable records stay independently addressable, but an
        # equivalent record should not consume another recall result.
        unique_chunks = []
        seen_memories: set[tuple[str, str]] = set()
        for chunk in chunks:
            meta = chunk.metadata or {}
            key = (str(meta.get("scope") or ""), normalize_memory_text(chunk.text))
            if key in seen_memories:
                continue
            seen_memories.add(key)
            unique_chunks.append(chunk)
        return unique_chunks[:requested_limit]

    def _build_retrieval_backends(self):
        try:
            from docmancer.embeddings import get_embeddings_provider
            from docmancer.stores.base import get_vector_store

            vector_store = get_vector_store(
                self.config.vector_store, embeddings_dim=self.config.embeddings.dimensions
            )
            provider = get_embeddings_provider(self.config.embeddings)
            return vector_store, provider
        except Exception as exc:  # noqa: BLE001 - degrade to lexical when backends are unavailable
            logger.debug("memory retrieval backends unavailable: %s", exc)
            return None, None

    # ------------------------------------------------------------------
    # Status / clear
    # ------------------------------------------------------------------

    def status(self) -> dict:
        # Do not construct the store when the index does not exist; that would
        # create an empty SQLite file and make `status` lie about existence.
        if not Path(self.db_path).exists():
            return {"db_path": self.db_path, "sources": 0, "atoms": 0, "sections": 0}
        try:
            stats = self._agent.collection_stats()
        except Exception:  # noqa: BLE001
            stats = {}
        rows = self.sources()
        return {
            "db_path": self.db_path,
            "sources": len(rows),
            "atoms": stats.get("sections_count", 0),
            "sections": stats.get("sections_count", 0),
        }

    def sources(self, *, live_preview: bool = False) -> list[dict]:
        """Return source-file provenance rows with memory atom counts.

        ``live_preview=True`` re-harvests (post-privacy, no writes) to show what
        WOULD index; otherwise it reads the stored atomic index. Rows are sorted
        by agent, then scope, then path.
        """
        rows: list[dict] = []
        if live_preview or not Path(self.db_path).exists():
            for e in [self.privacy.clean(item) for item in self.preview()]:
                atoms = extract_atoms(e)
                rows.append(
                    {
                        "agent": e.harness,
                        "type": e.extra.get("kind", "agent-memory"),
                        "scope": e.scope,
                        "title": e.title,
                        "path": e.path,
                        "chars": len(e.content or ""),
                        "atoms": len(atoms),
                    }
                )
        else:
            try:
                provenance = self._agent.store.list_source_provenance()
            except Exception:  # noqa: BLE001
                provenance = []
            grouped: dict[str, dict] = {}
            for item in provenance:
                meta = item.get("metadata", {})
                path = meta.get("source_path", item["source"].split(":", 1)[-1])
                row = grouped.setdefault(
                    str(path),
                    {
                        "agent": meta.get("harness", item["source"].split(":", 1)[0]),
                        "type": meta.get("kind", "agent-memory"),
                        "scope": meta.get("scope", ""),
                        "title": meta.get("title", ""),
                        "path": str(path),
                        "chars": 0,
                        "atoms": 0,
                    },
                )
                row["chars"] = max(int(row["chars"] or 0), int(meta.get("source_chars") or item.get("chars") or 0))
                row["atoms"] += 1
            rows = list(grouped.values())
        rows.sort(key=lambda r: (r["agent"], r["scope"], r["path"]))
        return rows

    def indexed_atoms(self, *, limit: int | None = None) -> list[AtomicMemoryEntry]:
        """Read atomic records from the stored index."""
        if not Path(self.db_path).exists():
            return []
        try:
            provenance = self._agent.store.list_source_provenance()
        except Exception:  # noqa: BLE001
            return []
        atoms: list[AtomicMemoryEntry] = []
        for item in provenance:
            atom = self._atom_from_provenance(item)
            if atom is not None:
                atoms.append(atom)
        atoms.sort(key=_atom_sort_key)
        if limit is not None:
            atoms = atoms[: max(0, limit)]
        return atoms

    def _atom_from_provenance(self, item: dict) -> AtomicMemoryEntry | None:
        meta = item.get("metadata", {}) or {}
        if meta.get("memory_layer") != "atomic":
            return None
        text = str(item.get("content") or "")
        return AtomicMemoryEntry(
            atom_id=str(meta.get("atom_id") or item.get("source") or ""),
            text=text,
            type=str(meta.get("memory_type") or "fact"),
            harness=str(meta.get("harness") or ""),
            kind=str(meta.get("kind") or "agent-memory"),
            scope=str(meta.get("scope") or ""),
            source_path=str(meta.get("source_path") or ""),
            source_title=str(meta.get("title") or ""),
            line_start=int(meta.get("line_start") or 0),
            line_end=int(meta.get("line_end") or 0),
            source_hash=str(meta.get("source_hash") or ""),
            content_hash=str(meta.get("content_hash") or ""),
            source_chars=int(meta.get("source_chars") or 0),
            confidence=float(meta.get("confidence") or 1.0),
            tags=[str(tag) for tag in meta.get("tags", []) if tag],
            status=str(meta.get("status") or "active"),
            timestamp=meta.get("timestamp"),
            source_count=int(meta.get("source_count") or 1),
            merged_from=[str(p) for p in meta.get("merged_from", []) if p],
            record_id=meta.get("record_id"),
            origin=str(meta.get("origin") or "harvested"),
            scope_kind=str(meta.get("scope_kind") or str(meta.get("scope") or "unknown").split(":", 1)[0]),
            project_path=meta.get("project_path"),
        )

    # ------------------------------------------------------------------
    # Durable record operations
    # ------------------------------------------------------------------

    def add_record(
        self,
        text: str,
        *,
        scope_kind: str = "global",
        project_path: str | Path | None = None,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        origin: str = "manual",
        session_id: str | None = None,
        promoted_from: str | None = None,
        sync_index: bool = True,
    ) -> tuple[MemoryRecord, bool]:
        if scope_kind == "team":
            project = Path(project_path or Path.cwd()).expanduser().resolve()
            if not (project / ".git").exists():
                raise ValueError("team memory requires an existing Git repository root")
            project_path = project
            self._extra_project_paths.add(str(project))
        elif scope_kind == "project":
            project_path = Path(project_path or Path.cwd()).expanduser().resolve()
            self._extra_project_paths.add(str(project_path))
        existing = self.records.find_equivalent(
            text,
            scope_kind=scope_kind,
            project_path=project_path,
        )
        if existing is not None:
            raise ValueError(
                "Equivalent memory already exists in this scope. "
                f"Memory ID: {existing.record_id[:12]}"
            )
        record = self.records.add(
            text,
            scope_kind=scope_kind,
            project_path=project_path,
            memory_type=memory_type,
            tags=tags,
            origin=origin,
            session_id=session_id,
            promoted_from=promoted_from,
        )
        indexed = False
        if sync_index:
            try:
                self.index_records([record])
                indexed = True
            except SyncInProgressError:
                indexed = False
        return record, indexed

    def find_atom(self, identifier: str) -> AtomicMemoryEntry | None:
        matches = [
            atom
            for atom in self.indexed_atoms()
            if atom.atom_id.startswith(identifier) or (atom.record_id or "").startswith(identifier)
        ]
        return matches[0] if len(matches) == 1 else None

    def forget(self, identifier: str) -> AtomicMemoryEntry:
        atom = self.find_atom(identifier)
        if atom is None:
            raise ValueError("memory id is missing or ambiguous")
        self.records.add_tombstone(atom)
        if atom.record_id:
            roots = self._project_paths()
            if atom.project_path:
                roots.append(atom.project_path)
                self._extra_project_paths.add(str(Path(atom.project_path).expanduser().resolve()))
            record = self.records.find_record(atom.record_id, project_paths=roots)
            if record is not None:
                self.records.delete_record(record)
        self.sync()
        return atom

    def promote(self, identifier: str, *, project_path: str | Path | None = None) -> tuple[MemoryRecord, bool]:
        atom = self.find_atom(identifier)
        if atom is None:
            raise ValueError("memory id is missing or ambiguous")
        return self.add_record(
            atom.text,
            scope_kind="team",
            project_path=project_path or Path.cwd(),
            memory_type=atom.type,
            tags=atom.tags,
            origin="promoted",
            promoted_from=atom.record_id or atom.atom_id,
        )

    def memory_paths(self) -> list[Path]:
        db = Path(self.db_path)
        return [
            db,
            db.with_name(db.stem + "-vec.db"),
            self._source_snapshot_path(),
            self._atom_cache_path(),
        ]

    def clear(self) -> list[Path]:
        """Delete the memory index files. Returns the paths removed."""
        self._close()
        removed: list[Path] = []
        for path in self.memory_paths():
            for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
                if candidate.exists():
                    try:
                        candidate.unlink()
                        if candidate == path:
                            removed.append(candidate)
                    except OSError as exc:
                        logger.debug("could not remove %s: %s", candidate, exc)
        return removed

    def _close(self) -> None:
        store = getattr(self._agent, "_store", None)
        close = getattr(store, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass

    def _source_snapshot_path(self) -> Path:
        db = Path(self.db_path)
        return db.with_name(db.stem + "-sources.json")

    def _write_source_snapshot(
        self,
        entries: list["MemoryEntry"],
        atoms: list[AtomicMemoryEntry],
    ) -> None:
        counts: dict[str, int] = {}
        for atom in atoms:
            counts[atom.source_path] = counts.get(atom.source_path, 0) + 1
        payload = {
            "sources": [
                {
                    "harness": entry.harness,
                    "scope": entry.scope,
                    "title": entry.title,
                    "path": entry.path,
                    "kind": entry.extra.get("kind", "agent-memory"),
                    "content": entry.content,
                    "chars": len(entry.content or ""),
                    "atoms": counts.get(entry.path, 0),
                }
                for entry in entries
            ],
            "atom_count": len(atoms),
        }
        path = self._source_snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _atom_sort_key(atom: AtomicMemoryEntry):
    priority = {
        "decision": 0,
        "preference": 1,
        "constraint": 2,
        "workflow": 3,
        "command": 4,
        "warning": 5,
        "fact": 6,
        "status": 7,
    }
    return (priority.get(atom.type, 9), atom.scope, atom.source_path, atom.line_start, atom.text)


__all__ = [
    "MemoryAgent",
    "default_memory_db",
    "MEMORY_SCHEMA_VERSION",
    "SchemaMismatchError",
    "SyncInProgressError",
    "sync_lock_path",
]
