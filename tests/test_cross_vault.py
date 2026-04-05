from unittest.mock import patch, MagicMock
from docmancer.core.models import RetrievedChunk
from docmancer.vault.operations import cross_vault_query


def test_cross_vault_query_merges_results(tmp_path):
    """Cross-vault query should merge results from multiple vaults sorted by score."""
    mock_registry = MagicMock()
    mock_registry.list_vaults.return_value = [
        {"name": "vault1", "root_path": str(tmp_path / "v1")},
        {"name": "vault2", "root_path": str(tmp_path / "v2")},
    ]

    # Create minimal vault configs
    for vname in ["v1", "v2"]:
        vpath = tmp_path / vname
        vpath.mkdir()
        (vpath / "docmancer.yaml").write_text("embedding:\n  provider: fastembed\n")

    chunk1 = RetrievedChunk(source="doc1.md", chunk_index=0, text="from vault1", score=0.9)
    chunk2 = RetrievedChunk(source="doc2.md", chunk_index=0, text="from vault2", score=0.95)

    mock_agent1 = MagicMock()
    mock_agent1.query.return_value = [chunk1]
    mock_agent2 = MagicMock()
    mock_agent2.query.return_value = [chunk2]

    agents = iter([mock_agent1, mock_agent2])

    with patch("docmancer.vault.registry.VaultRegistry", return_value=mock_registry), \
         patch("docmancer.agent.DocmancerAgent", side_effect=lambda **kwargs: next(agents)):
        results = cross_vault_query("test query", limit=10)

    assert len(results) == 2
    assert results[0].score == 0.95  # highest first
    assert results[0].vault_name == "vault2"
    assert results[1].vault_name == "vault1"


def test_cross_vault_query_filters_by_name(tmp_path):
    """Cross-vault query with vault_names should only query specified vaults."""
    mock_registry = MagicMock()
    mock_registry.list_vaults.return_value = [
        {"name": "vault1", "root_path": str(tmp_path / "v1")},
        {"name": "vault2", "root_path": str(tmp_path / "v2")},
    ]

    vpath = tmp_path / "v1"
    vpath.mkdir()
    (vpath / "docmancer.yaml").write_text("embedding:\n  provider: fastembed\n")

    chunk1 = RetrievedChunk(source="doc1.md", chunk_index=0, text="from vault1", score=0.9)
    mock_agent = MagicMock()
    mock_agent.query.return_value = [chunk1]

    with patch("docmancer.vault.registry.VaultRegistry", return_value=mock_registry), \
         patch("docmancer.agent.DocmancerAgent", return_value=mock_agent):
        results = cross_vault_query("test", vault_names=["vault1"], limit=10)

    assert len(results) == 1
    assert results[0].vault_name == "vault1"
