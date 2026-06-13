from docmancer.stores.base import VectorStore
from docmancer.stores.sqlite_vec_store import SqliteVecStore
from docmancer.core.config import VectorStoreConfig, DocmancerConfig


def test_base_default_supports_sparse_false():
    assert VectorStore.supports_sparse is False


def test_sqlite_vec_declares_no_sparse(tmp_path):
    store = SqliteVecStore(
        config=VectorStoreConfig(
            provider="sqlite-vec", options={"db_path": str(tmp_path / "v.db")}
        )
    )
    assert store.supports_sparse is False


def test_qdrant_declares_sparse():
    from docmancer.stores.qdrant_store import QdrantStore

    assert QdrantStore.supports_sparse is True


def test_sqlite_vec_search_from_worker_thread(tmp_path):
    """The hybrid dispatcher runs dense search in a ThreadPoolExecutor worker.
    The sqlite-vec connection is opened on the main thread, so searching from
    another thread must not raise SQLite's cross-thread ProgrammingError."""
    from concurrent.futures import ThreadPoolExecutor

    from docmancer.stores.base import VectorPoint

    store = SqliteVecStore(
        config=VectorStoreConfig(
            provider="sqlite-vec", options={"db_path": str(tmp_path / "v.db")}
        )
    )
    store.ensure_collection("c", dimensions=3)
    store.upsert("c", [VectorPoint(id=1, vector=[0.1, 0.2, 0.3], payload={"section_id": 1})])

    with ThreadPoolExecutor(max_workers=1) as ex:
        hits = ex.submit(store.search, "c", [0.1, 0.2, 0.3], limit=1).result()
    assert hits and hits[0].id == "1"


def test_fanout_skips_sparse_when_unsupported():
    from docmancer.retrieval.dispatch import RetrievalDispatcher
    from docmancer.stores.base import VectorHit

    class FakeStore:
        supports_sparse = False

        def count(self, c):
            return 1

        def search(self, *a, **k):
            return [VectorHit(id="1", score=1.0, payload={"section_id": 1})]

    class FakeLex:
        def query(self, *a, **k):
            return []

        def fetch_sections_by_id(self, ids, budget):
            return []

        def distinct_document_count(self):
            return 0

    class FakeProvider:
        name = "fake"

        def embed_query(self, q):
            return [0.1, 0.2]

    disp = RetrievalDispatcher(
        store=FakeLex(),
        config=DocmancerConfig(),
        vector_store=FakeStore(),
        provider=FakeProvider(),
        collection="c",
    )
    lists, counts, failures = disp._fan_out(
        query="x", mode="hybrid", per_source_limit=5, filters=None
    )
    assert "sparse" not in failures and "sparse" not in lists
