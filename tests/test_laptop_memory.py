from types import SimpleNamespace

import pytest

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
        "canonical-memory.md",
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


def _tree(tmp_path):
    return tmp_path / "home" / "tree"


def test_self_description_names_every_alias_for_the_store(tmp_path):
    """Recall had no text saying what this store is called, so "where is my
    canonical memory?" retrieved an installed SKILL.md instead."""
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")

    reconciler.reconcile(use_provider=False)

    body = (_tree(tmp_path) / "canonical-memory.md").read_text()
    for alias in (
        "canonical memory",
        "master memory",
        "laptop memory",
        "machine-wide memory",
        "global memory",
        "curated memory",
        "the memory tree",
        "long-term memory",
        "the central memory",
        "single source of truth",
    ):
        assert alias in body, alias


def test_self_description_locates_the_tree_and_disowns_skill_files(tmp_path):
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")

    reconciler.reconcile(use_provider=False)

    body = (_tree(tmp_path) / "canonical-memory.md").read_text()
    assert str(_tree(tmp_path)) in body
    # The exact confusion that produced the wrong answer.
    assert "are not canonical memory" in body
    assert "SKILL.md" in body
    assert "CLAUDE.md" in body
    # Derived indexes must not be mistaken for the store either.
    assert "memory.db" in body
    assert "`docmancer read --global <address>`" in body


def test_self_description_lists_each_section_file(tmp_path):
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")

    reconciler.reconcile(use_provider=False)

    body = (_tree(tmp_path) / "canonical-memory.md").read_text()
    for name in ("about.md", "preferences.md", "working-principles.md", "active-projects.md"):
        assert f"`{name}`" in body


def test_self_description_is_regenerated_when_deleted(tmp_path):
    """The fingerprint short-circuit must not leave the entry missing."""
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    target = _tree(tmp_path) / "canonical-memory.md"
    target.unlink()

    result = reconciler.reconcile(use_provider=False)

    assert result["changed"] is True
    assert target.is_file()


def test_self_description_never_goes_through_the_provider(tmp_path, monkeypatch):
    """A paraphrasing model would drop the alias terms that make it findable."""
    atom = _atom(
        "preference",
        "Prefer findings-first technical reviews.",
        "preference",
        source_path="/Users/gaurang/.codex/memories/MEMORY.md",
    )
    reconciler = LaptopMemoryReconciler(_Agent([atom]), root=tmp_path / "home")

    class _Client:
        provider_id = "openrouter"

        def complete_text(self, *_args, **_kwargs):
            return SimpleNamespace(text="# Rewritten\n\n- The model paraphrased this away.")

        def close(self):
            return None

    monkeypatch.setattr(reconciler, "_provider_fingerprint", lambda **_kwargs: "openrouter")
    monkeypatch.setattr(reconciler, "_provider_client", lambda: _Client())
    result = reconciler.reconcile()

    body = (_tree(tmp_path) / "canonical-memory.md").read_text()
    assert "master memory" in body
    assert "paraphrased this away" not in body
    entry = next(row for row in result["sections"] if row["section"] == "canonical-memory")
    assert entry["curation_origin"] == "deterministic_curation"


def test_self_description_does_not_skew_the_provider_label(tmp_path, monkeypatch):
    """It is deterministic by design, so a fully curated run stays fully curated."""
    atoms = [
        _atom(
            "about",
            "Gaurang builds local-first developer tools.",
            "fact",
            source_path="/Users/gaurang/Documents/Claude_Workspace/About/Gaurang CV.md",
            tags=["local-profile"],
        ),
        _atom(
            "preference",
            "Prefer findings-first technical reviews.",
            "preference",
            source_path="/Users/gaurang/.codex/memories/MEMORY.md",
        ),
        _atom(
            "principle",
            "Reconcile shared memory automatically.",
            "constraint",
            source_path="/Users/gaurang/.codex/memories/MEMORY.md",
        ),
        _atom(
            "project",
            "Docmancer is the active product.",
            "decision",
            source_path=str(tmp_path / "repo" / "AGENTS.md"),
            scope_kind="project",
            project_path=str(tmp_path / "repo"),
        ),
    ]
    reconciler = LaptopMemoryReconciler(_Agent(atoms), root=tmp_path / "home")

    class _Client:
        """Echoes the evidence back, which satisfies the section validator."""

        provider_id = "openrouter"

        def complete_text(self, messages, *_args, **_kwargs):
            prompt = messages[0]["content"]
            return SimpleNamespace(text=prompt.split("Do not use em dashes.\n\n", 1)[1])

        def close(self):
            return None

    monkeypatch.setattr(reconciler, "_provider_fingerprint", lambda **_kwargs: "openrouter")
    monkeypatch.setattr(reconciler, "_provider_client", lambda: _Client())
    result = reconciler.reconcile()

    assert result["provider_failures"] == []
    assert result["provider"] == "openrouter"
    # The self-description is still present and still deterministic.
    entry = next(row for row in result["sections"] if row["section"] == "canonical-memory")
    assert entry["curation_origin"] == "deterministic_curation"


