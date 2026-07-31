"""Deterministic memory atom extraction.

The memory index is built from small, source-attributed records. Each atom is
one durable memory item and is indexed as one SQLite section.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docmancer.core.models import Document
    from docmancer.harness.base import MemoryEntry


_BULLET_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(?P<body>.+?)\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*```")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")
_MIN_CHARS = 12
_MAX_ATOM_CHARS = 700

_MANAGED_BLOCK_PATTERNS = (
    re.compile(
        r"<!-- docmancer:memory:begin[^>]*-->[\s\S]*?<!-- docmancer:memory:end -->",
        re.IGNORECASE,
    ),
    re.compile(
        r"<!-- docmancer:start -->[\s\S]*?<!-- docmancer:end -->",
        re.IGNORECASE,
    ),
)

_NOISE = {
    "todo",
    "todos",
    "notes",
    "note",
    "misc",
    "scratch",
    "context",
    "summary",
    "references",
    "sources",
}


@dataclass
class AtomicMemoryEntry:
    """One source-attributed memory atom."""

    atom_id: str
    text: str
    type: str
    harness: str
    kind: str
    scope: str
    source_path: str
    source_title: str
    line_start: int
    line_end: int
    source_hash: str
    content_hash: str
    source_chars: int = 0
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    timestamp: str | None = None
    # Cross-agent merge provenance: how many near-duplicate atoms this canonical
    # record stands in for, and the distinct source paths they came from.
    source_count: int = 1
    merged_from: list[str] = field(default_factory=list)
    record_id: str | None = None
    # True when this atom came from consolidation output rather than from a
    # harvested or user-authored source. Generated atoms are excluded from
    # consolidation input by `MemoryAgent.indexed_atoms`; see spec 15.6.
    generated: bool = False
    origin: str = "harvested"
    scope_kind: str = "unknown"
    project_path: str | None = None
    # Session/turn adjacency (retrieval-unit contract, docs/contracts/retrieval-unit-contract.md).
    # Set only for atoms harvested from a source with real turn structure
    # (currently: imported conversation exports). None for every markdown
    # memory/instruction source, which has no underlying turns to preserve.
    session_id: str | None = None
    turn_index: int | None = None
    speaker: str | None = None
    project_id: str | None = None
    revision_id: str | None = None
    parent_revision_ids: list[str] = field(default_factory=list)
    deleted: bool = False
    audience_kind: str = "personal"
    applicability_kind: str = "global"
    pack_ids: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.source_title or self.type.title()

    @property
    def content(self) -> str:
        return self.text

    @property
    def path(self) -> str:
        return self.source_path

    @property
    def extra(self) -> dict:
        return {
            "kind": self.kind,
            "memory_type": self.type,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "atom_id": self.atom_id,
            "tags": list(self.tags),
            "source_count": self.source_count,
            "merged_from": list(self.merged_from),
            "record_id": self.record_id,
            "record_uri": f"docmancer://record/{self.record_id}" if self.record_id else None,
            "origin": self.origin,
            "scope_kind": self.scope_kind,
            "project_path": self.project_path,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "project_id": self.project_id,
            "revision_id": self.revision_id,
            "parent_revision_ids": list(self.parent_revision_ids),
            "deleted": self.deleted,
            "audience_kind": self.audience_kind,
            "applicability_kind": self.applicability_kind,
            "pack_ids": list(self.pack_ids),
        }

    def to_document(self) -> "Document":
        from docmancer.core.models import Document

        metadata = {
            "harness": self.harness,
            "scope": self.scope,
            "title": self.source_title,
            "source_path": self.source_path,
            "kind": self.kind,
            "memory_type": self.type,
            "memory_layer": "atomic",
            "atom_id": self.atom_id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "source_chars": self.source_chars,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "status": self.status,
            "timestamp": self.timestamp,
            "source_count": self.source_count,
            "merged_from": list(self.merged_from),
            "record_id": self.record_id,
            "origin": self.origin,
            "scope_kind": self.scope_kind,
            "project_path": self.project_path,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "project_id": self.project_id,
            "revision_id": self.revision_id,
            "parent_revision_ids": list(self.parent_revision_ids),
            "deleted": self.deleted,
            "audience_kind": self.audience_kind,
            "applicability_kind": self.applicability_kind,
            "pack_ids": list(self.pack_ids),
            "format": "memory-atomic",
            "chunking_strategy": "single",
            "anchor": f"{self.source_title}:{self.line_start}",
        }
        return Document(
            source=f"memory://atom/{self.atom_id}",
            content=self.text,
            metadata=metadata,
        )


def extract_atoms(entry: "MemoryEntry") -> list[AtomicMemoryEntry]:
    """Extract deterministic atomic records from one harvested memory entry."""
    content = _strip_managed_blocks(entry.content or "")
    source_hash = _hash(content)
    timestamp = _mtime(entry.path)
    candidates = _candidate_spans(content)
    atoms: list[AtomicMemoryEntry] = []
    seen: set[str] = set()
    for text, line_start, line_end, heading in candidates:
        body = _normalize_text(text)
        if not _keep(body):
            continue
        # Fold the heading breadcrumb into the atom text so each atom stays
        # self-contained when it is injected on its own, far from its source.
        normalized = f"{heading}: {body}" if heading else body
        dedupe_key = _dedupe_key(normalized)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        memory_type = classify_memory(body)
        source_title = heading or entry.title or Path(entry.path).name
        content_hash = _hash(normalized)
        atom_id = _atom_id(entry, normalized)
        kind = str(entry.extra.get("kind", "agent-memory"))
        scope_prefix, _, scope_value = (entry.scope or "").partition(":")
        scope_prefix = scope_prefix or "unknown"
        project_path = scope_value if scope_prefix == "project" and scope_value else None
        tags = [entry.harness, kind, scope_prefix, memory_type]
        atoms.append(
            AtomicMemoryEntry(
                atom_id=atom_id,
                text=normalized,
                type=memory_type,
                harness=entry.harness,
                kind=kind,
                scope=entry.scope,
                source_path=entry.path,
                source_title=source_title,
                line_start=line_start,
                line_end=line_end,
                source_hash=source_hash,
                content_hash=content_hash,
                source_chars=len(content),
                tags=tags,
                timestamp=timestamp,
                origin="harvested",
                scope_kind=scope_prefix,
                project_path=project_path,
            )
        )
    return atoms


def _strip_managed_blocks(content: str) -> str:
    """Remove generated docmancer blocks while preserving source line numbers."""
    cleaned = content
    for pattern in _MANAGED_BLOCK_PATTERNS:
        cleaned = pattern.sub(lambda match: "\n" * match.group(0).count("\n"), cleaned)
    return cleaned


def merge_atoms(
    atoms: list[AtomicMemoryEntry],
    *,
    embed_texts,
    threshold: float = 0.82,
) -> list[AtomicMemoryEntry]:
    """Collapse near-duplicate atoms into one canonical record per cluster.

    ``embed_texts`` maps a list of strings to a list of vectors. Clustering is a
    stable greedy pass: each atom joins the first existing cluster whose
    representative it matches at or above ``threshold`` cosine similarity, else
    it starts a new cluster. The best-phrased atom in a cluster (longest text,
    then a stable key) becomes canonical and carries merged provenance:
    ``source_count`` and the distinct ``merged_from`` source paths.

    Merge is best effort: if embedding fails or returns the wrong shape, the
    atoms are returned unchanged so indexing never breaks on the merge step.
    """
    if len(atoms) <= 1:
        return list(atoms)
    try:
        import numpy as np

        raw = embed_texts([atom.text for atom in atoms])
        vectors = np.asarray(raw, dtype="float32")
        if vectors.ndim != 2 or vectors.shape[0] != len(atoms):
            return list(atoms)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit = vectors / norms
    except Exception:  # noqa: BLE001 - never let merge break indexing
        return list(atoms)

    # Scope, type, and polarity are hard merge boundaries. Computing one
    # similarity matrix per compatible group moves the expensive dot products
    # into optimized NumPy code instead of performing millions of tiny Python
    # operations. The stable greedy cluster semantics remain unchanged.
    grouped: dict[tuple[str, str, bool], list[int]] = {}
    for index, atom in enumerate(atoms):
        grouped.setdefault((atom.type, atom.scope, _is_negative(atom.text)), []).append(index)

    clusters: list[list[int]] = []
    for members in grouped.values():
        local_unit = unit[np.asarray(members, dtype="int64")]
        local_clusters: list[list[int]] = []
        representative_positions: list[int] = []
        durable_ids: list[str | None] = []
        # Bound temporary similarity memory while retaining batched BLAS work.
        # A 256-row block uses roughly 1 MB per 1,000 group members.
        block_size = 256
        for block_start in range(0, len(members), block_size):
            block_end = min(block_start + block_size, len(members))
            similarity_rows = local_unit[block_start:block_end] @ local_unit.T
            for position in range(block_start, block_end):
                atom_index = members[position]
                atom = atoms[atom_index]
                best_cluster = -1
                if representative_positions:
                    scores = similarity_rows[position - block_start, representative_positions]
                    eligible = scores >= threshold
                    if atom.record_id:
                        eligible &= np.asarray(
                            [record_id in {None, atom.record_id} for record_id in durable_ids],
                            dtype=bool,
                        )
                    choices = np.flatnonzero(eligible)
                    if choices.size:
                        best_score = scores[choices].max()
                        # The old greedy loop chose the later cluster on an
                        # exact tie, so retain that deterministic behavior.
                        best_cluster = int(choices[np.flatnonzero(scores[choices] == best_score)[-1]])
                if best_cluster < 0:
                    local_clusters.append([atom_index])
                    representative_positions.append(position)
                    durable_ids.append(atom.record_id)
                else:
                    local_clusters[best_cluster].append(atom_index)
                    if atom.record_id:
                        durable_ids[best_cluster] = atom.record_id
        clusters.extend(local_clusters)

    # Grouped processing changes traversal order, so restore the original
    # first-seen cluster order before electing canonical atoms.
    clusters.sort(key=lambda members: members[0])

    merged: list[AtomicMemoryEntry] = []
    for members in clusters:
        if not members:
            continue
        canonical = _elect_canonical([atoms[i] for i in members])
        merged.append(canonical)
    return merged


def _can_merge(left: AtomicMemoryEntry, right: AtomicMemoryEntry) -> bool:
    """Only compare atoms whose metadata and polarity make a merge safe."""
    if left.type != right.type or left.scope != right.scope:
        return False
    if left.record_id and right.record_id and left.record_id != right.record_id:
        return False
    return _is_negative(left.text) == _is_negative(right.text)


def _is_negative(text: str) -> bool:
    lower = f" {text.lower()} "
    return bool(
        re.search(
            r"\b(?:must not|do not|don't|never|avoid|no longer|not|isn't|is not)\s+"
            r"(?:use|run|deploy|enable|allow|read|write|install|choose|prefer|keep|store|send|expose)\b",
            lower,
        )
    )


def _elect_canonical(group: list[AtomicMemoryEntry]) -> AtomicMemoryEntry:
    """Pick the best-phrased atom in a cluster and attach merged provenance."""
    if len(group) == 1:
        return group[0]
    winner = max(group, key=lambda a: (len(a.text), a.harness, a.source_path, a.line_start))
    sources: list[str] = []
    for atom in group:
        if atom.source_path and atom.source_path not in sources:
            sources.append(atom.source_path)
    winner.source_count = len(group)
    winner.merged_from = sources
    winner.confidence = min(1.0, winner.confidence + 0.1 * (len(group) - 1))
    durable = next((atom for atom in group if atom.record_id), None)
    if durable is not None:
        winner.record_id = durable.record_id
        winner.origin = durable.origin
    return winner


def classify_memory(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ("must not", "never ", "do not ", "don't ", "avoid ")):
        return "constraint"
    if any(term in lower for term in ("warning", "risk", "danger", "failure", "broken", "blocked")):
        return "warning"
    if any(term in lower for term in ("we chose", "we picked", "decided", "decision", "because")):
        return "decision"
    if any(term in lower for term in ("prefer ", "preference", "default to", "tone", "style")):
        return "preference"
    if "`" in text or lower.startswith(("run ", "use ", "install ", "execute ")):
        return "command"
    if any(term in lower for term in ("workflow", "process", "steps", "first ", "then ")):
        return "workflow"
    if lower.startswith(("current ", "status", "done:", "shelved", "active ")):
        return "status"
    return "fact"


def _leading_indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" \t"))


def _candidate_spans(content: str) -> list[tuple[str, int, int, str]]:
    lines = content.splitlines()
    heading_stack: list[tuple[int, str]] = []
    in_fence = False
    paragraph: list[tuple[int, str]] = []
    # An open bullet block groups a bullet with its indented sub-bullets and
    # wrapped continuation lines so a parent and its children stay one atom.
    bullet: dict | None = None
    out: list[tuple[str, int, int, str]] = []

    def current_heading() -> str:
        return " > ".join(title for _level, title in heading_stack)

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        start = paragraph[0][0]
        end = paragraph[-1][0]
        text = " ".join(part for _line, part in paragraph)
        for item in _split_long_text(text):
            out.append((item, start, end, current_heading()))
        paragraph = []

    def flush_bullet() -> None:
        nonlocal bullet
        if bullet is None:
            return
        text = " ".join(bullet["parts"])
        for item in _split_long_text(text):
            out.append((item, bullet["start"], bullet["end"], bullet["heading"]))
        bullet = None

    for index, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if _FENCE_RE.match(line):
            flush_paragraph()
            flush_bullet()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_paragraph()
            flush_bullet()
            level = len(heading_match.group(1))
            title = _normalize_text(heading_match.group("title"))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if title:
                heading_stack.append((level, title))
            continue
        if not stripped:
            flush_paragraph()
            flush_bullet()
            continue
        indent = _leading_indent(raw)
        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            flush_paragraph()
            body = bullet_match.group("body")
            if bullet is not None and indent > bullet["base"]:
                bullet["parts"].append(body)
                bullet["end"] = index
            else:
                flush_bullet()
                bullet = {
                    "base": indent,
                    "start": index,
                    "end": index,
                    "parts": [body],
                    "heading": current_heading(),
                }
            continue
        # A non-blank, non-bullet line indented under an open bullet is a
        # wrapped continuation of it; otherwise it belongs to a paragraph.
        if bullet is not None and indent > bullet["base"]:
            bullet["parts"].append(_normalize_text(stripped))
            bullet["end"] = index
            continue
        flush_bullet()
        paragraph.append((index, stripped))
    flush_paragraph()
    flush_bullet()
    return out


def _split_long_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if len(normalized) <= _MAX_ATOM_CHARS:
        return [normalized]
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(normalized) if p.strip()]
    if not parts:
        parts = [normalized]
    merged: list[str] = []
    current = ""
    for part in parts:
        if len(part) > _MAX_ATOM_CHARS:
            if current:
                merged.append(current)
                current = ""
            words = part.split()
            window = ""
            for word in words:
                if window and len(window) + 1 + len(word) > _MAX_ATOM_CHARS:
                    merged.append(window)
                    window = word
                elif len(word) > _MAX_ATOM_CHARS:
                    if window:
                        merged.append(window)
                        window = ""
                    merged.extend(
                        word[start:start + _MAX_ATOM_CHARS]
                        for start in range(0, len(word), _MAX_ATOM_CHARS)
                    )
                else:
                    window = f"{window} {word}".strip()
            if window:
                merged.append(window)
            continue
        if not current:
            current = part
        elif len(current) + 1 + len(part) <= _MAX_ATOM_CHARS:
            current = f"{current} {part}"
        else:
            merged.append(current)
            current = part
    if current:
        merged.append(current)
    return merged


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", "", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _keep(text: str) -> bool:
    if len(text) < _MIN_CHARS:
        return False
    words = re.findall(r"[A-Za-z0-9_]+", text)
    if len(words) < 3:
        return False
    lower = text.lower().strip("#: ")
    if lower in _NOISE:
        return False
    if lower.startswith(("http://", "https://")) and len(words) < 5:
        return False
    return True


def _dedupe_key(text: str) -> str:
    return _SPACE_RE.sub(" ", text.lower()).strip()


def _atom_id(entry: "MemoryEntry", text: str) -> str:
    """Return a logical atom ID that survives unrelated line insertions."""
    raw = "\n".join([entry.harness, entry.scope, entry.path, _dedupe_key(text)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _mtime(path: str) -> str | None:
    from docmancer.memory.sources import source_updated_at

    try:
        ts = Path(path).stat().st_mtime
    except OSError:
        fallback = None
    else:
        fallback = datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
    return source_updated_at(path, fallback)


__all__ = ["AtomicMemoryEntry", "classify_memory", "extract_atoms", "merge_atoms"]
