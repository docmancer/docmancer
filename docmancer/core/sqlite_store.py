from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from docmancer.core.models import Document, RetrievedChunk
from docmancer.core.registry_models import InstalledPack


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


class SQLiteStore:
    def __init__(self, db_path: str | Path, extracted_dir: str | Path | None = None):
        self.db_path = Path(db_path).expanduser()
        self.extracted_dir = Path(extracted_dir).expanduser() if extracted_dir else self.db_path.parent / "extracted"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
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
                    ingested_at TEXT NOT NULL
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
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
                    title,
                    text,
                    source,
                    content='sections',
                    content_rowid='id'
                );

                CREATE TABLE IF NOT EXISTS installed_packs (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    trust_tier TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    registry_url TEXT NOT NULL,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    sections_count INTEGER NOT NULL DEFAULT 0,
                    archive_sha256 TEXT NOT NULL,
                    index_db_sha256 TEXT NOT NULL,
                    extracted_path TEXT NOT NULL DEFAULT '',
                    installed_at TEXT NOT NULL,
                    UNIQUE(name, version)
                );
                """
            )

    def add_documents(self, documents: Iterable[Document], recreate: bool = False) -> IndexResult:
        docs = list(documents)
        with self._connect() as conn:
            if recreate:
                conn.execute("DELETE FROM sections_fts")
                conn.execute("DELETE FROM sections")
                conn.execute("DELETE FROM sources")

            section_count = 0
            for doc in docs:
                section_count += self._add_document(conn, doc)
            return IndexResult(sources=len(docs), sections=section_count)

    def _add_document(self, conn: sqlite3.Connection, doc: Document) -> int:
        metadata = dict(doc.metadata or {})
        docset_root = str(metadata.get("docset_root") or "")
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source_slug = _slug(doc.source)
        markdown_path = self.extracted_dir / f"{source_slug}.md"
        json_path = self.extracted_dir / f"{source_slug}.json"
        markdown_path.write_text(doc.content, encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {"source": doc.source, "metadata": metadata, "content": doc.content},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        existing = conn.execute("SELECT id FROM sources WHERE source = ?", (doc.source,)).fetchone()
        if existing:
            source_id = int(existing["id"])
            row_ids = [row["id"] for row in conn.execute("SELECT id FROM sections WHERE source_id = ?", (source_id,))]
            for row_id in row_ids:
                conn.execute("DELETE FROM sections_fts WHERE rowid = ?", (row_id,))
            conn.execute("DELETE FROM sections WHERE source_id = ?", (source_id,))
            conn.execute(
                """
                UPDATE sources
                SET docset_root = ?, content = ?, metadata_json = ?, markdown_path = ?,
                    json_path = ?, raw_tokens = ?, ingested_at = ?
                WHERE id = ?
                """,
                (
                    docset_root,
                    doc.content,
                    json.dumps(metadata, ensure_ascii=False),
                    str(markdown_path),
                    str(json_path),
                    estimate_tokens(doc.content),
                    ingested_at,
                    source_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO sources
                    (source, docset_root, content, metadata_json, markdown_path, json_path, raw_tokens, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.source,
                    docset_root,
                    doc.content,
                    json.dumps(metadata, ensure_ascii=False),
                    str(markdown_path),
                    str(json_path),
                    estimate_tokens(doc.content),
                    ingested_at,
                ),
            )
            source_id = int(cursor.lastrowid)

        section_count = 0
        for chunk_index, (title, level, text) in enumerate(_split_sections(doc.content)):
            section_meta = {**metadata, "section_title": title, "section_level": level}
            cursor = conn.execute(
                """
                INSERT INTO sections
                    (source_id, source, chunk_index, title, level, text, token_estimate, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    doc.source,
                    chunk_index,
                    title,
                    level,
                    text,
                    estimate_tokens(text),
                    json.dumps(section_meta, ensure_ascii=False),
                ),
            )
            row_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO sections_fts(rowid, title, text, source) VALUES (?, ?, ?, ?)",
                (row_id, title, text, doc.source),
            )
            section_count += 1
        return section_count

    def query(
        self,
        text: str,
        *,
        limit: int,
        budget: int,
        expand: str | None = None,
    ) -> list[RetrievedChunk]:
        expand_mode = expand or "none"
        rows = [dict(r) for r in self._search_rows(text, max(limit * 4, limit))]

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
                    "token_estimate": int(row["token_estimate"]),
                    "docmancer_tokens": token_total,
                    "raw_tokens": raw_tokens,
                    "savings_percent": round(savings, 1),
                    "runway_multiplier": round(runway, 2),
                }
            )
            # FTS5 bm25 is lower-is-better. Present a positive rank-like score.
            score = max(0.0, 1.0 - (index * 0.05))
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

    def _search_rows(self, query: str, limit: int) -> list[sqlite3.Row]:
        cleaned = self._strip_stopwords(query)
        terms = [token for token in re.findall(r"\w+", cleaned) if token]
        with self._connect() as conn:
            try:
                rows = list(
                    conn.execute(
                        """
                        SELECT sections.*, bm25(sections_fts) AS rank
                        FROM sections_fts
                        JOIN sections ON sections.id = sections_fts.rowid
                        WHERE sections_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (cleaned, limit),
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
                    """
                    SELECT sections.*, bm25(sections_fts) AS rank
                    FROM sections_fts
                    JOIN sections ON sections.id = sections_fts.rowid
                    WHERE sections_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fallback_query, limit),
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
        return {
            "collection_exists": self.db_path.exists(),
            "sources_count": int(sources),
            "points_count": int(sections),
            "sections_count": int(sections),
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
                {"source": row["source"], "ingested_at": row["ingested_at"]}
                for row in conn.execute(
                    """
                    SELECT COALESCE(NULLIF(docset_root, ''), source) AS source, MAX(ingested_at) AS ingested_at
                    FROM sources
                    GROUP BY COALESCE(NULLIF(docset_root, ''), source)
                    ORDER BY ingested_at DESC, source
                    """
                )
            ]

    def install_pack(self, pack: InstalledPack) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO installed_packs (
                    name, version, trust_tier, source_url, registry_url,
                    total_tokens, sections_count, archive_sha256, index_db_sha256,
                    extracted_path, installed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name, version) DO UPDATE SET
                    trust_tier = excluded.trust_tier,
                    source_url = excluded.source_url,
                    registry_url = excluded.registry_url,
                    total_tokens = excluded.total_tokens,
                    sections_count = excluded.sections_count,
                    archive_sha256 = excluded.archive_sha256,
                    index_db_sha256 = excluded.index_db_sha256,
                    extracted_path = excluded.extracted_path,
                    installed_at = excluded.installed_at
                """,
                (
                    pack.name,
                    pack.version,
                    pack.trust_tier.value if hasattr(pack.trust_tier, "value") else str(pack.trust_tier),
                    pack.source_url,
                    pack.registry_url,
                    pack.total_tokens,
                    pack.sections_count,
                    pack.archive_sha256,
                    pack.index_db_sha256,
                    pack.extracted_path or "",
                    str(pack.installed_at),
                ),
            )

    def list_installed_packs(self) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM installed_packs
                    ORDER BY installed_at DESC, name, version
                    """
                )
            ]

    def get_installed_pack(self, name: str, version: str | None = None) -> dict | None:
        with self._connect() as conn:
            if version:
                row = conn.execute(
                    "SELECT * FROM installed_packs WHERE name = ? AND version = ?",
                    (name, version),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM installed_packs WHERE name = ? ORDER BY installed_at DESC LIMIT 1",
                    (name,),
                ).fetchone()
            return dict(row) if row else None

    def uninstall_pack(self, name: str, version: str | None = None) -> bool:
        rows = []
        with self._connect() as conn:
            if version:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM installed_packs WHERE name = ? AND version = ?",
                        (name, version),
                    )
                ]
            else:
                rows = [dict(row) for row in conn.execute("SELECT * FROM installed_packs WHERE name = ?", (name,))]
        deleted = False
        for row in rows:
            docset_root = f"registry://{row['name']}@{row['version']}"
            deleted = self.delete_docset(docset_root) or deleted
            extracted_path = row.get("extracted_path") or ""
            if extracted_path:
                shutil.rmtree(extracted_path, ignore_errors=True)
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM installed_packs WHERE name = ? AND version = ?",
                    (row["name"], row["version"]),
                )
                deleted = True
        return deleted

    def import_pack_db(self, pack_db_path: str | Path, docset_root: str, local_extracted_prefix: str | Path) -> int:
        pack_db = Path(pack_db_path).expanduser().resolve()
        local_prefix = Path(local_extracted_prefix).expanduser().resolve()
        local_prefix.mkdir(parents=True, exist_ok=True)
        section_count = 0
        with self._connect() as conn:
            conn.execute("ATTACH DATABASE ? AS packdb", (str(pack_db),))
            try:
                source_rows = list(
                    conn.execute(
                        """
                        SELECT id, source, content, metadata_json, markdown_path, json_path, raw_tokens, ingested_at
                        FROM packdb.sources
                        ORDER BY id
                        """
                    )
                )
                source_id_map: dict[int, int] = {}
                for row in source_rows:
                    original_source = str(row["source"])
                    namespaced_source = f"{docset_root}::{original_source}"
                    metadata = json.loads(row["metadata_json"] or "{}")
                    metadata["docset_root"] = docset_root

                    markdown_path = local_prefix / Path(str(row["markdown_path"] or f"{_slug(original_source)}.md")).name
                    json_path = local_prefix / Path(str(row["json_path"] or f"{_slug(original_source)}.json")).name
                    markdown_path.write_text(str(row["content"]), encoding="utf-8")
                    json_path.write_text(
                        json.dumps(
                            {"source": original_source, "metadata": metadata, "content": row["content"]},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                    existing = conn.execute("SELECT id FROM sources WHERE source = ?", (namespaced_source,)).fetchone()
                    if existing:
                        new_source_id = int(existing["id"])
                        old_section_ids = [
                            r["id"]
                            for r in conn.execute("SELECT id FROM sections WHERE source_id = ?", (new_source_id,))
                        ]
                        for old_id in old_section_ids:
                            conn.execute("DELETE FROM sections_fts WHERE rowid = ?", (old_id,))
                        conn.execute("DELETE FROM sections WHERE source_id = ?", (new_source_id,))
                        conn.execute(
                            """
                            UPDATE sources
                            SET docset_root = ?, content = ?, metadata_json = ?, markdown_path = ?,
                                json_path = ?, raw_tokens = ?, ingested_at = ?
                            WHERE id = ?
                            """,
                            (
                                docset_root,
                                row["content"],
                                json.dumps(metadata, ensure_ascii=False),
                                str(markdown_path),
                                str(json_path),
                                int(row["raw_tokens"] or 0),
                                row["ingested_at"],
                                new_source_id,
                            ),
                        )
                    else:
                        cursor = conn.execute(
                            """
                            INSERT INTO sources (
                                source, docset_root, content, metadata_json, markdown_path,
                                json_path, raw_tokens, ingested_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                namespaced_source,
                                docset_root,
                                row["content"],
                                json.dumps(metadata, ensure_ascii=False),
                                str(markdown_path),
                                str(json_path),
                                int(row["raw_tokens"] or 0),
                                row["ingested_at"],
                            ),
                        )
                        new_source_id = int(cursor.lastrowid)
                    source_id_map[int(row["id"])] = new_source_id

                section_rows = list(conn.execute(
                    """
                    SELECT source_id, source, chunk_index, title, level, text, token_estimate, metadata_json
                    FROM packdb.sections
                    ORDER BY source_id, chunk_index
                    """
                ))
                for row in section_rows:
                    new_source_id = source_id_map[int(row["source_id"])]
                    namespaced_source = f"{docset_root}::{row['source']}"
                    metadata = json.loads(row["metadata_json"] or "{}")
                    metadata["docset_root"] = docset_root
                    cursor = conn.execute(
                        """
                        INSERT INTO sections (
                            source_id, source, chunk_index, title, level, text, token_estimate, metadata_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_source_id,
                            namespaced_source,
                            int(row["chunk_index"]),
                            row["title"],
                            int(row["level"]),
                            row["text"],
                            int(row["token_estimate"]),
                            json.dumps(metadata, ensure_ascii=False),
                        ),
                    )
                    row_id = int(cursor.lastrowid)
                    conn.execute(
                        "INSERT INTO sections_fts(rowid, title, text, source) VALUES (?, ?, ?, ?)",
                        (row_id, row["title"], row["text"], namespaced_source),
                    )
                    section_count += 1
            finally:
                conn.commit()
                conn.execute("DETACH DATABASE packdb")
        return section_count

    def list_sources(self) -> list[str]:
        return [entry["source"] for entry in self.list_sources_with_dates()]

    def get_document_content(self, source: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT content FROM sources WHERE source = ?", (source,)).fetchone()
            return str(row["content"]) if row else None

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
            row_ids = [r["id"] for r in conn.execute("SELECT id FROM sections WHERE source_id = ?", (source_id,))]
            for row_id in row_ids:
                conn.execute("DELETE FROM sections_fts WHERE rowid = ?", (row_id,))
            conn.execute("DELETE FROM sections WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return True

    def delete_all(self) -> bool:
        stats = self.collection_stats()
        with self._connect() as conn:
            conn.execute("DELETE FROM sections_fts")
            conn.execute("DELETE FROM sections")
            conn.execute("DELETE FROM sources")
            conn.execute("DELETE FROM installed_packs")
        return stats["sources_count"] > 0 or stats["sections_count"] > 0
