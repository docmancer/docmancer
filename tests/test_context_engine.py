import json
from pathlib import Path

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.context_engine import ContextEngine, context_cache_key


def _atom(atom_id: str, text: str, *, kind: str = "agent-memory") -> AtomicMemoryEntry:
    digest = __import__("hashlib").sha256(text.encode()).hexdigest()
    return AtomicMemoryEntry(
        atom_id=atom_id,
        text=text,
        type="decision",
        harness="codex",
        kind=kind,
        scope="project:/repo",
        source_path=f"/memory/{atom_id}.md",
        source_title="Deployment decision",
        line_start=1,
        line_end=1,
        source_hash=digest,
        content_hash=digest,
        timestamp="2026-07-25T10:00:00+00:00",
    )


class _Agent:
    def __init__(self, atoms):
        self.atoms = atoms

    def indexed_atoms(self):
        return list(self.atoms)


def _engine(tmp_path: Path, atoms) -> ContextEngine:
    project = tmp_path / "repo"
    project.mkdir(exist_ok=True)
    return ContextEngine(project, agent=_Agent(atoms))


def test_providerless_build_creates_revision_and_topic_files_without_network(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    atoms = [
        _atom("a1", "Production deploys run through Railway."),
        _atom("a2", "Production deploys run through Railway."),
        _atom("a3", "A smoke test is required after production deployment.", kind="instructions"),
    ]
    engine = _engine(tmp_path, atoms)

    result = engine.build()
    latest = engine.latest()

    assert result["changed"] is True
    assert result["provider_calls"] == 0
    assert latest["cost_estimate"]["provider_calls"] == 0
    assert latest["cost_estimate"]["provider_cost_usd"] == 0
    assert latest["scope"]["audience"] == "personal"
    assert latest["scope"]["project_id"]
    assert latest["topics"]
    for topic in latest["topics"]:
        path = Path(topic["path"])
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "generated: true" in text
        assert "synthesized: false" in text
        assert topic["source_addresses"]


def test_same_revision_and_target_are_byte_idempotent_even_on_full_rebuild(tmp_path):
    engine = _engine(
        tmp_path,
        [_atom("a1", "Production deploys run through Railway.")],
    )
    first = engine.build()
    path = Path(engine.latest()["topics"][0]["path"])
    before = path.read_bytes()

    second = engine.build(full=True)

    assert first["revision_id"] == second["revision_id"]
    assert path.read_bytes() == before


def test_generated_edit_is_never_overwritten_and_produces_diff(tmp_path):
    atoms = [_atom("a1", "Production deploys run through Railway.")]
    engine = _engine(tmp_path, atoms)
    engine.build()
    path = Path(engine.latest()["topics"][0]["path"])
    path.write_text(path.read_text(encoding="utf-8") + "\nHuman note.\n", encoding="utf-8")
    atoms.append(_atom("a2", "A smoke test follows a production deploy."))

    result = engine.build()

    assert "Human note." in path.read_text(encoding="utf-8")
    edited = next(row for row in result["writes"] if row["state"] == "generated-edited")
    assert Path(edited["proposal"]).is_file()


def test_retired_cluster_does_not_reappear_and_rollback_appends(tmp_path):
    engine = _engine(
        tmp_path,
        [_atom("a1", "Production deploys run through Railway.")],
    )
    first = engine.build()
    first_manifest = engine.latest()
    cluster_id = first_manifest["clusters"][0]["cluster_id"]
    engine.retire(cluster_id)
    second = engine.build(full=True)

    assert second["clusters"] == 0
    current = engine.latest()
    restored = engine.rollback(first["revision_id"])
    assert restored["revision_id"] != current["revision_id"]
    assert restored["parent_revision_id"] == current["revision_id"]
    assert restored["reinstates"] == first["revision_id"]


def test_context_dry_run_is_read_only(tmp_path, monkeypatch):
    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(tmp_path / "harness"))

    result = CliRunner().invoke(
        cli,
        ["context", "refresh", "--project", str(project), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert not (project / ".docmancer" / "state" / "context" / "latest.json").exists()


def test_cache_key_changes_for_members_provider_model_and_generation(tmp_path):
    engine = _engine(tmp_path, [_atom("a1", "Use Railway.")])
    cluster = engine.plan()["clusters"][0]

    baseline = context_cache_key(cluster, provider=None, model=None)
    with_provider = context_cache_key(cluster, provider="openrouter", model="m1")
    with_model = context_cache_key(cluster, provider="openrouter", model="m2")
    with_generation = context_cache_key(
        cluster,
        provider="openrouter",
        model="m2",
        generation={"mode": "thorough"},
    )

    assert len({baseline, with_provider, with_model, with_generation}) == 4
