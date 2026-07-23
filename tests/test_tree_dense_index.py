from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree.dense_index import TreeDenseIndex
from docmancer.memory.tree.store import TreeStore
from docmancer.stores.base import VectorHit


class FakeProvider:
    dimensions = 2

    def __init__(self, model_name: str = "fake-v1") -> None:
        self.model_name = model_name
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]


class FakeStore:
    def __init__(self) -> None:
        self.points = {}

    def ensure_collection(self, _name: str, _dimensions: int) -> None:
        return None

    def upsert(self, _name: str, points: list, *, bulk: bool = False) -> None:
        self.points.update({point.id: point for point in points})

    def delete_points(self, _name: str, ids: list) -> int:
        deleted = 0
        for identifier in ids:
            deleted += self.points.pop(identifier, None) is not None
        return deleted

    def search(self, _name: str, _vector: list[float], *, limit: int = 10):
        return [VectorHit(id=identifier, score=0.8, payload=point.payload) for identifier, point in list(self.points.items())[:limit]]


def test_dense_index_reuses_unchanged_chunks_and_reembeds_only_edit(tmp_path: Path) -> None:
    tree = TreeStore(tmp_path / "tree")
    entry = tree.write(relative_path="decision.md", text="# Deploy\n\nUse Railway.\n\nKeep rollback notes.\n", expect="absent")
    provider = FakeProvider()
    vectors = FakeStore()
    index = TreeDenseIndex(tree.root, provider=provider, store=vectors)

    first = index.sync(tree.index.entries())
    assert first["embedded"] == 3
    assert len(provider.embedded) == 3

    second = index.sync(tree.index.entries())
    assert second["embedded"] == 0
    assert second["reused"] == 3
    assert len(provider.embedded) == 3

    tree.edit(entry.address, text="# Deploy\n\nUse Railway.\n\nKeep two rollback notes.\n", expected_hash=entry.content_hash)
    third = index.sync(tree.index.entries())
    assert third["embedded"] == 1
    assert third["reused"] == 2
    assert third["deleted"] == 1
    assert len(provider.embedded) == 4

    scores = index.search("deployment")
    assert scores[entry.memory_id] == 0.8

    replacement = FakeProvider("fake-v2")
    changed_model = TreeDenseIndex(tree.root, provider=replacement, store=vectors)
    model_stats = changed_model.sync(tree.index.entries())
    assert model_stats["embedded"] == 3
