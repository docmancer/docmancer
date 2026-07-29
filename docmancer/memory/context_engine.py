"""Deterministic local Context artifact, revisions, and incremental builds."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from docmancer.ai.provider_protocol import CompletionOptions
from docmancer.memory.tree.providerless_context import (
    ClusterMember,
    ConflictEntry,
    ConflictSide,
    ProviderlessCluster,
    render_providerless_cluster,
)
from docmancer.memory.tree.compiler import authority_for_kind
from docmancer.memory.tree.revision_identity import content_revision_id

CONTEXT_SCHEMA_VERSION = 2
CLUSTERING_VERSION = "topic-jaccard-stable-v3"
DEDUP_POLICY_VERSION = "safe-two-tier-indexed-v2"
AUTHORITY_RULES_VERSION = "authority-v1"
REDACTION_POLICY_VERSION = "privacy-filter-v1"
CONTEXT_POLICY_VERSION = "context-v1"
PROMPT_VERSION = "context-cluster-batched-v2"
DEFAULT_SIMILARITY_THRESHOLD = 0.18
DEFAULT_SEMANTIC_DUPLICATE_THRESHOLD = 0.96
DEFAULT_MAX_CLUSTER_MEMBERS = 25
# Order-of-magnitude rates for the dry-run cost preview, based on a small
# model such as gpt-4.1-nano. Deliberately a planning estimate, not billing:
# the report labels it as such and a real run reports actual cost.
# Context builds batch several topics into each request and execute bounded
# batches concurrently. Retries remain isolated to the failed batch.
CONTEXT_PROVIDER_ATTEMPTS = 4
CONTEXT_PROVIDER_BACKOFF_SECONDS = 1.5
# Provider work is network-bound. This is the fallback when an older config
# does not contain a distillation block.
CONTEXT_BUILD_CONCURRENCY = 16


def _is_transient_provider_error(exc: BaseException) -> bool:
    """Whether a failed provider call is worth retrying.

    Deliberately narrow: transport and availability faults only. An invalid key,
    a malformed request, or a refusal will fail identically on every attempt, so
    retrying those only multiplies the bill.
    """
    import ssl

    if isinstance(exc, (ssl.SSLError, ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__
    if name in {
        "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
        "ReadError", "WriteError", "RemoteProtocolError", "ProtocolError", "TransportError",
    }:
        return True
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in ("bad record mac", "connection reset", "timed out", "temporarily unavailable", "rate limit")
    )


def _complete_with_retry(client, messages, options):
    """Call the provider, retrying transient transport failures with backoff."""
    import time

    last: BaseException | None = None
    for attempt in range(CONTEXT_PROVIDER_ATTEMPTS):
        try:
            return client.complete_text(messages, options)
        except Exception as exc:  # noqa: BLE001 - re-raised below when not transient
            last = exc
            if not _is_transient_provider_error(exc) or attempt == CONTEXT_PROVIDER_ATTEMPTS - 1:
                raise
            time.sleep(CONTEXT_PROVIDER_BACKOFF_SECONDS * (2**attempt))
    raise last  # unreachable; the loop either returns or raises


def _is_transcript_noise(atom) -> bool:
    """Raw session transcript material, excluded from consolidation.

    ``_sources`` previously took every non-generated atom, so a build paid a
    provider to summarise running commentary of what an agent did turn by turn
    ("Raw Memories > Thread ...", "Task Group: ..."). On a real corpus that was
    42% of the input. The laptop reconciler already refuses this material; the
    Context engine now applies the same test rather than inventing a second
    notion of what is worth consolidating.
    """
    from docmancer.memory.laptop import TASK_HISTORY_MARKERS

    haystack = " ".join(
        str(value or "")
        for value in (
            getattr(atom, "source_path", ""),
            getattr(atom, "source_title", ""),
            getattr(atom, "text", ""),
        )
    ).casefold()
    return any(marker in haystack for marker in TASK_HISTORY_MARKERS)


ESTIMATED_OUTPUT_TOKENS_PER_CLUSTER = 400
ESTIMATED_INPUT_USD_PER_1K = 0.0001
ESTIMATED_OUTPUT_USD_PER_1K = 0.0004

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]{1,}")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_LIST_PREFIX_RE = re.compile(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[.,;:!?]+$")
_VALUE_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?(?:%|ms|s|m|h|d|kb|mb|gb)?\b|"
    r"`[^`]+`|\b(?:true|false|enabled|disabled|on|off)\b)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> set[str]:
    stop = {
        "about", "after", "agent", "also", "because", "before", "being",
        "context", "docmancer", "from", "have", "into", "memory", "should",
        "that", "their", "there", "these", "this", "through", "when", "with",
    }
    return {token for token in _WORD_RE.findall(text.casefold()) if token not in stop}


def _normalize_mechanical(text: str) -> str:
    value = _LIST_PREFIX_RE.sub("", text)
    value = _SPACE_RE.sub(" ", value).strip().casefold()
    return _PUNCT_RE.sub("", value)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned[:56].rstrip("-") or "topic"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ContextSource:
    address: str
    content_hash: str
    text: str
    title: str
    path: str
    harness: str
    recorded_at: str
    scope: str
    authority: str
    lifecycle: str = "active"


@dataclass
class DedupGroup:
    representative: ContextSource
    collapsed: list[ContextSource] = field(default_factory=list)
    held_back_reason: str | None = None


@dataclass
class TopicCluster:
    cluster_id: str
    topic_label: str
    groups: list[DedupGroup]
    split_from: list[str] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)

    @property
    def sources(self) -> list[ContextSource]:
        return [group.representative for group in self.groups]


def _contradicts(left: ContextSource, right: ContextSource) -> bool:
    left_values = {value.casefold() for value in _VALUE_RE.findall(left.text)}
    right_values = {value.casefold() for value in _VALUE_RE.findall(right.text)}
    if not left_values or not right_values or left_values == right_values:
        return False
    shared_terms = _tokens(left.text).intersection(_tokens(right.text))
    return len(shared_terms) >= 2


def safe_deduplicate(
    sources: Iterable[ContextSource],
    *,
    semantic_threshold: float = DEFAULT_SEMANTIC_DUPLICATE_THRESHOLD,
) -> tuple[list[DedupGroup], list[dict], dict]:
    """Collapse exact/near-exact equivalents only after safety checks."""
    ordered = sorted(sources, key=lambda item: (item.scope, item.authority, item.address))
    groups: list[DedupGroup] = []
    group_tokens: list[set[str]] = []
    group_normalized: list[str] = []
    mechanical: dict[tuple[str, str, str], DedupGroup] = {}
    semantic_index: dict[tuple[str, str, str], set[int]] = {}
    conflicts: list[dict] = []
    stats = {
        "input": len(ordered),
        "mechanical_collapsed": 0,
        "semantic_candidates": 0,
        "semantic_collapsed": 0,
        "held_back": {},
    }
    for source in ordered:
        normalized = _normalize_mechanical(source.text)
        mechanical_key = (source.scope, source.authority, normalized)
        exact = mechanical.get(mechanical_key)
        if exact is not None:
            exact.collapsed.append(source)
            stats["mechanical_collapsed"] += 1
            continue
        matched: DedupGroup | None = None
        source_tokens = sorted(_tokens(normalized))
        shingles = {
            " ".join(source_tokens[index:index + 3])
            for index in range(max(0, len(source_tokens) - 2))
        }
        if not shingles:
            shingles = set(source_tokens)
        candidate_ids: set[int] = set()
        for shingle in sorted(shingles)[:24]:
            candidate_ids.update(
                semantic_index.get((source.scope, source.authority, shingle), set())
            )
        ranked_candidates = sorted(
            candidate_ids,
            key=lambda group_id: (
                abs(len(group_normalized[group_id]) - len(normalized)),
                group_id,
            ),
        )[:24]
        for group_id in ranked_candidates:
            group = groups[group_id]
            representative = group.representative
            other_tokens = group_tokens[group_id]
            if (
                not source_tokens
                or not other_tokens
                or len(set(source_tokens).intersection(other_tokens))
                / len(set(source_tokens).union(other_tokens)) < 0.72
            ):
                continue
            other = group_normalized[group_id]
            ratio = difflib.SequenceMatcher(None, normalized, other, autojunk=False).ratio()
            if ratio < 0.82:
                continue
            stats["semantic_candidates"] += 1
            if _contradicts(source, representative):
                reason = "contradiction"
            elif ratio < semantic_threshold:
                reason = "residual_ambiguity"
            else:
                reason = None
            if reason:
                stats["held_back"][reason] = stats["held_back"].get(reason, 0) + 1
                if reason == "contradiction":
                    conflicts.append(
                        {
                            "description": f"Conflicting values in {source.title}",
                            "addresses": [representative.address, source.address],
                        }
                    )
                continue
            matched = group
            stats["semantic_collapsed"] += 1
            break
        if matched is None:
            group_id = len(groups)
            group = DedupGroup(representative=source)
            groups.append(group)
            group_tokens.append(set(source_tokens))
            group_normalized.append(normalized)
            mechanical[mechanical_key] = group
            for shingle in sorted(shingles)[:24]:
                semantic_index.setdefault(
                    (source.scope, source.authority, shingle),
                    set(),
                ).add(group_id)
        else:
            matched.collapsed.append(source)
    return groups, conflicts, stats


def _topic_label(groups: list[DedupGroup]) -> str:
    headings = []
    for group in groups:
        match = _HEADING_RE.search(group.representative.text)
        if match:
            headings.append(match.group(1).strip())
        elif group.representative.title:
            headings.append(group.representative.title.strip())
    if headings:
        counts: dict[str, int] = {}
        display: dict[str, str] = {}
        for heading in headings:
            key = heading.casefold()
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, heading)
        key = sorted(counts, key=lambda value: (-counts[value], value))[0]
        return display[key]
    frequencies: dict[str, int] = {}
    for group in groups:
        for token in _tokens(group.representative.text):
            frequencies[token] = frequencies.get(token, 0) + 1
    top = sorted(frequencies, key=lambda token: (-frequencies[token], token))[:4]
    return " ".join(top).title() or "Context"


def _jaccard(left: ContextSource, right: ContextSource) -> float:
    a = _tokens(f"{left.title} {left.text}")
    b = _tokens(f"{right.title} {right.text}")
    if not a or not b:
        return 0.0
    return len(a.intersection(b)) / len(a.union(b))


def cluster_topics(
    groups: list[DedupGroup],
    *,
    previous: list[dict] | None = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_members: int = DEFAULT_MAX_CLUSTER_MEMBERS,
) -> list[TopicCluster]:
    """Deterministic indexed single-link clusters with stable IDs and lineage."""
    ordered = sorted(groups, key=lambda group: group.representative.address)
    token_sets = [
        _tokens(f"{group.representative.title} {group.representative.text}")
        for group in ordered
    ]
    frequencies: dict[str, int] = {}
    for tokens in token_sets:
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
    parents = list(range(len(ordered)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    inverted: dict[str, list[int]] = {}
    rare_ceiling = max(25, len(ordered) // 50)
    for index, tokens in enumerate(token_sets):
        rare = sorted(tokens, key=lambda token: (frequencies[token], token))
        selected = [token for token in rare if frequencies[token] <= rare_ceiling][:24]
        if not selected:
            selected = rare[:8]
        candidate_scores: dict[int, int] = {}
        for token in selected:
            for candidate_id in inverted.get(token, []):
                candidate_scores[candidate_id] = candidate_scores.get(candidate_id, 0) + 1
        candidate_ids = sorted(
            candidate_scores,
            key=lambda candidate_id: (-candidate_scores[candidate_id], candidate_id),
        )[:96]
        for candidate_id in candidate_ids:
            left, right = token_sets[index], token_sets[candidate_id]
            if left and right and len(left.intersection(right)) / len(left.union(right)) >= threshold:
                union(index, candidate_id)
        for token in selected:
            inverted.setdefault(token, []).append(index)

    components: dict[int, list[DedupGroup]] = {}
    for index, group in enumerate(ordered):
        components.setdefault(find(index), []).append(group)
    raw = [components[key] for key in sorted(components)]

    split: list[list[DedupGroup]] = []
    for group_list in raw:
        if len(group_list) <= max_members:
            split.append(group_list)
            continue
        candidates = sorted(
            group_list,
            key=lambda group: (
                -len(_tokens(f"{group.representative.title} {group.representative.text}")),
                group.representative.address,
            ),
        )
        buckets: list[list[DedupGroup]] = []
        bucket_tokens: list[set[str]] = []
        for group in candidates:
            tokens = _tokens(f"{group.representative.title} {group.representative.text}")
            choices: list[tuple[float, int]] = []
            for index, bucket in enumerate(buckets):
                if len(bucket) >= max_members:
                    continue
                current = bucket_tokens[index]
                score = (
                    len(tokens.intersection(current)) / len(tokens.union(current))
                    if tokens and current
                    else 0.0
                )
                choices.append((score, index))
            if not choices:
                buckets.append([group])
                bucket_tokens.append(set(tokens))
                continue
            score, bucket_index = max(choices, key=lambda item: (item[0], -item[1]))
            if score < threshold and len(buckets) * max_members < len(group_list):
                buckets.append([group])
                bucket_tokens.append(set(tokens))
                continue
            buckets[bucket_index].append(group)
            bucket_tokens[bucket_index].update(tokens)
        split.extend(buckets)

    clusters = []
    for group_list in split:
        label = _topic_label(group_list)
        seed = min(group.representative.address for group in group_list)
        cluster_id = "ctx_" + _hash_text(seed)[:20]
        clusters.append(TopicCluster(cluster_id, label, group_list))

    previous = previous or []
    claimed_previous: set[str] = set()
    for cluster in clusters:
        current_members = {source.address for source in cluster.sources}
        ranked_overlaps = sorted(
            (
                (
                    len(current_members.intersection(set(row.get("member_addresses") or []))),
                    row,
                )
                for row in previous
            ),
            key=lambda item: (-item[0], str(item[1].get("cluster_id") or "")),
        )
        overlaps = [row for overlap, row in ranked_overlaps if overlap]
        if ranked_overlaps and ranked_overlaps[0][0]:
            overlap, prior = ranked_overlaps[0]
            prior_id = str(prior.get("cluster_id") or "")
            prior_members = set(prior.get("member_addresses") or [])
            if (
                prior_id
                and prior_id not in claimed_previous
                and overlap / max(1, len(current_members)) >= 0.5
                and overlap / max(1, len(prior_members)) >= 0.5
            ):
                cluster.cluster_id = prior_id
                claimed_previous.add(prior_id)
        if len(overlaps) > 1:
            cluster.merged_from = sorted(str(row["cluster_id"]) for row in overlaps)
        elif len(overlaps) == 1 and str(overlaps[0].get("cluster_id")) != cluster.cluster_id:
            cluster.split_from = [str(overlaps[0]["cluster_id"])]
    return sorted(clusters, key=lambda cluster: (cluster.topic_label.casefold(), cluster.cluster_id))


def context_cache_key(
    cluster: TopicCluster,
    *,
    provider: str | None,
    model: str | None,
    generation: dict[str, Any] | None = None,
    topic_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    semantic_threshold: float = DEFAULT_SEMANTIC_DUPLICATE_THRESHOLD,
) -> str:
    """Hash every input that can change a cluster's rendered body.

    Thresholds are parameters rather than module constants because the caller
    can override them; reading the constants here would return an identical key
    for two builds run at different thresholds, serving stale prose after a
    policy change while reporting a cache hit.

    Collapsed members are included because the rendered body reports duplicate
    counts and collapsed sources, so a dedup change alters output even when the
    representatives are unchanged.
    """
    payload = {
        "member_atom_ids_and_hashes": sorted(
            (source.address, source.content_hash) for source in cluster.sources
        ),
        "collapsed_member_hashes": sorted(
            (member.address, member.content_hash)
            for group in cluster.groups
            for member in group.collapsed
        ),
        "held_back_reasons": sorted(
            group.held_back_reason for group in cluster.groups if group.held_back_reason
        ),
        "clustering_algorithm_version": CLUSTERING_VERSION,
        "similarity_thresholds": {
            "topic": topic_threshold,
            "semantic_duplicate": semantic_threshold,
        },
        "dedup_policy_version": DEDUP_POLICY_VERSION,
        "authority_rules_version": AUTHORITY_RULES_VERSION,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "provider": provider,
        "role": "consolidate",
        "generation_parameters": generation or {},
    }
    return _hash_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def artifact_is_user_edited(path: Path) -> bool:
    """True when a generated topic file has been changed by hand.

    Derived from the file's own `body_hash` frontmatter rather than from the
    state file, so a missing or corrupt `latest.json` cannot silently downgrade
    an edited file to overwritable. Unparseable frontmatter is treated as edited,
    because the safe failure here is refusing to overwrite.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not raw.startswith("---\n"):
        return True
    _, _, remainder = raw.partition("---\n")
    front, separator, body = remainder.partition("\n---\n")
    if not separator:
        return True
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        return True
    if not isinstance(meta, dict):
        return True
    recorded = meta.get("body_hash")
    if not isinstance(recorded, str) or not recorded:
        # Written before body_hash existed. Fall back to the state file, which
        # the caller consults; do not claim the file is untouched.
        return False
    return _hash_text(body.lstrip("\n")) != recorded


