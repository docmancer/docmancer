"""First-class local memory graph and lifecycle intelligence.

The graph is a rebuildable projection beside the search index. Durable human
decisions about suggested relations live in a separate overrides table so a
normal ``memory sync`` can recompute the graph without discarding review work.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable, Sequence

from docmancer.memory.atomic import AtomicMemoryEntry


GRAPH_SCHEMA_VERSION = 2
RELATION_TYPES = {"relates_to", "derived_from", "supersedes", "contradicts"}
RESOLUTION_STATES = {"suggested", "confirmed", "rejected"}
_TRUST = {"manual": 4, "mcp": 4, "promoted": 3, "capture": 2, "harvested": 1}
_ASSIGNMENT = re.compile(
    r"^(?P<subject>[a-z0-9][a-z0-9 _./-]{1,79}?)\s+"
    r"(?P<predicate>uses?|runs? on|deploys? (?:to|on)|database is|"
    r"package manager is|is stored in|is hosted on)\s+"
    r"(?P<value>[a-z0-9][a-z0-9 _./+-]{0,79})[.!]?$",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[a-z0-9][a-z0-9_.-]*", re.IGNORECASE)
_CURRENT_CUE = re.compile(r"\b(?:current|currently|latest|now|active)\b", re.IGNORECASE)
_STALE_CUE = re.compile(r"\b(?:retired|obsolete|previous|formerly|legacy|old)\b", re.IGNORECASE)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "we", "with",
}


@dataclass(frozen=True)
class MemoryRelation:
    relation_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    resolution_state: str
    winner_node_id: str | None
    confidence: float
    detector: str
    evidence: dict
    created_at: str
    updated_at: str


def node_id(atom: AtomicMemoryEntry) -> str:
    """Return a stable graph identity without exposing an absolute path."""
    if atom.record_id:
        # A durable record is a stable logical object, but each immutable
        # revision needs its own graph node so a supersedes edge never loops
        # back onto the same node.
        revision = atom.revision_id or atom.content_hash
        return f"record:{atom.record_id}:{revision}"
    portable_source = Path(atom.source_path).name
    if atom.project_path:
        try:
            portable_source = str(Path(atom.source_path).resolve().relative_to(Path(atom.project_path).resolve()))
        except (OSError, ValueError):
            pass
    identity = "\n".join(
        [atom.scope_kind, atom.project_id or "", atom.harness, portable_source, atom.content_hash]
    )
    return "node:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


@lru_cache(maxsize=32_768)
def _tokens(text: str) -> set[str]:
    return {word.casefold() for word in _WORDS.findall(text) if word.casefold() not in _STOP}


@lru_cache(maxsize=32_768)
def _assignment_parts(text: str) -> tuple[str, str, str] | None:
    compact = " ".join(text.split())
    if len(compact) > 240 or any(marker in compact for marker in (" > ", "`", ":")):
        return None
    match = _ASSIGNMENT.fullmatch(compact)
    if not match:
        return None
    subject = " ".join(match["subject"].casefold().split())
    predicate = " ".join(match["predicate"].casefold().split())
    value = " ".join(match["value"].casefold().split())
    return f"{subject}|{predicate}", subject, value


def _relation_id(kind: str, left: str, right: str) -> str:
    ordered = sorted((left, right)) if kind == "contradicts" else [left, right]
    raw = "\n".join([kind, *ordered])
    return "rel_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _pair_fingerprint(kind: str, left_hash: str, right_hash: str) -> str:
    raw = "\n".join([kind, *sorted((left_hash, right_hash))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MemoryGraphStore:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self._initialized = False
        self._initialize_lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _schema_is_current(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM memory_graph_meta WHERE key='schema_version'"
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).casefold():
                return False
            raise
        return row is not None and str(row["value"]) == str(GRAPH_SCHEMA_VERSION)

    def initialize(self) -> None:
        if self._initialized and self.path.is_file():
            return
        with self._initialize_lock:
            if self._initialized and self.path.is_file():
                return
            # Existing graph databases need no schema write. This matters when
            # another process is rebuilding the graph: readers can keep using
            # the previous committed snapshot without competing for its write
            # lock merely because they opened the Intelligence tab.
            if self._schema_is_current():
                self._initialized = True
                return
            with self._connect() as conn:
                conn.executescript(
                    """
                CREATE TABLE IF NOT EXISTS memory_atoms (
                    node_id TEXT PRIMARY KEY,
                    atom_id TEXT NOT NULL,
                    record_id TEXT,
                    revision_id TEXT,
                    text TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    harness TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_kind TEXT NOT NULL,
                    project_id TEXT,
                    project_path TEXT,
                    source_path TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    source_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_count INTEGER NOT NULL DEFAULT 1,
                    timestamp TEXT,
                    lifecycle_state TEXT NOT NULL DEFAULT 'current'
                        CHECK (lifecycle_state IN ('current','superseded','expired')),
                    present INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS memory_atoms_record_idx ON memory_atoms(record_id);
                CREATE INDEX IF NOT EXISTS memory_atoms_scope_idx ON memory_atoms(scope_kind, project_id);
                CREATE INDEX IF NOT EXISTS memory_atoms_state_idx ON memory_atoms(lifecycle_state, present);

                CREATE TABLE IF NOT EXISTS memory_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_node_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL
                        CHECK (relation_type IN ('relates_to','derived_from','supersedes','contradicts')),
                    pair_fingerprint TEXT NOT NULL,
                    resolution_state TEXT NOT NULL DEFAULT 'suggested'
                        CHECK (resolution_state IN ('suggested','confirmed','rejected')),
                    winner_node_id TEXT,
                    confidence REAL NOT NULL,
                    detector TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memory_relations_source_idx ON memory_relations(source_node_id);
                CREATE INDEX IF NOT EXISTS memory_relations_target_idx ON memory_relations(target_node_id);
                CREATE INDEX IF NOT EXISTS memory_relations_type_idx ON memory_relations(relation_type, resolution_state);

                CREATE TABLE IF NOT EXISTS memory_relation_overrides (
                    pair_fingerprint TEXT PRIMARY KEY,
                    resolution_state TEXT NOT NULL
                        CHECK (resolution_state IN ('confirmed','rejected')),
                    winner_content_hash TEXT,
                    resolution TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_graph_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cloud_graph_objects (
                    object_id TEXT PRIMARY KEY,
                    object_kind TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                    """
                )
                self._repair_legacy_machine_conflicts(conn)
                conn.execute(
                    "INSERT INTO memory_graph_meta(key,value) VALUES('schema_version',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(GRAPH_SCHEMA_VERSION),),
                )
            self._initialized = True

    @classmethod
    def _repair_legacy_machine_conflicts(cls, conn: sqlite3.Connection) -> None:
        """Remove pre-v2 guesses and restore atom lifecycle before normal reads."""
        conn.execute(
            """
            DELETE FROM memory_relations
            WHERE relation_type='contradicts'
              AND NOT EXISTS(
                SELECT 1 FROM memory_relation_overrides o
                WHERE o.pair_fingerprint=memory_relations.pair_fingerprint
              )
            """
        )
        conn.execute(
            """
            UPDATE memory_atoms SET lifecycle_state=CASE
              WHEN memory_type='status' AND timestamp IS NOT NULL
                AND julianday('now') - julianday(timestamp) > 90 THEN 'expired'
              ELSE 'current' END
            """
        )
        cls._apply_confirmed_lifecycle(conn)

    def rebuild(
        self,
        atoms: list[AtomicMemoryEntry],
        *,
        now: datetime | None = None,
        embed_texts: Callable[[list[str]], Sequence[Sequence[float]]] | None = None,
    ) -> dict[str, int]:
        self.initialize()
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        stamp = moment.isoformat(timespec="seconds")
        current = [(node_id(atom), atom) for atom in atoms]
        with self._connect() as conn:
            previous = {
                str(row["node_id"]): dict(row)
                for row in conn.execute("SELECT * FROM memory_atoms")
            }
            conn.execute("UPDATE memory_atoms SET present=0")
            for identity, atom in current:
                state = self._lifecycle(atom, moment)
                metadata = {
                    "tags": atom.tags,
                    "parent_revision_ids": atom.parent_revision_ids,
                    "merged_from": atom.merged_from,
                    "deleted": atom.deleted,
                }
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                      node_id,atom_id,record_id,revision_id,text,memory_type,origin,harness,kind,
                      scope,scope_kind,project_id,project_path,source_path,source_title,line_start,
                      line_end,source_hash,content_hash,source_count,timestamp,lifecycle_state,
                      present,first_seen_at,last_seen_at,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)
                    ON CONFLICT(node_id) DO UPDATE SET
                      atom_id=excluded.atom_id,record_id=excluded.record_id,revision_id=excluded.revision_id,
                      text=excluded.text,memory_type=excluded.memory_type,origin=excluded.origin,
                      harness=excluded.harness,kind=excluded.kind,scope=excluded.scope,
                      scope_kind=excluded.scope_kind,project_id=excluded.project_id,
                      project_path=excluded.project_path,source_path=excluded.source_path,
                      source_title=excluded.source_title,line_start=excluded.line_start,
                      line_end=excluded.line_end,source_hash=excluded.source_hash,
                      content_hash=excluded.content_hash,source_count=excluded.source_count,
                      timestamp=excluded.timestamp,lifecycle_state=excluded.lifecycle_state,
                      present=1,last_seen_at=memory_atoms.last_seen_at,
                      metadata_json=excluded.metadata_json
                    """,
                    (
                        identity, atom.atom_id, atom.record_id, atom.revision_id, atom.text, atom.type,
                        atom.origin, atom.harness, atom.kind, atom.scope, atom.scope_kind, atom.project_id,
                        atom.project_path, atom.source_path, atom.source_title, atom.line_start, atom.line_end,
                        atom.source_hash, atom.content_hash, atom.source_count, atom.timestamp, state,
                        previous.get(identity, {}).get("first_seen_at", stamp), stamp,
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
            relations = self._detect_relations(current, previous, stamp)
            conn.execute("DELETE FROM memory_relations")
            for relation in relations:
                self._insert_relation(conn, relation)
            self._merge_cloud_relations(conn)
            self._merge_cloud_overrides(conn)
            self._discard_unsafe_machine_conflicts(conn)
            self._apply_overrides(conn)
            self._apply_confirmed_lifecycle(conn)
        return {
            "nodes": len(current),
            "relations": len(relations),
            "conflicts": sum(1 for row in relations if row.relation_type == "contradicts"),
        }

    @staticmethod
    def _lifecycle(atom: AtomicMemoryEntry, now: datetime) -> str:
        timestamp = _parse_time(atom.timestamp)
        if atom.type == "status" and timestamp and now - timestamp > timedelta(days=90):
            return "expired"
        return "current"

    def _detect_relations(
        self,
        current: list[tuple[str, AtomicMemoryEntry]],
        previous: dict[str, dict],
        stamp: str,
    ) -> list[MemoryRelation]:
        relations: dict[str, MemoryRelation] = {}
        current_by_record = {atom.record_id: (identity, atom) for identity, atom in current if atom.record_id}
        for old_id, old in previous.items():
            record = old.get("record_id")
            if not record or record not in current_by_record:
                continue
            new_id, new = current_by_record[record]
            if old.get("revision_id") and old.get("revision_id") in new.parent_revision_ids:
                relation = self._relation(
                    "supersedes", new_id, old_id, new, old,
                    state="confirmed", winner=new_id, confidence=1.0,
                    detector="revision-lineage", stamp=stamp,
                )
                relations[relation.relation_id] = relation

        candidates = self._candidate_pairs(current)
        for left_index, right_index in candidates:
            left_id, left = current[left_index]
            right_id, right = current[right_index]
            if left.content_hash == right.content_hash:
                relation = self._relation(
                    "derived_from", left_id, right_id, left, asdict(right),
                    state="confirmed", winner=self._winner(left_id, left, right_id, right),
                    confidence=1.0, detector="exact-content", stamp=stamp,
                )
                relations[relation.relation_id] = relation
                continue
            confidence, evidence = self._contradiction_confidence(left.text, right.text)
            if confidence <= 0:
                continue
            relation = self._relation(
                "contradicts", left_id, right_id, left, asdict(right),
                state="suggested", winner=None, confidence=confidence,
                detector=str(evidence.pop("detector")), stamp=stamp, evidence=evidence,
            )
            relations[relation.relation_id] = relation
        return list(relations.values())

    @classmethod
    def _candidate_pairs(
        cls, current: list[tuple[str, AtomicMemoryEntry]]
    ) -> list[tuple[int, int]]:
        """Compare exact duplicates and concise assignments in the same scope."""
        buckets: dict[tuple[str, str, str], list[int]] = {}
        for index, (_identity, atom) in enumerate(current):
            buckets.setdefault((atom.scope, atom.type, f"hash:{atom.content_hash}"), []).append(index)
            assignment = _assignment_parts(atom.text)
            if assignment:
                claim_key, _subject, _value = assignment
                buckets.setdefault((atom.scope, atom.type, f"claim:{claim_key}"), []).append(index)
        pairs: set[tuple[int, int]] = set()
        for members in buckets.values():
            for offset, left_index in enumerate(members):
                for right_index in members[offset + 1 :]:
                    pairs.add((left_index, right_index))
        return sorted(pairs)

    @staticmethod
    def _contradiction_confidence(
        left: str,
        right: str,
    ) -> tuple[float, dict]:
        left_assignment, right_assignment = _assignment_parts(left), _assignment_parts(right)
        if left_assignment and right_assignment:
            left_key, subject, left_raw_value = left_assignment
            right_key, _right_subject, right_raw_value = right_assignment
            left_value = _tokens(left_raw_value)
            right_value = _tokens(right_raw_value)
            if left_key == right_key and left_value and right_value and not (left_value & right_value):
                return 0.95, {
                    "detector": "exclusive-assignment",
                    "claim_key": left_key,
                    "subject": subject,
                    "source_value": left_raw_value,
                    "target_value": right_raw_value,
                }
        return 0.0, {}

    @staticmethod
    def _winner(left_id: str, left: AtomicMemoryEntry, right_id: str, right: AtomicMemoryEntry) -> str:
        def currentness(text: str) -> int:
            return int(bool(_CURRENT_CUE.search(text))) - int(bool(_STALE_CUE.search(text)))

        left_key = (
            _TRUST.get(left.origin, 1),
            currentness(left.text),
            _parse_time(left.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        )
        right_key = (
            _TRUST.get(right.origin, 1),
            currentness(right.text),
            _parse_time(right.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        )
        # The current list is ordered oldest to newest during sync, so the
        # right-hand atom wins an exact trust and timestamp tie.
        return left_id if left_key > right_key else right_id

    def _relation(
        self, kind: str, left_id: str, right_id: str, left: AtomicMemoryEntry,
        right: dict, *, state: str, winner: str | None, confidence: float,
        detector: str, stamp: str, evidence: dict | None = None,
    ) -> MemoryRelation:
        right_hash = str(right.get("content_hash") or "")
        fingerprint = _pair_fingerprint(kind, left.content_hash, right_hash)
        return MemoryRelation(
            relation_id=_relation_id(kind, left_id, right_id),
            source_node_id=left_id, target_node_id=right_id, relation_type=kind,
            resolution_state=state, winner_node_id=winner, confidence=round(confidence, 6),
            detector=detector, evidence={"pair_fingerprint": fingerprint, **(evidence or {})},
            created_at=stamp, updated_at=stamp,
        )

    @staticmethod
    def _insert_relation(conn: sqlite3.Connection, relation: MemoryRelation) -> None:
        evidence = dict(relation.evidence)
        fingerprint = str(evidence.pop("pair_fingerprint"))
        conn.execute(
            "INSERT INTO memory_relations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                relation.relation_id, relation.source_node_id, relation.target_node_id,
                relation.relation_type, fingerprint, relation.resolution_state,
                relation.winner_node_id, relation.confidence, relation.detector,
                json.dumps(evidence, sort_keys=True), relation.created_at, relation.updated_at,
            ),
        )

    @staticmethod
    def _apply_overrides(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE memory_relations SET
              resolution_state=(SELECT resolution_state FROM memory_relation_overrides o
                                WHERE o.pair_fingerprint=memory_relations.pair_fingerprint),
              winner_node_id=(
                SELECT CASE
                  WHEN o.winner_content_hash=(SELECT content_hash FROM memory_atoms WHERE node_id=memory_relations.source_node_id)
                    THEN memory_relations.source_node_id
                  WHEN o.winner_content_hash=(SELECT content_hash FROM memory_atoms WHERE node_id=memory_relations.target_node_id)
                    THEN memory_relations.target_node_id
                  ELSE NULL END
                FROM memory_relation_overrides o WHERE o.pair_fingerprint=memory_relations.pair_fingerprint
              )
            WHERE EXISTS(SELECT 1 FROM memory_relation_overrides o
                         WHERE o.pair_fingerprint=memory_relations.pair_fingerprint)
            """
        )

    @staticmethod
    def _discard_unsafe_machine_conflicts(conn: sqlite3.Connection) -> None:
        """Reject legacy or imported guesses that lack a structured claim key."""
        conn.execute(
            """
            DELETE FROM memory_relations
            WHERE relation_type='contradicts'
              AND (
                detector IN ('semantic-polarity','polarity')
                OR json_extract(evidence_json, '$.claim_key') IS NULL
              )
              AND NOT EXISTS(
                SELECT 1 FROM memory_relation_overrides o
                WHERE o.pair_fingerprint=memory_relations.pair_fingerprint
              )
            """
        )

    @staticmethod
    def _merge_cloud_relations(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT payload_json FROM cloud_graph_objects WHERE object_kind='relation'"
        ).fetchall()
        for row in rows:
            payload = json.loads(row[0])
            data = dict(payload.get("data") or {})
            required = {
                "relation_id", "source_node_id", "target_node_id", "relation_type",
                "pair_fingerprint", "resolution_state", "winner_node_id", "confidence",
                "detector", "evidence_json", "created_at", "updated_at",
            }
            if not required <= set(data):
                continue
            nodes = conn.execute(
                "SELECT COUNT(*) FROM memory_atoms WHERE node_id IN (?,?)",
                (data["source_node_id"], data["target_node_id"]),
            ).fetchone()[0]
            if int(nodes) != 2:
                continue
            conn.execute(
                """INSERT INTO memory_relations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(relation_id) DO UPDATE SET
                   resolution_state=CASE WHEN excluded.updated_at>memory_relations.updated_at
                     THEN excluded.resolution_state ELSE memory_relations.resolution_state END,
                   winner_node_id=CASE WHEN excluded.updated_at>memory_relations.updated_at
                     THEN excluded.winner_node_id ELSE memory_relations.winner_node_id END,
                   updated_at=max(memory_relations.updated_at,excluded.updated_at)""",
                tuple(data[key] for key in (
                    "relation_id", "source_node_id", "target_node_id", "relation_type",
                    "pair_fingerprint", "resolution_state", "winner_node_id", "confidence",
                    "detector", "evidence_json", "created_at", "updated_at",
                )),
            )

    @staticmethod
    def _merge_cloud_overrides(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT payload_json FROM cloud_graph_objects WHERE object_kind='override'"
        ).fetchall()
        for row in rows:
            data = dict(json.loads(row[0]).get("data") or {})
            required = {
                "pair_fingerprint", "resolution_state", "winner_content_hash", "resolution", "updated_at"
            }
            if not required <= set(data):
                continue
            conn.execute(
                """INSERT INTO memory_relation_overrides VALUES(?,?,?,?,?)
                   ON CONFLICT(pair_fingerprint) DO UPDATE SET
                   resolution_state=excluded.resolution_state,
                   winner_content_hash=excluded.winner_content_hash,
                   resolution=excluded.resolution,updated_at=excluded.updated_at
                   WHERE excluded.updated_at>memory_relation_overrides.updated_at""",
                tuple(data[key] for key in (
                    "pair_fingerprint", "resolution_state", "winner_content_hash", "resolution", "updated_at"
                )),
            )

    @staticmethod
    def _apply_confirmed_lifecycle(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE memory_atoms SET lifecycle_state='superseded'
            WHERE node_id IN (
              SELECT CASE WHEN winner_node_id=source_node_id THEN target_node_id ELSE source_node_id END
              FROM memory_relations
              WHERE resolution_state='confirmed' AND winner_node_id IS NOT NULL
                AND (
                  relation_type IN ('supersedes','derived_from')
                  OR (
                    relation_type='contradicts'
                    AND EXISTS(
                      SELECT 1 FROM memory_relation_overrides o
                      WHERE o.pair_fingerprint=memory_relations.pair_fingerprint
                        AND o.resolution_state='confirmed'
                    )
                  )
                )
            )
            """
        )

    def relations(self, node: str | None = None, *, relation_type: str | None = None) -> list[dict]:
        self.initialize()
        clauses, params = [], []
        if node:
            clauses.append("(r.source_node_id=? OR r.target_node_id=?)")
            params.extend([node, node])
        if relation_type:
            clauses.append("r.relation_type=?")
            params.append(relation_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT r.*, a.text source_text, b.text target_text,
                    a.atom_id source_atom_id, b.atom_id target_atom_id,
                    a.content_hash source_content_hash, b.content_hash target_content_hash,
                    a.scope source_scope, b.scope target_scope,
                    a.project_path source_project_path, b.project_path target_project_path,
                    a.memory_type source_memory_type, b.memory_type target_memory_type,
                    a.origin source_origin, b.origin target_origin
                    FROM memory_relations r
                    JOIN memory_atoms a ON a.node_id=r.source_node_id
                    JOIN memory_atoms b ON b.node_id=r.target_node_id
                    {where} ORDER BY r.updated_at DESC, r.relation_id""",
                params,
            ).fetchall()
        return [self._relation_dict(row) for row in rows]

    def conflicts(self, *, unresolved_only: bool = True) -> list[dict]:
        rows = self.relations(relation_type="contradicts")
        return [row for row in rows if not unresolved_only or row["resolution_state"] == "suggested"]

    def resolve(self, relation_id: str, resolution: str, *, winner_node_id: str | None = None) -> dict:
        if resolution not in {"choose", "keep-both", "dismiss"}:
            raise ValueError("resolution must be choose, keep-both, or dismiss")
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_relations WHERE relation_id=?", (relation_id,)).fetchone()
            if row is None:
                raise ValueError("relation is missing")
            pair = {str(row["source_node_id"]), str(row["target_node_id"])}
            if resolution == "choose" and winner_node_id not in pair:
                raise ValueError("winner must be one of the conflicting node IDs")
            winner_hash = None
            if winner_node_id:
                winner = conn.execute("SELECT content_hash FROM memory_atoms WHERE node_id=?", (winner_node_id,)).fetchone()
                winner_hash = str(winner[0]) if winner else None
            state = "rejected" if resolution == "dismiss" else "confirmed"
            conn.execute(
                """INSERT INTO memory_relation_overrides
                   (pair_fingerprint,resolution_state,winner_content_hash,resolution,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(pair_fingerprint) DO UPDATE SET
                   resolution_state=excluded.resolution_state,
                   winner_content_hash=excluded.winner_content_hash,
                   resolution=excluded.resolution,updated_at=excluded.updated_at""",
                (row["pair_fingerprint"], state, winner_hash, resolution, _now()),
            )
            conn.execute(
                "UPDATE memory_relations SET resolution_state=?,winner_node_id=?,updated_at=? WHERE relation_id=?",
                (state, winner_node_id, _now(), relation_id),
            )
            self._apply_confirmed_lifecycle(conn)
        return next(row for row in self.relations() if row["relation_id"] == relation_id)

    def current_state(self, atom_ids: Iterable[str]) -> dict[str, str]:
        values = list(dict.fromkeys(str(value) for value in atom_ids if value))
        if not values or not self.path.exists():
            return {}
        self.initialize()
        placeholders = ",".join("?" for _ in values)
        with self._connect() as conn:
            conn.execute(
                """UPDATE memory_atoms SET lifecycle_state='expired'
                   WHERE memory_type='status' AND lifecycle_state='current' AND timestamp IS NOT NULL
                     AND julianday('now') - julianday(timestamp) > 90"""
            )
            rows = conn.execute(
                f"""SELECT atom_id,lifecycle_state,present FROM memory_atoms
                    WHERE atom_id IN ({placeholders})
                    ORDER BY present DESC,
                      CASE lifecycle_state WHEN 'current' THEN 0 WHEN 'superseded' THEN 1 ELSE 2 END""",
                values,
            ).fetchall()
        states: dict[str, str] = {}
        for row in rows:
            states.setdefault(str(row["atom_id"]), str(row["lifecycle_state"]))
        return states

    def atoms_for_ids(self, atom_ids: Iterable[str]) -> dict[str, AtomicMemoryEntry]:
        """Read only requested atom rows from the first-class graph table."""
        values = list(dict.fromkeys(str(value) for value in atom_ids if value))
        if not values or not self.path.exists():
            return {}
        self.initialize()
        placeholders = ",".join("?" for _ in values)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM memory_atoms WHERE atom_id IN ({placeholders}) AND present=1
                    ORDER BY CASE lifecycle_state WHEN 'current' THEN 0 ELSE 1 END""",
                values,
            ).fetchall()
        output: dict[str, AtomicMemoryEntry] = {}
        for row in rows:
            output.setdefault(str(row["atom_id"]), self._row_to_atom(row))
        return output

    def atom_for_node(self, identity: str) -> AtomicMemoryEntry | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_atoms WHERE node_id=?", (identity,)).fetchone()
        return self._row_to_atom(row) if row is not None else None

    @staticmethod
    def _row_to_atom(row) -> AtomicMemoryEntry:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
        return AtomicMemoryEntry(
            atom_id=str(row["atom_id"]), text=str(row["text"]), type=str(row["memory_type"]),
            harness=str(row["harness"]), kind=str(row["kind"]), scope=str(row["scope"]),
            source_path=str(row["source_path"]), source_title=str(row["source_title"]),
            line_start=int(row["line_start"]), line_end=int(row["line_end"]),
            source_hash=str(row["source_hash"]), content_hash=str(row["content_hash"]),
            tags=list(metadata.get("tags") or []), timestamp=row["timestamp"],
            source_count=int(row["source_count"]), merged_from=list(metadata.get("merged_from") or []),
            record_id=row["record_id"], origin=str(row["origin"]), scope_kind=str(row["scope_kind"]),
            project_path=row["project_path"], project_id=row["project_id"], revision_id=row["revision_id"],
            parent_revision_ids=list(metadata.get("parent_revision_ids") or []),
            deleted=bool(metadata.get("deleted", False)), status=str(row["lifecycle_state"]),
            audience_kind=str(metadata.get("audience_kind") or "personal"),
            applicability_kind=str(metadata.get("applicability_kind") or "global"),
            pack_ids=list(metadata.get("pack_ids") or []),
        )

    def orphans(self) -> list[dict]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT a.* FROM memory_atoms a
                   WHERE a.present=1 AND a.lifecycle_state='current'
                   AND NOT EXISTS(SELECT 1 FROM memory_relations r
                                  WHERE (r.source_node_id=a.node_id OR r.target_node_id=a.node_id)
                                    AND r.resolution_state!='rejected')
                   AND (a.record_id IS NOT NULL OR a.origin IN ('manual','mcp','promoted','capture'))
                   ORDER BY a.last_seen_at DESC, a.node_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def recent(
        self,
        since: datetime,
        *,
        until: datetime | None = None,
        harness: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return a recency-ordered memory timeline with source mtime fallback."""
        self.initialize()
        start = since.astimezone(timezone.utc)
        end = (until or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_atoms WHERE present=1
                   ORDER BY COALESCE(timestamp,last_seen_at) DESC, node_id"""
            ).fetchall()
        output: list[dict] = []
        for raw in rows:
            row = dict(raw)
            stamp = _parse_time(row.get("timestamp"))
            fallback = False
            if stamp is None:
                try:
                    stamp = datetime.fromtimestamp(Path(str(row["source_path"])).stat().st_mtime, timezone.utc)
                    fallback = True
                except OSError:
                    stamp = _parse_time(row.get("last_seen_at"))
                    fallback = True
            if stamp is None or stamp < start or stamp > end:
                continue
            if harness and str(row.get("harness") or "").casefold() != harness.casefold():
                continue
            row["activity_at"] = stamp.isoformat(timespec="seconds")
            row["timestamp_fallback"] = fallback
            output.append(row)
            if len(output) >= max(0, limit):
                break
        return output

    def search_history(self, query: str, *, limit: int = 20) -> list[dict]:
        """Return lexical matches from revisions no longer in the search projection."""
        wanted = _tokens(query)
        if not wanted:
            return []
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_atoms
                   WHERE present=0 OR lifecycle_state!='current'
                   ORDER BY last_seen_at DESC"""
            ).fetchall()
        matches = []
        for row in rows:
            overlap = wanted & _tokens(str(row["text"]))
            if not overlap:
                continue
            value = dict(row)
            value["score"] = min(0.95, 0.45 + 0.5 * len(overlap) / len(wanted))
            matches.append(value)
        matches.sort(key=lambda item: (-float(item["score"]), str(item["last_seen_at"])))
        return matches[: max(0, limit)]

    def recap(self, since: datetime, *, until: datetime | None = None, project_id: str | None = None) -> dict:
        self.initialize()
        end = until or datetime.now(timezone.utc)
        clauses = ["last_seen_at>=?", "last_seen_at<=?"]
        params: list[object] = [since.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()]
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        with self._connect() as conn:
            atoms = [dict(row) for row in conn.execute(
                f"SELECT * FROM memory_atoms WHERE {' AND '.join(clauses)} ORDER BY last_seen_at DESC", params
            )]
            relations = [self._relation_dict(row) for row in conn.execute(
                "SELECT * FROM memory_relations WHERE updated_at>=? AND updated_at<=? ORDER BY updated_at DESC",
                (since.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
            )]
        return {
            "since": since.astimezone(timezone.utc).isoformat(),
            "until": end.astimezone(timezone.utc).isoformat(),
            "counts": {
                "memories": len(atoms),
                "conflicts": sum(1 for row in relations if row["relation_type"] == "contradicts"),
                "superseded": sum(1 for row in relations if row["relation_type"] == "supersedes"),
            },
            "memories": atoms,
            "relations": relations,
        }

    def cloud_objects(self) -> list[dict]:
        """Return the encrypted-sync projection without absolute project paths."""
        self.initialize()
        with self._connect() as conn:
            atoms = [dict(row) for row in conn.execute(
                "SELECT * FROM memory_atoms WHERE present=1 ORDER BY node_id"
            )]
            relations = [dict(row) for row in conn.execute(
                "SELECT * FROM memory_relations ORDER BY relation_id"
            )]
            overrides = [dict(row) for row in conn.execute(
                "SELECT * FROM memory_relation_overrides ORDER BY pair_fingerprint"
            )]
        objects: list[dict] = []
        for atom in atoms:
            atom.pop("project_path", None)
            atom["source_path"] = f"cloud://atom/{atom['node_id']}"
            atom["source_title"] = "Synced memory"
            metadata = json.loads(str(atom.get("metadata_json") or "{}"))
            metadata.pop("merged_from", None)
            atom["metadata_json"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            objects.append({
                "object_kind": "atom",
                "object_id": str(atom["node_id"]),
                "updated_at": str(atom["last_seen_at"]),
                "data": atom,
            })
        for relation in relations:
            objects.append({
                "object_kind": "relation",
                "object_id": str(relation["relation_id"]),
                "updated_at": str(relation["updated_at"]),
                "data": relation,
            })
        for override in overrides:
            objects.append({
                "object_kind": "override",
                "object_id": str(override["pair_fingerprint"]),
                "updated_at": str(override["updated_at"]),
                "data": override,
            })
        return objects

    def imported_atoms(self) -> list[AtomicMemoryEntry]:
        """Materialize decrypted cloud atoms for the ordinary local index rebuild."""
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM cloud_graph_objects WHERE object_kind='atom' ORDER BY object_id"
            ).fetchall()
        atoms = []
        for row in rows:
            data = dict(json.loads(row[0]).get("data") or {})
            try:
                atoms.append(
                    AtomicMemoryEntry(
                        atom_id=str(data["atom_id"]), text=str(data["text"]),
                        type=str(data["memory_type"]), harness=str(data["harness"]),
                        kind=str(data["kind"]), scope=str(data["scope"]),
                        scope_kind=str(data["scope_kind"]), project_id=data.get("project_id"),
                        project_path=None, source_path=str(data["source_path"]),
                        source_title=str(data["source_title"]), line_start=int(data["line_start"]),
                        line_end=int(data["line_end"]), source_hash=str(data["source_hash"]),
                        content_hash=str(data["content_hash"]), source_count=int(data.get("source_count") or 1),
                        timestamp=data.get("timestamp"), record_id=data.get("record_id"),
                        revision_id=data.get("revision_id"), origin=str(data["origin"]),
                        audience_kind=str(data.get("audience_kind") or "personal"),
                        applicability_kind=str(data.get("applicability_kind") or "global"),
                        pack_ids=list(data.get("pack_ids") or []),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return atoms

    def apply_cloud_object(self, payload: dict) -> str:
        """Persist a decrypted Protocol v2 graph object for local inspection."""
        self.initialize()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT revision_id FROM cloud_graph_objects WHERE object_id=?",
                (payload["object_id"],),
            ).fetchone()
            if existing and str(existing[0]) == str(payload["revision_id"]):
                return "duplicate"
            conn.execute(
                """INSERT INTO cloud_graph_objects(object_id,object_kind,revision_id,payload_json,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(object_id) DO UPDATE SET
                   object_kind=excluded.object_kind,revision_id=excluded.revision_id,
                   payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                (
                    payload["object_id"], payload["object_kind"], payload["revision_id"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), payload["updated_at"],
                ),
            )
        return "applied"

    @staticmethod
    def _relation_dict(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json", "{}") or "{}")
        return value


def temporal_multiplier(atom: AtomicMemoryEntry, *, now: datetime | None = None) -> float:
    moment = now or datetime.now(timezone.utc)
    if atom.type == "preference":
        return min(1.25, 1.0 + max(0, atom.source_count - 1) * 0.05)
    if atom.type != "status":
        return 1.0
    timestamp = _parse_time(atom.timestamp)
    if timestamp is None:
        return 1.0
    age_days = max(0.0, (moment.astimezone(timezone.utc) - timestamp).total_seconds() / 86400)
    return max(0.25, math.pow(0.5, age_days / 14.0))


__all__ = [
    "GRAPH_SCHEMA_VERSION", "MemoryGraphStore", "MemoryRelation", "node_id",
    "temporal_multiplier",
]
