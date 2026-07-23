"""Dry-run-first migration tooling from ``MemoryRecord`` files to the
Release A tree (checklist A.4).

This module is tooling to be reviewed by a human before it is ever pointed
at real data. It is not wired into the CLI, MCP surface, or any default
config path by this change, and it never guesses a production root.

**No hidden defaults.** Every public function below takes its record-store
root, backup directory, and/or tree root(s) as explicit arguments. None of
them fall back to ``~/.docmancer``, ``Path.home()``, ``DOCMANCER_HOME``, or
any other environment-derived location. Callers (a future CLI command, a
human running this interactively, or a test) must supply real paths; there
is no way to invoke this module against "the current machine's real memory"
by accident.

## scope_kind/audience_kind/applicability_kind -> tree scope/authority

The frozen tree contract (``contracts.py``) already says explicitly that
"team" is expressed by *which root* a file lives under, not by a value
inside frontmatter (`scope` there is just ``{"global", "project"}``). That
matches ``MemoryRecord.applicability_kind`` almost exactly, so the mapping
used here is:

    tree `scope`     = record.applicability_kind   ("global" or "project" --
                        already the same two-value vocabulary as
                        contracts.VALID_SCOPES, no translation needed)
    tree `authority`  = "mandatory" if record.audience_kind == "team"
                        else "advisory"
    which tree root   = chosen by the caller-supplied ``tree_store_factory``
                        / ``tree_root_for_scope`` callable, keyed on
                        (record.scope_kind, record.project_path)

Rationale:

- ``applicability_kind`` is already binary (global/project) and already
  means "does this apply everywhere or just to one project", which is
  exactly what tree `scope` means. Reusing it directly avoids inventing a
  second, possibly-inconsistent mapping.
- ``audience_kind`` ("personal" vs "team") is the closest existing concept
  to "was this reviewed/curated by more than one person, or is it one
  person's working memory". Team-authored/team-scoped content is treated as
  already curated, so it becomes `authority="mandatory"` in the new tree
  (it always survives Context Compiler selection). Personal content stays
  `authority="advisory"` (ordinary relevance-ranked content).
- Physical "team-ness" (committed to a repo's ``.docmancer/memory`` versus a
  user's personal store versus the cross-project team-memory directory)
  is preserved by directing the migrated file into a different tree root,
  never by adding a third scope value -- matching the frozen contract's own
  design instead of working around it.

This gives the following concrete table (derived, not exhaustive -- any
future audience/applicability combination falls out of the same two rules):

| scope_kind | audience_kind | applicability_kind | tree scope | tree authority |
|------------|----------------|---------------------|------------|-----------------|
| global     | personal       | global              | global     | advisory        |
| global     | team           | global              | global     | mandatory       |
| project    | personal       | project             | project    | advisory        |
| team       | team           | project             | project    | mandatory       |

Source attribution (`source_path`), the original record id (as the new
`memory_id`, unchanged), and the original `created_at`/`updated_at` are
always preserved so a migrated file never looks like newly learned memory.
The original record id, revision id, and source path are additionally kept
in `extra_frontmatter` under `migrated_from_*` keys as a compatibility
trail for the agreed transition period.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable

from docmancer.memory.records import MemoryRecord, MemoryRecordStore
from docmancer.memory.tree.contracts import (
    VALID_AUTHORITY,
    VALID_CURATION_ORIGIN,
    VALID_SCOPES,
    VALID_STATUS,
)
from docmancer.memory.tree.parser import TreeMemoryFile, new_id, parse_tree_file, render_tree_file
from docmancer.memory.tree.store import TreeStore

MIGRATION_CURATION_ORIGIN = "migration"


# -- small local helpers (deliberately not imported from records.py/store.py
#    private names, to keep this module's dependency surface explicit) -----

def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (value[:48].rstrip("-") or "memory")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _tree_scope_and_authority(record: MemoryRecord) -> tuple[str, str]:
    """See module docstring for the full mapping table and rationale."""
    scope = record.applicability_kind if record.applicability_kind in VALID_SCOPES else "global"
    authority = "mandatory" if record.audience_kind == "team" else "advisory"
    return scope, authority


# -- 1. inventory (read-only) ------------------------------------------------

def inventory(
    record_store: MemoryRecordStore,
    project_paths: list[str] | None = None,
) -> dict:
    """A read-only report of what exists. Never writes anything.

    Covers checklist items "inventory existing global/project/team records"
    and "inventory revision lineage, tombstones, suppressions, project IDs,
    pack references, and cloud revision state" at the level this local
    client can see them (there is no live cloud connection here).
    """
    records = record_store.records(project_paths=project_paths)
    by_scope_kind: dict[str, int] = {}
    by_audience_kind: dict[str, int] = {}
    by_applicability_kind: dict[str, int] = {}
    project_ids: set[str] = set()
    pack_ids: set[str] = set()
    revision_count = 0
    for record in records:
        by_scope_kind[record.scope_kind] = by_scope_kind.get(record.scope_kind, 0) + 1
        by_audience_kind[record.audience_kind] = by_audience_kind.get(record.audience_kind, 0) + 1
        by_applicability_kind[record.applicability_kind] = (
            by_applicability_kind.get(record.applicability_kind, 0) + 1
        )
        if record.project_id:
            project_ids.add(record.project_id)
        pack_ids.update(record.pack_ids)
        revision_count += len(record_store.revisions(record.record_id))

    tombstones = record_store.tombstones()
    return {
        "total_records": len(records),
        "by_scope_kind": by_scope_kind,
        "by_audience_kind": by_audience_kind,
        "by_applicability_kind": by_applicability_kind,
        "distinct_project_ids": sorted(project_ids),
        "distinct_pack_ids": sorted(pack_ids),
        "total_revisions": revision_count,
        "tombstone_count": len(tombstones),
        "tombstone_record_ids": sorted({t.get("record_id") for t in tombstones if t.get("record_id")}),
    }


# -- 2. backup ---------------------------------------------------------------

def backup(record_store_root: Path, backup_dir: Path) -> Path:
    """Copy the entire record-store root to ``backup_dir``.

    Refuses to overwrite an existing non-empty ``backup_dir`` -- a prior
    backup is never silently merged with or clobbered by a new one.
    """
    record_store_root = Path(record_store_root)
    backup_dir = Path(backup_dir)
    if backup_dir.exists() and any(backup_dir.iterdir()):
        raise FileExistsError(
            f"refusing to back up into non-empty directory {backup_dir}; "
            "choose a fresh backup_dir or remove the prior backup first"
        )
    if backup_dir.exists():
        backup_dir.rmdir()
    if not record_store_root.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    shutil.copytree(record_store_root, backup_dir)
    return backup_dir


def rollback_migration(backup_dir: Path, record_store_root: Path) -> Path:
    """Restore ``backup_dir`` back over ``record_store_root``.

    Manual-use-only recovery path: removes whatever currently exists at
    ``record_store_root`` and replaces it with the backup's contents.
    """
    backup_dir = Path(backup_dir)
    record_store_root = Path(record_store_root)
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"no backup found at {backup_dir}")
    if record_store_root.exists():
        shutil.rmtree(record_store_root)
    shutil.copytree(backup_dir, record_store_root)
    return record_store_root


# -- 3. plan (dry run, no writes) --------------------------------------------

def plan_migration(
    record_store: MemoryRecordStore,
    project_paths: list[str] | None,
    tree_root_for_scope: Callable[[MemoryRecord], Path],
) -> list[dict]:
    """Compute, without writing anything, what ``apply_migration`` would do.

    One dict per existing :class:`MemoryRecord`. ``memory_id`` always equals
    the original ``record_id`` (identity is preserved, never regenerated).
    ``created_at``/``updated_at`` are copied verbatim from the record, not
    set to "now", so applying the plan never looks like newly learned
    memory. Duplicate text within the same destination scope, and records
    that appear in the tombstone/suppression list, are flagged with a
    warning and marked ``skip: True`` so ``apply_migration`` will not
    resurrect or duplicate them.
    """
    records = record_store.records(project_paths=project_paths)
    tombstoned_ids = {t.get("record_id") for t in record_store.tombstones() if t.get("record_id")}

    plan: list[dict] = []
    seen_paths: set[str] = set()
    seen_content: dict[tuple[str, str | None, str], str] = {}  # (scope, project_path, hash) -> record_id

    for record in records:
        warnings: list[str] = []
        skip = False

        tree_scope, authority = _tree_scope_and_authority(record)
        tree_root = Path(tree_root_for_scope(record))
        relative_path = f"migrated/{_slug(record.type)}/{_slug(record.text)}-{record.record_id[:8]}.md"

        if relative_path in seen_paths:
            warnings.append(f"duplicate proposed path {relative_path!r}; would skip")
            skip = True
        seen_paths.add(relative_path)

        content_key = (tree_scope, record.project_id, record.content_hash)
        prior_record_id = seen_content.get(content_key)
        if prior_record_id is not None:
            warnings.append(
                f"duplicate text detected (same as record {prior_record_id}) in scope "
                f"{tree_scope!r}; would skip"
            )
            skip = True
        else:
            seen_content[content_key] = record.record_id

        if record.record_id in tombstoned_ids:
            warnings.append(
                "record_id appears in local tombstones (forgotten); would skip to avoid "
                "resurrecting suppressed content"
            )
            skip = True

        status = "archived" if record.deleted else "active"
        sources = [record.source_path] if record.source_path else []

        plan.append(
            {
                "record_id": record.record_id,
                "old_scope_kind": record.scope_kind,
                "old_project_path": record.project_path,
                "old_source_path": record.source_path,
                "memory_id": record.record_id,
                "tree_root": str(tree_root),
                "relative_path": relative_path,
                "text": record.text,
                "frontmatter": {
                    "memory_type": record.type,
                    "scope": tree_scope,
                    "authority": authority,
                    "project_id": record.project_id,
                    "sources": sources,
                    "status": status,
                    "tags": list(record.tags),
                    "curation_origin": MIGRATION_CURATION_ORIGIN,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
                "extra_frontmatter": {
                    "migrated_from_record_id": record.record_id,
                    "migrated_from_revision_id": record.revision_id,
                    "migrated_from_source_path": record.source_path,
                },
                "warnings": warnings,
                "skip": skip,
            }
        )
    return plan


# -- 4. apply (actually writes) ---------------------------------------------

def apply_migration(
    plan: list[dict],
    record_store: MemoryRecordStore,
    tree_store_factory: Callable[[str, str | None], TreeStore],
) -> dict:
    """Perform the writes described by a previously computed ``plan``.

    Idempotent: re-running over the same plan skips anything already
    written by a prior migration run rather than duplicating it. Tolerates
    partial failure: one item failing is recorded in the summary and does
    not abort the remaining items.
    """
    created = 0
    skipped = 0
    failed = 0
    results: list[dict] = []

    for item in plan:
        record_id = item["record_id"]
        if item.get("skip"):
            skipped += 1
            results.append(
                {
                    "record_id": record_id,
                    "status": "skipped",
                    "reason": "; ".join(item.get("warnings") or ["planned skip"]),
                }
            )
            continue

        try:
            store = tree_store_factory(item["old_scope_kind"], item["old_project_path"])
            fm = item["frontmatter"]
            if fm["scope"] not in VALID_SCOPES:
                raise ValueError(f"invalid scope {fm['scope']!r}")
            if fm["authority"] not in VALID_AUTHORITY:
                raise ValueError(f"invalid authority {fm['authority']!r}")
            if fm["status"] not in VALID_STATUS:
                raise ValueError(f"invalid status {fm['status']!r}")
            if fm["curation_origin"] not in VALID_CURATION_ORIGIN:
                raise ValueError(f"invalid curation_origin {fm['curation_origin']!r}")

            target = store.index.resolve_target(item["relative_path"])

            if target.exists():
                existing = parse_tree_file(target)
                if (
                    existing is not None
                    and existing.memory_id == item["memory_id"]
                    and existing.curation_origin == MIGRATION_CURATION_ORIGIN
                ):
                    # Already migrated by a prior run of this same plan.
                    skipped += 1
                    results.append(
                        {"record_id": record_id, "status": "skipped", "reason": "already migrated (re-run safe)"}
                    )
                    continue
                raise FileExistsError(
                    f"target {item['relative_path']!r} already exists and is not this "
                    "migration's own output; refusing to overwrite"
                )

            entry = TreeMemoryFile(
                memory_id=item["memory_id"],
                type=fm["memory_type"],
                scope=fm["scope"],
                authority=fm["authority"],
                project_id=fm["project_id"],
                created_at=fm["created_at"],
                updated_at=fm["updated_at"],
                sources=fm["sources"],
                status=fm["status"],
                revision_id=new_id(),
                parent_revision_ids=[],
                tags=fm["tags"],
                curation_origin=fm["curation_origin"],
                extra_frontmatter=dict(item.get("extra_frontmatter") or {}),
                body=item["text"],
                path=target,
            )
            data = render_tree_file(entry)
            _atomic_write(target, data)
            entry.content_hash = hashlib.sha256(data).hexdigest()
            store.index.note_write(entry)

            created += 1
            results.append({"record_id": record_id, "status": "created", "address": entry.address})
        except Exception as exc:  # noqa: BLE001 - partial-failure tolerance is required by design
            failed += 1
            results.append({"record_id": record_id, "status": "failed", "error": str(exc)})
            continue

    return {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


__all__ = [
    "MIGRATION_CURATION_ORIGIN",
    "inventory",
    "backup",
    "rollback_migration",
    "plan_migration",
    "apply_migration",
]
