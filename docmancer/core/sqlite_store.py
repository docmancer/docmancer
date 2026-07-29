from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from docmancer.core.chunking import (
    chunk_markdown_tokens,
    chunk_paragraphs,
    chunk_paragraphs_tokens,
)
from docmancer.core.models import Document, RetrievedChunk


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Keywords that indicate boilerplate/legal content.  Matched against
# normalized title words so numbered headings like "12. Miscellaneous"
# and subsections like "Privacy Policy" are caught.
_BOILERPLATE_KEYWORDS = frozenset({
    "terms", "conditions", "privacy", "policy", "legal", "disclaimer",
    "eula", "license", "agreement", "dmca", "copyright", "sla",
    "miscellaneous", "modifications", "indemnification", "severability",
    "arbitration", "jurisdiction", "governing", "waiver", "warranties",
    "limitation", "liability",
})

# Query stopwords that inflate BM25 scores for legal text without
# carrying search intent.
_QUERY_STOPWORDS = frozenset({
    "how", "do", "i", "a", "an", "the", "to", "is", "it", "in", "on",
    "of", "for", "my", "can", "what", "where", "when", "why", "does",
    "should", "would", "could", "with", "this", "that", "are", "was",
    "be", "have", "has", "will", "we", "you", "your", "me",
})


