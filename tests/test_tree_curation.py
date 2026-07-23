"""Deterministic Curation Engine v1 tests (checklist A.8)."""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree.curation import CurationEngine
from docmancer.memory.tree.store import TreeStore


def _engine(tmp_path: Path) -> tuple[CurationEngine, TreeStore]:
    store = TreeStore(tmp_path / "memory")
    engine = CurationEngine(store, tmp_path / "inbox")
    return engine, store


def test_clean_evidence_with_explicit_destination_lands_in_curated_tree(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    result = engine.curate(
        "# Deploy steps\n\n- [decision] Use blue/green deploys\n",
        relative_path="deployment/deploy-steps.md",
        scope="global",
        project_id=None,
    )

    assert result.destination == "tree"
    assert result.entry is not None
    assert result.entry.curation_origin == "deterministic_curation"
    assert result.entry.path.is_file()
    assert result.entry.status == "active"
    assert len(store.index.entries()) == 1


def test_curating_the_same_evidence_twice_does_not_duplicate(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    evidence = "# Deploy steps\n\n- [decision] Use blue/green deploys\n"
    first = engine.curate(evidence, relative_path="deployment/deploy-steps.md")
    assert first.destination == "tree"
    assert len(store.index.entries()) == 1

    # Same normalized content, different casing/whitespace, different target path.
    again = engine.curate(
        "#   Deploy steps  \n\n-   [decision]   Use blue/green deploys   \n",
        relative_path="deployment/deploy-steps-2.md",
    )

    assert again.destination == "duplicate_skip"
    assert again.entry is not None
    assert again.entry.memory_id == first.entry.memory_id
    assert len(store.index.entries()) == 1


def test_ambiguous_evidence_with_no_destination_goes_to_inbox_only(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    result = engine.curate("Just some loose prose with no clear heading or destination.")

    assert result.destination == "inbox"
    assert result.inbox_path is not None
    assert result.inbox_path.is_file()
    assert result.inbox_path.parent == engine.inbox_dir

    # Nothing landed in the curated tree.
    assert store.index.entries() == []

    # No second "review queue" object of any kind was created alongside
    # the inbox file itself: the inbox directory contains exactly the one
    # markdown file the engine wrote, nothing else.
    inbox_contents = list(engine.inbox_dir.iterdir())
    assert inbox_contents == [result.inbox_path]


def test_supersession_archives_old_entry_and_activates_new_one(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    old = store.write(
        relative_path="deployment/legacy.md",
        text="# Legacy deploy process\n\n- [decision] Use manual FTP deploys\n",
        expect="absent",
    )

    result = engine.curate(
        "# New deploy process\n\n- [decision] Use blue/green deploys\n",
        relative_path="deployment/new.md",
        supersedes_address=old.address,
    )

    assert result.destination == "tree"
    assert result.superseded_address == old.address

    archived = store.read(old.address)
    assert archived.status == "archived"
    assert archived.memory_id == old.memory_id

    new_entry = store.read(result.entry.address)
    assert new_entry.status == "active"
    assert new_entry.memory_id != old.memory_id


def test_source_path_is_never_opened_for_writing(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    source_path = tmp_path / "harvested-evidence.md"
    original_text = "# Harvested note\n\nSome captured content.\n"
    source_path.write_text(original_text, encoding="utf-8")

    result = engine.curate(
        original_text,
        relative_path="captured/harvested-note.md",
        source_path=source_path,
    )

    assert result.destination == "tree"
    assert result.entry is not None
    assert str(source_path) in result.entry.sources
    # The original evidence source file on disk is byte-for-byte unchanged.
    assert source_path.read_text(encoding="utf-8") == original_text


def test_source_path_is_never_opened_for_writing_on_inbox_fallback(tmp_path: Path) -> None:
    engine, store = _engine(tmp_path)
    source_path = tmp_path / "loose-note.md"
    original_text = "Loose prose with no heading.\n"
    source_path.write_text(original_text, encoding="utf-8")

    result = engine.curate(original_text, source_path=source_path)

    assert result.destination == "inbox"
    assert source_path.read_text(encoding="utf-8") == original_text
