"""Incremental local dense index for canonical tree chunks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from docmancer.core.config import EmbeddingsConfig, VectorStoreConfig
from docmancer.embeddings.model2vec_provider import Model2VecProvider
from docmancer.memory.tree.fingerprint import chunk_body, chunk_hash, file_fingerprint
from docmancer.memory.tree.parser import TreeMemoryFile
from docmancer.stores.base import VectorPoint
from docmancer.stores.sqlite_vec_store import SqliteVecStore

COLLECTION = "tree_chunks"


class TreeDenseIndex:
    """Own one sqlite-vec chunk collection beside a canonical tree."""

    def __init__(self, tree_root: Path, *, provider=None, store=None) -> None:
        self.tree_root = tree_root.resolve()
        self.state_dir = self.tree_root.parent / "index"
        self.state_path = self.state_dir / "tree-fingerprints.json"
        self.db_path = self.state_dir / "tree-vectors.sqlite"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or Model2VecProvider(EmbeddingsConfig(cache=str(self.state_dir / "embeddings-cache")))
        if store is None:
            ensure = getattr(self.provider, "_ensure_dense", None)
            if callable(ensure):
                ensure()
            store = SqliteVecStore(VectorStoreConfig(options={"db_path": str(self.db_path)}), embeddings_dim=int(self.provider.dimensions))
        self.store = store
        self.store.ensure_collection(COLLECTION, int(self.provider.dimensions))

    @classmethod
    def exists(cls, tree_root: Path) -> bool:
        return (tree_root.resolve().parent / "index" / "tree-vectors.sqlite").is_file()

    def _state(self) -> dict:
        if not self.state_path.is_file():
            return {"files": {}}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"files": {}}
        except (OSError, json.JSONDecodeError):
            return {"files": {}}

    def sync(self, entries: Iterable[TreeMemoryFile]) -> dict[str, int]:
        state = self._state()
        model_id = str(getattr(self.provider, "model_name", None) or getattr(self.provider, "name", None) or type(self.provider).__name__)
        previous = state.get("files", {}) if state.get("model") == model_id else {}
        if not isinstance(previous, dict):
            previous = {}
        current: dict[str, dict] = {}
        points: list[VectorPoint] = []
        texts: list[str] = []
        reused = 0
        old_points = {point for row in previous.values() if isinstance(row, dict) for point in row.get("points", [])}
        for entry in entries:
            chunks = chunk_body(entry.body)
            point_ids = [f"{entry.memory_id}:{chunk_hash(chunk)}" for chunk in chunks]
            fingerprint = file_fingerprint(entry)
            current[entry.memory_id] = {"fingerprint": fingerprint, "points": point_ids, "type": entry.type, "authority": entry.authority}
            old = previous.get(entry.memory_id, {}) if isinstance(previous.get(entry.memory_id), dict) else {}
            if old.get("fingerprint") == fingerprint:
                reused += len(point_ids)
                continue
            metadata_changed = old.get("type") != entry.type or old.get("authority") != entry.authority
            for chunk, point_id in zip(chunks, point_ids):
                if not metadata_changed and point_id in old_points:
                    reused += 1
                    continue
                texts.append(f"{entry.title}\nType: {entry.type}\nAuthority: {entry.authority}\n{chunk}")
                points.append(VectorPoint(id=point_id, vector=None, payload={"memory_id": entry.memory_id, "address": entry.address}))
        if texts:
            vectors = self.provider.embed(texts)
            for point, vector in zip(points, vectors):
                point.vector = vector
            self.store.upsert(COLLECTION, points, bulk=True)
        new_points = {point for row in current.values() for point in row["points"]}
        deleted = self.store.delete_points(COLLECTION, sorted(old_points - new_points))
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"format": 1, "model": model_id, "files": current}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(self.state_path)
        return {"embedded": len(points), "reused": reused, "deleted": deleted, "files": len(current)}

    def search(self, query: str, *, limit: int = 50) -> dict[str, float]:
        if not query.strip():
            return {}
        hits = self.store.search(COLLECTION, self.provider.embed_query(query), limit=limit)
        scores: dict[str, float] = {}
        for hit in hits:
            memory_id = str(hit.payload.get("memory_id") or "")
            if memory_id:
                scores[memory_id] = max(scores.get(memory_id, 0.0), float(hit.score))
        return scores

    def close(self) -> None:
        close = getattr(self.store, "close", None)
        if callable(close):
            close()


__all__ = ["TreeDenseIndex"]