def _compile(tree_root, task):
    from docmancer.memory.tree.compiler import ContextRequest, compile_context
    from docmancer.memory.tree.store import TreeStore

    bundle = compile_context(
        TreeStore(tree_root).index,
        ContextRequest(task=task, project_path="/tmp", token_budget=4000),
    )
    return [item.title for item in bundle.curated_memory]


def test_terminology_questions_retrieve_the_self_description(tmp_path):
    """The acceptance test for the whole entry: every name the store answers to
    has to actually pull it out of retrieval, ranked first."""
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    tree = _tree(tmp_path)

    for task in (
        "where is my canonical memory?",
        "where is my master memory?",
        "what is my laptop memory?",
        "where does docmancer keep machine-wide memory?",
        "where is the global memory stored?",
        "what is the memory tree?",
        "where is my curated memory?",
        "where does docmancer store the single source of truth?",
        "what is my long-term memory?",
        "where is the central memory kept?",
    ):
        titles = _compile(tree, task)
        assert titles and titles[0] == "Canonical Memory", (task, titles)


def test_self_description_stays_out_of_unrelated_questions(tmp_path):
    """It is a long document, so it must not crowd real memory off the budget."""
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    tree = _tree(tmp_path)

    from docmancer.memory.tree.store import TreeStore

    TreeStore(tree).write(
        relative_path="deploy.md",
        text="# Deploy\n\nProduction deploys run through Railway with a manual approval gate.",
        memory_type="note",
        scope="global",
        authority="advisory",
        sources=[],
        tags=[],
        curation_origin="deliberate_write",
        expect="absent",
        actor_surface="test",
        actor_harness="docmancer",
        operation="write",
    )

    assert _compile(tree, "how do we deploy to production?") == ["Deploy"]
    assert _compile(tree, "what are the interest rate batches?") == []
    assert _compile(tree, "zebra quantum flux capacitor") == []


def _pref_atom(atom_id="preference", text="Keep shared memory concise and source attributed."):
    return _atom(atom_id, text, "preference", source_path="/Users/gaurang/.codex/memories/MEMORY.md")


def test_pinned_zone_survives_a_regeneration(tmp_path):
    """The defect this whole zone split exists to fix: before it, any note a
    human or an agent wrote into a section file was destroyed on the next sync."""
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)

    reconciler.pin("preferences", "Never use em dashes in public prose.")

    # New evidence changes the fingerprint, so the generated zone is rebuilt.
    reconciler.agent._atoms.append(_pref_atom("preference-2", "Prefer findings-first reviews."))
    result = reconciler.reconcile(use_provider=False)

    assert result["changed"] is True
    section = reconciler.read_section("preferences")
    assert "Never use em dashes in public prose." in section["pinned"]
    assert "findings-first" in section["generated"]
    assert "Never use em dashes" not in section["generated"]


def test_pinning_does_not_trigger_a_provider_run(tmp_path):
    """Pinned text is the user's own words and never needs regenerating, so it
    must stay out of the evidence fingerprint."""
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    before = reconciler._state()["evidence_fingerprint"]

    reconciler.pin("preferences", "A durable note.")

    assert reconciler.reconcile(use_provider=False)["changed"] is False
    assert reconciler._state()["evidence_fingerprint"] == before


def test_pin_is_idempotent_and_unpin_removes(tmp_path):
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)

    assert reconciler.pin("preferences", "One note.")["changed"] is True
    assert reconciler.pin("preferences", "One note.")["changed"] is False
    assert reconciler.read_section("preferences")["pinned_lines"] == 1

    assert reconciler.unpin("preferences", "One note")["removed"] == 1
    assert reconciler.read_section("preferences")["pinned_lines"] == 0

    with pytest.raises(ValueError, match="no pinned line"):
        reconciler.unpin("preferences", "missing")


