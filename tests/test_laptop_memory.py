from types import SimpleNamespace

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.laptop import LaptopMemoryReconciler


def _atom(
    atom_id: str,
    text: str,
    memory_type: str,
    *,
    source_path: str,
    scope_kind: str = "global",
    project_path: str | None = None,
    tags: list[str] | None = None,
) -> AtomicMemoryEntry:
    return AtomicMemoryEntry(
        atom_id=atom_id,
        text=text,
        type=memory_type,
        harness="codex",
        kind="agent-memory",
        scope="global:docmancer" if scope_kind == "global" else f"project:{project_path}",
        source_path=source_path,
        source_title="Memory",
        line_start=1,
        line_end=1,
        source_hash=f"source-{atom_id}",
        content_hash=f"content-{atom_id}",
        tags=tags or [],
        timestamp="2026-07-27T12:00:00+00:00",
        scope_kind=scope_kind,
        project_path=project_path,
    )


class _Agent:
    def __init__(self, atoms):
        self._atoms = atoms
        self.config = SimpleNamespace(
            providers=SimpleNamespace(default_llm="openrouter"),
        )

    def indexed_atoms(self):
        return list(self._atoms)


def test_reconcile_writes_stable_laptop_files_and_is_idempotent(tmp_path):
    project = tmp_path / "repos" / "docmancer"
    atoms = [
        _atom(
            "about",
            "Gaurang is a technical founder who builds local-first developer tools.",
            "fact",
            source_path="/Users/gaurang/Documents/Claude_Workspace/About/Gaurang CV.md",
            tags=["local-profile"],
        ),
        _atom(
            "preference",
            "Prefer findings-first technical reviews grounded in the live repository.",
            "preference",
            source_path="/Users/gaurang/.codex/memories/MEMORY.md",
        ),
        _atom(
            "principle",
            "Automatically reconcile shared memory without a per-item approval queue.",
            "constraint",
            source_path="/Users/gaurang/.codex/memories/MEMORY.md",
        ),
        _atom(
            "project",
            "Docmancer is the active local agent-memory product.",
            "decision",
            source_path=str(project / "AGENTS.md"),
            scope_kind="project",
            project_path=str(project),
        ),
    ]
    reconciler = LaptopMemoryReconciler(_Agent(atoms), root=tmp_path / "home")

    first = reconciler.reconcile(use_provider=False)
    second = reconciler.reconcile(use_provider=False)

    assert first["changed"] is True
    assert second["changed"] is False
    assert first["provider"] == "deterministic"
    assert {path.name for path in (tmp_path / "home" / "tree").glob("*.md")} == {
        "about.md",
        "preferences.md",
        "working-principles.md",
        "active-projects.md",
    }
    assert "technical founder" in (tmp_path / "home" / "tree" / "about.md").read_text()
    projects = (tmp_path / "home" / "tree" / "active-projects.md").read_text()
    assert str(project) in projects
    assert "active local agent-memory product" in projects


def test_provider_failure_falls_back_per_section_without_blocking(tmp_path, monkeypatch):
    atom = _atom(
        "preference",
        "Keep shared memory concise and source attributed.",
        "preference",
        source_path="/Users/gaurang/.codex/memories/MEMORY.md",
    )
    reconciler = LaptopMemoryReconciler(_Agent([atom]), root=tmp_path / "home")

    class _FailingClient:
        provider_id = "openrouter"

        def complete_text(self, *_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        def close(self):
            return None

    monkeypatch.setattr(reconciler, "_provider_fingerprint", lambda **_kwargs: "openrouter")
    monkeypatch.setattr(reconciler, "_provider_client", lambda: _FailingClient())
    result = reconciler.reconcile()

    assert result["changed"] is True
    assert result["provider"] == "deterministic"
    assert len(result["provider_failures"]) == 1
    assert "source attributed" in (tmp_path / "home" / "tree" / "preferences.md").read_text()


def test_ready_provider_synthesizes_nonempty_sections_with_redacted_citations(tmp_path, monkeypatch):
    source = "/Users/gaurang/.codex/memories/MEMORY.md"
    atom = _atom(
        "preference",
        "Keep shared memory concise and source attributed.",
        "preference",
        source_path=source,
    )
    reconciler = LaptopMemoryReconciler(_Agent([atom]), root=tmp_path / "home")

    class _Client:
        provider_id = "openrouter"

        def complete_text(self, *_args, **_kwargs):
            return SimpleNamespace(
                text=(
                    "# Preferences\n\n"
                    f"- Keep shared memory concise and attributed. ({redact_secrets(f'{source}:1')})"
                )
            )

        def close(self):
            return None

    monkeypatch.setattr(reconciler, "_provider_fingerprint", lambda **_kwargs: "openrouter")
    monkeypatch.setattr(reconciler, "_provider_client", lambda: _Client())
    result = reconciler.reconcile()

    assert result["provider"] == "openrouter+deterministic"
    preferences = next(row for row in result["sections"] if row["section"] == "preferences")
    assert preferences["curation_origin"] == "byok_curation"
