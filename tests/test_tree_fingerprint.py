"""Tests for the deterministic chunking/hashing/fingerprint layer
(checklist A.7, scoped to pure functions -- no embedding model, no
sqlite-vec).
"""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree.fingerprint import (
    chunk_body,
    chunk_hash,
    diff_chunks,
    file_fingerprint,
)
from docmancer.memory.tree.store import TreeStore


def test_chunk_body_splits_on_blank_lines_deterministically() -> None:
    body = "# Title\n\nFirst paragraph.\n\nSecond paragraph.\n"
    assert chunk_body(body) == ["# Title", "First paragraph.", "Second paragraph."]
    # Same input, called twice, produces the same list and order.
    assert chunk_body(body) == chunk_body(body)


def test_chunk_body_drops_empty_chunks() -> None:
    body = "A\n\n\n\nB\n\n   \n\nC"
    assert chunk_body(body) == ["A", "B", "C"]


def test_chunk_body_empty_string() -> None:
    assert chunk_body("") == []


def test_chunk_hash_stable_and_normalizes_whitespace() -> None:
    assert chunk_hash("Hello world.") == chunk_hash("Hello world.")
    # Reformatted whitespace (rewrapped line) hashes the same.
    assert chunk_hash("Hello   world.") == chunk_hash("Hello\nworld.")
    assert chunk_hash("  Hello world.  ") == chunk_hash("Hello world.")


def test_chunk_hash_changes_with_content() -> None:
    assert chunk_hash("Hello world.") != chunk_hash("Hello there.")


def test_chunk_hash_is_sha256_hex() -> None:
    digest = chunk_hash("anything")
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


def test_same_body_written_twice_produces_same_fingerprint(tmp_path: Path) -> None:
    """Zero re-embed signal: TreeStore.write's own idempotency check means
    resubmitting byte-identical content (which also bumps updated_at
    internally) must not change the fingerprint."""
    store = TreeStore(tmp_path / "memory")
    first = store.write(relative_path="a.md", text="# A\n\nBody text.\n", expect="absent")

    # Resubmit the same content -- store treats this as idempotent and does
    # not advance revision_id, but it does compute a fresh updated_at
    # internally before discovering no semantic change occurred.
    again = store.write(
        relative_path="a.md",
        text="# A\n\nBody text.\n",
        memory_type=first.type,
        scope=first.scope,
        authority=first.authority,
        sources=first.sources,
        status=first.status,
        tags=first.tags,
        curation_origin=first.curation_origin,
        expect=first.content_hash,
    )
    assert again.revision_id == first.revision_id  # confirms idempotent path taken

    assert file_fingerprint(first) == file_fingerprint(again)


def test_editing_one_paragraph_changes_only_that_chunk_and_the_fingerprint(
    tmp_path: Path,
) -> None:
    store = TreeStore(tmp_path / "memory")
    original_body = "# Title\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"
    entry = store.write(relative_path="a.md", text=original_body, expect="absent")

    edited_body = "# Title\n\nFirst paragraph.\n\nSECOND PARAGRAPH EDITED.\n\nThird paragraph.\n"
    edited = store.edit(entry.address, text=edited_body, expected_hash=entry.content_hash)

    old_chunks = chunk_body(entry.body)
    new_chunks = chunk_body(edited.body)
    diff = diff_chunks(old_chunks, new_chunks)

    # Exactly one chunk is new (the edited paragraph); no orphans since the
    # count of chunks is unchanged, just one chunk's content changed.
    assert len(diff.new) == 1
    assert diff.orphaned == [chunk_hash("Second paragraph.")]
    assert chunk_hash("SECOND PARAGRAPH EDITED.") in diff.new

    # Unrelated chunks kept the same hash.
    assert chunk_hash("# Title") in diff.unchanged
    assert chunk_hash("First paragraph.") in diff.unchanged
    assert chunk_hash("Third paragraph.") in diff.unchanged

    assert file_fingerprint(entry) != file_fingerprint(edited)


