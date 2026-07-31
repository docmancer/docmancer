"""Derived recurring-memory clusters across independent agent harnesses."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from docmancer.memory.atomic import AtomicMemoryEntry, _is_negative


_GENERATED_PARTS = {
    ("skills", "docmancer"),
    ("skills", "docmancer-memory"),
    ("plugins", "docmancer"),
    ("distribution", "claude-marketplace"),
    ("distribution", "codex-plugin"),
}


def _generated_integration_path(value: str) -> bool:
    parts = tuple(part.casefold() for part in Path(value).parts)
    return any(
        parts[index : index + len(marker)] == marker
        for marker in _GENERATED_PARTS
        for index in range(max(0, len(parts) - len(marker) + 1))
    )


def _normalized_scope(atom: AtomicMemoryEntry, project_path: str | Path | None) -> str | None:
    kind = (atom.scope_kind or atom.scope.partition(":")[0] or "unknown").casefold()
    if kind == "global":
        return "global"
    if kind != "project":
        return kind
    raw = atom.project_path or atom.scope.partition(":")[2]
    if not raw:
        return None
    try:
        source = Path(raw).expanduser().resolve()
        selected = Path(project_path).expanduser().resolve() if project_path else None
    except OSError:
        return None
    if selected is not None and source != selected and source not in selected.parents:
        return None
    return f"{kind}:{selected or source}"


def _source_rows(
    atom: AtomicMemoryEntry,
    source_harnesses: dict[str, str],
) -> list[dict]:
    paths = atom.merged_from or [atom.source_path]
    rows = []
    for path in dict.fromkeys(str(value) for value in paths if value):
        if _generated_integration_path(path):
            continue
        rows.append(
            {
                "path": path,
                "harness": source_harnesses.get(path) or atom.harness or "unknown",
            }
        )
    return rows


def recurring_memory(
    atoms: Iterable[AtomicMemoryEntry],
    *,
    embed_texts: Callable[[list[str]], list],
    source_harnesses: dict[str, str] | None = None,
    project_path: str | Path | None = None,
    threshold: float = 0.82,
) -> list[dict]:
    """Cluster equivalent active memories after normalizing agent-specific scope.

    Results require at least two distinct harnesses and exclude generated
    Docmancer integration copies. They are evidence of recurrence, not
    consensus, correctness, or authority.
    """
    source_harnesses = source_harnesses or {}
    eligible: list[tuple[AtomicMemoryEntry, str, list[dict]]] = []
    for atom in atoms:
        if atom.deleted or atom.status not in {"", "active", "current"}:
            continue
        scope = _normalized_scope(atom, project_path)
        sources = _source_rows(atom, source_harnesses)
        if scope is None or not sources:
            continue
        eligible.append((atom, scope, sources))
    if not eligible:
        return []

    try:
        import numpy as np

        vectors = np.asarray(embed_texts([item[0].text for item in eligible]), dtype="float32")
        if vectors.ndim != 2 or vectors.shape[0] != len(eligible):
            return []
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
    except Exception:
        return []

    grouped: dict[tuple[str, bool], list[int]] = defaultdict(list)
    for index, (atom, scope, _sources) in enumerate(eligible):
        grouped[(scope, _is_negative(atom.text))].append(index)

    clusters: list[list[int]] = []
    for members in grouped.values():
        local: list[list[int]] = []
        representative_positions: list[int] = []
        local_vectors = vectors[np.asarray(members, dtype="int64")]
        block_size = 256
        for block_start in range(0, len(members), block_size):
            block_end = min(block_start + block_size, len(members))
            similarity_rows = local_vectors[block_start:block_end] @ local_vectors.T
            for position in range(block_start, block_end):
                member = members[position]
                match = None
                if representative_positions:
                    scores = similarity_rows[position - block_start, representative_positions]
                    choices = np.flatnonzero(scores >= threshold)
                    if choices.size:
                        best = scores[choices].max()
                        match = int(choices[np.flatnonzero(scores[choices] == best)[-1]])
                if match is None:
                    local.append([member])
                    representative_positions.append(position)
                else:
                    local[match].append(member)
        clusters.extend(local)

    results = []
    for members in clusters:
        variants = [eligible[index] for index in members]
        sources = [
            source
            for _atom, _scope, atom_sources in variants
            for source in atom_sources
        ]
        unique_sources = {
            (str(source["path"]), str(source["harness"])): source for source in sources
        }
        harnesses = sorted({str(source["harness"]) for source in unique_sources.values()})
        if len(harnesses) < 2:
            continue
        representative, scope, _ = max(
            variants,
            key=lambda item: (len(item[0].text), item[0].timestamp or "", item[0].atom_id),
        )
        results.append(
            {
                "cluster_id": "common:" + representative.content_hash[:20],
                "text": representative.text,
                "memory_type": representative.type,
                "memory_types": sorted({atom.type for atom, _scope, _sources in variants}),
                "normalized_scope": scope,
                "harnesses": harnesses,
                "harness_count": len(harnesses),
                "source_count": len(unique_sources),
                "sources": sorted(unique_sources.values(), key=lambda row: (row["harness"], row["path"])),
                "variants": [
                    {
                        "atom_id": atom.atom_id,
                        "text": atom.text,
                        "harness": atom.harness,
                        "source_path": atom.source_path,
                        "last_seen_at": atom.timestamp,
                    }
                    for atom, _scope, _sources in variants
                ],
                "last_seen_at": max(
                    (atom.timestamp or "" for atom, _scope, _sources in variants),
                    default="",
                ),
                "interpretation": "recurring across independent harness sources; not consensus or truth",
            }
        )
    results.sort(
        key=lambda row: (
            -int(row["harness_count"]),
            -int(row["source_count"]),
            str(row["text"]).casefold(),
        )
    )
    return results


__all__ = ["recurring_memory"]
