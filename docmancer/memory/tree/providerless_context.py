"""The providerless Context artifact (T013, docs/contracts/providerless-context-artifact-contract.md).

``render_providerless_cluster`` assembles a ``synthesized: false`` cluster's
Markdown body deterministically from its member records. No model call, ever:
every line is a structural label this module emits or a verbatim copy of
something a member record already contains. T066 (Block E) wires this into
the real clustering/dedup pipeline; this module is the rendering primitive
that stays true regardless of what feeds it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClusterMember:
    """One representative record inside a cluster."""

    record_id: str
    path: str
    harness: str
    recorded_at: str
    text: str


@dataclass(frozen=True)
class ConflictSide:
    """One side of a conflict entry (spec 4.2's Conflicts section, applied structurally)."""

    claim: str
    date: str
    source: str
    record_id: str


@dataclass(frozen=True)
class ConflictEntry:
    description: str
    sides: tuple[ConflictSide, ...]


@dataclass(frozen=True)
class ProviderlessCluster:
    """Everything ``render_providerless_cluster`` needs; nothing it doesn't."""

    cluster_id: str
    topic_label: str
    members: tuple[ClusterMember, ...]
    duplicate_counts: dict[str, int] = field(default_factory=dict)
    collapsed_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    conflicts: tuple[ConflictEntry, ...] = ()


def render_providerless_cluster(cluster: ProviderlessCluster) -> str:
    """Deterministic Markdown body for a ``synthesized: false`` cluster.

    Pure function: identical input produces byte-identical output, which is
    also what makes rendering idempotent (T085) for the providerless case.
    """
    lines: list[str] = [f"# {cluster.topic_label}", ""]

    for member in cluster.members:
        lines.append(f"## {member.path}")
        lines.append(f"Source: {member.harness}, recorded {member.recorded_at}")
        occurrences = cluster.duplicate_counts.get(member.record_id)
        if occurrences and occurrences > 1:
            other_sources = cluster.collapsed_sources.get(member.record_id, ())
            sources_note = f" ({', '.join(other_sources)})" if other_sources else ""
            lines.append(f"Duplicates: appeared verbatim in {occurrences} source(s){sources_note}")
        lines.append("")
        lines.append(member.text.strip())
        lines.append("")

    if cluster.conflicts:
        lines.append("## Conflicts")
        lines.append("")
        for conflict in cluster.conflicts:
            lines.append(f"Conflict: {conflict.description}")
            for side in conflict.sides:
                lines.append(f"- {side.claim} ({side.date}, {side.source}, {side.record_id})")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ClusterMember",
    "ConflictSide",
    "ConflictEntry",
    "ProviderlessCluster",
    "render_providerless_cluster",
]