@dataclass(slots=True)
class IndexResult:
    sources: int
    sections: int


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _slug(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")[:72] or "source"
    return f"{stem}-{digest}"


def _normalize_source_like(value: str | Path) -> str:
    return str(value).replace("\\", "/").rstrip("/")


def _split_sections(content: str) -> list[tuple[str, int, str]]:
    matches = list(HEADING_RE.finditer(content))
    if not matches:
        return [("Document", 1, content.strip())] if content.strip() else []

    sections: list[tuple[str, int, str]] = []
    if matches[0].start() > 0:
        intro = content[: matches[0].start()].strip()
        if intro:
            sections.append(("Introduction", 1, intro))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        level = len(match.group(1))
        title = match.group(2).strip()
        text = content[start:end].strip()
        if text:
            sections.append((title, level, text))
    return sections


def _split_sections_with_anchors(content: str) -> list[tuple[str, int, str, str]]:
    matches = list(HEADING_RE.finditer(content))
    if not matches:
        stripped = content.strip()
        return [("Document", 1, stripped, "Document")] if stripped else []

    sections: list[tuple[str, int, str, str]] = []
    if matches[0].start() > 0:
        intro = content[: matches[0].start()].strip()
        if intro:
            sections.append(("Introduction", 1, intro, "Introduction"))

    heading_stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[start:end].strip()
        if text:
            sections.append((title, level, text, " > ".join(item for _, item in heading_stack)))
    return sections


def _sections_for_document(doc: Document) -> list[tuple[str, int, str, dict[str, str]]]:
    metadata = dict(doc.metadata or {})
    strategy = str(metadata.get("chunking_strategy") or "heading")
    chunk_size = int(metadata.get("chunk_size") or 800)
    chunk_overlap = int(metadata.get("chunk_overlap") or 100)
    chunk_unit = str(metadata.get("chunk_unit") or "characters")

    if strategy == "paragraph":
        title = str(metadata.get("title") or Path(doc.source).stem or "Document")
        chunks = (
            chunk_paragraphs_tokens(
                doc.content,
                chunk_tokens=chunk_size,
                overlap_tokens=chunk_overlap,
            )
            if chunk_unit == "tokens"
            else chunk_paragraphs(
                doc.content,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
        sections: list[tuple[str, int, str, dict[str, str]]] = []
        for index, text in enumerate(chunks):
            page_match = re.search(r"##\s+Page\s+(\d+)", text)
            anchor = f"Page {page_match.group(1)}" if page_match else f"{title} chunk {index + 1}"
            sections.append((title, 1, text, {"anchor": anchor}))
        return sections

    if strategy == "single":
        # Atomic-record sources: the whole document is one
        # section. We do not split on headings — heading-aware splitting would
        # otherwise carve each record into two or three sub-sections, which is
        # the wrong shape for "match the mark against every case file".
        title = str(metadata.get("title") or Path(doc.source).stem or "Document")
        anchor = str(metadata.get("anchor") or title)
        text = doc.content.strip()
        if not text:
            return []
        return [(title, 1, text, {"anchor": anchor})]

    sections: list[tuple[str, int, str, dict[str, str]]] = []
    for title, level, text, anchor in _split_sections_with_anchors(doc.content):
        if chunk_unit != "tokens":
            sections.append((title, level, text, {"anchor": anchor}))
            continue
        chunks = chunk_markdown_tokens(
            text,
            chunk_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )
        for index, chunk in enumerate(chunks):
            chunk_anchor = anchor if len(chunks) == 1 else f"{anchor} / part {index + 1}"
            sections.append((title, level, chunk, {"anchor": chunk_anchor}))
    return sections


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object, length: int = 32) -> str:
    raw = "\0".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


def _lexical_relevance_score(
    query: str,
    title: str,
    body: str,
    *,
    term_weights: dict[str, float] | None = None,
) -> float:
    """Return an interpretable 0..1 lexical relevance score.

    FTS5's BM25 value is useful for ordering matches within one query, but its
    magnitude is not comparable across queries. Token coverage is. A score of
    1 means every meaningful query term is present, while a partial literal
    match receives the corresponding fraction. Exact phrase matches receive a
    small boost without turning rank position into fake confidence.
    """
    query_terms = [
        token.lower()
        for token in re.findall(r"\w+", query)
        if token.lower() not in _QUERY_STOPWORDS
    ]
    if not query_terms:
        query_terms = [token.lower() for token in re.findall(r"\w+", query)]
    if not query_terms:
        return 0.0
    haystack = f"{title}\n{body}".lower()
    haystack_terms = set(re.findall(r"\w+", haystack))
    unique_query_terms = set(query_terms)
    weights = term_weights or {term: 1.0 for term in unique_query_terms}
    total_weight = sum(weights.get(term, 1.0) for term in unique_query_terms)
    matched_weight = sum(weights.get(term, 1.0) for term in unique_query_terms & haystack_terms)
    coverage = matched_weight / total_weight if total_weight else 0.0
    phrase = " ".join(query_terms)
    if phrase and phrase in haystack:
        coverage = min(1.0, coverage + 0.1)
    return round(max(0.0, min(1.0, coverage)), 6)


class SQLiteStore:
    def __init__(self, db_path: str | Path, extracted_dir: str | Path | None = None):
        self.db_path = Path(db_path).expanduser()
        self.extracted_dir = Path(extracted_dir).expanduser() if extracted_dir else self.db_path.parent / "extracted"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts5_check USING fts5(value)")
                conn.execute("DROP TABLE IF EXISTS fts5_check")
            except sqlite3.OperationalError as exc:
                raise RuntimeError(
                    "SQLite FTS5 is required but is not available in this Python build. "
                    "Install a Python distribution compiled with SQLite FTS5."
                ) from exc

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL UNIQUE,
                    docset_root TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    markdown_path TEXT NOT NULL DEFAULT '',
                    json_path TEXT NOT NULL DEFAULT '',
                    raw_tokens INTEGER NOT NULL DEFAULT 0,
                    ingested_at TEXT NOT NULL,
                    source_uid TEXT,
                    current_version_id TEXT,
                    content_hash TEXT
                );

                CREATE TABLE IF NOT EXISTS sections (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    source_path TEXT,
                    document_title TEXT,
                    format TEXT,
                    anchor TEXT,
                    content_hash TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    document_id TEXT,
                    unit_id TEXT,
                    unit_revision_id TEXT,
                    project_id TEXT,
                    scope_kind TEXT,
                    kind TEXT,
                    lifecycle TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
                    title,
                    text,
                    source,
                    content='sections',
                    content_rowid='id'
                );

                """
            )
            self._ensure_nullable_column(conn, "sections", "source_path", "TEXT")
            self._ensure_nullable_column(conn, "sections", "document_title", "TEXT")
            self._ensure_nullable_column(conn, "sections", "format", "TEXT")
            self._ensure_nullable_column(conn, "sections", "anchor", "TEXT")
            self._ensure_nullable_column(conn, "sections", "content_hash", "TEXT")
            self._ensure_nullable_column(conn, "sources", "source_uid", "TEXT")
            self._ensure_nullable_column(conn, "sources", "current_version_id", "TEXT")
            self._ensure_nullable_column(conn, "sources", "content_hash", "TEXT")
            self._ensure_nullable_column(conn, "sections", "document_id", "TEXT")
            self._ensure_nullable_column(conn, "sections", "unit_id", "TEXT")
            self._ensure_nullable_column(conn, "sections", "unit_revision_id", "TEXT")
            self._ensure_nullable_column(conn, "sections", "project_id", "TEXT")
            self._ensure_nullable_column(conn, "sections", "scope_kind", "TEXT")
            self._ensure_nullable_column(conn, "sections", "kind", "TEXT")
            self._ensure_nullable_column(
                conn, "sections", "lifecycle", "TEXT NOT NULL DEFAULT 'active'"
            )
            self._ensure_nullable_column(conn, "sections", "updated_at", "TEXT")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_versions (
                    version_id TEXT PRIMARY KEY,
                    source_uid TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    chunker_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    lifecycle TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_versions_source
                    ON source_versions(source_uid, created_at);

                CREATE TABLE IF NOT EXISTS retrieval_unit_revisions (
                    revision_id TEXT PRIMARY KEY,
                    unit_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source_version_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    lifecycle TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_unit_revisions_unit
                    ON retrieval_unit_revisions(unit_id, created_at);

                CREATE TABLE IF NOT EXISTS index_jobs (
                    job_id TEXT PRIMARY KEY,
                    source_version_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    stage_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    UNIQUE(source_version_id, stage, stage_version)
                );
                CREATE INDEX IF NOT EXISTS idx_index_jobs_status
                    ON index_jobs(status, stage);

                CREATE TABLE IF NOT EXISTS embedding_upserts (
                    chunk_id INTEGER NOT NULL,
                    qdrant_collection TEXT NOT NULL,
                    content_hash TEXT,
                    embedding_hash TEXT,
                    upserted_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    PRIMARY KEY (chunk_id, qdrant_collection)
                );
                CREATE INDEX IF NOT EXISTS idx_embedding_upserts_collection
                    ON embedding_upserts(qdrant_collection);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sections_unit_id
                    ON sections(unit_id) WHERE unit_id IS NOT NULL AND unit_id <> '';
                CREATE INDEX IF NOT EXISTS idx_sections_document_id
                    ON sections(document_id);
                CREATE INDEX IF NOT EXISTS idx_sections_source_id
                    ON sections(source_id);
                CREATE INDEX IF NOT EXISTS idx_sections_project_scope
                    ON sections(project_id, scope_kind, kind, lifecycle);
                """
            )
            self._ensure_nullable_column(
                conn,
                "source_versions",
                "lifecycle",
                "TEXT NOT NULL DEFAULT 'active'",
            )
            self._backfill_v2_identity(conn)

    @staticmethod
    def _ensure_nullable_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _backfill_v2_identity(conn: sqlite3.Connection) -> None:
        """Give pre-v2 rows stable source, document, and retrieval-unit identities."""
        source_needs_backfill = conn.execute(
            """
            SELECT 1 FROM sources
            WHERE source_uid IS NULL OR source_uid = ''
               OR current_version_id IS NULL OR current_version_id = ''
               OR content_hash IS NULL OR content_hash = ''
            LIMIT 1
            """
        ).fetchone()
        section_needs_backfill = conn.execute(
            """
            SELECT 1 FROM sections
            WHERE document_id IS NULL OR document_id = ''
               OR unit_id IS NULL OR unit_id = ''
               OR unit_revision_id IS NULL OR unit_revision_id = ''
            LIMIT 1
            """
        ).fetchone()
        if source_needs_backfill is None and section_needs_backfill is None:
            return

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sources = list(
            conn.execute(
                "SELECT id, source, content, metadata_json, source_uid, "
                "current_version_id, content_hash FROM sources"
            )
        )
        for source in sources:
            try:
                metadata = json.loads(source["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            source_uid = source["source_uid"] or _stable_id("src", source["source"])
            content_hash = source["content_hash"] or str(
                metadata.get("content_hash") or _chunk_hash(source["content"] or "")
            )
            parser_version = str(metadata.get("parser_version") or "legacy")
            chunker_version = str(metadata.get("chunker_version") or "character-v1")
            version_id = source["current_version_id"] or _stable_id(
                "ver", source_uid, content_hash, parser_version, chunker_version
            )
            conn.execute(
                "UPDATE sources SET source_uid=?, current_version_id=?, content_hash=? WHERE id=?",
                (source_uid, version_id, content_hash, int(source["id"])),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO source_versions
                    (version_id, source_uid, source_id, content_hash, parser_version,
                     chunker_version, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    source_uid,
                    int(source["id"]),
                    content_hash,
                    parser_version,
                    chunker_version,
                    source["metadata_json"] or "{}",
                    now,
                ),
            )
            rows = list(
                conn.execute(
                    """
                    SELECT id, chunk_index, anchor, content_hash, text, metadata_json,
                           document_id, unit_id, unit_revision_id
                    FROM sections WHERE source_id=? ORDER BY chunk_index
                    """,
                    (int(source["id"]),),
                )
            )
            seen_anchors: dict[str, int] = {}
            for row in rows:
                try:
                    section_meta = json.loads(row["metadata_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    section_meta = {}
                document_id = row["document_id"] or str(
                    section_meta.get("document_id") or source_uid
                )
                anchor = str(row["anchor"] or section_meta.get("anchor") or row["chunk_index"])
                occurrence = seen_anchors.get(anchor, 0)
                seen_anchors[anchor] = occurrence + 1
                unit_id = row["unit_id"] or _stable_id(
                    "unit", document_id, anchor, occurrence
                )
                row_hash = row["content_hash"] or _chunk_hash(row["text"] or "")
                revision_id = row["unit_revision_id"] or _stable_id(
                    "urev", unit_id, row_hash, chunker_version
                )
                section_meta.update(
                    {
                        "document_id": document_id,
                        "unit_id": unit_id,
                        "unit_revision_id": revision_id,
                        "source_version_id": version_id,
                    }
                )
                conn.execute(
                    """
                    UPDATE sections
                    SET document_id=?, unit_id=?, unit_revision_id=?, lifecycle='active',
                        updated_at=?, metadata_json=?
                    WHERE id=?
                    """,
                    (
                        document_id,
                        unit_id,
                        revision_id,
                        now,
                        json.dumps(section_meta, ensure_ascii=False),
                        int(row["id"]),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO retrieval_unit_revisions
                        (revision_id, unit_id, document_id, source_version_id, content_hash,
                         text, metadata_json, lifecycle, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (
                        revision_id,
                        unit_id,
                        document_id,
                        version_id,
                        row_hash,
                        row["text"] or "",
                        json.dumps(section_meta, ensure_ascii=False),
                        now,
                    ),
                )

    def add_documents(self, documents: Iterable[Document], recreate: bool = False) -> IndexResult:
        docs = list(documents)
        with self._connect() as conn:
            if recreate:
                conn.execute("DELETE FROM sections_fts")
                conn.execute("DELETE FROM sections")
                conn.execute("DELETE FROM sources")
                conn.execute("DELETE FROM source_versions")
                conn.execute("DELETE FROM retrieval_unit_revisions")
                conn.execute("DELETE FROM index_jobs")

            section_count = 0
            for doc in docs:
                section_count += self._add_document(conn, doc)
            return IndexResult(sources=len(docs), sections=section_count)

    def add_documents_stream(
        self,
        documents: Iterable[Document],
        *,
        recreate: bool = False,
        batch_size: int = 1000,
        progress_callback=None,
    ) -> IndexResult:
        """Stream-ingest an iterable of documents, committing in batches.

        Use this for atomic-record corpora (court filings,
        product catalogs) where the iterator would yield millions of records
        and ``list(documents)`` would OOM. Commits every ``batch_size`` rows
        so a killed process loses at most one batch.
        """
        section_count = 0
        source_count = 0
        conn = self._connect()
        try:
            if recreate:
                conn.execute("DELETE FROM sections_fts")
                conn.execute("DELETE FROM sections")
                conn.execute("DELETE FROM sources")
                conn.execute("DELETE FROM source_versions")
                conn.execute("DELETE FROM retrieval_unit_revisions")
                conn.execute("DELETE FROM index_jobs")
                conn.commit()
            for doc in documents:
                section_count += self._add_document(conn, doc)
                source_count += 1
                if source_count % batch_size == 0:
                    conn.commit()
                    if progress_callback is not None:
                        progress_callback(source_count, section_count)
            conn.commit()
        finally:
            conn.close()
        if progress_callback is not None:
            progress_callback(source_count, section_count)
        return IndexResult(sources=source_count, sections=section_count)

    def _add_document(self, conn: sqlite3.Connection, doc: Document) -> int:
        metadata = dict(doc.metadata or {})
        docset_root = str(metadata.get("docset_root") or "")
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source_uid = str(metadata.get("source_id") or _stable_id("src", doc.source))
        source_content_hash = str(
            metadata.get("content_hash") or _chunk_hash(doc.content)
        )
        parser_version = str(metadata.get("parser_version") or "parser-v1")
        chunker_version = str(
            metadata.get("chunker_version")
            or (
                "token-structural-v2"
                if metadata.get("chunk_unit") == "tokens"
                else "character-v1"
            )
        )
        source_version_id = _stable_id(
            "ver",
            source_uid,
            source_content_hash,
            parser_version,
            chunker_version,
        )
        document_id = str(metadata.get("document_id") or source_uid)
        source_slug = _slug(doc.source)
        persist_extracted = bool(metadata.get("persist_extracted", True))
        markdown_path = (
            self.extracted_dir / f"{source_slug}.md"
            if persist_extracted
            else None
        )
        json_path = (
            self.extracted_dir / f"{source_slug}.json"
            if persist_extracted
            else None
        )

        existing = conn.execute(
            "SELECT id, current_version_id FROM sources WHERE source = ?",
            (doc.source,),
        ).fetchone()
        if existing and str(existing["current_version_id"] or "") == source_version_id:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM sections WHERE source_id=?",
                (int(existing["id"]),),
            ).fetchone()
            return int(row["n"] or 0)

        if markdown_path is not None and json_path is not None:
            markdown_path.write_text(doc.content, encoding="utf-8")
            json_path.write_text(
                json.dumps(
                    {
                        "source": doc.source,
                        "source_id": source_uid,
                        "source_version_id": source_version_id,
                        "metadata": metadata,
                        "content": doc.content,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        if existing:
            source_id = int(existing["id"])
            conn.execute(
                """
                UPDATE sources
                SET docset_root = ?, content = ?, metadata_json = ?, markdown_path = ?,
                    json_path = ?, raw_tokens = ?, ingested_at = ?, source_uid = ?,
                    current_version_id = ?, content_hash = ?
                WHERE id = ?
                """,
                (
                    docset_root,
                    doc.content,
                    json.dumps(metadata, ensure_ascii=False),
                    str(markdown_path or ""),
                    str(json_path or ""),
                    estimate_tokens(doc.content),
                    ingested_at,
                    source_uid,
                    source_version_id,
                    source_content_hash,
                    source_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO sources
                    (source, docset_root, content, metadata_json, markdown_path, json_path,
                     raw_tokens, ingested_at, source_uid, current_version_id, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.source,
                    docset_root,
                    doc.content,
                    json.dumps(metadata, ensure_ascii=False),
                    str(markdown_path or ""),
                    str(json_path or ""),
                    estimate_tokens(doc.content),
                    ingested_at,
                    source_uid,
                    source_version_id,
                    source_content_hash,
                ),
            )
            source_id = int(cursor.lastrowid)

        conn.execute(
            """
            UPDATE source_versions
            SET lifecycle='superseded'
            WHERE source_uid=? AND lifecycle='active' AND version_id<>?
            """,
            (source_uid, source_version_id),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO source_versions
                (version_id, source_uid, source_id, content_hash, parser_version,
                 chunker_version, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_version_id,
                source_uid,
                source_id,
                source_content_hash,
                parser_version,
                chunker_version,
                json.dumps(metadata, ensure_ascii=False),
                ingested_at,
            ),
        )

        section_count = 0
        source_path = str(metadata.get("source_path") or doc.source)
        document_title = str(metadata.get("title") or Path(doc.source).stem or "Document")
        format_name = str(metadata.get("format") or "")
        project_id = str(metadata.get("project_id") or "")
        scope_kind = str(metadata.get("scope_kind") or "")
        kind = str(metadata.get("kind") or "")
        raw_lifecycle = str(metadata.get("status") or "active").casefold()
        lifecycle = "active" if raw_lifecycle in {"active", "current"} else raw_lifecycle
        existing_sections = {
            str(row["unit_id"]): row
            for row in conn.execute(
                """
                SELECT id, unit_id, unit_revision_id
                FROM sections WHERE source_id=? AND unit_id IS NOT NULL
                """,
                (source_id,),
            )
        }
        active_unit_ids: set[str] = set()
        anchor_occurrences: dict[str, int] = {}
        for chunk_index, (title, level, text, chunk_meta) in enumerate(_sections_for_document(doc)):
            anchor = str(chunk_meta.get("anchor") or title)
            occurrence = anchor_occurrences.get(anchor, 0)
            anchor_occurrences[anchor] = occurrence + 1
            content_hash = _chunk_hash(text)
            unit_id = str(
                metadata.get("atom_id")
                or _stable_id("unit", document_id, anchor, occurrence)
            )
            unit_revision_id = _stable_id(
                "urev", unit_id, content_hash, chunker_version
            )
            active_unit_ids.add(unit_id)
            section_meta = {
                **metadata,
                "section_title": title,
                "section_level": level,
                "source_path": source_path,
                "document_title": document_title,
                "document_title_hash": hashlib.sha1(
                    (document_title or "").encode("utf-8")
                ).hexdigest()[:16],
                "format": format_name,
                "anchor": anchor,
                "content_hash": content_hash,
                "document_id": document_id,
                "unit_id": unit_id,
                "unit_revision_id": unit_revision_id,
                "source_version_id": source_version_id,
                "lifecycle": lifecycle,
            }
            previous = existing_sections.get(unit_id)
            if previous:
                row_id = int(previous["id"])
                previous_revision = str(previous["unit_revision_id"] or "")
                if previous_revision and previous_revision != unit_revision_id:
                    conn.execute(
                        "UPDATE retrieval_unit_revisions SET lifecycle='superseded' "
                        "WHERE revision_id=?",
                        (previous_revision,),
                    )
                conn.execute("DELETE FROM sections_fts WHERE rowid=?", (row_id,))
                conn.execute(
                    """
                    UPDATE sections
                    SET source=?, chunk_index=?, title=?, level=?, text=?, token_estimate=?,
                        source_path=?, document_title=?, format=?, anchor=?, content_hash=?,
                        metadata_json=?, document_id=?, unit_revision_id=?, project_id=?,
                        scope_kind=?, kind=?, lifecycle=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        doc.source,
                        chunk_index,
                        title,
                        level,
                        text,
                        estimate_tokens(text),
                        source_path,
                        document_title,
                        format_name,
                        anchor,
                        content_hash,
                        json.dumps(section_meta, ensure_ascii=False),
                        document_id,
                        unit_revision_id,
                        project_id,
                        scope_kind,
                        kind,
                        lifecycle,
                        ingested_at,
                        row_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO sections
                        (source_id, source, chunk_index, title, level, text, token_estimate,
                         source_path, document_title, format, anchor, content_hash, metadata_json,
                         document_id, unit_id, unit_revision_id, project_id, scope_kind, kind,
                         lifecycle, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        doc.source,
                        chunk_index,
                        title,
                        level,
                        text,
                        estimate_tokens(text),
                        source_path,
                        document_title,
                        format_name,
                        anchor,
                        content_hash,
                        json.dumps(section_meta, ensure_ascii=False),
                        document_id,
                        unit_id,
                        unit_revision_id,
                        project_id,
                        scope_kind,
                        kind,
                        lifecycle,
                        ingested_at,
                    ),
                )
                row_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO sections_fts(rowid, title, text, source) VALUES (?, ?, ?, ?)",
                (row_id, title, text, doc.source),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO retrieval_unit_revisions
                    (revision_id, unit_id, document_id, source_version_id, content_hash,
                     text, metadata_json, lifecycle, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    unit_revision_id,
                    unit_id,
                    document_id,
                    source_version_id,
                    content_hash,
                    text,
                    json.dumps(section_meta, ensure_ascii=False),
                    lifecycle,
                    ingested_at,
                ),
            )
            section_count += 1

        stale_rows = [
            row
            for unit_id, row in existing_sections.items()
            if unit_id not in active_unit_ids
        ]
        for row in stale_rows:
            row_id = int(row["id"])
            revision_id = str(row["unit_revision_id"] or "")
            if revision_id:
                conn.execute(
                    "UPDATE retrieval_unit_revisions SET lifecycle='deleted' "
                    "WHERE revision_id=?",
                    (revision_id,),
                )
            conn.execute("DELETE FROM sections_fts WHERE rowid=?", (row_id,))
            conn.execute("DELETE FROM sections WHERE id=?", (row_id,))

        for stage in ("unitize", "lexical-index"):
            stage_version = "v2"
            job_id = _stable_id("job", source_version_id, stage, stage_version)
            conn.execute(
                """
                INSERT INTO index_jobs
                    (job_id, source_version_id, stage, stage_version, status, attempts,
                     checkpoint_json, started_at, finished_at)
                VALUES (?, ?, ?, ?, 'completed', 1, ?, ?, ?)
                ON CONFLICT(source_version_id, stage, stage_version) DO UPDATE SET
                    status='completed',
                    attempts=index_jobs.attempts + 1,
                    checkpoint_json=excluded.checkpoint_json,
                    last_error=NULL,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
                """,
                (
                    job_id,
                    source_version_id,
                    stage,
                    stage_version,
                    json.dumps({"sections": section_count}),
                    ingested_at,
                    ingested_at,
                ),
            )
        return section_count

    def query(
        self,
        text: str,
        *,
        limit: int,
        budget: int,
        expand: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        expand_mode = expand or "none"
        rows = [dict(r) for r in self._search_rows(text, max(limit * 4, limit), filters=filters)]
        term_weights = self._query_term_weights(text)

        # --- Re-ranking passes (BM25 rank is negative, lower = better) ---
        query_lower = text.lower()
        content_terms = set(re.findall(r"\w+", self._strip_stopwords(text).lower()))

        for r in rows:
            tokens = int(r["token_estimate"])
            title_lower = r["title"].lower()
            title_words = set(re.findall(r"\w+", title_lower))
            text_lower = r["text"].lower()

            # 1. Penalize long sections to prefer focused matches.
            if tokens > 600:
                r["rank"] -= 0.3 * (tokens - 600) / 600

            # 2. Penalize boilerplate/legal sections.  Use keyword overlap
            #    so numbered headings ("12. Miscellaneous") and subsections
            #    ("1. Modifications") are caught, not just exact titles.
            boilerplate_overlap = title_words & _BOILERPLATE_KEYWORDS
            if boilerplate_overlap:
                # Scale penalty by how many boilerplate keywords match.
                r["rank"] -= 3.0 * len(boilerplate_overlap)

            # 3. Boost sections where content terms appear in the title.
            title_term_overlap = title_words & content_terms
            if title_term_overlap:
                r["rank"] += 1.5 * len(title_term_overlap)

            # 4. Boost sections where the stripped query phrase appears
            #    verbatim in the first 500 chars of body text.
            stripped_query = self._strip_stopwords(text).lower()
            if stripped_query and stripped_query in text_lower[:500]:
                r["rank"] += 2.0

            # 5. Boost sections with action verbs in the title when the
            #    query is task-oriented.
            _task_signals = {"how", "create", "setup", "set", "configure",
                             "install", "add", "build", "deploy", "start",
                             "connect", "enable", "generate", "register"}
            if content_terms & _task_signals:
                _action_verbs = {"create", "set", "setup", "configure",
                                 "install", "add", "build", "deploy", "start",
                                 "connect", "enable", "initialize", "register",
                                 "sign", "generate", "getting", "started"}
                if title_words & _action_verbs:
                    r["rank"] += 1.5

        rows.sort(key=lambda r: r["rank"])
        selected: list[dict] = []
        used_ids: set[int] = set()
        seen_content: set[str] = set()
        token_total = 0

        for row in rows:
            expanded = self._expand_row(row, expand_mode)
            for candidate in expanded:
                row_id = int(candidate["id"])
                if row_id in used_ids:
                    continue
                # Dedupe sections with identical content (common in
                # aggregated sources like llms-full.txt where the same
                # heading/text can appear in multiple pages).
                content_key = hashlib.sha1(
                    (candidate["title"] + "\n" + candidate["text"]).encode()
                ).hexdigest()
                if content_key in seen_content:
                    used_ids.add(row_id)
                    continue
                tokens = int(candidate["token_estimate"])
                if selected and token_total + tokens > budget:
                    continue
                selected.append(candidate)
                used_ids.add(row_id)
                seen_content.add(content_key)
                token_total += tokens
                if len(selected) >= limit:
                    break
            if len(selected) >= limit or token_total >= budget:
                break

        raw_tokens = self._raw_token_total([row["source"] for row in selected])
        savings = 0.0 if raw_tokens <= 0 else max(0.0, 100.0 * (1 - (token_total / raw_tokens)))
        runway = 1.0 if token_total <= 0 else raw_tokens / token_total
        results: list[RetrievedChunk] = []
        for index, row in enumerate(selected):
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata.update(
                {
                    "title": row["title"],
                    "section_id": int(row["id"]),
                    "token_estimate": int(row["token_estimate"]),
                    "docmancer_tokens": token_total,
                    "raw_tokens": raw_tokens,
                    "savings_percent": round(savings, 1),
                    "runway_multiplier": round(runway, 2),
                }
            )
            score = _lexical_relevance_score(
                text,
                row["title"],
                row["text"],
                term_weights=term_weights,
            )
            results.append(
                RetrievedChunk(
                    source=row["source"],
                    chunk_index=int(row["chunk_index"]),
                    text=row["text"],
                    score=score,
                    metadata=metadata,
                )
            )
        return results

    def fetch_sections_by_id(
        self,
        section_ids: list[int],
        *,
        budget: int = 2400,
        scores: dict[int, float] | None = None,
        fusion_scores: dict[int, float] | None = None,
    ) -> list[RetrievedChunk]:
        """Hydrate ``RetrievedChunk`` objects from raw section ids, preserving order."""
        if not section_ids:
            return []
        placeholders = ",".join("?" * len(section_ids))
        with self._connect() as conn:
            rows = {
                int(row["id"]): row
                for row in conn.execute(
                    f"""
                    SELECT s.id, s.source, s.chunk_index, s.title, s.text,
                           s.token_estimate, s.metadata_json
                    FROM sections s
                    WHERE s.id IN ({placeholders})
                    """,
                    section_ids,
                )
            }
        selected_rows: list[tuple[int, sqlite3.Row]] = []
        used_tokens = 0
        for rank, sid in enumerate(section_ids):
            row = rows.get(int(sid))
            if row is None:
                continue
            tok = int(row["token_estimate"] or 0)
            if used_tokens and used_tokens + tok > budget:
                break
            used_tokens += tok
            selected_rows.append((rank, row))

        # Compute pack-level token metrics so the hybrid dispatcher returns
        # the same shape as the lexical path. Without these, the CLI prints
        # "~0 tokens" / "~0 raw tokens" because nothing else sets them.
        raw_tokens = self._raw_token_total([row["source"] for _, row in selected_rows])
        token_total = used_tokens
        savings = 0.0 if raw_tokens <= 0 else max(0.0, 100.0 * (1 - (token_total / raw_tokens)))
        runway = 1.0 if token_total <= 0 else raw_tokens / token_total

        results: list[RetrievedChunk] = []
        for rank, row in selected_rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata.setdefault("title", row["title"])
            metadata.setdefault("section_id", int(row["id"]))
            metadata["token_estimate"] = int(row["token_estimate"] or 0)
            metadata["docmancer_tokens"] = token_total
            metadata["raw_tokens"] = raw_tokens
            metadata["savings_percent"] = round(savings, 1)
            metadata["runway_multiplier"] = round(runway, 2)
            score = float((scores or {}).get(int(row["id"]), 0.0))
            if fusion_scores and int(row["id"]) in fusion_scores:
                metadata["fusion_score"] = float(fusion_scores[int(row["id"])])
            results.append(
                RetrievedChunk(
                    source=row["source"],
                    chunk_index=int(row["chunk_index"]),
                    text=row["text"],
                    score=score,
                    metadata=metadata,
                )
            )
        return results

    @staticmethod
    def _strip_stopwords(query: str) -> str:
        """Remove common stopwords to reduce noise in BM25 scoring."""
        tokens = re.findall(r"\w+", query)
        filtered = [t for t in tokens if t.lower() not in _QUERY_STOPWORDS]
        return " ".join(filtered) if filtered else query

    def _query_term_weights(self, query: str) -> dict[str, float]:
        """Compute per-query IDF weights from the current section corpus."""
        cleaned = self._strip_stopwords(query)
        terms = sorted({token.lower() for token in re.findall(r"\w+", cleaned) if token})
        original_tokens = re.findall(r"\w+", query)
        named_terms = {
            token.lower()
            for index, token in enumerate(original_tokens)
            if index > 0 and token[:1].isupper()
        }
        if not terms:
            return {}
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] or 0)
            weights: dict[str, float] = {}
            for term in terms:
                try:
                    count = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM sections_fts WHERE sections_fts MATCH ?",
                            (term,),
                        ).fetchone()[0]
                        or 0
                    )
                except sqlite3.OperationalError:
                    count = total
                weight = math.log((total + 1) / (count + 1)) + 1.0
                if term in named_terms:
                    weight *= 3.0
                weights[term] = weight
        return weights

    def _search_rows(self, query: str, limit: int, *, filters: dict | None = None) -> list[sqlite3.Row]:
        cleaned = self._strip_stopwords(query)
        terms = [token for token in re.findall(r"\w+", cleaned) if token]
        filter_sql = ""
        filter_params: list = []
        allowed_columns = {
            "source": "sections.source",
            "source_path": "sections.source_path",
            "format": "sections.format",
            "document_id": "sections.document_id",
            "document_title_hash": "sections.document_id",
            "project_id": "sections.project_id",
            "scope_kind": "sections.scope_kind",
            "kind": "sections.kind",
            "lifecycle": "sections.lifecycle",
        }
        for key, value in (filters or {}).items():
            column = allowed_columns.get(str(key))
            if column is None:
                continue
            values = value.get("in") if isinstance(value, dict) and "in" in value else [value]
            values = [item for item in values if item is not None]
            if not values:
                filter_sql += " AND 0"
                continue
            placeholders = ",".join("?" for _ in values)
            filter_sql += f" AND {column} IN ({placeholders})"
            filter_params.extend(values)
        with self._connect() as conn:
            try:
                rows = list(
                    conn.execute(
                        f"""
                        SELECT sections.*, bm25(sections_fts) AS rank
                        FROM sections_fts
                        JOIN sections ON sections.id = sections_fts.rowid
                        WHERE sections_fts MATCH ?
                        {filter_sql}
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (cleaned, *filter_params, limit),
                    )
                )
                if rows or len(terms) <= 1:
                    return rows
            except sqlite3.OperationalError:
                pass

            fallback_query = " OR ".join(terms)
            if not fallback_query:
                return []
            return list(
                conn.execute(
                    f"""
                    SELECT sections.*, bm25(sections_fts) AS rank
                    FROM sections_fts
                    JOIN sections ON sections.id = sections_fts.rowid
                    WHERE sections_fts MATCH ?
                    {filter_sql}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fallback_query, *filter_params, limit),
                )
            )

    def _expand_row(self, row: sqlite3.Row, expand: str) -> list[sqlite3.Row]:
        if expand == "none":
            return [row]
        with self._connect() as conn:
            if expand == "page":
                # Find sections that belong to the same logical page as the
                # matching row.  For multi-page docsets the page boundary is
                # the nearest preceding level-1 heading.  For single-page
                # sources (e.g. llms-full.txt) this avoids returning the
                # entire document from chunk_index 0 and instead anchors on
                # the matched section's page neighbourhood.
                anchor_idx = int(row["chunk_index"])
                source_id = row["source_id"]

                # Walk backwards to find the nearest level-1 heading.
                prev_h1 = conn.execute(
                    """
                    SELECT chunk_index FROM sections
                    WHERE source_id = ? AND chunk_index <= ? AND level = 1
                    ORDER BY chunk_index DESC LIMIT 1
                    """,
                    (source_id, anchor_idx),
                ).fetchone()
                page_start = int(prev_h1["chunk_index"]) if prev_h1 else anchor_idx

                # Walk forward to find the next level-1 heading (exclusive).
                next_h1 = conn.execute(
                    """
                    SELECT chunk_index FROM sections
                    WHERE source_id = ? AND chunk_index > ? AND level = 1
                    ORDER BY chunk_index ASC LIMIT 1
                    """,
                    (source_id, anchor_idx),
                ).fetchone()
                page_end = int(next_h1["chunk_index"]) - 1 if next_h1 else anchor_idx + 20

                # Return sections within this page, anchored section first.
                rows = list(
                    conn.execute(
                        """
                        SELECT * FROM sections
                        WHERE source_id = ? AND chunk_index BETWEEN ? AND ?
                        ORDER BY chunk_index
                        """,
                        (source_id, page_start, page_end),
                    )
                )
                # Reorder so the matching section comes first (budget
                # packing keeps early items, so this ensures the actual
                # match is always included).
                anchor_rows = [r for r in rows if int(r["chunk_index"]) == anchor_idx]
                other_rows = [r for r in rows if int(r["chunk_index"]) != anchor_idx]
                return anchor_rows + other_rows

            if expand == "adjacent":
                return list(
                    conn.execute(
                        """
                        SELECT * FROM sections
                        WHERE source_id = ? AND chunk_index BETWEEN ? AND ?
                        ORDER BY chunk_index
                        """,
                        (row["source_id"], max(0, int(row["chunk_index"]) - 1), int(row["chunk_index"]) + 1),
                    )
                )
        return [row]

    def _raw_token_total(self, sources: list[str]) -> int:
        if not sources:
            return 0
        unique_sources = sorted(set(sources))
        placeholders = ",".join("?" for _ in unique_sources)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COALESCE(SUM(raw_tokens), 0) AS total FROM sources WHERE source IN ({placeholders})",
                unique_sources,
            ).fetchone()
            return int(row["total"] or 0)

    def collection_stats(self) -> dict:
        with self._connect() as conn:
            sources = conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"]
            sections = conn.execute("SELECT COUNT(*) AS count FROM sections").fetchone()["count"]
            source_versions = conn.execute(
                "SELECT COUNT(*) AS count FROM source_versions"
            ).fetchone()["count"]
            unit_revisions = conn.execute(
                "SELECT COUNT(*) AS count FROM retrieval_unit_revisions"
            ).fetchone()["count"]
            job_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM index_jobs GROUP BY status"
            ).fetchall()
            format_rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(format, ''), 'unknown') AS format, COUNT(*) AS count
                FROM sections
                GROUP BY COALESCE(NULLIF(format, ''), 'unknown')
                ORDER BY format
                """
            ).fetchall()
            source_format_rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(json_extract(metadata_json, '$.format'), ''), 'unknown') AS format,
                       COUNT(*) AS count
                FROM sources
                GROUP BY COALESCE(NULLIF(json_extract(metadata_json, '$.format'), ''), 'unknown')
                ORDER BY format
                """
            ).fetchall()
        return {
            "collection_exists": self.db_path.exists(),
            "sources_count": int(sources),
            "points_count": int(sections),
            "sections_count": int(sections),
            "source_versions_count": int(source_versions),
            "unit_revisions_count": int(unit_revisions),
            "index_jobs": {str(row["status"]): int(row["count"]) for row in job_rows},
            "sources_by_format": {str(row["format"]): int(row["count"]) for row in source_format_rows},
            "sections_by_format": {str(row["format"]): int(row["count"]) for row in format_rows},
            "db_path": str(self.db_path),
            "extracted_dir": str(self.extracted_dir),
        }

    def list_sources_with_dates(self) -> list[dict]:
        with self._connect() as conn:
            return [
                {"source": row["source"], "ingested_at": row["ingested_at"]}
                for row in conn.execute("SELECT source, ingested_at FROM sources ORDER BY ingested_at DESC, source")
            ]

    def list_grouped_sources_with_dates(self) -> list[dict]:
        with self._connect() as conn:
            return [
                {
                    "source": row["source"],
                    "ingested_at": row["ingested_at"],
                    "pages": int(row["pages"] or 0),
                    "sections": int(row["sections"] or 0),
                    "formats": [value for value in str(row["formats"] or "").split(",") if value],
                }
                for row in conn.execute(
                    """
                    SELECT COALESCE(NULLIF(s.docset_root, ''), s.source) AS source,
                           MAX(s.ingested_at) AS ingested_at,
                           COUNT(DISTINCT s.id) AS pages,
                           COUNT(sec.id) AS sections,
                           GROUP_CONCAT(DISTINCT COALESCE(NULLIF(sec.format, ''), 'unknown')) AS formats
                    FROM sources AS s
                    LEFT JOIN sections AS sec ON sec.source_id = s.id
                    GROUP BY COALESCE(NULLIF(s.docset_root, ''), s.source)
                    ORDER BY ingested_at DESC, source
                    """
                )
            ]

    def get_grouped_source_documents(self, source_root: str) -> dict | None:
        """Return complete indexed pages and their section outline for a docset."""
        with self._connect() as conn:
            source_rows = conn.execute(
                """
                SELECT id, source, content, metadata_json, ingested_at
                FROM sources
                WHERE COALESCE(NULLIF(docset_root, ''), source) = ?
                ORDER BY source
                """,
                (source_root,),
            ).fetchall()
            if not source_rows:
                return None
            source_ids = [int(row["id"]) for row in source_rows]
            placeholders = ",".join("?" for _ in source_ids)
            section_rows = conn.execute(
                f"""
                SELECT source_id, chunk_index, title, level, text, anchor, format
                FROM sections
                WHERE source_id IN ({placeholders})
                ORDER BY source_id, chunk_index
                """,
                source_ids,
            ).fetchall()

        sections_by_source: dict[int, list[dict]] = {source_id: [] for source_id in source_ids}
        for row in section_rows:
            sections_by_source[int(row["source_id"])].append(
                {
                    "chunk_index": int(row["chunk_index"]),
                    "title": str(row["title"] or "Section"),
                    "level": int(row["level"] or 0),
                    "text": str(row["text"] or ""),
                    "anchor": str(row["anchor"] or ""),
                    "format": str(row["format"] or ""),
                }
            )

        pages = []
        for row in source_rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (json.JSONDecodeError, ValueError):
                metadata = {}
            pages.append(
                {
                    "source": str(row["source"]),
                    "title": str(metadata.get("title") or Path(str(row["source"])).name or row["source"]),
                    "format": str(metadata.get("format") or "unknown"),
                    "ingested_at": str(row["ingested_at"] or ""),
                    "content": str(row["content"] or ""),
                    "sections": sections_by_source[int(row["id"])],
                }
            )
        return {"source": source_root, "pages": pages}

    def list_sources(self) -> list[str]:
        return [entry["source"] for entry in self.list_sources_with_dates()]

    def list_source_provenance(self) -> list[dict]:
        """Return per-source document-level metadata plus content char count.

        Used by ``docmancer memory sources`` to report exactly what was indexed
        and from where. Each row exposes the harness, scope, title, kind,
        absolute source path, and character count.
        """
        out: list[dict] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, content, metadata_json FROM sources ORDER BY source"
            )
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                except (json.JSONDecodeError, ValueError):
                    meta = {}
                out.append(
                    {
                        "source": str(row["source"]),
                        "content": str(row["content"] or ""),
                        "chars": len(row["content"] or ""),
                        "metadata": meta,
                    }
                )
        return out

    def list_embedding_upserts(self, collection: str) -> dict[int, dict]:
        """Return ``{chunk_id: {content_hash, embedding_hash, status}}`` for a collection."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, content_hash, embedding_hash, upserted_at, status
                FROM embedding_upserts
                WHERE qdrant_collection = ?
                """,
                (collection,),
            )
            return {
                int(row["chunk_id"]): {
                    "content_hash": row["content_hash"] or "",
                    "embedding_hash": row["embedding_hash"] or "",
                    "upserted_at": row["upserted_at"] or "",
                    "status": row["status"] or "",
                }
                for row in rows
            }

    def embedding_upserts_for_ids(
        self,
        collection: str,
        chunk_ids: list[int],
    ) -> dict[int, dict]:
        if not chunk_ids:
            return {}
        output: dict[int, dict] = {}
        with self._connect() as conn:
            for start in range(0, len(chunk_ids), 500):
                batch = chunk_ids[start:start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"""
                    SELECT chunk_id, content_hash, embedding_hash, upserted_at, status
                    FROM embedding_upserts
                    WHERE qdrant_collection=? AND chunk_id IN ({placeholders})
                    """,
                    (collection, *batch),
                )
                for row in rows:
                    output[int(row["chunk_id"])] = {
                        "content_hash": row["content_hash"] or "",
                        "embedding_hash": row["embedding_hash"] or "",
                        "upserted_at": row["upserted_at"] or "",
                        "status": row["status"] or "",
                    }
        return output

    def stale_embedding_upsert_ids(self, collection: str) -> list[int]:
        """Return vector bookkeeping IDs with no active SQLite retrieval unit."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT up.chunk_id
                FROM embedding_upserts AS up
                LEFT JOIN sections AS sec ON sec.id = up.chunk_id
                WHERE up.qdrant_collection=? AND sec.id IS NULL
                ORDER BY up.chunk_id
                """,
                (collection,),
            )
            return [int(row["chunk_id"]) for row in rows]

    def record_embedding_upserts(
        self,
        collection: str,
        records: list[dict],
    ) -> None:
        """Insert/replace rows in ``embedding_upserts``.

        Each record needs ``chunk_id``, ``content_hash``, ``embedding_hash``,
        and optionally ``status`` (defaults to "ok").
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO embedding_upserts
                    (chunk_id, qdrant_collection, content_hash, embedding_hash, upserted_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, qdrant_collection) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    embedding_hash = excluded.embedding_hash,
                    upserted_at = excluded.upserted_at,
                    status = excluded.status
                """,
                [
                    (
                        int(r["chunk_id"]),
                        collection,
                        r.get("content_hash") or "",
                        r.get("embedding_hash") or "",
                        now,
                        r.get("status") or "ok",
                    )
                    for r in records
                ],
            )

    def delete_embedding_upserts(self, collection: str, chunk_ids: list[int]) -> int:
        if not chunk_ids:
            return 0
        placeholders = ",".join("?" * len(chunk_ids))
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM embedding_upserts "
                f"WHERE qdrant_collection = ? AND chunk_id IN ({placeholders})",
                (collection, *chunk_ids),
            )
            return cur.rowcount or 0

    def clear_embedding_upserts(self, collection: str) -> int:
        """Drop all embedding bookkeeping rows for a collection.

        A full rebuild deletes the sections and (separately) the vector points,
        but ``add_documents(recreate=True)`` leaves ``embedding_upserts`` intact.
        Callers that wipe the vectors must also clear this bookkeeping, or the
        next sync treats already-recorded sections as up to date, skips
        re-embedding, and the vector consistency check then sees zero points.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM embedding_upserts WHERE qdrant_collection = ?",
                (collection,),
            )
            return cur.rowcount or 0

    def adjacent_section_ids(self, section_id: int, *, mode: str = "adjacent") -> list[int]:
        """Return neighboring section ids for hybrid-mode neighbor expansion.

        ``mode="adjacent"`` returns the prev + next sections within the same
        source. ``mode="page"`` returns every section belonging to the same
        source as the target.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source, chunk_index FROM sections WHERE id = ?",
                (int(section_id),),
            ).fetchone()
            if not row:
                return []
            source = row["source"]
            chunk_index = int(row["chunk_index"])
            if mode == "page":
                rows = conn.execute(
                    """
                    SELECT id, chunk_index FROM sections
                    WHERE source = ? AND id != ?
                    ORDER BY chunk_index
                    """,
                    (source, int(section_id)),
                )
                return [int(r["id"]) for r in rows]
            # default: adjacent (prev + next)
            rows = conn.execute(
                """
                SELECT id, chunk_index FROM sections
                WHERE source = ? AND chunk_index IN (?, ?)
                ORDER BY chunk_index
                """,
                (source, chunk_index - 1, chunk_index + 1),
            )
            return [int(r["id"]) for r in rows]

    def document_title_hashes_for(self, section_ids: list[int]) -> dict[int, str]:
        """Return stable document identities for hierarchical retrieval.

        The compatibility method name predates ``document_id``. New indexes use
        the stable top-level identity; older rows fall back to their metadata.
        """
        if not section_ids:
            return {}
        placeholders = ",".join("?" * len(section_ids))
        out: dict[int, str] = {}
        with self._connect() as conn:
            for row in conn.execute(
                f"SELECT id, document_id, metadata_json "
                f"FROM sections WHERE id IN ({placeholders})",
                section_ids,
            ):
                try:
                    md = json.loads(row["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    md = {}
                doc_hash = (
                    row["document_id"]
                    or md.get("document_id")
                    or md.get("document_title_hash")
                    or md.get("docset_root")
                    or ""
                )
                if doc_hash:
                    out[int(row["id"])] = str(doc_hash)
        return out

    def distinct_document_count(self) -> int:
        """Return the number of distinct documents in the index.

        Documents are grouped by stable source-derived identity rather than
        title, so unrelated files named README or index never collapse.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT document_id) AS n "
                "FROM sections WHERE document_id IS NOT NULL AND document_id <> ''"
            ).fetchone()
            return int(row["n"]) if row else 0

    def section_count_grouped_by_format(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(format, ''), 'unknown') AS fmt, COUNT(*) AS n
                FROM sections
                GROUP BY fmt
                """
            )
            return {row["fmt"]: int(row["n"]) for row in rows}

    def list_sections_for_embedding(self) -> list[dict]:
        """Return canonical section chunks for embedding-based consumers.

        Emits the same chunks the FTS index stores, so future embedding
        features can reuse identical section boundaries. Each row has:
        section_id (int), source, chunk_index, title, level, text, and
        token_estimate.
        """
        return [
            section
            for batch in self.iter_sections_for_embedding(batch_size=1_000)
            for section in batch
        ]

    def iter_sections_for_embedding(self, *, batch_size: int = 256):
        """Yield bounded batches of active retrieval units for vector indexing."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT id, source, chunk_index, title, level, text, token_estimate,
                       source_path, document_title, format, anchor, content_hash,
                       metadata_json, document_id, unit_id, unit_revision_id,
                       project_id, scope_kind, kind, lifecycle
                FROM sections
                WHERE lifecycle='active'
                ORDER BY source, chunk_index
                """
            )
            while True:
                rows = cursor.fetchmany(max(1, batch_size))
                if not rows:
                    break
                output = []
                for row in rows:
                    try:
                        metadata = json.loads(row["metadata_json"] or "{}")
                    except (json.JSONDecodeError, ValueError):
                        metadata = {}
                    output.append({
                        "section_id": int(row["id"]),
                        "source": str(row["source"]),
                        "chunk_index": int(row["chunk_index"]),
                        "title": str(row["title"] or ""),
                        "level": int(row["level"] or 0),
                        "text": str(row["text"] or ""),
                        "token_estimate": int(row["token_estimate"] or 0),
                        "source_path": str(row["source_path"] or ""),
                        "document_title": str(row["document_title"] or ""),
                        "format": str(row["format"] or ""),
                        "anchor": str(row["anchor"] or ""),
                        "content_hash": str(row["content_hash"] or ""),
                        "document_id": str(row["document_id"] or ""),
                        "unit_id": str(row["unit_id"] or ""),
                        "unit_revision_id": str(row["unit_revision_id"] or ""),
                        "project_id": str(row["project_id"] or ""),
                        "scope_kind": str(row["scope_kind"] or ""),
                        "kind": str(row["kind"] or ""),
                        "lifecycle": str(row["lifecycle"] or "active"),
                        "metadata": metadata,
                    })
                yield output
        finally:
            conn.close()

    def get_document_content(self, source: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT content FROM sources WHERE source = ?", (source,)).fetchone()
            return str(row["content"]) if row else None

    def has_source_content_hash(self, source: str, content_hash: str) -> bool:
        if not content_hash:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT metadata_json FROM sources WHERE source = ?", (source,)).fetchone()
        if not row:
            return False
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            return False
        return metadata.get("content_hash") == content_hash

    def delete_docset(self, docset_root: str) -> bool:
        with self._connect() as conn:
            sources = [
                row["source"]
                for row in conn.execute("SELECT source FROM sources WHERE docset_root = ?", (docset_root,))
            ]
        deleted = False
        for source in sources:
            deleted = self.delete_source(source) or deleted
        return deleted

    def delete_source(self, source: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM sources WHERE source = ?", (source,)).fetchone()
            if not row:
                return False
            source_id = int(row["id"])
            rows = list(
                conn.execute(
                    "SELECT id, unit_revision_id FROM sections WHERE source_id=?",
                    (source_id,),
                )
            )
            for row in rows:
                row_id = int(row["id"])
                conn.execute("DELETE FROM sections_fts WHERE rowid = ?", (row_id,))
                if row["unit_revision_id"]:
                    conn.execute(
                        "UPDATE retrieval_unit_revisions SET lifecycle='deleted' "
                        "WHERE revision_id=?",
                        (str(row["unit_revision_id"]),),
                    )
            conn.execute(
                "UPDATE source_versions SET lifecycle='deleted' WHERE source_id=?",
                (source_id,),
            )
            conn.execute("DELETE FROM sections WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return True

    def delete_sources_not_in(self, *, prefix: str, keep: set[str]) -> int:
        """Delete derived sources under ``prefix`` that are absent from a projection."""
        with self._connect() as conn:
            sources = [
                str(row["source"])
                for row in conn.execute(
                    "SELECT source FROM sources WHERE source LIKE ?",
                    (f"{prefix}%",),
                )
                if str(row["source"]) not in keep
            ]
        return sum(1 for source in sources if self.delete_source(source))

    def delete_sources_under_roots(self, roots: Iterable[str | Path]) -> int:
        """Delete sources whose source/docset_root live under any local root."""
        normalized_roots = [
            _normalize_source_like(root)
            for root in roots
            if str(root).strip()
        ]
        if not normalized_roots:
            return 0

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, docset_root, markdown_path, json_path FROM sources"
            ).fetchall()

        sources_to_delete: list[str] = []
        artifact_paths: set[Path] = set()
        for row in rows:
            source = str(row["source"] or "")
            docset_root = str(row["docset_root"] or "")
            source_norm = _normalize_source_like(source)
            docset_norm = _normalize_source_like(docset_root)

            matched = False
            for root in normalized_roots:
                prefix = root + "/"
                if source_norm == root or source_norm.startswith(prefix):
                    matched = True
                    break
                if docset_norm == root or docset_norm.startswith(prefix):
                    matched = True
                    break

            if not matched:
                continue

            sources_to_delete.append(source)
            for path_value in (row["markdown_path"], row["json_path"]):
                if path_value:
                    artifact_paths.add(Path(str(path_value)))

        deleted = 0
        for source in sources_to_delete:
            if self.delete_source(source):
                deleted += 1

        for artifact_path in artifact_paths:
            try:
                artifact_path.unlink(missing_ok=True)
            except TypeError:
                if artifact_path.exists():
                    artifact_path.unlink()

        return deleted

    def delete_all(self) -> bool:
        stats = self.collection_stats()
        with self._connect() as conn:
            conn.execute("DELETE FROM sections_fts")
            conn.execute("DELETE FROM sections")
            conn.execute("DELETE FROM sources")
        return stats["sources_count"] > 0 or stats["sections_count"] > 0
