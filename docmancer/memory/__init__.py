"""Local memory agent: index and recall coding-agent memory on this machine.

``MemoryAgent`` harvests harness memory and instruction files (Claude Code,
Codex, Cursor) through :mod:`docmancer.harness`, applies the privacy filter,
indexes everything into a dedicated local SQLite + sqlite-vec store, and
answers queries through the real hybrid (lexical + dense) dispatcher.

Nothing is uploaded: the index is a single local SQLite file. The memory index
uses its own collection, separate from any docs index.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from docmancer.harness import default_home, harvest_all
from docmancer.harness.privacy import PrivacyFilter

if TYPE_CHECKING:
    from docmancer.core.config import DocmancerConfig
    from docmancer.core.models import RetrievedChunk
    from docmancer.harness.base import MemoryEntry

logger = logging.getLogger(__name__)

_MEMORY_COLLECTION = "docmancer_memory"


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
        self.config = config or self._build_config()
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

    def sync(self, *, recreate: bool = False) -> int:
        """Harvest, filter, redact, and index. Returns the entry count."""
        entries = self.preview()
        if recreate:
            # Rebuild from scratch: drop the vector collection up front so
            # "--recreate" truly starts clean, even when the harvest is now
            # empty (all entries deleted or excluded). Otherwise the FTS index
            # is cleared but the co-located sqlite-vec collection keeps stale
            # vectors from the previous sync.
            self._drop_vectors()
        if not entries:
            if recreate:
                self._agent.store.add_documents([], recreate=True)
            return 0
        docs = [self.privacy.clean(e).to_document() for e in entries]
        self._agent.ingest_documents(docs, recreate=recreate, with_vectors=True)
        return len(docs)

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
    ) -> list["RetrievedChunk"]:
        from docmancer.retrieval.dispatch import RetrievalDispatcher

        vector_store, provider = self._build_retrieval_backends()
        dispatcher = RetrievalDispatcher(
            store=self._agent.store,
            config=self.config,
            vector_store=vector_store,
            provider=provider,
            collection=self._agent._vector_collection_name(),
        )
        result = dispatcher.run(text, mode=mode, limit=limit, budget=budget, allow_degraded=allow_degraded)
        return result.chunks

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
            return {"db_path": self.db_path, "sources": 0, "sections": 0}
        try:
            stats = self._agent.collection_stats()
        except Exception:  # noqa: BLE001
            stats = {}
        return {
            "db_path": self.db_path,
            "sources": stats.get("sources_count", 0),
            "sections": stats.get("sections_count", 0),
        }

    def sources(self, *, live_preview: bool = False) -> list[dict]:
        """Return provenance rows: agent, type, scope, title, path, chars.

        ``live_preview=True`` re-harvests (post-privacy, no writes) to show what
        WOULD index; otherwise it reads the stored index (what was actually
        consolidated). Rows are sorted by agent, then scope, then path.
        """
        rows: list[dict] = []
        if live_preview or not Path(self.db_path).exists():
            for e in self.preview():
                rows.append(
                    {
                        "agent": e.harness,
                        "type": e.extra.get("kind", "agent-memory"),
                        "scope": e.scope,
                        "title": e.title,
                        "path": e.path,
                        "chars": len(e.content or ""),
                    }
                )
        else:
            try:
                provenance = self._agent.store.list_source_provenance()
            except Exception:  # noqa: BLE001
                provenance = []
            for item in provenance:
                meta = item.get("metadata", {})
                rows.append(
                    {
                        "agent": meta.get("harness", item["source"].split(":", 1)[0]),
                        "type": meta.get("kind", "agent-memory"),
                        "scope": meta.get("scope", ""),
                        "title": meta.get("title", ""),
                        "path": meta.get("source_path", item["source"].split(":", 1)[-1]),
                        "chars": item["chars"],
                    }
                )
        rows.sort(key=lambda r: (r["agent"], r["scope"], r["path"]))
        return rows

    def memory_paths(self) -> list[Path]:
        db = Path(self.db_path)
        return [db, db.with_name(db.stem + "-vec.db")]

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


__all__ = ["MemoryAgent", "default_memory_db"]
