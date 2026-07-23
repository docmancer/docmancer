"""Deterministic Curation Engine v1 (checklist A.8, plan section 5.1).

This engine turns raw "evidence" text (a captured note, a harvested
harness memory file, a repository instruction snippet, ...) into either a
new/updated file in a curated ``TreeStore``, or -- when the destination or
duplicate status is not unambiguous -- a plain Markdown file dropped into
an *inbox* directory. It never fabricates semantic judgement: everything
it does is a mechanical, inspectable rule (heading/list-item extraction,
exact/normalised text comparison, explicit-caller-supplied destination
and supersession). There is no LLM call, no network call, and no API key
anywhere in this module, matching plan section 5.1's "local mode remains
fully usable with no API key" requirement.

Deterministic rules implemented here (checklist A.8):

1. Structural extraction -- ``_extract_title_and_body`` pulls a title from
   the first ``# heading`` line, falling back to the first non-blank line
   of prose. The full text (minus a redundant leading heading) becomes the
   body. This mirrors ``TreeMemoryFile.title`` (parser.py) so a curated
   file's derived title matches what the engine extracted.
2. Exact/normalised duplicate detection -- ``_normalize`` lowercases and
   collapses whitespace before comparing candidate body text against every
   existing entry's body *within the same scope and project* (plan 5.1:
   "duplicate detection inside compatible project and scope"). A match is
   treated as the same memory and curation is a no-op against that entry
   (no new file, no duplicate).
3. Explicit supersession -- the caller passes ``supersedes_address``
   (an existing ``docmancer://memory/<id>`` address) rather than the
   engine inferring supersession from prose. This keeps the rule
   mechanical: the engine never guesses "this looks like it replaces
   that." The prior entry is rewritten with ``status="archived"`` (all
   other frontmatter preserved) before the new entry is written.
4. Deterministic placement -- curation only ever writes into the curated
   tree when the caller supplies an explicit ``relative_path``. There is
   no domain/topic inference in v1; "unambiguous destination" is defined
   as "the caller told us exactly where," which is the only destination
   signal that is mechanical rather than a semantic guess.
5. Safe fallback to the inbox -- whenever ``relative_path`` is omitted,
   the material is ambiguous by the above definition and is written
   as a plain ``.md`` file directly under the inbox directory. That file
   *is* the entire "not yet curated" state; this module never creates a
   second review-queue object (checklist: "never generate a per-item
   review queue"; plan 5.3: "no review queues").
6. Read-only evidence -- ``source_path``, when supplied, is only ever
   read (to fold its path into ``sources`` citations) or referenced;
   this module never opens it for writing.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from docmancer.memory.tree.parser import TreeMemoryFile, now_iso
from docmancer.memory.tree.store import TreeStore

_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Whitespace-collapsed, case-folded comparison key for duplicate
    detection. Purely mechanical -- no semantic similarity, no embeddings."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def _extract_title_and_body(evidence_text: str) -> tuple[str, str]:
    """Structural extraction (checklist A.8 bullet 2): pull a title from
    the first heading, or the first non-blank line if there is no
    heading. The body is the evidence text unchanged (the curated file's
    own ``title`` property re-derives the same title from the body, so we
    do not strip the heading out -- doing so would make the stored body a
    rewritten copy rather than the extracted structure)."""
    heading_match = _HEADING.search(evidence_text)
    if heading_match:
        return heading_match.group(1).strip(), evidence_text
    stripped = evidence_text.strip()
    if not stripped:
        return "", evidence_text
    first_line = stripped.splitlines()[0].strip()
    return first_line, evidence_text


@dataclass
class CurationResult:
    """What the engine did with one piece of evidence."""

    destination: str  # "tree" | "inbox" | "duplicate_skip"
    entry: TreeMemoryFile | None = None
    inbox_path: Path | None = None
    superseded_address: str | None = None
    reason: str = ""
    extracted_title: str = ""
    extra_frontmatter: dict = field(default_factory=dict)


class CurationEngine:
    """Deterministic (no LLM, no network) curation from evidence text into
    a curated ``TreeStore`` tree, with a plain-file inbox fallback."""

    def __init__(self, store: TreeStore, inbox_dir: Path) -> None:
        self.store = store
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    # -- duplicate detection -------------------------------------------------

    def _find_duplicate(
        self, normalized_body: str, *, scope: str, project_id: str | None
    ) -> TreeMemoryFile | None:
        """Exact/normalised duplicate detection scoped to compatible
        project and scope (plan 5.1). Returns the first matching curated
        entry, or ``None``."""
        for candidate in self.store.index.entries():
            if candidate.scope != scope or candidate.project_id != project_id:
                continue
            if _normalize(candidate.body) == normalized_body:
                return candidate
        return None

    # -- inbox fallback -------------------------------------------------------

    def _write_inbox(self, evidence_text: str, *, source_path: Path | None) -> Path:
        """Write plain (non-frontmatter) uncurated material into the inbox.
        This file is the entire "ambiguous, not yet curated" state -- no
        additional queue, ticket, or review object is created anywhere."""
        digest = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()[:12]
        name = f"{digest}-{uuid.uuid4().hex[:8]}.md"
        path = self.inbox_dir / name
        text = evidence_text
        if source_path is not None and str(source_path) not in text:
            text = f"{text.rstrip()}\n\n<!-- source: {source_path} -->\n"
        path.write_text(text, encoding="utf-8")
        return path

    # -- supersession -----------------------------------------------------------

    def _archive(self, address: str) -> TreeMemoryFile:
        """Mark an existing curated entry archived, preserving every other
        frontmatter field, guarded by its current content hash."""
        old = self.store.read(address)
        relative_path = old.path.relative_to(self.store.root)
        return self.store.write(
            relative_path=relative_path,
            text=old.body,
            memory_type=old.type,
            scope=old.scope,
            authority=old.authority,
            project_id=old.project_id,
            sources=old.sources,
            status="archived",
            tags=old.tags,
            curation_origin=old.curation_origin,
            expect=old.content_hash,
        )

    # -- entry point ------------------------------------------------------------

    def curate(
        self,
        evidence_text: str,
        *,
        relative_path: str | Path | None = None,
        memory_type: str = "fact",
        scope: str = "global",
        authority: str = "advisory",
        project_id: str | None = None,
        tags: list[str] | None = None,
        source_path: Path | None = None,
        supersedes_address: str | None = None,
    ) -> CurationResult:
        """Curate one piece of evidence text.

        ``relative_path`` is the only unambiguous-placement signal this
        engine recognises (checklist A.8: "place material deterministically
        only when the destination is unambiguous"). Omit it to force the
        safe inbox fallback.

        ``source_path``, if given, is never opened for writing here -- it
        is only folded into the new entry's ``sources`` citation list (or,
        for an inbox fallback, referenced in an HTML comment). The file at
        ``source_path`` is read-only from this engine's perspective and in
        fact is never read at all; only its path string is used.

        ``supersedes_address`` makes supersession explicit and caller-driven
        rather than inferred from prose: when supplied, the referenced
        curated entry is archived (``status="archived"``) before the new
        entry is written.
        """
        title, body = _extract_title_and_body(evidence_text)
        normalized_body = _normalize(body)

        sources = [str(source_path)] if source_path is not None else []

        # Ambiguous destination: no explicit placement -> inbox fallback.
        # This is checked before duplicate detection because an entry with
        # no destination can never be deterministically placed regardless
        # of whether it also happens to duplicate curated content.
        if relative_path is None:
            inbox_path = self._write_inbox(evidence_text, source_path=source_path)
            return CurationResult(
                destination="inbox",
                inbox_path=inbox_path,
                reason="no explicit relative_path supplied; destination is ambiguous",
                extracted_title=title,
            )

        duplicate = self._find_duplicate(normalized_body, scope=scope, project_id=project_id)
        if duplicate is not None:
            return CurationResult(
                destination="duplicate_skip",
                entry=duplicate,
                reason="normalised body already exists in the curated tree at this scope/project",
                extracted_title=title,
            )

        superseded_address: str | None = None
        if supersedes_address is not None:
            self._archive(supersedes_address)
            superseded_address = supersedes_address

        entry = self.store.write(
            relative_path=relative_path,
            text=body,
            memory_type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id,
            sources=sources,
            status="active",
            tags=tags or [],
            curation_origin="deterministic_curation",
            expect="absent",
        )
        return CurationResult(
            destination="tree",
            entry=entry,
            superseded_address=superseded_address,
            reason="explicit relative_path supplied; deterministic placement",
            extracted_title=title,
        )
