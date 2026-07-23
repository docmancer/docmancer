"""Deterministic chunking, hashing, and fingerprinting layer (checklist A.7,
scoped down).

This module is a pure, dependency-free foundation for incremental embedding.
It does not load any model and does not touch any vector store. A future
embedding step consumes its outputs (``chunk_hash`` per chunk plus
``file_fingerprint`` per file) to decide what to embed, what to reuse, and
what to delete -- without this module ever calling an embedding model
itself.

Design decision: what goes into ``file_fingerprint``
------------------------------------------------------
The fingerprint must change exactly when a future embedding step would need
to re-embed something, and must stay stable otherwise -- in particular it
must stay stable across ``TreeStore.write``'s own idempotency check (see
``store._identity_fields``), so that a no-op resubmission produces zero
re-embed work end to end.

Included (embedding-relevant):

- ``body`` (via the ordered chunk hashes) -- the text that is actually
  embedded.
- ``type`` and ``authority`` -- both are folded into retrieval-time context
  text per the A.7 checklist ("Include project, harness, source heading,
  type, authority, and reliable timestamp in retrieval text where useful"),
  so a change to either changes what gets embedded even if the body chunk
  text is byte-identical.

Excluded (not embedding-relevant, or too volatile to gate on):

- ``memory_id`` -- a stable identity token, not retrieval content. Including
  it would not change embedding meaning and is redundant with the file's own
  identity.
- ``updated_at`` -- ``TreeStore.write`` bumps this on every call, including
  the idempotent-resubmission path that keeps ``revision_id`` from
  advancing. If the fingerprint depended on it, every touch would force a
  re-embed even when body/type/authority are unchanged, defeating the
  "zero re-embed on no-op write" goal.
- ``revision_id`` / ``parent_revision_ids`` -- revision bookkeeping, not
  retrieval content.
- ``scope``, ``project_id``, ``sources``, ``status``, ``tags``,
  ``curation_origin`` -- may matter for filtering or future retrieval-text
  composition, but are deliberately left out of the embedding fingerprint
  for this scoped-down pass. A later change that folds one of these into
  retrieval text should add it here in the same change.

Callers only need an object exposing ``.body``, ``.type``, and
``.authority`` (``TreeMemoryFile`` satisfies this), so tests can also pass
a lightweight stand-in.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol


class FingerprintableEntry(Protocol):
    """Minimal shape ``file_fingerprint`` needs from a tree entry."""

    body: str
    type: str
    authority: str


_WHITESPACE_RUN = re.compile(r"\s+")


def chunk_body(body: str) -> list[str]:
    """Split a Markdown body into stable, deterministic chunks.

    Chunks are blank-line-separated paragraphs/sections (split on runs of
    two or more newlines), with empty/whitespace-only chunks dropped and
    each chunk's surrounding whitespace stripped. Order is preserved and is
    always the order the chunks appear in the source body, so the same
    input always produces the same chunk list.
    """
    if not body:
        return []
    raw_chunks = re.split(r"\n\s*\n", body)
    return [chunk.strip() for chunk in raw_chunks if chunk.strip()]


def _normalize(text: str) -> str:
    """Strip and collapse internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def chunk_hash(chunk: str) -> str:
    """SHA-256 hex digest of a chunk's normalized text.

    This is the "source hash" for one chunk: whitespace-only reformatting of
    a chunk (e.g. rewrapped lines) does not change its hash, but any change
    to the words themselves does.
    """
    normalized = _normalize(chunk)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def file_fingerprint(entry: FingerprintableEntry) -> str:
    """A single SHA-256 hex digest for the whole file's embedding-relevant
    state: ordered chunk hashes plus embedding-relevant metadata.

    See the module docstring for exactly what is and is not included and
    why. Byte-identical ``body``/``type``/``authority`` always produces the
    same fingerprint, regardless of any other field (e.g. ``updated_at``)
    that changed.
    """
    chunk_hashes = [chunk_hash(chunk) for chunk in chunk_body(entry.body)]
    payload = "\x1f".join([entry.type, entry.authority, *chunk_hashes])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChunkDiff:
    """Result of comparing an old and new ordered chunk-hash list.

    - ``unchanged``: chunk hashes present in both old and new (by hash,
      not position) -- a future embedding step reuses these vectors as-is.
    - ``new``: chunk hashes present only in the new list -- these need a
      fresh embedding call.
    - ``orphaned``: chunk hashes present only in the old list -- these
      chunks' vectors should be deleted, since nothing in the new body
      maps to them anymore.
    """

    unchanged: list[str]
    new: list[str]
    orphaned: list[str]


def diff_chunks(old_chunks: list[str], new_chunks: list[str]) -> ChunkDiff:
    """Diff two chunk lists by content hash so a future embedding step can
    embed only new/changed chunks and delete orphaned vectors.

    Comparison is by hash of normalized content, not by list position, so
    reordering identical chunks does not spuriously mark them as
    new/orphaned. Order within each returned list follows the order chunks
    appear in ``old_chunks`` / ``new_chunks`` respectively; duplicate hashes
    within one list collapse to a single entry.
    """
    old_hashes = [chunk_hash(chunk) for chunk in old_chunks]
    new_hashes = [chunk_hash(chunk) for chunk in new_chunks]
    old_set = set(old_hashes)
    new_set = set(new_hashes)

    unchanged = _dedupe_preserve_order(h for h in new_hashes if h in old_set)
    new = _dedupe_preserve_order(h for h in new_hashes if h not in old_set)
    orphaned = _dedupe_preserve_order(h for h in old_hashes if h not in new_set)
    return ChunkDiff(unchanged=unchanged, new=new, orphaned=orphaned)


def _dedupe_preserve_order(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
