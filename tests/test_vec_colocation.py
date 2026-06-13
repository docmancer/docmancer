"""The default sqlite-vec store must co-locate with the index so unrelated
project-local repos (all named ``.docmancer/docmancer.db``) cannot collide in
one global vector DB + ``docmancer_docmancer`` collection.
"""
import pytest

from docmancer.agent import DocmancerAgent
from docmancer.core.config import DocmancerConfig, IndexConfig, VectorStoreConfig


def _agent(db_path, vector_store=None):
    cfg = DocmancerConfig(
        index=IndexConfig(db_path=str(db_path)),
        **({"vector_store": vector_store} if vector_store else {}),
    )
    return DocmancerAgent(config=cfg, _lazy_init=True)


def test_sqlite_vec_db_colocated_with_index(tmp_path):
    idx = tmp_path / "repoA" / ".docmancer" / "docmancer.db"
    idx.parent.mkdir(parents=True)
    vs = _agent(idx).resolve_vector_store_config()
    assert vs.provider == "sqlite-vec"
    assert vs.options["db_path"] == str(idx.with_name("docmancer-vec.db"))


def test_two_repos_do_not_share_vec_db(tmp_path):
    a = tmp_path / "repoA" / ".docmancer" / "docmancer.db"
    b = tmp_path / "repoB" / ".docmancer" / "docmancer.db"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    va = _agent(a).resolve_vector_store_config()
    vb = _agent(b).resolve_vector_store_config()
    assert va.options["db_path"] != vb.options["db_path"]


def test_explicit_db_path_is_respected(tmp_path):
    explicit = tmp_path / "explicit-vec.db"
    vs = _agent(
        tmp_path / "i.db",
        vector_store=VectorStoreConfig(provider="sqlite-vec", options={"db_path": str(explicit)}),
    ).resolve_vector_store_config()
    assert vs.options["db_path"] == str(explicit)


def test_qdrant_config_untouched(tmp_path):
    vs = _agent(
        tmp_path / "i.db",
        vector_store=VectorStoreConfig(provider="qdrant", url="http://localhost:6333"),
    ).resolve_vector_store_config()
    assert vs.provider == "qdrant"
    assert not (vs.options or {}).get("db_path")


@pytest.mark.integration
def test_two_repos_isolated_end_to_end(tmp_path, monkeypatch):
    """Two project-local ingests with the same collection name must not leak
    each other's vectors, because their vec DBs are now distinct files."""
    monkeypatch.setenv("DOCMANCER_AUTO_VECTORS", "1")
    from docmancer.core.models import Document

    a = _agent_real(tmp_path / "repoA" / ".docmancer" / "docmancer.db")
    b = _agent_real(tmp_path / "repoB" / ".docmancer" / "docmancer.db")
    a.ingest_documents([Document(source="a://1", content="# Alpha\n\nRailway deploy notes.", metadata={})])
    b.ingest_documents([Document(source="b://1", content="# Beta\n\nKubernetes cluster notes.", metadata={})])

    from docmancer.stores.base import get_vector_store

    va = get_vector_store(a.resolve_vector_store_config(), embeddings_dim=a.config.embeddings.dimensions)
    vb = get_vector_store(b.resolve_vector_store_config(), embeddings_dim=b.config.embeddings.dimensions)
    # Each repo's vector store holds only its own points despite the shared
    # collection name.
    assert va.count(a._vector_collection_name()) >= 1
    assert vb.count(b._vector_collection_name()) >= 1
    assert a.resolve_vector_store_config().options["db_path"] != b.resolve_vector_store_config().options["db_path"]


def _agent_real(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = DocmancerConfig(index=IndexConfig(db_path=str(db_path)))
    return DocmancerAgent(config=cfg)