def test_removing_a_paragraph_shows_up_as_orphaned_chunk(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    original_body = "# Title\n\nKeep me.\n\nRemove me.\n"
    entry = store.write(relative_path="a.md", text=original_body, expect="absent")

    shortened_body = "# Title\n\nKeep me.\n"
    edited = store.edit(entry.address, text=shortened_body, expected_hash=entry.content_hash)

    diff = diff_chunks(chunk_body(entry.body), chunk_body(edited.body))
    assert diff.orphaned == [chunk_hash("Remove me.")]
    assert diff.new == []
    assert chunk_hash("Keep me.") in diff.unchanged
    assert chunk_hash("# Title") in diff.unchanged


def test_changing_type_changes_fingerprint(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(
        relative_path="a.md", text="# A\n\nBody.\n", memory_type="fact", expect="absent",
    )
    retyped = store.write(
        relative_path="a.md",
        text="# A\n\nBody.\n",
        memory_type="decision",
        authority=entry.authority,
        expect=entry.content_hash,
    )
    assert retyped.type != entry.type
    assert file_fingerprint(entry) != file_fingerprint(retyped)


def test_changing_authority_changes_fingerprint(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(
        relative_path="a.md", text="# A\n\nBody.\n", authority="advisory", expect="absent",
    )
    reauthorized = store.write(
        relative_path="a.md",
        text="# A\n\nBody.\n",
        memory_type=entry.type,
        authority="mandatory",
        expect=entry.content_hash,
    )
    assert reauthorized.authority != entry.authority
    assert file_fingerprint(entry) != file_fingerprint(reauthorized)


def test_metadata_only_churn_does_not_affect_fingerprint(tmp_path: Path) -> None:
    """updated_at is bumped by TreeStore.write on every call, including
    edits that touch tags/sources/status but leave body/type/authority
    alone. None of those fields are embedding-relevant in this scoped
    design, so the fingerprint must stay identical."""
    store = TreeStore(tmp_path / "memory")
    entry = store.write(
        relative_path="a.md",
        text="# A\n\nBody.\n",
        tags=["old-tag"],
        sources=["s1"],
        status="active",
        expect="absent",
    )
    assert entry.updated_at  # sanity: field exists and is populated

    retagged = store.write(
        relative_path="a.md",
        text="# A\n\nBody.\n",
        memory_type=entry.type,
        authority=entry.authority,
        tags=["new-tag", "another-tag"],
        sources=["s1", "s2"],
        status="active",
        expect=entry.content_hash,
    )

    # This is a genuine semantic change from the store's point of view
    # (new revision_id), proving updated_at/tags/sources really did change...
    assert retagged.revision_id != entry.revision_id
    assert retagged.tags != entry.tags
    # ...yet the embedding fingerprint, scoped to body/type/authority only,
    # is unchanged: zero re-embed work for this update.
    assert file_fingerprint(entry) == file_fingerprint(retagged)


def test_diff_chunks_identical_lists_are_all_unchanged() -> None:
    chunks = ["A", "B", "C"]
    diff = diff_chunks(chunks, chunks)
    assert diff.new == []
    assert diff.orphaned == []
    assert diff.unchanged == [chunk_hash("A"), chunk_hash("B"), chunk_hash("C")]


def test_diff_chunks_all_new_when_old_is_empty() -> None:
    diff = diff_chunks([], ["A", "B"])
    assert diff.orphaned == []
    assert diff.unchanged == []
    assert set(diff.new) == {chunk_hash("A"), chunk_hash("B")}


def test_diff_chunks_all_orphaned_when_new_is_empty() -> None:
    diff = diff_chunks(["A", "B"], [])
    assert diff.new == []
    assert diff.unchanged == []
    assert set(diff.orphaned) == {chunk_hash("A"), chunk_hash("B")}
