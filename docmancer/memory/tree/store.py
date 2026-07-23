"""Production file-first mutation service (checklist A.5).

Every mutation resolves its target server-side through ``AddressIndex``
(never a caller-supplied absolute path), guards existing-file changes with
a content hash, writes through a same-directory temp file plus
``os.replace``, and returns only after the canonical bytes are durable.
There is no DB-first acceptance path and no file-materialisation state
machine: success is defined purely by "the file is on disk."
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from docmancer.memory.tree.addressing import AddressIndex
from docmancer.memory.tree.contracts import (
    VALID_AUTHORITY,
    VALID_CURATION_ORIGIN,
    VALID_SCOPES,
    VALID_STATUS,
)
from docmancer.memory.tree.errors import (
    AlreadyExistsError,
    ForbiddenPathError,
    InvalidFrontmatterFieldError,
    StaleWriteError,
)
from docmancer.memory.tree.parser import (
    TreeMemoryFile,
    new_id,
    now_iso,
    parse_tree_file,
    render_tree_file,
)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        with tmp_path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        tmp_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_durable(path: Path) -> None:
    parent = path.parent
    path.unlink()
    _fsync_directory(parent)


def _validate_choice(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise InvalidFrontmatterFieldError(field, value, allowed)


def _identity_fields(entry: TreeMemoryFile) -> tuple:
    """Fields compared for write-idempotency, excluding revision bookkeeping."""
    return (
        entry.type, entry.scope, entry.authority, entry.project_id,
        tuple(entry.sources), entry.status, tuple(entry.tags),
        entry.curation_origin, entry.body, tuple(sorted(entry.extra_frontmatter.items())),
    )


class TreeStore:
    """File-first mutation service pinned to one memory root."""

    def __init__(self, root: Path, *, trash_root: Path | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.index = AddressIndex(self.root)
        self.trash_root = Path(trash_root).resolve() if trash_root else self.root.parent / "trash"

    # -- create / read / write ------------------------------------------------

    def write(
        self,
        *,
        relative_path: str | Path,
        text: str,
        memory_type: str = "fact",
        scope: str = "global",
        authority: str = "advisory",
        project_id: str | None = None,
        sources: list[str] | None = None,
        status: str = "active",
        tags: list[str] | None = None,
        curation_origin: str = "deliberate_write",
        expect: str | None = None,
    ) -> TreeMemoryFile:
        """Create or update. ``expect`` is ``"absent"`` for a create-only
        write, a content-hash string for a guarded update, or ``None`` --
        which is only valid when the target does not yet exist."""
        _validate_choice("scope", scope, VALID_SCOPES)
        _validate_choice("authority", authority, VALID_AUTHORITY)
        _validate_choice("status", status, VALID_STATUS)
        _validate_choice("curation_origin", curation_origin, VALID_CURATION_ORIGIN)

        path = self.index.resolve_target(relative_path)
        existing: TreeMemoryFile | None = None
        if path.exists():
            if expect == "absent":
                raise AlreadyExistsError(str(relative_path))
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if expect != actual_hash:
                raise StaleWriteError(str(relative_path), expect, actual_hash)
            existing = parse_tree_file(path)
        elif expect not in (None, "absent"):
            raise StaleWriteError(str(relative_path), expect, "<missing>")

        now = now_iso()
        candidate = TreeMemoryFile(
            memory_id=existing.memory_id if existing else new_id(),
            type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id if project_id is not None else (existing.project_id if existing else None),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            sources=sources if sources is not None else (existing.sources if existing else []),
            status=status,
            revision_id=existing.revision_id if existing else "",
            parent_revision_ids=existing.parent_revision_ids if existing else [],
            tags=tags if tags is not None else (existing.tags if existing else []),
            curation_origin=curation_origin,
            extra_frontmatter=existing.extra_frontmatter if existing else {},
            body=text,
            path=path,
        )

        if existing is not None and _identity_fields(candidate) == _identity_fields(existing):
            # Idempotent resubmission: no semantic change, no new revision.
            self.index.note_write(existing)
            return existing

        candidate.revision_id = new_id()
        candidate.parent_revision_ids = [existing.revision_id] if existing and existing.revision_id else []
        data = render_tree_file(candidate)
        _atomic_write(path, data)
        candidate.content_hash = hashlib.sha256(data).hexdigest()
        self.index.note_write(candidate)
        return candidate

    def read(self, address: str) -> TreeMemoryFile:
        return self.index.read(address)

    # -- edit / move / duplicate ----------------------------------------------

    def edit(self, address: str, *, text: str, expected_hash: str) -> TreeMemoryFile:
        """Replace body only, preserving all other frontmatter."""
        entry = self.index.read(address)
        relative_path = entry.path.relative_to(self.root)
        return self.write(
            relative_path=relative_path,
            text=text,
            memory_type=entry.type,
            scope=entry.scope,
            authority=entry.authority,
            project_id=entry.project_id,
            sources=entry.sources,
            status=entry.status,
            tags=entry.tags,
            curation_origin=entry.curation_origin,
            expect=expected_hash,
        )

    def move(self, address: str, new_relative_path: str | Path, *, expected_hash: str) -> TreeMemoryFile:
        entry = self.index.read(address)
        current_hash = hashlib.sha256(entry.path.read_bytes()).hexdigest()
        if expected_hash != current_hash:
            raise StaleWriteError(address, expected_hash, current_hash)
        destination = self.index.resolve_target(new_relative_path)
        if destination.exists():
            raise AlreadyExistsError(str(new_relative_path))
        data = entry.path.read_bytes()
        _atomic_write(destination, data)
        old_path = entry.path
        if old_path != destination:
            _unlink_durable(old_path)
        self.index.note_move(entry.memory_id, destination)
        moved = parse_tree_file(destination)
        assert moved is not None
        return moved

    def duplicate(self, address: str, new_relative_path: str | Path, *, expected_hash: str) -> TreeMemoryFile:
        """Create a new memory (new stable ID) with the same content and
        source attribution as ``address``."""
        entry = self.index.read(address)
        current_hash = hashlib.sha256(entry.path.read_bytes()).hexdigest()
        if expected_hash != current_hash:
            raise StaleWriteError(address, expected_hash, current_hash)
        return self.write(
            relative_path=new_relative_path,
            text=entry.body,
            memory_type=entry.type,
            scope=entry.scope,
            authority=entry.authority,
            project_id=entry.project_id,
            sources=entry.sources,
            status=entry.status,
            tags=entry.tags,
            curation_origin=entry.curation_origin,
            expect="absent",
        )

    # -- trash / restore --------------------------------------------------------

    def trash(self, address: str, *, expected_hash: str, actor_surface: str = "local") -> str:
        """Move a file to recoverable trash. Returns a restore token
        (the memory_id, which is sufficient to locate the trashed file)."""
        entry = self.index.read(address)
        current_hash = hashlib.sha256(entry.path.read_bytes()).hexdigest()
        if expected_hash != current_hash:
            raise StaleWriteError(address, expected_hash, current_hash)

        self.trash_root.mkdir(parents=True, exist_ok=True)
        trashed_path = self.trash_root / f"{entry.memory_id}.md"
        manifest_path = self.trash_root / f"{entry.memory_id}.manifest.json"
        data = entry.path.read_bytes()
        _atomic_write(trashed_path, data)
        manifest = {
            "memory_id": entry.memory_id,
            "original_relative_path": str(entry.path.relative_to(self.root)),
            "expected_hash": current_hash,
            "trashed_at": now_iso(),
            "actor_surface": actor_surface,
        }
        _atomic_write(manifest_path, json.dumps(manifest, indent=2).encode("utf-8"))
        _unlink_durable(entry.path)
        self.index.note_delete(entry.memory_id)
        return entry.memory_id

    def restore(self, token: str) -> TreeMemoryFile:
        trashed_path = self.trash_root / f"{token}.md"
        manifest_path = self.trash_root / f"{token}.manifest.json"
        if not trashed_path.is_file() or not manifest_path.is_file():
            from docmancer.memory.tree.errors import AddressNotFoundError

            raise AddressNotFoundError(f"trash:{token}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        destination = self.index.resolve_target(manifest["original_relative_path"])
        if destination.exists():
            raise AlreadyExistsError(manifest["original_relative_path"])
        data = trashed_path.read_bytes()
        _atomic_write(destination, data)
        _unlink_durable(trashed_path)
        _unlink_durable(manifest_path)
        self.index.note_write(parse_tree_file(destination))
        restored = parse_tree_file(destination)
        assert restored is not None
        return restored

    # -- index lifecycle --------------------------------------------------------

    def drop_index(self) -> None:
        self.index.drop()

    def rebuild_index(self) -> int:
        return self.index.rebuild()
