"""Incremental deterministic consolidation of agent session JSONL."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from docmancer.backup.inventory import inventory
from docmancer.core.config import EmbeddingsConfig
from docmancer.embeddings.model2vec_provider import Model2VecProvider
from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import classify_memory
from docmancer.memory.records import MemoryRecordStore, normalize_memory_text


CONSOLIDATION_SCHEMA_VERSION = 1
RULE_VERSION = 1
_SIGNAL_RE = re.compile(
    r"\b(?:we (?:decided|chose|picked)|decision|remember(?: that)?|from now on|"
    r"must not|never|do not|don't|the reason is|because|prefer|default to|"
    r"workflow|lesson|failed because|fixed by|supersed(?:e|es|ed))\b",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(r"\b(?:no[, ]|that's wrong|that is wrong|actually|correction|instead)\b", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")


class AssistedProposal(BaseModel):
    text: str = Field(min_length=12, max_length=700)
    memory_type: str
    cited_source_indices: list[int] = Field(min_length=1)
    conflicting_source_indices: list[int] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _session_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _prefix_hash(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as handle:
        while remaining > 0:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest() if remaining == 0 else ""


def _role(record: dict[str, Any]) -> str | None:
    for value in (record.get("role"), record.get("type")):
        if isinstance(value, str) and value.casefold() in {"user", "assistant", "summary", "compaction"}:
            return value.casefold()
    payload = record.get("payload")
    if isinstance(payload, dict):
        for value in (payload.get("role"), payload.get("type")):
            if isinstance(value, str) and value.casefold() in {"user", "assistant", "summary", "compaction"}:
                return value.casefold()
    return None


def _message_values(value: Any, *, key: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if key.casefold() in {"content", "message", "summary", "text", "input_text", "output_text"}:
            out.append(value)
    elif isinstance(value, dict):
        for child_key, child in value.items():
            if str(child_key).casefold() in {"tool_result", "tool_output", "output", "stdout", "stderr"}:
                continue
            out.extend(_message_values(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            out.extend(_message_values(child, key=key))
    return out


def _record_text(record: dict[str, Any]) -> str:
    if _role(record) is None:
        # Codex response items often wrap the actual role one level down.
        payload = record.get("payload")
        if not isinstance(payload, dict) or _role(payload) is None:
            return ""
    values = _message_values(record)
    text = "\n".join(value.strip() for value in values if value.strip())
    return redact_secrets(text[:12_000])


def _candidate_text(text: str) -> str:
    sentences = _SENTENCE_RE.split(" ".join(text.split()))
    selected = [sentence for sentence in sentences if _SIGNAL_RE.search(sentence) or _CORRECTION_RE.search(sentence)]
    value = " ".join(selected[:3]).strip() or " ".join(text.split()).strip()
    value = re.sub(r"^(?:please\s+)?remember(?: that)?\s+", "", value, flags=re.IGNORECASE)
    return value[:700].rstrip()


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    lnorm = math.sqrt(sum(value * value for value in left))
    rnorm = math.sqrt(sum(value * value for value in right))
    return dot / (lnorm * rnorm) if lnorm and rnorm else 0.0


@dataclass
class Candidate:
    text: str
    normalized: str
    memory_type: str
    agent: str
    session_path: str
    session_hash: str
    record_hash: str
    byte_offset: int
    timestamp: str | None
    project_root: str | None
    role: str
    signals: list[str]


class TranscriptConsolidator:
    def __init__(self, *, root: Path | None = None, home: Path | None = None) -> None:
        self.root = Path(root or (Path.home() / ".docmancer")).expanduser().resolve()
        self.home = Path(home or Path.home()).expanduser().resolve()
        self.db_path = self.root / "transcript-consolidation.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS transcript_sessions (
                session_path TEXT PRIMARY KEY,
                session_hash TEXT NOT NULL,
                agent TEXT NOT NULL,
                project_root TEXT,
                processed_at TEXT NOT NULL,
                rule_version INTEGER NOT NULL,
                processed_bytes INTEGER NOT NULL DEFAULT 0,
                prefix_hash TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS transcript_evidence (
                evidence_id TEXT PRIMARY KEY,
                record_hash TEXT NOT NULL,
                session_path TEXT NOT NULL,
                session_hash TEXT NOT NULL,
                byte_offset INTEGER NOT NULL,
                agent TEXT NOT NULL,
                project_root TEXT,
                role TEXT NOT NULL,
                timestamp TEXT,
                excerpt TEXT NOT NULL,
                signals_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS transcript_evidence_lineage
                ON transcript_evidence(record_hash, project_root);
            CREATE TABLE IF NOT EXISTS transcript_proposals (
                proposal_id TEXT PRIMARY KEY,
                normalized TEXT NOT NULL,
                text TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                project_root TEXT,
                evidence_json TEXT NOT NULL,
                recurrence INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                applied_record_id TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS transcript_proposal_identity
                ON transcript_proposals(normalized, COALESCE(project_root, ''));
        """)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(transcript_sessions)")}
        if "processed_bytes" not in columns:
            connection.execute("ALTER TABLE transcript_sessions ADD COLUMN processed_bytes INTEGER NOT NULL DEFAULT 0")
        if "prefix_hash" not in columns:
            connection.execute("ALTER TABLE transcript_sessions ADD COLUMN prefix_hash TEXT NOT NULL DEFAULT ''")
        proposal_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(transcript_proposals)")}
        for name in ("wording", "provider", "model"):
            if name not in proposal_columns:
                connection.execute(f"ALTER TABLE transcript_proposals ADD COLUMN {name} TEXT")
        if "provider_cost" not in proposal_columns:
            connection.execute("ALTER TABLE transcript_proposals ADD COLUMN provider_cost REAL")
        return connection

    def scan(
        self,
        *,
        project: str | None = None,
        session_paths: set[Path] | None = None,
        dry_run: bool = False,
        provider_id: str | None = None,
        model: str | None = None,
        provider_client=None,
    ) -> dict[str, Any]:
        selected = {project} if project else None
        found = inventory(home=self.home, include_projects=selected)
        sessions = [artifact for artifact in found.artifacts if artifact.category == "session" and artifact.content_kind == "jsonl"]
        if session_paths is not None:
            allowed = {Path(path).expanduser().resolve() for path in session_paths}
            sessions = [artifact for artifact in sessions if artifact.source_path.resolve() in allowed]
        candidates: list[Candidate] = []
        skipped = 0
        existing: dict[str, dict[str, Any]] = {}
        if self.db_path.exists():
            with self._connect() as connection:
                existing = {
                    str(row["session_path"]): dict(row)
                    for row in connection.execute(
                        "SELECT session_path, session_hash, processed_bytes, prefix_hash FROM transcript_sessions WHERE rule_version = ?",
                        (RULE_VERSION,),
                    )
                }
        scanned_bytes = 0
        checkpoints: dict[str, tuple[str, int, str]] = {}
        for artifact in sessions:
            digest = _session_hash(artifact.source_path)
            path_key = str(artifact.source_path)
            previous = existing.get(path_key)
            if previous and previous["session_hash"] == digest:
                skipped += 1
                continue
            start_offset = 0
            if previous:
                processed = int(previous.get("processed_bytes") or 0)
                if processed and artifact.source_path.stat().st_size >= processed:
                    if _prefix_hash(artifact.source_path, processed) == str(previous.get("prefix_hash") or ""):
                        start_offset = processed
            found_candidates, complete_offset = self._scan_session(
                artifact.source_path,
                artifact.agent,
                artifact.project_root,
                digest,
                start_offset=start_offset,
            )
            candidates.extend(found_candidates)
            scanned_bytes += max(0, complete_offset - start_offset)
            checkpoints[path_key] = (digest, complete_offset, _prefix_hash(artifact.source_path, complete_offset))
        groups = self._group(candidates)
        provider_characters = sum(len(item.text) for group in groups for item in group)
        preview = {
            "schema_version": CONSOLIDATION_SCHEMA_VERSION,
            "sessions": len(sessions),
            "sessions_scanned": len(sessions) - skipped,
            "sessions_unchanged": skipped,
            "bytes_scanned": scanned_bytes,
            "candidate_spans": len(candidates),
            "candidate_percentage": None,
            "clusters": len(groups),
            "proposals": len(groups),
            "provider_characters": provider_characters if provider_id or provider_client else 0,
            "provider_tokens": (provider_characters + 3) // 4 if provider_id or provider_client else 0,
            "provider_cost": 0.0,
        }
        if dry_run:
            preview["items"] = [self._group_preview(group) for group in groups]
            return preview
        assisted: dict[int, dict[str, Any]] = {}
        if groups and (provider_id or provider_client):
            client = provider_client or self._provider(provider_id, model=model)
            client.preflight(model=model)
            for index, group in enumerate(groups):
                assisted[index] = self._assist_group(group, client, model=model)
            preview["provider_cost"] = sum(float(row.get("cost") or 0.0) for row in assisted.values())
        with self._connect() as connection:
            for candidate in candidates:
                evidence_id = "evi_" + hashlib.sha256(f"{candidate.record_hash}\0{candidate.project_root or ''}".encode()).hexdigest()[:24]
                connection.execute(
                    "INSERT OR IGNORE INTO transcript_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        evidence_id, candidate.record_hash, candidate.session_path, candidate.session_hash,
                        candidate.byte_offset, candidate.agent, candidate.project_root, candidate.role,
                        candidate.timestamp, candidate.text, json.dumps(candidate.signals),
                    ),
                )
            for index, group in enumerate(groups):
                self._save_group(connection, group, assisted=assisted.get(index))
            for artifact in sessions:
                checkpoint = checkpoints.get(str(artifact.source_path))
                if checkpoint is None:
                    continue
                digest, processed_bytes, prefix_hash = checkpoint
                connection.execute(
                    "INSERT INTO transcript_sessions (session_path, session_hash, agent, project_root, processed_at, rule_version, processed_bytes, prefix_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_path) DO UPDATE SET session_hash=excluded.session_hash, agent=excluded.agent, project_root=excluded.project_root, processed_at=excluded.processed_at, rule_version=excluded.rule_version, processed_bytes=excluded.processed_bytes, prefix_hash=excluded.prefix_hash",
                    (str(artifact.source_path), digest, artifact.agent, artifact.project_root, _now(), RULE_VERSION, processed_bytes, prefix_hash),
                )
            connection.commit()
        preview["items"] = self.proposals(state="pending")
        return preview

    @staticmethod
    def _provider(provider_id: str | None, *, model: str | None):
        from docmancer.ai.providers.factory import provider_client
        from docmancer.core.config import DocmancerConfig

        providers = DocmancerConfig().providers
        selected = provider_id or providers.default_llm
        return provider_client(selected, config=providers, model=model)

    @staticmethod
    def _assist_group(group: list[Candidate], client, *, model: str | None) -> dict[str, Any]:
        evidence = "\n\n".join(
            f"[{index}] {item.role} ({item.agent}, {item.record_hash[:12]}):\n{redact_secrets(item.text)}"
            for index, item in enumerate(group)
        )
        response = client.parse(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite only the supplied redacted evidence as one durable memory proposal. "
                        "Preserve scope, dates, qualifiers, and uncertainty. Cite supplied indices only. "
                        "Do not add facts or resolve a contradiction without explicit evidence."
                    ),
                },
                {"role": "user", "content": evidence},
            ],
            AssistedProposal,
            model=model,
            temperature=0.0,
        )
        value = response if isinstance(response, AssistedProposal) else AssistedProposal.model_validate(response)
        indices = [*value.cited_source_indices, *value.conflicting_source_indices]
        if any(index < 0 or index >= len(group) for index in indices):
            raise ValueError("provider-assisted proposal cited evidence outside the supplied cluster")
        if value.memory_type not in {"fact", "decision", "preference", "constraint", "workflow", "warning", "status"}:
            raise ValueError("provider-assisted proposal returned an unsupported memory type")
        return {
            "text": " ".join(value.text.split()),
            "memory_type": value.memory_type,
            "provider": str(getattr(client, "provider_name", "provider")),
            "model": str(getattr(client, "model", model or "unknown")),
            "cost": float(getattr(response, "cost_usd", 0.0) or 0.0),
        }

    def _scan_session(
        self,
        path: Path,
        agent: str,
        project_root: str | None,
        session_hash: str,
        *,
        start_offset: int = 0,
    ) -> tuple[list[Candidate], int]:
        candidates = []
        offset = start_offset
        seen_record_hashes: set[str] = set()
        with path.open("rb") as handle:
            handle.seek(start_offset)
            for raw in handle:
                current_offset = offset
                offset += len(raw)
                if not raw.endswith((b"\n", b"\r")):
                    offset = current_offset
                    break
                record_hash = _hash_bytes(raw.rstrip(b"\r\n"))
                if record_hash in seen_record_hashes:
                    continue
                seen_record_hashes.add(record_hash)
                try:
                    record = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                text = _record_text(record)
                if len(text) < 12:
                    continue
                signals = []
                if _SIGNAL_RE.search(text):
                    signals.append("durable-language")
                if _CORRECTION_RE.search(text):
                    signals.append("correction")
                if not signals:
                    continue
                proposal = _candidate_text(text)
                normalized = normalize_memory_text(proposal)
                if len(normalized) < 12:
                    continue
                candidates.append(Candidate(
                    text=proposal,
                    normalized=normalized,
                    memory_type=classify_memory(proposal),
                    agent=agent,
                    session_path=str(path),
                    session_hash=session_hash,
                    record_hash=record_hash,
                    byte_offset=current_offset,
                    timestamp=str(record.get("timestamp") or "") or None,
                    project_root=project_root,
                    role=_role(record) or _role(record.get("payload") or {}) or "unknown",
                    signals=signals,
                ))
        return candidates, offset

    def _group(self, candidates: list[Candidate]) -> list[list[Candidate]]:
        if not candidates:
            return []
        provider = Model2VecProvider(EmbeddingsConfig())
        vectors = provider.embed([candidate.text for candidate in candidates])
        groups: list[list[Candidate]] = []
        representatives: list[list[float]] = []
        for candidate, vector in zip(candidates, vectors):
            match = None
            best = 0.0
            for index, (group, representative) in enumerate(zip(groups, representatives)):
                if group[0].project_root != candidate.project_root:
                    continue
                score = _cosine(vector, representative)
                if score >= 0.86 and score > best:
                    match = index
                    best = score
            if match is None:
                groups.append([candidate])
                representatives.append(vector)
            else:
                groups[match].append(candidate)
        return groups

    @staticmethod
    def _group_preview(group: list[Candidate]) -> dict[str, Any]:
        winner = max(group, key=lambda item: (len(item.signals), len(item.text)))
        return {
            "text": winner.text,
            "memory_type": winner.memory_type,
            "project_root": winner.project_root,
            "recurrence": len({item.record_hash for item in group}),
            "sources": [
                {"agent": item.agent, "session_path": item.session_path, "byte_offset": item.byte_offset, "record_hash": item.record_hash}
                for item in group
            ],
        }

    def _save_group(self, connection: sqlite3.Connection, group: list[Candidate], *, assisted: dict[str, Any] | None = None) -> None:
        preview = self._group_preview(group)
        if assisted:
            preview["text"] = assisted["text"]
            preview["memory_type"] = assisted["memory_type"]
        normalized = normalize_memory_text(preview["text"])
        proposal_id = "tc_" + hashlib.sha256(f"{normalized}\0{preview['project_root'] or ''}".encode()).hexdigest()[:24]
        now = _now()
        evidence = json.dumps(preview["sources"], sort_keys=True)
        connection.execute(
            "INSERT INTO transcript_proposals (proposal_id, normalized, text, memory_type, project_root, evidence_json, recurrence, state, created_at, updated_at, wording, provider, model, provider_cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(proposal_id) DO UPDATE SET evidence_json=excluded.evidence_json, recurrence=excluded.recurrence, updated_at=excluded.updated_at, wording=excluded.wording, provider=excluded.provider, model=excluded.model, provider_cost=excluded.provider_cost",
            (
                proposal_id, normalized, preview["text"], preview["memory_type"], preview["project_root"],
                evidence, preview["recurrence"], now, now,
                "provider-assisted" if assisted else "extractive",
                assisted.get("provider") if assisted else None,
                assisted.get("model") if assisted else None,
                assisted.get("cost") if assisted else None,
            ),
        )

    def proposals(self, *, state: str | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect() as connection:
            query = "SELECT * FROM transcript_proposals"
            params: tuple[Any, ...] = ()
            if state:
                query += " WHERE state = ?"
                params = (state,)
            query += " ORDER BY updated_at DESC, proposal_id"
            return [self._row(row) for row in connection.execute(query, params)]

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        if not self.db_path.exists():
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM transcript_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
            return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "proposal_id": row["proposal_id"], "text": row["text"], "memory_type": row["memory_type"],
            "project_root": row["project_root"], "evidence": json.loads(row["evidence_json"]),
            "recurrence": row["recurrence"], "state": row["state"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "applied_record_id": row["applied_record_id"],
            "wording": row["wording"] or "extractive", "provider": row["provider"],
            "model": row["model"], "provider_cost": row["provider_cost"],
        }

    def reject(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE transcript_proposals SET state='rejected', updated_at=? WHERE proposal_id=? AND state='pending'",
                (_now(), proposal_id),
            )
            if updated.rowcount != 1:
                raise ValueError("pending transcript proposal not found")
            connection.commit()
        return self.proposal(proposal_id) or {}

    def approve(self, proposal_id: str, *, text: str | None = None) -> dict[str, Any]:
        proposal = self.proposal(proposal_id)
        if not proposal or proposal["state"] != "pending":
            raise ValueError("pending transcript proposal not found")
        approved_text = " ".join((text or proposal["text"]).split()).strip()
        if not approved_text:
            raise ValueError("approved memory text cannot be empty")
        sources = proposal["evidence"]
        tags = ["transcript-consolidation", *(f"source-agent:{item['agent']}" for item in sources)]
        record = MemoryRecordStore(self.root).add(
            approved_text,
            scope_kind="project" if proposal["project_root"] else "global",
            project_path=proposal["project_root"],
            memory_type=proposal["memory_type"],
            tags=sorted(set(tags)),
            origin="transcript-consolidation",
            promoted_from=proposal_id,
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE transcript_proposals SET state='approved', text=?, applied_record_id=?, updated_at=? WHERE proposal_id=? AND state='pending'",
                (approved_text, record.record_id, _now(), proposal_id),
            )
            connection.commit()
        return {"proposal_id": proposal_id, "record_id": record.record_id, "source_path": record.source_path, "text": record.text}


__all__ = ["CONSOLIDATION_SCHEMA_VERSION", "TranscriptConsolidator"]
