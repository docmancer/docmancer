"""Migration tooling tests (checklist A.4).

Every test here uses a synthetic ``tmp_path``-rooted ``MemoryRecordStore``
and ``TreeStore``. Nothing in this file touches a real home directory.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from docmancer.memory.records import MemoryRecordStore
from docmancer.memory.tree.migration import (
    apply_migration,
    backup,
    inventory,
    plan_migration,
    rollback_migration,
)
from docmancer.memory.tree.parser import parse_tree_file
from docmancer.memory.tree.store import TreeStore


def _seed_records(tmp_path: Path) -> tuple[MemoryRecordStore, Path]:
    """A synthetic record store with a representative mix of records."""
    record_root = tmp_path / "record-home"
    project_dir = tmp_path / "project-a"
    project_dir.mkdir()
    store = MemoryRecordStore(record_root)

    personal_global = store.add(
        "Prefer pytest over unittest for new tests.",
        scope_kind="global",
        tags=["testing"],
    )
    personal_project = store.add(
        "Staging DB lives in us-east-1.",
        scope_kind="project",
        project_path=project_dir,
    )
    team_record = store.add(
        "Ship blue/green deploys for production.",
        scope_kind="team",
        project_path=project_dir,
        audience_kind="team",
        promoted_from=personal_global.record_id,
    )
    return store, project_dir


def _tree_root_for_scope(record, tmp_path: Path) -> Path:
    if record.scope_kind == "global":
        return tmp_path / "tree-global"
    return tmp_path / "tree-project"


def _tree_store_factory(tmp_path: Path):
    stores: dict[str, TreeStore] = {}

    def factory(scope_kind: str, project_path: str | None) -> TreeStore:
        root = tmp_path / "tree-global" if scope_kind == "global" else tmp_path / "tree-project"
        key = str(root)
        if key not in stores:
            stores[key] = TreeStore(root)
        return stores[key]

    return factory


# -- inventory ----------------------------------------------------------------


def test_inventory_is_read_only_and_reports_breakdowns(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    before = sorted(p for p in store.root.rglob("*") if p.is_file())

    report = inventory(store, project_paths=[str(project_dir)])

    after = sorted(p for p in store.root.rglob("*") if p.is_file())
    assert before == after  # zero side effects

    assert report["total_records"] == 3
    assert report["by_scope_kind"] == {"global": 1, "project": 1, "team": 1}
    assert report["by_audience_kind"]["team"] == 1
    assert report["by_audience_kind"]["personal"] == 2
    assert "project" in report["by_applicability_kind"]
    assert report["tombstone_count"] == 0


# -- backup ---------------------------------------------------------------------


def test_backup_copies_files_unchanged_and_refuses_nonempty_target(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    backup_dir = tmp_path / "backup-1"

    result = backup(store.root, backup_dir)
    assert result == backup_dir
    original_files = {p.relative_to(store.root) for p in store.root.rglob("*") if p.is_file()}
    backed_up_files = {p.relative_to(backup_dir) for p in backup_dir.rglob("*") if p.is_file()}
    assert original_files == backed_up_files
    for rel in original_files:
        assert (store.root / rel).read_bytes() == (backup_dir / rel).read_bytes()

    with pytest.raises(FileExistsError):
        backup(store.root, backup_dir)


def test_backup_allows_reuse_of_an_empty_directory(tmp_path: Path) -> None:
    store, _ = _seed_records(tmp_path)
    backup_dir = tmp_path / "backup-empty"
    backup_dir.mkdir()

    result = backup(store.root, backup_dir)
    assert result == backup_dir
    assert any(backup_dir.rglob("*"))


# -- plan_migration -------------------------------------------------------------


def test_plan_preserves_identity_and_timestamps_without_writing(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    tree_files_before = list(tmp_path.rglob("*.md"))

    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )

    assert list(tmp_path.rglob("*.md")) == [
        p for p in tree_files_before
    ]  # plan_migration wrote nothing new
    assert len(plan) == 3

    by_record_id = {item["record_id"]: item for item in plan}
    original_records = {r.record_id: r for r in store.records(project_paths=[str(project_dir)])}

    for record_id, item in by_record_id.items():
        original = original_records[record_id]
        assert item["memory_id"] == original.record_id  # identity preserved, not regenerated
        assert item["frontmatter"]["created_at"] == original.created_at  # copied, not "now"
        assert item["frontmatter"]["updated_at"] == original.updated_at
        assert item["frontmatter"]["curation_origin"] == "migration"
        assert item["frontmatter"]["sources"] == (
            [original.source_path] if original.source_path else []
        )
        assert item["frontmatter"]["tags"] == list(original.tags)
        assert item["extra_frontmatter"]["migrated_from_record_id"] == original.record_id
        assert item["extra_frontmatter"]["migrated_from_revision_id"] == original.revision_id
        assert item["text"] == original.text

    # audience/applicability semantics preserved via the documented mapping
    team_item = next(
        item for item in plan if original_records[item["record_id"]].scope_kind == "team"
    )
    assert team_item["frontmatter"]["authority"] == "mandatory"
    assert team_item["frontmatter"]["scope"] == "project"

    personal_global_item = next(
        item for item in plan if original_records[item["record_id"]].scope_kind == "global"
    )
    assert personal_global_item["frontmatter"]["authority"] == "advisory"
    assert personal_global_item["frontmatter"]["scope"] == "global"


def test_plan_flags_duplicate_text_as_skip(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    store.add("Staging DB lives in us-east-1.", scope_kind="project", project_path=project_dir)

    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    skipped_items = [item for item in plan if item["skip"]]
    assert len(skipped_items) == 1
    assert "duplicate text" in skipped_items[0]["warnings"][0]


def test_plan_flags_tombstoned_record_for_skip(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    victim = store.add("Temporary note to forget.", scope_kind="global")
    store.add_tombstone(victim.to_atom())

    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    item = next(i for i in plan if i["record_id"] == victim.record_id)
    assert item["skip"] is True
    assert any("tombstone" in w for w in item["warnings"])


# -- apply_migration --------------------------------------------------------------


def test_apply_writes_readable_tree_files_matching_the_plan(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    factory = _tree_store_factory(tmp_path)

    summary = apply_migration(plan, store, factory)
    assert summary["created"] == 3
    assert summary["failed"] == 0
    assert summary["skipped"] == 0

    global_store = TreeStore(tmp_path / "tree-global")
    project_store = TreeStore(tmp_path / "tree-project")

    original_records = {r.record_id: r for r in store.records(project_paths=[str(project_dir)])}
    for item in plan:
        original = original_records[item["record_id"]]
        target_store = global_store if item["frontmatter"]["scope"] == "global" else project_store
        entry = target_store.read(f"docmancer://memory/{item['memory_id']}")
        assert entry.memory_id == original.record_id
        assert entry.created_at == original.created_at
        assert entry.curation_origin == "migration"
        assert original.text in entry.body


def test_apply_is_idempotent_on_rerun(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    factory = _tree_store_factory(tmp_path)

    first = apply_migration(plan, store, factory)
    assert first["created"] == 3

    second = apply_migration(plan, store, factory)
    assert second["created"] == 0
    assert second["skipped"] == 3
    assert second["failed"] == 0

    # No duplicate files were produced by the second run.
    tree_root = tmp_path / "tree-project"
    all_md = list(tree_root.rglob("*.md"))
    memory_ids = [parse_tree_file(p).memory_id for p in all_md if parse_tree_file(p)]
    assert len(memory_ids) == len(set(memory_ids))


def test_apply_reports_partial_failure_and_continues(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    factory = _tree_store_factory(tmp_path)

    # Pre-create a conflicting, non-migration file at the exact target path
    # of one plan item so that item's write fails.
    doomed_item = plan[0]
    doomed_target = (tmp_path / doomed_item["tree_root"]).joinpath(doomed_item["relative_path"])
    doomed_target.parent.mkdir(parents=True, exist_ok=True)
    doomed_target.write_text("---\nmemory_id: not-migration\n---\n\nConflict.\n", encoding="utf-8")

    summary = apply_migration(plan, store, factory)
    assert summary["failed"] == 1
    assert summary["created"] == 2
    failed_results = [r for r in summary["results"] if r["status"] == "failed"]
    assert failed_results[0]["record_id"] == doomed_item["record_id"]
    assert "already exists" in failed_results[0]["error"]

    # The other two records still migrated successfully despite the failure.
    succeeded = [r for r in summary["results"] if r["status"] == "created"]
    assert len(succeeded) == 2


def test_apply_reports_failure_when_target_directory_is_read_only(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    plan = plan_migration(
        store,
        [str(project_dir)],
        lambda record: _tree_root_for_scope(record, tmp_path),
    )
    factory = _tree_store_factory(tmp_path)

    tree_project_root = tmp_path / "tree-project"
    tree_project_root.mkdir(parents=True, exist_ok=True)
    readonly_mode = stat.S_IRUSR | stat.S_IXUSR
    original_mode = tree_project_root.stat().st_mode
    os.chmod(tree_project_root, readonly_mode)
    try:
        summary = apply_migration(plan, store, factory)
    finally:
        os.chmod(tree_project_root, original_mode)

    assert summary["failed"] >= 1
    failed_ids = {r["record_id"] for r in summary["results"] if r["status"] == "failed"}
    project_scoped = {
        item["record_id"] for item in plan if item["frontmatter"]["scope"] == "project"
    }
    assert failed_ids & project_scoped


# -- rollback -------------------------------------------------------------------


def test_rollback_restores_backup_over_original_location(tmp_path: Path) -> None:
    store, project_dir = _seed_records(tmp_path)
    backup_dir = tmp_path / "backup-2"
    backup(store.root, backup_dir)

    original_files = {p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}

    # Simulate destructive/partial migration damage to the live store.
    for path in store.root.rglob("*.md"):
        path.unlink()
    extra = store.root / "memories" / "garbage.md"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("not a real record", encoding="utf-8")

    restored_root = rollback_migration(backup_dir, store.root)
    assert restored_root == store.root

    restored_files = {p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert restored_files == original_files
    assert not extra.exists()