def test_pin_rejects_a_stale_content_hash(tmp_path):
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)

    with pytest.raises(ValueError, match="changed since it was read"):
        reconciler.set_pinned("preferences", "- note", expect="0" * 64)


def test_pin_rejects_a_concurrent_pinned_zone_write(tmp_path, monkeypatch):
    """A CLI or MCP pin must not erase a note written after its initial read."""
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    set_pinned = reconciler.set_pinned

    def race(section, pinned, *, expect=None):
        set_pinned(section, "- concurrent note")
        return set_pinned(section, pinned, expect=expect)

    monkeypatch.setattr(reconciler, "set_pinned", race)

    with pytest.raises(ValueError, match="changed since it was read"):
        reconciler.pin("preferences", "later note")

    assert reconciler.read_section("preferences")["pinned"] == "- concurrent note"


def test_unpin_rejects_a_concurrent_pinned_zone_write(tmp_path, monkeypatch):
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    reconciler.pin("preferences", "remove me")
    set_pinned = reconciler.set_pinned

    def race(section, pinned, *, expect=None):
        set_pinned(section, "- remove me\n- concurrent note")
        return set_pinned(section, pinned, expect=expect)

    monkeypatch.setattr(reconciler, "set_pinned", race)

    with pytest.raises(ValueError, match="changed since it was read"):
        reconciler.unpin("preferences", "remove me")

    assert reconciler.read_section("preferences")["pinned"] == (
        "- remove me\n- concurrent note"
    )


def test_self_description_cannot_be_pinned(tmp_path):
    """It is regenerated wholesale from a versioned constant and carries no
    pinned zone forward, so accepting a pin there would be a broken promise."""
    reconciler = LaptopMemoryReconciler(_Agent([]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)

    with pytest.raises(ValueError, match="cannot be pinned"):
        reconciler.pin("canonical-memory", "note")


def test_guard_body_write_rejects_generated_zone_edits(tmp_path):
    from docmancer.memory.tree.zones import ZoneViolation, replace_pinned

    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    body = reconciler.read_section("preferences")["body"]

    # Editing only the pinned zone is allowed.
    reconciler.guard_body_write("preferences", replace_pinned(body, "- fine", section="preferences"))

    with pytest.raises(ZoneViolation) as caught:
        reconciler.guard_body_write("preferences", body.replace("concise", "TAMPERED"))
    assert "pin" in caught.value.payload()["recovery"]


def test_status_reports_sections_without_a_provider_call(tmp_path):
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)
    reconciler.pin("preferences", "A durable note.")

    status = reconciler.status()

    assert status["available"] is True
    assert status["provider"] == "deterministic"
    assert status["pinned_total"] == 1
    assert {row["section"] for row in status["sections"]} == {
        "about",
        "preferences",
        "working-principles",
        "active-projects",
        "canonical-memory",
    }
    assert all(row["present"] for row in status["sections"])


def test_legacy_unzoned_section_migrates_without_losing_content(tmp_path):
    """Existing machines have unmarked files. The first zoned reconcile must not
    promote their generated body into a permanently pinned block."""
    reconciler = LaptopMemoryReconciler(_Agent([_pref_atom()]), root=tmp_path / "home")
    reconciler.reconcile(use_provider=False)

    path = tmp_path / "home" / "tree" / "preferences.md"
    raw = path.read_text()
    path.write_text(raw.replace(_zone_markers(raw), ""), encoding="utf-8")

    reconciler.agent._atoms.append(_pref_atom("preference-3", "Another durable preference."))
    reconciler.reconcile(use_provider=False)

    section = reconciler.read_section("preferences")
    assert section["pinned"] == ""
    assert "Another durable preference." in section["generated"]


def _zone_markers(raw: str) -> str:
    """The pinned block from a rendered file, used to simulate a pre-zone file."""
    from docmancer.memory.tree.zones import PINNED_CLOSE, PINNED_OPEN

    start = raw.index(PINNED_OPEN)
    return raw[start:raw.index(PINNED_CLOSE) + len(PINNED_CLOSE)]
