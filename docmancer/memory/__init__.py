"""Local memory agent: index and recall coding-agent memory on this machine.

``MemoryAgent`` harvests harness memory and instruction files (Claude Code,
Codex, Cursor) through :mod:`docmancer.harness`, applies the privacy filter,
indexes everything into dedicated local SQLite + sqlite-vec files, and
answers queries through the real hybrid (lexical + dense) dispatcher.

Sync and recall do not upload anything. The memory index uses its own
collection, separate from any docs index.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from difflib import SequenceMatcher
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from docmancer.harness import default_home, harvest_all
from docmancer.harness.privacy import PrivacyFilter
from docmancer.memory.atomic import AtomicMemoryEntry, extract_atoms, merge_atoms
from docmancer.memory.hooks import DEFAULT_HOOK_THRESHOLD as DEFAULT_MEMORY_RELEVANCE_THRESHOLD
from docmancer.memory.graph import GRAPH_SCHEMA_VERSION, MemoryGraphStore, node_id, temporal_multiplier
from docmancer.memory.records import MemoryRecord, MemoryRecordStore, normalize_memory_text
from docmancer.memory.sources import (
    MemorySourceDocument,
    MemorySourceFilters,
    MemorySourceMatch,
    MemorySourceMatchGroup,
    MemorySourceMatchPage,
    MemorySourcePage,
    MemorySourceSummary,
    memory_source_key,
    source_updated_at,
)

if TYPE_CHECKING:
    from docmancer.core.config import DocmancerConfig
    from docmancer.core.models import RetrievedChunk
    from docmancer.harness.base import MemoryEntry

logger = logging.getLogger(__name__)

_MEMORY_COLLECTION = "docmancer_memory"

# Bump when extraction logic changes so stale cached atoms are not reused.
_ATOM_CACHE_VERSION = 4
MEMORY_SCHEMA_VERSION = 3
_SOURCE_SNAPSHOT_VERSION = 2
_SCHEMA_META_TABLE = "docmancer_memory_meta"
_DEFAULT_SYNC_LOCK_TIMEOUT = 10.0
_EDITABLE_SOURCE_SUFFIXES = {".md", ".markdown", ".mdc", ".txt", ".yaml", ".yml"}


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
        self.graph = MemoryGraphStore(self.db_path)
        self._extra_project_paths: set[str] = set()
        from docmancer.agent import DocmancerAgent

        # Lazy: constructing the store would create the SQLite file, so defer
        # it until an operation that actually reads or writes the index. This
        # keeps preview()/status()/dry-run from materialising an empty index.
        self._agent = DocmancerAgent(config=self.config, _lazy_init=True)
        self._embedding_provider = None

    def _build_config(self) -> "DocmancerConfig":
        from docmancer.core.config import CaptureConfig, DocmancerConfig, IndexConfig, VectorStoreConfig

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
            capture=self._load_user_config_block("capture", CaptureConfig),
        )

    def _load_user_config_block(self, name: str, model):
        try:
            import yaml as _yaml

            cfg_path = self.home / ".docmancer" / "docmancer.yaml"
            if not cfg_path.is_file():
                return model()
            data = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            block = data.get(name)
            return model(**block) if isinstance(block, dict) else model()
        except Exception:  # noqa: BLE001 - local config must not break memory startup
            return model()

    def _load_user_discovery(self):
        """Read only the ``discovery`` block from the user's docmancer.yaml.

        The memory index keeps its own isolated config, but discovery tuning
        (disabled harnesses, custom paths) should still take effect from the
        user's config file. Looked up under ``<home>/.docmancer/docmancer.yaml``
        so it stays test-isolated. Anything missing falls back to defaults.
        """
        from docmancer.core.config import DiscoveryConfig

        return self._load_user_config_block("discovery", DiscoveryConfig)

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
            records = self.records.records(project_paths=self._project_paths(cleaned_entries))
            atoms.extend(record.to_atom() for record in records)
            imported = self.graph.imported_atoms()
            if imported:
                try:
                    from docmancer.cloud.config import CloudConfig

                    cloud_config = CloudConfig(Path(self.db_path).parent)
                    for atom in imported:
                        if atom.project_id:
                            linked = cloud_config.path_for_project(atom.project_id)
                            atom.project_path = str(linked) if linked else None
                except Exception as exc:  # noqa: BLE001 - a missing link keeps the atom unscoped locally
                    logger.debug("could not map imported cloud graph projects: %s", exc)
            atoms.extend(imported)
            atoms = [atom for atom in atoms if not self.records.is_forgotten(atom)]
            progress("merge", f"Deduplicating {len(atoms):,} extracted memory atoms")
            atoms = self._merge_all(atoms)
            self._last_sync_stats["atoms_after_merge"] = len(atoms)
            progress("graph", f"Reconciling relationships across {len(atoms):,} memory atoms")
            graph_stats = self.graph.rebuild(atoms, embed_texts=self._embed_fn())
            self._last_sync_stats.update({f"graph_{key}": value for key, value in graph_stats.items()})
            states = self.graph.current_state(atom.atom_id for atom in atoms)
            for atom in atoms:
                atom.status = states.get(atom.atom_id, atom.status)
            self._enqueue_cloud_graph_projection()
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
                self._agent.ingest_documents(
                    docs,
                    recreate=True,
                    with_vectors=True,
                    embeddings_provider=self._embedding_provider,
                )
            progress("finalize", "Writing provenance and schema metadata")
            from docmancer.harness.base import MemoryEntry

            record_entries = []
            for record in records:
                try:
                    content = Path(record.source_path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    content = record.text
                record_entries.append(
                    MemoryEntry(
                        harness=record.harness,
                        scope=record.scope,
                        title=f"{record.origin.title()} memory",
                        content=content,
                        path=record.source_path,
                        extra={"kind": "team-memory" if record.scope_kind == "team" else "docmancer-memory"},
                    )
                )
            self._write_source_snapshot([*cleaned_entries, *record_entries], atoms)
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
                "graph_schema_version": str(GRAPH_SCHEMA_VERSION),
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

            if self._embedding_provider is None:
                self._embedding_provider = get_embeddings_provider(self.config.embeddings)
            return self._embedding_provider.embed
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
            embed = self._embed_fn()
            self._agent.ingest_documents(
                [atom.to_document() for atom in atoms],
                recreate=False,
                with_vectors=True,
                embeddings_provider=self._embedding_provider,
            )
            self._stamp_schema()
            self.graph.rebuild(self.indexed_atoms(), embed_texts=embed)
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
        source_paths: list[str] | tuple[str, ...] | None = None,
        min_score: float | None = DEFAULT_MEMORY_RELEVANCE_THRESHOLD,
        include_history: bool = False,
        expand_relations: bool = False,
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
        retrieval_filters = None
        if source_paths:
            retrieval_filters = {"source_path": {"in": sorted({str(path) for path in source_paths})}}
        result = dispatcher.run(
            text,
            mode=mode,
            limit=search_limit,
            budget=budget,
            filters=retrieval_filters,
            allow_degraded=allow_degraded,
        )
        chunks = result.chunks
        states = self.graph.current_state(
            str((chunk.metadata or {}).get("atom_id") or "") for chunk in chunks
        )
        if not include_history:
            chunks = [
                chunk
                for chunk in chunks
                if states.get(str((chunk.metadata or {}).get("atom_id") or ""), "current") == "current"
            ]
        atom_lookup = self.graph.atoms_for_ids(
            str((chunk.metadata or {}).get("atom_id") or "") for chunk in chunks
        )
        for chunk in chunks:
            atom = atom_lookup.get(str((chunk.metadata or {}).get("atom_id") or ""))
            if atom is not None:
                chunk.score = min(1.0, float(chunk.score or 0.0) * temporal_multiplier(atom))
                chunk.metadata["lifecycle_state"] = states.get(atom.atom_id, "current")
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

        if include_history:
            from docmancer.core.models import RetrievedChunk

            existing_nodes: set[str] = set()
            for chunk in chunks:
                atom_id = str((chunk.metadata or {}).get("atom_id") or "")
                if atom_id in atom_lookup:
                    existing_nodes.add(node_id(atom_lookup[atom_id]))
            for row in self.graph.search_history(text, limit=search_limit):
                if row["node_id"] in existing_nodes:
                    continue
                if scope and row["scope_kind"] != scope:
                    continue
                if project_path and row["scope_kind"] in {"project", "team"}:
                    try:
                        memory_project = Path(str(row.get("project_path") or "")).expanduser().resolve()
                        project = Path(project_path).expanduser().resolve()
                    except OSError:
                        continue
                    if project != memory_project and memory_project not in project.parents:
                        continue
                score = float(row["score"])
                if min_score is not None and score < min_score:
                    continue
                chunks.append(
                    RetrievedChunk(
                        source=f"memory://history/{row['node_id']}",
                        chunk_index=0,
                        text=str(row["text"]),
                        score=score,
                        metadata={
                            "atom_id": row["atom_id"],
                            "record_id": row.get("record_id"),
                            "memory_type": row["memory_type"],
                            "kind": row["kind"],
                            "scope": row["scope"],
                            "scope_kind": row["scope_kind"],
                            "project_path": row.get("project_path"),
                            "source_path": row["source_path"],
                            "title": row["source_title"],
                            "line_start": row["line_start"],
                            "lifecycle_state": row["lifecycle_state"],
                            "historical": True,
                        },
                    )
                )
            chunks.sort(key=lambda chunk: -float(chunk.score or 0.0))

        # Distinct durable records stay independently addressable, but an
        # equivalent record should not consume another recall result.
        unique_chunks = []
        seen_memories: dict[str, list[str]] = {}
        for chunk in chunks:
            meta = chunk.metadata or {}
            scope_key = str(meta.get("scope") or "")
            normalized = normalize_memory_text(chunk.text)
            prior = seen_memories.setdefault(scope_key, [])
            if any(
                normalized == value or SequenceMatcher(None, normalized, value, autojunk=False).ratio() >= 0.96
                for value in prior
            ):
                continue
            prior.append(normalized)
            unique_chunks.append(chunk)
        selected = unique_chunks[:requested_limit]
        if expand_relations:
            selected = self._expand_relation_chunks(selected, atom_lookup, requested_limit)
        return selected

    def _expand_relation_chunks(self, chunks, atom_lookup, limit: int):
        """Append directly related memories after their retrieved seed."""
        from docmancer.core.models import RetrievedChunk

        node_lookup = {node_id(atom): atom for atom in atom_lookup.values()}
        seen = {str((chunk.metadata or {}).get("atom_id") or "") for chunk in chunks}
        expanded = list(chunks)
        for chunk in list(chunks):
            atom = atom_lookup.get(str((chunk.metadata or {}).get("atom_id") or ""))
            if atom is None:
                continue
            identity = node_id(atom)
            for relation in self.graph.relations(identity):
                other_id = relation["target_node_id"] if relation["source_node_id"] == identity else relation["source_node_id"]
                other = node_lookup.get(other_id) or self.graph.atom_for_node(other_id)
                if other is None or other.atom_id in seen:
                    continue
                seen.add(other.atom_id)
                metadata = other.to_document().metadata
                metadata["relation_type"] = relation["relation_type"]
                metadata["relation_id"] = relation["relation_id"]
                expanded.append(
                    RetrievedChunk(
                        source=f"memory://atom/{other.atom_id}", chunk_index=0,
                        text=other.text, score=float(chunk.score) * 0.9, metadata=metadata,
                    )
                )
                if len(expanded) >= limit:
                    return expanded
        return expanded

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
        relations = self.graph.relations()
        return {
            "db_path": self.db_path,
            "sources": len(rows),
            "atoms": stats.get("sections_count", 0),
            "sections": stats.get("sections_count", 0),
            "relations": len(relations),
            "conflicts": sum(
                1 for row in relations
                if row["relation_type"] == "contradicts" and row["resolution_state"] == "suggested"
            ),
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

    def browse_sources(
        self,
        filters: MemorySourceFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> MemorySourcePage:
        """Browse complete indexed source files with filters before pagination."""
        filters = filters or MemorySourceFilters()
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        rows = [row for row in self._indexed_source_documents() if self._source_matches(row, filters)]
        rows.sort(key=self._source_sort_key)
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        summaries = [self._source_summary(row) for row in rows[start : start + page_size]]
        return MemorySourcePage(summaries, total, page, page_size, total_pages)

    def get_indexed_source(self, source_key: str) -> MemorySourceDocument | None:
        """Return the complete privacy-cleaned text used by the current index."""
        for row in self._indexed_source_documents():
            if row.source_key == source_key:
                return row
        return None

    @staticmethod
    def _validate_mutable_source_path(path: Path) -> Path:
        """Validate a user-selected text source without touching secret env files."""
        candidate = path.expanduser().resolve()
        name = candidate.name.casefold()
        if name == ".env" or name.startswith(".env."):
            raise ValueError("environment files cannot be managed through Docmancer")
        if candidate.suffix.casefold() not in _EDITABLE_SOURCE_SUFFIXES:
            allowed = ", ".join(sorted(_EDITABLE_SOURCE_SUFFIXES))
            raise ValueError(f"source files must use one of these text extensions: {allowed}")
        return candidate

    def live_source(self, source_key: str) -> dict:
        """Read the current on-disk contents for an indexed file-backed source."""
        document = self.get_indexed_source(source_key)
        if document is None:
            raise ValueError("indexed source is missing or ambiguous; run `docmancer memory sync`")
        path = self._validate_mutable_source_path(Path(document.path))
        if not path.is_file():
            raise ValueError("source file no longer exists")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("source file is not readable UTF-8 text") from exc
        return {
            **asdict(document),
            "path": str(path),
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    def edit_source(self, source_key: str, content: str, *, expected_hash: str) -> MemorySourceDocument:
        """Replace any indexed text source using optimistic concurrency control."""
        live = self.live_source(source_key)
        if live["content_hash"] != expected_hash:
            raise ValueError("source changed on disk after the editor opened; reopen it before saving")
        if not content.strip():
            raise ValueError("source content cannot be empty; use delete if you want to remove the file")
        path = Path(live["path"])
        mode = path.stat().st_mode
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            temporary.chmod(mode)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.sync()
        updated = next(
            (
                row
                for row in self._indexed_source_documents()
                if Path(row.path).expanduser().resolve() == path
                and row.harness == live["harness"]
                and row.kind == live["kind"]
            ),
            None,
        )
        if updated is None:
            raise ValueError("source was saved but is no longer discovered after sync")
        return updated

    def delete_source(self, source_key: str, *, expected_hash: str) -> str:
        """Delete an indexed text source after verifying it has not changed."""
        live = self.live_source(source_key)
        if live["content_hash"] != expected_hash:
            raise ValueError("source changed on disk after confirmation opened; review it before deleting")
        path = Path(live["path"])
        path.unlink()
        self.sync()
        return str(path)

    def create_source(self, path: str | Path, content: str) -> tuple[str, bool]:
        """Create a new text file and report whether harness discovery indexed it."""
        candidate = self._validate_mutable_source_path(Path(path))
        if not candidate.parent.is_dir():
            raise ValueError("destination directory does not exist")
        if candidate.exists():
            raise ValueError("destination file already exists")
        if not content.strip():
            raise ValueError("source content cannot be empty")
        try:
            with candidate.open("x", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ValueError("destination file already exists") from exc
        self.sync()
        indexed = any(
            Path(row.path).expanduser().resolve() == candidate
            for row in self._indexed_source_documents()
        )
        return str(candidate), indexed

    def search_sources(
        self,
        text: str,
        filters: MemorySourceFilters | None = None,
        *,
        mode: str = "hybrid",
        page: int = 1,
        page_size: int = 50,
    ) -> MemorySourceMatchPage:
        """Search atomic passages, grouped into human-facing source files."""
        filters = filters or MemorySourceFilters()
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        documents = [row for row in self._indexed_source_documents() if self._source_matches(row, filters)]
        lookup = {row.source_key: row for row in documents}
        if not lookup or not text.strip():
            return MemorySourceMatchPage([], page, page_size, False)

        atom_count = max(1, sum(row.atom_count for row in documents))
        requested = min(atom_count, 340)
        chunks = self.query(
            text,
            limit=requested,
            budget=max(50_000, requested * 2_000),
            mode=mode,
            project_path=None,
            scope=None,
            source_paths=sorted({row.path for row in documents}),
        )
        groups: dict[str, list[MemorySourceMatch]] = {}
        for chunk in chunks:
            meta = chunk.metadata or {}
            key = memory_source_key(
                harness=str(meta.get("harness") or ""),
                scope=str(meta.get("scope") or ""),
                kind=str(meta.get("kind") or "agent-memory"),
                path=str(meta.get("source_path") or ""),
            )
            if key not in lookup:
                continue
            atom_id = str(meta.get("atom_id") or "") or None
            record_id = str(meta.get("record_id") or "") or None
            groups.setdefault(key, []).append(
                MemorySourceMatch(
                    identifier=record_id or atom_id or str(chunk.source),
                    text=str(chunk.text or ""),
                    score=float(chunk.score or 0.0),
                    line_start=max(1, int(meta.get("line_start") or 1)),
                    line_end=max(1, int(meta.get("line_end") or meta.get("line_start") or 1)),
                    memory_type=str(meta.get("memory_type") or "fact"),
                    record_id=record_id,
                    atom_id=atom_id,
                    origin=str(meta.get("origin") or "harvested"),
                )
            )

        ranked: list[MemorySourceMatchGroup] = []
        for key, matches in groups.items():
            matches.sort(key=lambda match: (-match.score, match.line_start, match.text))
            ranked.append(MemorySourceMatchGroup(self._source_summary(lookup[key]), matches))
        ranked.sort(
            key=lambda group: (
                -float(group.matches[0].score if group.matches else 0.0),
                self._source_sort_key(lookup[group.source.source_key]),
            )
        )
        start = (page - 1) * page_size
        items = ranked[start : start + page_size]
        return MemorySourceMatchPage(items, page, page_size, start + page_size < len(ranked))

    def _read_source_snapshot(self) -> dict:
        path = self._source_snapshot_path()
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _indexed_source_documents(self) -> list[MemorySourceDocument]:
        snapshot = self._read_source_snapshot()
        raw_sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), list) else []
        indexed_at = str(snapshot.get("indexed_at") or "") or None

        atom_meta: dict[tuple[str, str, str, str], dict] = {}
        indexed_atoms = self.indexed_atoms()
        states = self.graph.current_state(atom.atom_id for atom in indexed_atoms)
        for atom in indexed_atoms:
            identity = (atom.harness, atom.scope, atom.kind, atom.source_path)
            row = atom_meta.setdefault(
                identity,
                {
                    "updated_at": atom.timestamp,
                    "source_hash": atom.source_hash,
                    "record_ids": set(),
                    "origins": set(),
                    "atoms": [],
                },
            )
            if atom.timestamp and (not row["updated_at"] or str(atom.timestamp) > str(row["updated_at"])):
                row["updated_at"] = atom.timestamp
            if atom.record_id:
                row["record_ids"].add(atom.record_id)
            row["origins"].add(atom.origin)
            row["atoms"].append(
                {
                    "navigation_kind": "atom",
                    "identifier": atom.record_id or atom.atom_id,
                    "atom_id": atom.atom_id,
                    "record_id": atom.record_id,
                    "text": atom.text,
                    "memory_type": atom.type,
                    "origin": atom.origin,
                    "status": states.get(
                        atom.atom_id,
                        "current" if atom.status in {"", "active"} else atom.status,
                    ),
                    "line_start": atom.line_start,
                    "line_end": atom.line_end,
                    "timestamp": atom.timestamp,
                    "tags": list(atom.tags),
                }
            )

        documents: list[MemorySourceDocument] = []
        for raw in raw_sources:
            if not isinstance(raw, dict):
                continue
            harness = str(raw.get("harness") or raw.get("agent") or "unknown")
            scope = str(raw.get("scope") or "unknown")
            kind = str(raw.get("kind") or raw.get("type") or "agent-memory")
            path = str(raw.get("path") or "")
            identity = (harness, scope, kind, path)
            meta = atom_meta.get(identity, {})
            content = str(raw.get("content") or "")
            updated_at = source_updated_at(
                path,
                str(raw.get("updated_at") or meta.get("updated_at") or "") or None,
            )
            source_hash = str(raw.get("source_hash") or meta.get("source_hash") or "")
            record_ids = sorted(meta.get("record_ids") or [])
            origins = set(meta.get("origins") or [])
            atoms = sorted(
                list(meta.get("atoms") or []),
                key=lambda item: (int(item.get("line_start") or 0), str(item.get("atom_id") or "")),
            )
            source_missing = False
            changed = False
            try:
                stat = Path(path).expanduser().stat()
                indexed_size = int(raw.get("source_size") or raw.get("chars") or len(content))
                indexed_mtime = raw.get("source_mtime_ns")
                if indexed_mtime is not None:
                    changed = stat.st_size != indexed_size or stat.st_mtime_ns != int(indexed_mtime)
            except OSError:
                source_missing = True
            documents.append(
                MemorySourceDocument(
                    source_key=memory_source_key(harness=harness, scope=scope, kind=kind, path=path),
                    harness=harness,
                    scope=scope,
                    scope_kind=str(raw.get("scope_kind") or scope.split(":", 1)[0] or "unknown"),
                    kind=kind,
                    title=str(raw.get("title") or Path(path).name or "Memory source"),
                    path=path,
                    chars=int(raw.get("chars") or len(content)),
                    atom_count=len(atoms) if atoms else int(raw.get("atoms") or 0),
                    updated_at=updated_at,
                    indexed_at=str(raw.get("indexed_at") or indexed_at or "") or None,
                    source_hash=source_hash,
                    record_id=record_ids[0] if len(record_ids) == 1 else None,
                    origin="manual" if origins and origins <= {"manual", "capture", "promoted"} else "harvested",
                    changed_since_sync=changed,
                    source_missing=source_missing,
                    content=content,
                    atoms=atoms,
                )
            )
        return documents

    @staticmethod
    def _source_summary(document: MemorySourceDocument) -> MemorySourceSummary:
        values = asdict(document)
        values.pop("content", None)
        values.pop("atoms", None)
        return MemorySourceSummary(**values)

    @staticmethod
    def _source_sort_key(document: MemorySourceDocument):
        raw = document.updated_at or ""
        try:
            updated = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, OSError):
            updated = 0.0
        return (-updated, document.title.casefold(), document.path.casefold(), document.source_key)

    @staticmethod
    def _source_matches(document: MemorySourceDocument, filters: MemorySourceFilters) -> bool:
        if filters.kinds and document.kind not in filters.kinds:
            return False
        if filters.harness and document.harness != filters.harness:
            return False
        if filters.scope_kind and document.scope_kind != filters.scope_kind:
            return False
        if filters.updated_after:
            if not document.updated_at:
                return False
            try:
                updated = datetime.fromisoformat(document.updated_at.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except ValueError:
                return False
            cutoff = filters.updated_after
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            if updated < cutoff:
                return False
        if filters.project_path:
            if document.scope_kind == "global":
                return True
            if document.scope_kind not in {"project", "team"}:
                return False
            raw_project = document.scope.split(":", 1)[1] if ":" in document.scope else ""
            if not raw_project:
                return False
            try:
                selected = Path(filters.project_path).expanduser().resolve()
                source_project = Path(raw_project).expanduser().resolve()
            except OSError:
                return False
            if selected != source_project and source_project not in selected.parents:
                return False
        return True

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
            project_id=meta.get("project_id"),
            revision_id=meta.get("revision_id"),
            parent_revision_ids=[str(value) for value in meta.get("parent_revision_ids", []) if value],
            deleted=bool(meta.get("deleted", False)),
            audience_kind=str(meta.get("audience_kind") or "personal"),
            applicability_kind=str(meta.get("applicability_kind") or "global"),
            pack_ids=[str(value) for value in meta.get("pack_ids", []) if value],
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
        self._enqueue_cloud_revision(record.to_revision_payload())
        indexed = False
        if sync_index:
            try:
                self.index_records([record])
                indexed = True
            except SyncInProgressError:
                indexed = False
        return record, indexed

    def find_atom(self, identifier: str) -> AtomicMemoryEntry | None:
        identifier = str(identifier).strip()
        if identifier.startswith("docmancer://record/"):
            identifier = identifier.removeprefix("docmancer://record/").split("?", 1)[0].split("#", 1)[0]
        matches = [
            atom
            for atom in self.indexed_atoms()
            if atom.atom_id.startswith(identifier) or (atom.record_id or "").startswith(identifier)
        ]
        return matches[0] if len(matches) == 1 else None

    def recent(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        harness: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self.graph.recent(since, until=until, harness=harness, limit=limit)

    def import_conversations(
        self,
        path: str | Path,
        *,
        source: str = "auto",
        scope_kind: str = "global",
        project_path: str | Path | None = None,
        dry_run: bool = False,
    ) -> dict:
        from docmancer.memory.importers import conversation_atoms

        atoms = conversation_atoms(path, source=source, scope_kind=scope_kind, project_path=project_path)
        existing = {normalize_memory_text(atom.text) for atom in self.indexed_atoms()}
        candidates = [atom for atom in atoms if normalize_memory_text(atom.text) not in existing]
        if dry_run:
            return {"source": source, "candidates": len(candidates), "created": 0, "records": []}
        created: list[MemoryRecord] = []
        for atom in candidates:
            try:
                record = self.records.add(
                    atom.text,
                    scope_kind=scope_kind,
                    project_path=project_path,
                    memory_type=atom.type,
                    tags=["conversation-import", atom.harness],
                    origin="imported",
                )
            except ValueError:
                continue
            created.append(record)
            existing.add(normalize_memory_text(atom.text))
            self._enqueue_cloud_revision(record.to_revision_payload())
        if created:
            self.sync(recreate=False)
        return {
            "source": source,
            "candidates": len(candidates),
            "created": len(created),
            "records": [record.record_id for record in created],
        }

    def clear_filtered(
        self,
        *,
        harness: str | None = None,
        since: datetime | None = None,
        before: datetime | None = None,
        scope: str | None = None,
        dry_run: bool = False,
    ) -> list[AtomicMemoryEntry]:
        """Forget matching records and harvested atoms, then rebuild once."""
        matches = []
        for atom in self.indexed_atoms():
            if harness and atom.harness.casefold() != harness.casefold():
                continue
            if scope and atom.scope_kind.casefold() != scope.casefold():
                continue
            stamp = None
            if atom.timestamp:
                try:
                    stamp = datetime.fromisoformat(atom.timestamp.replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                except ValueError:
                    stamp = None
            if stamp is None:
                try:
                    stamp = datetime.fromtimestamp(Path(atom.source_path).stat().st_mtime, timezone.utc)
                except OSError:
                    pass
            if since and (stamp is None or stamp < since):
                continue
            if before and (stamp is None or stamp >= before):
                continue
            matches.append(atom)
        if dry_run or not matches:
            return matches
        roots = self._project_paths()
        for atom in matches:
            self.records.add_tombstone(atom)
            if not atom.record_id:
                continue
            search_roots = [*roots, atom.project_path] if atom.project_path else roots
            record = self.records.find_record(atom.record_id, project_paths=search_roots)
            if record is None:
                continue
            self.records.append_tombstone_revision(record)
            self._enqueue_cloud_revision(self.records.revisions(record.record_id)[-1])
            self.records.delete_record(record)
        self.sync(recreate=False)
        return matches

    def profile_preview(self, *, limit: int = 24) -> dict:
        """Distil a small local working profile without a model or network call."""
        states = self.graph.current_state(atom.atom_id for atom in self.indexed_atoms())
        atoms = [
            atom for atom in self.indexed_atoms()
            if states.get(atom.atom_id, "current") == "current"
            and atom.type in {"preference", "constraint", "decision", "fact", "workflow"}
            and "local-profile" not in atom.tags
        ]
        trust = {"manual": 4, "mcp": 4, "promoted": 3, "capture": 2, "imported": 2, "harvested": 1}
        atoms.sort(key=lambda atom: (trust.get(atom.origin, 1), atom.timestamp or "", atom.source_count), reverse=True)
        selected = atoms[: max(1, limit)]
        grouped: dict[str, list[str]] = {}
        for atom in selected:
            grouped.setdefault(atom.type, []).append(atom.text)
        sections = []
        for memory_type in ("preference", "constraint", "workflow", "decision", "fact"):
            values = grouped.get(memory_type, [])
            if values:
                sections.append(f"{memory_type.title()}s: " + " ".join(values))
        return {
            "text": "Local profile: " + " ".join(sections) if sections else "",
            "source_atoms": len(selected),
            "types": {key: len(value) for key, value in grouped.items()},
        }

    def apply_profile(self, *, limit: int = 24) -> tuple[MemoryRecord, bool]:
        preview = self.profile_preview(limit=limit)
        if not preview["text"]:
            raise ValueError("no current preference, constraint, workflow, decision, or fact memories are available")
        existing = next(
            (record for record in self.records.records(project_paths=self._project_paths()) if "local-profile" in record.tags),
            None,
        )
        if existing is not None:
            updated = self.records.update_record(existing, preview["text"])
            self._enqueue_cloud_revision(updated.to_revision_payload())
            self.sync(recreate=False)
            return updated, True
        return self.add_record(
            preview["text"],
            memory_type="fact",
            tags=["local-profile"],
            origin="manual",
        )

    def edit_record(self, identifier: str, text: str) -> MemoryRecord:
        """Edit a user-owned durable record and rebuild the memory index.

        Harvested atoms are intentionally read-only because their source files
        belong to another agent or to the user. Only records created or
        promoted through Docmancer have a stable ``record_id`` and writable
        Markdown source.
        """
        atom = self.find_atom(identifier)
        if atom is None:
            raise ValueError("memory id is missing or ambiguous")
        if not atom.record_id or atom.origin == "harvested":
            raise ValueError("only user-owned Docmancer records can be edited")
        roots = self._project_paths()
        if atom.project_path:
            roots.append(atom.project_path)
            self._extra_project_paths.add(str(Path(atom.project_path).expanduser().resolve()))
        record = self.records.find_record(atom.record_id, project_paths=roots)
        if record is None:
            raise ValueError("memory record file no longer exists")
        equivalent = self.records.find_equivalent(
            text,
            scope_kind=record.scope_kind,
            project_path=record.project_path,
        )
        if equivalent is not None and equivalent.record_id != record.record_id:
            raise ValueError(
                "Equivalent memory already exists in this scope. "
                f"Memory ID: {equivalent.record_id[:12]}"
            )
        updated = self.records.update_record(record, text)
        self._enqueue_cloud_revision(updated.to_revision_payload())
        self.sync()
        return updated

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
                self.records.append_tombstone_revision(record)
                self._enqueue_cloud_revision(self.records.revisions(record.record_id)[-1])
                self.records.delete_record(record)
        self.sync()
        return atom

    def _enqueue_cloud_revision(self, payload: dict) -> bool:
        """Best-effort local queueing that never performs network I/O."""
        try:
            from docmancer.cloud.lifecycle import enqueue_revision_if_enabled

            return enqueue_revision_if_enabled(payload, root=Path(self.db_path).parent)
        except Exception as exc:  # noqa: BLE001 - cloud queueing cannot break local memory
            logger.debug("cloud revision queueing skipped: %s", exc)
            return False

    def _enqueue_cloud_graph_projection(self) -> int:
        """Best-effort queue of deterministic Protocol v2 graph objects."""
        try:
            from docmancer.cloud.lifecycle import enqueue_revisions_if_enabled
            from docmancer.cloud.serialize import build_graph_payload

            root = Path(self.db_path).parent
            payloads = (
                build_graph_payload(**item) for item in self.graph.cloud_objects()
            )
            return enqueue_revisions_if_enabled(payloads, root=root)
        except Exception as exc:  # noqa: BLE001 - optional sync cannot break local indexing
            logger.debug("cloud graph projection queueing skipped: %s", exc)
            return 0

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

    # ------------------------------------------------------------------
    # Memory intelligence
    # ------------------------------------------------------------------

    def conflicts(self, *, unresolved_only: bool = True) -> list[dict]:
        return self.graph.conflicts(unresolved_only=unresolved_only)

    def relations(
        self,
        identifier: str | None = None,
        *,
        relation_type: str | None = None,
    ) -> list[dict]:
        identity = None
        if identifier:
            atom = self.find_atom(identifier)
            if atom is None:
                raise ValueError("memory ID is missing or ambiguous")
            identity = node_id(atom)
        return self.graph.relations(identity, relation_type=relation_type)

    def resolve_relation(
        self,
        relation_id: str,
        resolution: str,
        *,
        winner: str | None = None,
    ) -> dict:
        winner_node = None
        if winner:
            atom = self.find_atom(winner)
            if atom is None:
                raise ValueError("winner memory ID is missing or ambiguous")
            winner_node = node_id(atom)
        result = self.graph.resolve(relation_id, resolution, winner_node_id=winner_node)
        self._enqueue_cloud_graph_projection()
        return result

    def resolve_relation_group(
        self,
        relation_ids: list[str],
        resolution: str,
        *,
        winner: str | None = None,
    ) -> list[dict]:
        """Resolve one displayed claim group while persisting each pair decision."""
        relation_ids = list(dict.fromkeys(str(value) for value in relation_ids if value))
        if not relation_ids:
            raise ValueError("conflict group has no relations")
        winner_node = None
        if resolution == "choose":
            if not winner:
                raise ValueError("winner memory ID is required")
            atom = self.find_atom(winner)
            if atom is None:
                raise ValueError("winner memory ID is missing or ambiguous")
            winner_node = node_id(atom)

        available = {row["relation_id"]: row for row in self.graph.relations(relation_type="contradicts")}
        missing = [value for value in relation_ids if value not in available]
        if missing:
            raise ValueError(f"conflict relation is missing: {missing[0]}")
        if winner_node and not any(
            winner_node in {available[value]["source_node_id"], available[value]["target_node_id"]}
            for value in relation_ids
        ):
            raise ValueError("winner must belong to the selected claim group")

        resolved = []
        for relation_id in relation_ids:
            row = available[relation_id]
            pair = {str(row["source_node_id"]), str(row["target_node_id"])}
            if resolution == "choose" and winner_node not in pair:
                # Both values lose to the selected winner through other edges in
                # the complete claim group, so this pair no longer needs review.
                resolved.append(self.graph.resolve(relation_id, "dismiss"))
            else:
                resolved.append(
                    self.graph.resolve(
                        relation_id,
                        resolution,
                        winner_node_id=winner_node if resolution == "choose" else None,
                    )
                )
        self._enqueue_cloud_graph_projection()
        return resolved

    def orphans(self) -> list[dict]:
        return self.graph.orphans()

    def recap(
        self,
        since: datetime,
        *,
        until: datetime | None = None,
        project_id: str | None = None,
    ) -> dict:
        return self.graph.recap(since, until=until, project_id=project_id)

    def _source_snapshot_path(self) -> Path:
        db = Path(self.db_path)
        return db.with_name(db.stem + "-sources.json")

    def _write_source_snapshot(
        self,
        entries: list["MemoryEntry"],
        atoms: list[AtomicMemoryEntry],
    ) -> None:
        counts: dict[str, int] = {}
        atom_state: dict[str, dict[str, str | None]] = {}
        for atom in atoms:
            counts[atom.source_path] = counts.get(atom.source_path, 0) + 1
            state = atom_state.setdefault(atom.source_path, {"updated_at": None, "source_hash": ""})
            if atom.timestamp and (not state["updated_at"] or str(atom.timestamp) > str(state["updated_at"])):
                state["updated_at"] = atom.timestamp
            if atom.source_hash:
                state["source_hash"] = atom.source_hash
        indexed_at = datetime.now(timezone.utc).isoformat()
        sources = []
        for entry in entries:
            try:
                stat = Path(entry.path).expanduser().stat()
                source_size = stat.st_size
                source_mtime_ns = stat.st_mtime_ns
            except OSError:
                source_size = len((entry.content or "").encode("utf-8"))
                source_mtime_ns = None
            state = atom_state.get(entry.path, {})
            sources.append(
                {
                    "source_key": memory_source_key(
                        harness=entry.harness,
                        scope=entry.scope,
                        kind=entry.extra.get("kind", "agent-memory"),
                        path=entry.path,
                    ),
                    "harness": entry.harness,
                    "scope": entry.scope,
                    "scope_kind": str(entry.scope or "unknown").split(":", 1)[0],
                    "title": entry.title,
                    "path": entry.path,
                    "kind": entry.extra.get("kind", "agent-memory"),
                    "content": entry.content,
                    "chars": len(entry.content or ""),
                    "source_size": source_size,
                    "source_mtime_ns": source_mtime_ns,
                    "source_hash": state.get("source_hash") or hashlib.sha256((entry.content or "").encode("utf-8")).hexdigest(),
                    "updated_at": state.get("updated_at"),
                    "indexed_at": indexed_at,
                    "atoms": counts.get(entry.path, 0),
                }
            )
        payload = {
            "version": _SOURCE_SNAPSHOT_VERSION,
            "indexed_at": indexed_at,
            "sources": sources,
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
    "MemorySourceDocument",
    "MemorySourceFilters",
    "MemorySourceMatch",
    "MemorySourceMatchGroup",
    "MemorySourceMatchPage",
    "MemorySourcePage",
    "MemorySourceSummary",
    "default_memory_db",
    "MEMORY_SCHEMA_VERSION",
    "SchemaMismatchError",
    "SyncInProgressError",
    "sync_lock_path",
]