class ContextEngine:
    def __init__(self, project_path: str | Path, *, agent=None) -> None:
        from docmancer.memory import MemoryAgent
        from docmancer.memory.tree.project import ensure_project, tree_paths

        self.project_path = Path(project_path).expanduser().resolve()
        self.project = ensure_project(self.project_path)
        self.tree_root = tree_paths(self.project_path)[0]
        self.generated_root = self.tree_root / "context"
        self.state_root = self.project_path / ".docmancer" / "state" / "context"
        self.revisions_root = self.state_root / "revisions"
        self.cache_root = self.state_root / "cache"
        self.proposals_root = self.state_root / "proposals"
        self.latest_path = self.state_root / "latest.json"
        self.tombstones_path = self.state_root / "retired-clusters.json"
        self.trash_root = self.state_root / "trash"
        # Held on the engine so the cache key can record the values actually
        # used rather than the module defaults.
        self.topic_threshold = DEFAULT_SIMILARITY_THRESHOLD
        self.semantic_threshold = DEFAULT_SEMANTIC_DUPLICATE_THRESHOLD
        self.agent = agent or MemoryAgent()
        self.distillation = getattr(
            getattr(self.agent, "config", None),
            "distillation",
            None,
        )
        self._last_render_stats: dict[str, Any] = {}

    def _generation_options(self, mode: str) -> CompletionOptions:
        """Per-role options from config, falling back to the consolidate defaults."""
        from docmancer.ai.provider_protocol import options_for_role

        providers = getattr(getattr(self.agent, "config", None), "providers", None)
        if providers is None:
            return CompletionOptions(
                top_p=0.95, max_output_tokens=8192, reasoning_effort="low", mode=mode
            )
        return options_for_role("consolidate", providers, mode=mode)

    def _resolve_generated_path(self, value: object) -> Path:
        """Resolve a manifest-recorded artifact path back inside the tree.

        Manifests record absolute paths, but a project can move and a manifest
        can be hand-edited, so paths are re-resolved against `generated_root`
        and rejected if they escape it. Without this, `rollback` and `retire`
        would write to and unlink arbitrary locations named by a JSON file.
        """
        candidate = Path(str(value or ""))
        root = self.generated_root.resolve()
        try:
            resolved = candidate.resolve()
            if resolved.is_relative_to(root):
                return resolved
        except (OSError, ValueError):
            pass
        return root / candidate.name

    def _project_id(self) -> str:
        value = getattr(self.project, "project_id", None)
        return str(value or hashlib.sha256(str(self.project_path).encode()).hexdigest()[:20])

    def _sources(self) -> list[ContextSource]:
        """Collect consolidation input.

        Generated content is excluded by the retrieval layer itself
        (`indexed_atoms` and `TreeMemoryFile.is_generated`), not by a path check
        here, so the spec 15.6 invariant survives a relocated tree or a caller
        that forgets to filter.
        """
        sources: list[ContextSource] = []
        for atom in self.agent.indexed_atoms():
            if atom.generated:  # defence in depth; already excluded upstream
                continue
            if _is_transcript_noise(atom):
                continue
            path = str(atom.source_path or "")
            authority = authority_for_kind(atom.kind)
            sources.append(
                ContextSource(
                    address=f"memory://atom/{atom.atom_id}",
                    content_hash=atom.content_hash,
                    text=atom.text,
                    title=atom.title,
                    path=path,
                    harness=atom.harness,
                    recorded_at=str(atom.timestamp or ""),
                    scope=atom.scope,
                    authority=authority,
                    lifecycle=atom.status,
                )
            )
        from docmancer.memory.tree.store import TreeStore

        for entry in TreeStore(self.tree_root).index.entries():
            if (
                entry.is_generated
                or entry.status != "active"
                or "docmancer-scaffold" in entry.tags
            ):
                continue
            sources.append(
                ContextSource(
                    address=entry.address,
                    content_hash=entry.content_hash,
                    text=entry.body,
                    title=entry.title,
                    path=str(entry.path),
                    harness="docmancer",
                    recorded_at=entry.updated_at,
                    scope=entry.scope,
                    authority=entry.authority,
                    lifecycle=entry.status,
                )
            )
        unique = {source.address: source for source in sources}
        return sorted(unique.values(), key=lambda source: source.address)

    def _load_json(self, path: Path, default):
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def latest(self) -> dict | None:
        value = self._load_json(self.latest_path, None)
        return value if isinstance(value, dict) else None

    def revisions(self) -> list[dict]:
        if not self.revisions_root.is_dir():
            return []
        rows = []
        for path in sorted(self.revisions_root.glob("*.json")):
            value = self._load_json(path, None)
            if isinstance(value, dict):
                rows.append(value)
        return sorted(rows, key=lambda row: str(row.get("generated_at") or ""))

    def revision(self, revision_id: str) -> dict:
        matches = [
            row for row in self.revisions()
            if str(row.get("revision_id") or "").startswith(revision_id)
        ]
        if len(matches) != 1:
            raise ValueError("context revision is missing or ambiguous")
        return matches[0]

    def _retired(self) -> set[str]:
        value = self._load_json(self.tombstones_path, [])
        return {str(item) for item in value if item}

    def _providerless_cluster(self, cluster: TopicCluster) -> ProviderlessCluster:
        collapsed_sources = {
            group.representative.address: tuple(source.path for source in group.collapsed)
            for group in cluster.groups
            if group.collapsed
        }
        duplicate_counts = {
            group.representative.address: 1 + len(group.collapsed)
            for group in cluster.groups
            if group.collapsed
        }
        conflicts: list[ConflictEntry] = []
        for left_index, left in enumerate(cluster.sources):
            for right in cluster.sources[left_index + 1:]:
                if _contradicts(left, right):
                    conflicts.append(
                        ConflictEntry(
                            description=f"{left.title} has conflicting recorded values",
                            sides=(
                                ConflictSide(
                                    left.text,
                                    left.recorded_at,
                                    left.path,
                                    left.address,
                                ),
                                ConflictSide(
                                    right.text,
                                    right.recorded_at,
                                    right.path,
                                    right.address,
                                ),
                            ),
                        )
                    )
        return ProviderlessCluster(
            cluster_id=cluster.cluster_id,
            topic_label=cluster.topic_label,
            members=tuple(
                ClusterMember(
                    record_id=source.address,
                    path=source.path,
                    harness=source.harness,
                    recorded_at=source.recorded_at,
                    text=source.text,
                )
                for source in cluster.sources
            ),
            duplicate_counts=duplicate_counts,
            collapsed_sources=collapsed_sources,
            conflicts=tuple(conflicts),
        )

    def _cluster_cache_path(
        self,
        cluster: TopicCluster,
        *,
        client,
        mode: str,
    ) -> tuple[str, Path]:
        generation = asdict(self._generation_options(mode))
        key = context_cache_key(
            cluster,
            provider=getattr(client, "provider_id", None) if client else None,
            model=getattr(client, "model", None) if client else None,
            generation=generation if client else {},
            topic_threshold=self.topic_threshold,
            semantic_threshold=self.semantic_threshold,
        )
        return key, self.cache_root / f"{key}.json"

    @staticmethod
    def _validated_provider_body(cluster: TopicCluster, value: object) -> str:
        body = str(value or "").strip()
        if not body:
            raise ValueError(f"provider returned an empty topic for {cluster.cluster_id}")
        allowed = {source.address for source in cluster.sources}
        if allowed and not any(address in body for address in allowed):
            raise ValueError(
                f"provider omitted source attribution for {cluster.cluster_id}"
            )
        cited = set(re.findall(r"docmancer://[^\s)]+", body))
        unknown = {
            address.rstrip(".,;:")
            for address in cited
            if address.rstrip(".,;:") not in allowed
        }
        if unknown:
            raise ValueError(
                f"provider invented source addresses for {cluster.cluster_id}"
            )
        if "\u2014" in body:
            raise ValueError("provider returned prohibited punctuation")
        return f"# {cluster.topic_label}\n\n{body}\n"

    def _render_cluster(
        self,
        cluster: TopicCluster,
        *,
        client=None,
        mode: str = "normal",
    ) -> tuple[str, bool, float | None, bool]:
        cache_key, cache_path = self._cluster_cache_path(
            cluster,
            client=client,
            mode=mode,
        )
        cached = self._load_json(cache_path, None)
        if isinstance(cached, dict) and isinstance(cached.get("body"), str):
            return (
                cached["body"],
                bool(cached.get("synthesized")),
                cached.get("cost_usd"),
                True,
            )

        providerless = self._providerless_cluster(cluster)
        if client is None:
            body = render_providerless_cluster(providerless)
            synthesized = False
            cost = None
        else:
            from docmancer.harness.secrets import redact_secrets

            evidence = redact_secrets(render_providerless_cluster(providerless))
            prompt = (
                "Synthesize the following one-topic source records into concise durable "
                "context. Preserve conflicts as both-sided warnings. Every factual sentence "
                "must end with the exact source address in parentheses. Do not invent facts "
                "and do not use em dashes.\n\n" + evidence
            )
            result = _complete_with_retry(
                client,
                [{"role": "user", "content": prompt}],
                self._generation_options(mode),
            )
            body = self._validated_provider_body(cluster, result.text)
            synthesized = True
            cost = result.cost_usd
        _atomic_text(
            cache_path,
            json.dumps(
                {
                    "cache_key": cache_key,
                    "body": body,
                    "synthesized": synthesized,
                    "cost_usd": cost,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return body, synthesized, cost, False

    def _artifact_text(
        self,
        *,
        revision_id: str,
        cluster: TopicCluster,
        body: str,
        synthesized: bool,
        source_addresses: list[str],
        evidence_addresses: list[str],
        build_inputs: dict,
        timestamp: str | None = None,
    ) -> str:
        rendered_at = timestamp or _now()
        meta = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "memory_id": _hash_text(cluster.cluster_id)[:32],
            "type": "context",
            "scope": "project",
            "authority": "advisory",
            "project_id": self._project_id(),
            "created_at": rendered_at,
            "updated_at": rendered_at,
            "sources": source_addresses,
            "status": "active",
            "revision_id": revision_id,
            "parent_revision_ids": [],
            "tags": ["generated-context", f"cluster:{cluster.cluster_id}"],
            "curation_origin": "deterministic_curation",
            "generated": True,
            # Hash of the body this file was generated with. Edit detection
            # compares the current body against this, so a user edit is
            # protected even when the state file is missing or corrupt.
            "body_hash": _hash_text(body),
            "synthesized": synthesized,
            "cluster_id": cluster.cluster_id,
            "source_addresses": source_addresses,
            "evidence_addresses": evidence_addresses,
            "build_inputs": build_inputs,
        }
        return (
            "---\n"
            + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
            + "\n---\n\n"
            + (body if body.endswith("\n") else body + "\n")
        )

    def _cluster_batches(self, clusters: list[TopicCluster]) -> list[list[TopicCluster]]:
        topic_limit = int(
            getattr(self.distillation, "topics_per_request", 16) or 16
        )
        token_limit = int(
            getattr(self.distillation, "max_input_tokens", 24_000) or 24_000
        )
        batches: list[list[TopicCluster]] = []
        current: list[TopicCluster] = []
        current_tokens = 0
        for cluster in clusters:
            estimate = max(
                1,
                len(render_providerless_cluster(self._providerless_cluster(cluster))) // 4,
            )
            if current and (
                len(current) >= topic_limit
                or current_tokens + estimate > token_limit
            ):
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(cluster)
            current_tokens += estimate
        if current:
            batches.append(current)
        return batches

    def _render_provider_batch(
        self,
        clusters: list[TopicCluster],
        *,
        client,
        mode: str,
    ) -> dict[str, tuple[str, bool, float | None, bool]]:
        from docmancer.harness.secrets import redact_secrets

        evidence_blocks = []
        for cluster in clusters:
            evidence_blocks.append(
                "TOPIC "
                + cluster.cluster_id
                + "\n"
                + redact_secrets(
                    render_providerless_cluster(
                        self._providerless_cluster(cluster)
                    )
                )
            )
        prompt = (
            "Synthesize each independent topic into concise durable context. "
            "Return only JSON with this shape: "
            '{"topics":[{"cluster_id":"ctx_...","body":"..."}]}. '
            "Return exactly one item for every supplied cluster_id and no others. "
            "The body must not include a Markdown heading. Preserve conflicts as "
            "both-sided warnings. Every factual sentence must end with an exact "
            "source address from that topic in parentheses. Do not invent facts "
            "and do not use em dashes.\n\n"
            + "\n\n".join(evidence_blocks)
        )
        result = _complete_with_retry(
            client,
            [{"role": "user", "content": prompt}],
            self._generation_options(mode),
        )
        raw = result.text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("provider did not return the requested JSON object")
        payload = json.loads(raw[start:end + 1])
        rows = payload.get("topics") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("provider JSON is missing the topics list")
        by_id = {
            str(row.get("cluster_id")): row.get("body")
            for row in rows
            if isinstance(row, dict) and row.get("cluster_id")
        }
        expected = {cluster.cluster_id for cluster in clusters}
        if set(by_id) != expected:
            raise ValueError("provider JSON did not return exactly the requested topics")

        weights = {
            cluster.cluster_id: max(
                1,
                sum(max(1, len(source.text) // 4) for source in cluster.sources),
            )
            for cluster in clusters
        }
        weight_total = sum(weights.values()) or 1
        output: dict[str, tuple[str, bool, float | None, bool]] = {}
        for cluster in clusters:
            body = self._validated_provider_body(
                cluster,
                by_id[cluster.cluster_id],
            )
            cost = (
                float(result.cost_usd) * weights[cluster.cluster_id] / weight_total
                if result.cost_usd is not None
                else None
            )
            cache_key, cache_path = self._cluster_cache_path(
                cluster,
                client=client,
                mode=mode,
            )
            _atomic_text(
                cache_path,
                json.dumps(
                    {
                        "cache_key": cache_key,
                        "body": body,
                        "synthesized": True,
                        "cost_usd": cost,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            output[cluster.cluster_id] = (body, True, cost, False)
        return output

    def _render_clusters(self, clusters, *, client, mode: str) -> dict:
        """Render changed topics in bounded parallel provider batches."""
        started = time.monotonic()
        cluster_list = list(clusters)
        if client is None:
            result = {
                cluster.cluster_id: self._render_cluster(
                    cluster, client=None, mode=mode
                )
                for cluster in cluster_list
            }
            self._last_render_stats = {
                "provider_calls": 0,
                "provider_batches": 0,
                "provider_failures": 0,
                "elapsed_seconds": time.monotonic() - started,
            }
            return result

        rendered: dict[str, tuple[str, bool, float | None, bool]] = {}
        pending: list[TopicCluster] = []
        for cluster in cluster_list:
            _cache_key, cache_path = self._cluster_cache_path(
                cluster,
                client=client,
                mode=mode,
            )
            cached = self._load_json(cache_path, None)
            if isinstance(cached, dict) and isinstance(cached.get("body"), str):
                rendered[cluster.cluster_id] = (
                    cached["body"],
                    bool(cached.get("synthesized")),
                    cached.get("cost_usd"),
                    True,
                )
            else:
                pending.append(cluster)

        batches = self._cluster_batches(pending)
        failures = 0
        if batches:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            configured = int(
                getattr(
                    self.distillation,
                    "max_concurrency",
                    CONTEXT_BUILD_CONCURRENCY,
                )
                or CONTEXT_BUILD_CONCURRENCY
            )
            workers = max(1, min(configured, len(batches)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        self._render_provider_batch,
                        batch,
                        client=client,
                        mode=mode,
                    ): batch
                    for batch in batches
                }
                for future in as_completed(futures):
                    batch = futures[future]
                    try:
                        rendered.update(future.result())
                    except Exception:
                        failures += 1
                        # A failed provider batch must not discard successful
                        # work or fail the whole build. Keep every topic visible
                        # through the deterministic renderer and leave the
                        # provider-specific cache empty for a future retry.
                        for cluster in batch:
                            rendered[cluster.cluster_id] = self._render_cluster(
                                cluster,
                                client=None,
                                mode=mode,
                            )

        self._last_render_stats = {
            "provider_calls": len(batches),
            "provider_batches": len(batches),
            "provider_failures": failures,
            "elapsed_seconds": time.monotonic() - started,
        }
        target = float(
            getattr(self.distillation, "target_seconds", 8.0) or 8.0
        )
        self._last_render_stats["target_seconds"] = target
        self._last_render_stats["target_met"] = (
            self._last_render_stats["elapsed_seconds"] <= target
        )
        return rendered

    def _artifact_path(self, cluster: TopicCluster) -> Path:
        return self.generated_root / f"{_slug(cluster.topic_label)}-{cluster.cluster_id[4:12]}.md"

    def plan(self) -> dict:
        sources = self._sources()
        groups, conflicts, dedup_stats = safe_deduplicate(sources, semantic_threshold=self.semantic_threshold)
        previous = self.latest() or {}
        clusters = [
            cluster
            for cluster in cluster_topics(groups, previous=previous.get("clusters"), threshold=self.topic_threshold)
            if cluster.cluster_id not in self._retired()
        ]
        batches = self._cluster_batches(clusters)
        return {
            "sources": sources,
            "groups": groups,
            "conflicts": conflicts,
            "dedup": dedup_stats,
            "clusters": clusters,
            "estimated_provider_calls": len(batches),
            "estimated_provider_batches": len(batches),
            "estimated_input_tokens": sum(max(1, len(source.text) // 4) for source in sources),
            "estimated_output_tokens": len(clusters) * ESTIMATED_OUTPUT_TOKENS_PER_CLUSTER,
            "estimated_cost_usd": round(
                (
                    sum(max(1, len(source.text) // 4) for source in sources)
                    * ESTIMATED_INPUT_USD_PER_1K
                    + len(clusters)
                    * ESTIMATED_OUTPUT_TOKENS_PER_CLUSTER
                    * ESTIMATED_OUTPUT_USD_PER_1K
                )
                / 1000,
                6,
            ),
        }

    def build(
        self,
        *,
        client=None,
        dry_run: bool = False,
        full: bool = False,
        mode: str = "normal",
        rollback_from: dict | None = None,
    ) -> dict:
        plan = self.plan()
        previous = self.latest()
        provider = getattr(client, "provider_id", None) if client else None
        model = getattr(client, "model", None) if client else None
        policy = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "clustering_version": CLUSTERING_VERSION,
            "dedup_policy_version": DEDUP_POLICY_VERSION,
            "authority_rules_version": AUTHORITY_RULES_VERSION,
            "redaction_policy_version": REDACTION_POLICY_VERSION,
            "context_policy_version": CONTEXT_POLICY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "provider": provider,
            "model": model,
            "mode": mode,
            "retired_cluster_ids": sorted(self._retired()),
        }
        if rollback_from is not None:
            policy["rollback_nonce"] = _now()
            source_pairs = [
                (str(row["file_address"]), str(row["file_revision_hash"]))
                for row in rollback_from.get("members", [])
            ]
        else:
            source_pairs = [(source.address, source.content_hash) for source in plan["sources"]]
        revision_id = content_revision_id(source_pairs, policy)
        report = {
            "dry_run": dry_run,
            "revision_id": revision_id,
            "previous_revision_id": previous.get("revision_id") if previous else None,
            "input_sources": len(plan["sources"]),
            "clusters": len(plan["clusters"]),
            "dedup": plan["dedup"],
            "conflicts": len(plan["conflicts"]),
            # A cost preview that reports zero because no client was built is
            # the opposite of a cost preview. Estimate from the plan; report
            # actual calls separately once a run happens.
            "estimated_provider_calls": plan["estimated_provider_calls"],
            "estimated_input_tokens": plan["estimated_input_tokens"],
            "estimated_output_tokens": plan["estimated_output_tokens"],
            "estimated_cost_usd": plan["estimated_cost_usd"],
            "provider": provider,
            "model": model,
            "writes": [],
        }
        if dry_run:
            report["collapse_plan"] = [
                {
                    "representative": group.representative.address,
                    "collapsed": [source.address for source in group.collapsed],
                }
                for group in plan["groups"]
                if group.collapsed
            ]
            report["holdbacks"] = plan["conflicts"]
            report["cluster_plan"] = [
                {
                    "cluster_id": cluster.cluster_id,
                    "topic_label": cluster.topic_label,
                    "members": len(cluster.sources),
                    "split_from": cluster.split_from,
                    "merged_from": cluster.merged_from,
                }
                for cluster in plan["clusters"]
            ]
            return report
        if previous and previous.get("revision_id") == revision_id and not full:
            return {**report, "changed": False, "cache_hits": len(plan["clusters"])}

        build_time = (
            str(previous.get("generated_at"))
            if previous and previous.get("revision_id") == revision_id
            else _now()
        )
        topics = []
        cache_hits = 0
        cost = 0.0
        previous_cluster_hashes = {
            str(row.get("cluster_id")): str(row.get("member_hash") or "")
            for row in (previous or {}).get("clusters", [])
        }
        # Render clusters up front, concurrently when a provider is involved.
        # Each call is an independent HTTP round trip of several seconds, so a
        # sequential loop made wall-clock scale linearly with cluster count: a
        # 634-cluster build took over an hour purely waiting on the network.
        # The writes below stay sequential and in order, so artifact ordering
        # and the manifest are unchanged; only the network waiting overlaps.
        rendered = self._render_clusters(plan["clusters"], client=client, mode=mode)

        stale_cluster_ids = []
        for cluster in plan["clusters"]:
            member_hash = _hash_text(
                json.dumps(
                    sorted((source.address, source.content_hash) for source in cluster.sources)
                )
            )
            if previous_cluster_hashes.get(cluster.cluster_id) != member_hash:
                stale_cluster_ids.append(cluster.cluster_id)
            body, synthesized, cluster_cost, cache_hit = rendered[cluster.cluster_id]
            cache_hits += int(cache_hit)
            cost += float(cluster_cost or 0.0)
            path = self._artifact_path(cluster)
            source_addresses = [source.address for source in cluster.sources]
            artifact = self._artifact_text(
                revision_id=revision_id,
                cluster=cluster,
                body=body,
                synthesized=synthesized,
                source_addresses=source_addresses,
                evidence_addresses=[
                    collapsed.address
                    for group in cluster.groups
                    for collapsed in group.collapsed
                ],
                build_inputs=policy,
                timestamp=build_time,
            )
            state = "generated-untouched"
            if path.is_file():
                current = path.read_text(encoding="utf-8")
                prior_topic = next(
                    (
                        topic for topic in (previous or {}).get("topics", [])
                        if topic.get("path") == str(path)
                    ),
                    None,
                )
                # The file's own body_hash is authoritative; the state file is a
                # fallback for artifacts written before that marker existed.
                edited = artifact_is_user_edited(path)
                if not edited and prior_topic:
                    edited = (
                        prior_topic.get("state") == "generated-edited"
                        or _hash_text(current) != prior_topic.get("artifact_hash")
                    )
                if edited:
                    state = "generated-edited"
                    proposal = self.proposals_root / f"{cluster.cluster_id}.diff"
                    diff = "".join(
                        difflib.unified_diff(
                            current.splitlines(keepends=True),
                            artifact.splitlines(keepends=True),
                            fromfile=str(path),
                            tofile=str(path) + " (proposed)",
                        )
                    )
                    _atomic_text(proposal, diff)
                    report["writes"].append(
                        {"path": str(path), "state": state, "proposal": str(proposal)}
                    )
                else:
                    _atomic_text(path, artifact)
                    report["writes"].append({"path": str(path), "state": state})
            else:
                _atomic_text(path, artifact)
                report["writes"].append({"path": str(path), "state": state})
            topics.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "revision_id": revision_id,
                    "path": str(path),
                    "artifact_hash": _hash_text(
                        path.read_text(encoding="utf-8") if path.is_file() else artifact
                    ),
                    "body": body,
                    "synthesized": synthesized,
                    "source_addresses": source_addresses,
                    "state": state,
                }
            )

        manifest = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "revision_id": revision_id,
            "parent_revision_id": (
                previous.get("parent_revision_id")
                if previous and previous.get("revision_id") == revision_id
                else previous.get("revision_id") if previous else None
            ),
            "reinstates": rollback_from.get("revision_id") if rollback_from else None,
            "scope": {"audience": "personal", "project_id": self._project_id()},
            "generated_at": build_time,
            "members": [
                {
                    "file_address": source.address,
                    "file_revision_hash": source.content_hash,
                    "cluster_id": next(
                        (
                            cluster.cluster_id
                            for cluster in plan["clusters"]
                            if any(item.address == source.address for item in cluster.sources)
                        ),
                        None,
                    ),
                    "authority": source.authority,
                    "lifecycle": source.lifecycle,
                }
                for source in plan["sources"]
            ],
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "topic_label": cluster.topic_label,
                    "member_count": len(cluster.sources),
                    "source_count": sum(1 + len(group.collapsed) for group in cluster.groups),
                    "synthesized": bool(
                        next(topic for topic in topics if topic["cluster_id"] == cluster.cluster_id)["synthesized"]
                    ),
                    "member_hash": _hash_text(
                        json.dumps(
                            sorted(
                                (source.address, source.content_hash)
                                for source in cluster.sources
                            )
                        )
                    ),
                    "member_addresses": [source.address for source in cluster.sources],
                    "split_from": cluster.split_from,
                    "merged_from": cluster.merged_from,
                }
                for cluster in plan["clusters"]
            ],
            "conflicts": plan["conflicts"],
            "excluded": [
                {
                    "reason": reason,
                    "count": count,
                }
                for reason, count in sorted(plan["dedup"]["held_back"].items())
            ],
            "freshness": {
                "stale_cluster_ids": stale_cluster_ids,
                "oldest_member_at": min(
                    (source.recorded_at for source in plan["sources"] if source.recorded_at),
                    default=None,
                ),
                "last_full_build_at": (
                    _now()
                    if full or not previous
                    else (previous.get("freshness") or {}).get("last_full_build_at")
                ),
            },
            "cost_estimate": {
                "provider_calls": (
                    int(self._last_render_stats.get("provider_calls") or 0)
                    if client
                    else 0
                ),
                "provider_cost_usd": cost if client else 0.0,
                "provider_failures": int(
                    self._last_render_stats.get("provider_failures") or 0
                ),
                "elapsed_seconds": round(
                    float(self._last_render_stats.get("elapsed_seconds") or 0.0),
                    6,
                ),
                "target_seconds": float(
                    self._last_render_stats.get("target_seconds")
                    or getattr(self.distillation, "target_seconds", 8.0)
                    or 8.0
                ),
                "target_met": bool(self._last_render_stats.get("target_met")),
            },
            "build_inputs": policy,
            "topics": topics,
        }
        _atomic_text(
            self.revisions_root / f"{revision_id}.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        _atomic_text(self.latest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return {
            **report,
            "changed": True,
            "cache_hits": cache_hits,
            "provider_calls": manifest["cost_estimate"]["provider_calls"],
            "cost_usd": manifest["cost_estimate"]["provider_cost_usd"],
            "stale_cluster_ids": stale_cluster_ids,
        }

    def rollback(self, revision_id: str) -> dict:
        selected = self.revision(revision_id)
        current = self.latest()
        if current is None:
            raise ValueError("no current context revision exists")
        restored = dict(selected)
        policy = dict(selected.get("build_inputs") or {})
        policy["rollback_nonce"] = _now()
        new_id = content_revision_id(
            (
                (str(row["file_address"]), str(row["file_revision_hash"]))
                for row in selected.get("members", [])
            ),
            policy,
        )
        restored.update(
            revision_id=new_id,
            parent_revision_id=current["revision_id"],
            reinstates=selected["revision_id"],
            generated_at=_now(),
            build_inputs=policy,
        )
        skipped_edited: list[str] = []
        for topic in restored.get("topics", []):
            path = self._resolve_generated_path(topic.get("path"))
            body = str(topic.get("body") or "")
            cluster = next(
                row for row in restored.get("clusters", [])
                if row["cluster_id"] == topic["cluster_id"]
            )
            artifact = self._artifact_text(
                revision_id=new_id,
                cluster=TopicCluster(
                    cluster_id=str(cluster["cluster_id"]),
                    topic_label=str(cluster["topic_label"]),
                    groups=[],
                ),
                body=body,
                synthesized=bool(topic.get("synthesized")),
                source_addresses=list(topic.get("source_addresses") or []),
                evidence_addresses=[],
                build_inputs=policy,
                timestamp=str(restored["generated_at"]),
            )
            if artifact_is_user_edited(path):
                # Reinstating a revision must not silently discard hand edits.
                # Propose the historical body as a diff and leave the file alone.
                proposal = self.proposals_root / f"{topic['cluster_id']}.rollback.diff"
                _atomic_text(
                    proposal,
                    "".join(
                        difflib.unified_diff(
                            path.read_text(encoding="utf-8").splitlines(keepends=True),
                            artifact.splitlines(keepends=True),
                            fromfile=str(path),
                            tofile=f"{path} (reinstated {selected['revision_id']})",
                        )
                    ),
                )
                topic["state"] = "generated-edited"
                topic["proposal"] = str(proposal)
                skipped_edited.append(str(path))
                continue
            _atomic_text(path, artifact)
            topic["revision_id"] = new_id
            topic["artifact_hash"] = _hash_text(artifact)
        _atomic_text(
            self.revisions_root / f"{new_id}.json",
            json.dumps(restored, indent=2, sort_keys=True) + "\n",
        )
        _atomic_text(self.latest_path, json.dumps(restored, indent=2, sort_keys=True) + "\n")
        if skipped_edited:
            restored["skipped_user_edited"] = skipped_edited
        return restored

    def retire(self, cluster_id: str) -> dict:
        retired = self._retired()
        retired.add(cluster_id)
        _atomic_text(
            self.tombstones_path,
            json.dumps(sorted(retired), indent=2) + "\n",
        )
        latest = self.latest() or {}
        topic = next(
            (
                row for row in latest.get("topics", [])
                if str(row.get("cluster_id")) == cluster_id
            ),
            None,
        )
        result = {"cluster_id": cluster_id, "retired": True}
        if topic:
            path = self._resolve_generated_path(topic.get("path"))
            if path.is_file():
                if artifact_is_user_edited(path):
                    # Never delete work a human wrote. Retire the topic so it is
                    # not rebuilt, and leave the file for the user to remove.
                    result["kept_user_edited"] = str(path)
                else:
                    trashed = self.trash_root / f"{cluster_id}-{path.name}"
                    trashed.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_text(trashed, path.read_text(encoding="utf-8"))
                    path.unlink(missing_ok=True)
                    result["trashed"] = str(trashed)
        return result

    def adopt(self, cluster_id: str, *, destination: str | None = None) -> dict:
        latest = self.latest()
        if latest is None:
            raise ValueError("no current context revision exists")
        topic = next(
            (
                row for row in latest.get("topics", [])
                if str(row.get("cluster_id")) == cluster_id
            ),
            None,
        )
        if topic is None:
            raise ValueError("context cluster was not found")
        cluster = next(
            row for row in latest.get("clusters", [])
            if str(row.get("cluster_id")) == cluster_id
        )
        from docmancer.memory.tree.store import TreeStore

        relative = destination or f"adopted/{_slug(str(cluster['topic_label']))}.md"
        entry = TreeStore(self.tree_root).write(
            relative_path=relative,
            text=str(topic.get("body") or ""),
            memory_type="fact",
            scope="project",
            project_id=self._project_id(),
            sources=list(topic.get("source_addresses") or []),
            curation_origin="deliberate_write",
            expect="absent",
            actor_surface="context-adopt",
        )
        self.retire(cluster_id)
        return {
            "cluster_id": cluster_id,
            "adopted": True,
            "address": entry.address,
            "path": str(entry.path),
        }


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "ContextEngine",
    "ContextSource",
    "DedupGroup",
    "TopicCluster",
    "cluster_topics",
    "context_cache_key",
    "safe_deduplicate",
]
