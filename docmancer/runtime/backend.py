"""Async presentation-independent facade shared by every local interface."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from docmancer.memory.audit import audit_secrets
from docmancer.memory.sources import MemorySourceFilters


class LocalRuntime:
    """Lazily construct and call Docmancer's blocking local services."""

    def __init__(
        self,
        *,
        config_path: str | None = None,
        project_path: str | Path | None = None,
        memory_factory: Callable[[], Any] | None = None,
        docs_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config_path = config_path
        self.project_path = str(Path(project_path or Path.cwd()).expanduser().resolve())
        self._memory_factory = memory_factory
        self._docs_factory = docs_factory
        self.memory: Any | None = None
        self.docs: Any | None = None
        self.service: Any | None = None
        self.ready = False
        self.last_latency = 0.0
        self._docs_source_rows: list[dict] = []
        self._docs_document_cache: dict[str, dict] = {}
        self._audit_source_state: tuple[tuple[str, int, int, int], ...] | None = None
        self._audit_report: dict | None = None
        self.model_label = "local"

    async def initialize(self) -> dict:
        if self.ready:
            return await self.counts()
        self.memory, self.docs = await asyncio.gather(
            asyncio.to_thread(self._make_memory),
            asyncio.to_thread(self._make_docs),
        )
        from docmancer.memory.service import MemoryService

        self.service = MemoryService(self.memory)
        self.ready = True
        embeddings = getattr(getattr(self.memory, "config", None), "embeddings", None)
        self.model_label = str(getattr(embeddings, "provider", None) or getattr(embeddings, "model", None) or "local")
        return await self.counts()

    def _make_memory(self):
        if self._memory_factory is not None:
            return self._memory_factory()
        from docmancer.memory import MemoryAgent

        return MemoryAgent()

    def _make_docs(self):
        if self._docs_factory is not None:
            return self._docs_factory()
        from docmancer.async_agent import AsyncDocmancerAgent
        from docmancer.core.config import DocmancerConfig

        path = Path(self.config_path).expanduser() if self.config_path else Path.home() / ".docmancer" / "docmancer.yaml"
        config = DocmancerConfig.from_yaml(path) if path.is_file() else DocmancerConfig()
        return AsyncDocmancerAgent(config)

    def _require_memory(self):
        if self.memory is None:
            raise RuntimeError("memory backend is still loading")
        return self.memory

    def _require_docs(self):
        if self.docs is None:
            raise RuntimeError("documentation backend is still loading")
        return self.docs

    def _require_service(self):
        if self.service is None:
            from docmancer.memory.service import MemoryService

            self.service = MemoryService(self._require_memory())
        return self.service

    async def counts(self) -> dict:
        memory = self._require_memory()
        docs = self._require_docs()
        memory_status, docs_status = await asyncio.gather(
            asyncio.to_thread(memory.status),
            docs.collection_stats(),
        )
        memory_page, instructions_page = await asyncio.gather(
            asyncio.to_thread(memory.browse_sources, MemorySourceFilters(kinds=("agent-memory", "docmancer-memory", "team-memory")), page=1, page_size=1),
            asyncio.to_thread(memory.browse_sources, MemorySourceFilters(kinds=("instructions", "rules")), page=1, page_size=1),
        )
        return {
            "memory": int(memory_page.total),
            "instructions": int(instructions_page.total),
            "atoms": int(memory_status.get("atoms") or 0),
            "docs": int(docs_status.get("sources_count") or 0),
            "intelligence": int(memory_status.get("conflicts") or 0),
            "context": len(self._require_service().list_context(project_path=self.project_path)),
            "sources": int(memory_page.total) + int(instructions_page.total),
        }

    async def context(self) -> list[dict]:
        service = self._require_service()
        packs = await asyncio.to_thread(service.list_context, project_path=self.project_path)
        proposals = await asyncio.to_thread(service.proposals)
        cloud_conflicts = await asyncio.to_thread(service.cloud_conflicts)
        rows = [dict(pack, view_kind="context-pack", text=pack["rendered"]) for pack in packs]
        pack_order = {
            "personal-defaults": 0,
            "personal-project": 1,
            "team-standards": 2,
            "team-project": 3,
        }
        rows.sort(
            key=lambda row: next(
                (priority for prefix, priority in pack_order.items() if str(row.get("pack_id") or "").startswith(prefix)),
                99,
            )
        )
        record_rows = []
        for pack in packs:
            records = await asyncio.to_thread(
                service.pack_records,
                str(pack["pack_id"]),
                project_path=self.project_path,
            )
            record_rows.extend(
                {
                    "view_kind": "context-record",
                    "id": record.record_id,
                    "record_id": record.record_id,
                    "pack_id": pack["pack_id"],
                    "pack_name": pack["name"],
                    "audience_kind": pack["audience_kind"],
                    "applicability_kind": pack["applicability_kind"],
                    "memory_type": record.type,
                    "text": record.text,
                    "source_path": record.source_path,
                    "origin": record.origin,
                    "updated_at": record.updated_at,
                    "promoted_from": record.promoted_from,
                }
                for record in records
            )
        rows.extend(
            {
                "view_kind": "context-proposal",
                "id": proposal.proposal_id,
                "proposal_id": proposal.proposal_id,
                "pack_id": proposal.pack_id,
                "context_name": next(
                    (str(pack["name"]) for pack in packs if pack["pack_id"] == proposal.pack_id),
                    None,
                ),
                "text": "\n".join(operation.text or str(operation.record_id or "") for operation in proposal.operations),
                "operations": [asdict(operation) for operation in proposal.operations],
            }
            for proposal in proposals
        )
        rows.extend(
            {
                "view_kind": "context-proposal",
                "proposal_kind": "cloud-conflict",
                "id": f"cloud:{conflict['conflict_id']}",
                "proposal_id": f"cloud:{conflict['conflict_id']}",
                "pack_id": "cloud-transport",
                "text": (
                    f"Encrypted sync conflict: {conflict['reason']}\n"
                    f"local={conflict.get('local_revision_id') or '-'} "
                    f"remote={conflict.get('remote_revision_id') or '-'}"
                ),
                "operations": [],
            }
            for conflict in cloud_conflicts
        )
        rows.extend(record_rows)
        return rows

    async def distill_context(self, pack_id: str = "personal-defaults"):
        return await asyncio.to_thread(self._require_service().distill, pack_id, project_path=self.project_path)

    async def review_context(self, proposal_id: str, decision: str, **options):
        if proposal_id.startswith("cloud:"):
            strategy = {"approve": "keep-right", "reject": "keep-left"}.get(decision, decision)
            return await asyncio.to_thread(
                self._require_service().resolve_cloud_conflict,
                proposal_id,
                strategy,
                text=options.get("text"),
            )
        return await asyncio.to_thread(self._require_service().review, proposal_id, decision, **options)

    async def add_context(self, text: str, pack_id: str = "personal-defaults"):
        return await asyncio.to_thread(
            self._require_service().add_canonical,
            text,
            pack_id=pack_id,
            project_path=self.project_path,
        )

    async def share_context(self, pack_id: str = "personal-defaults"):
        return await asyncio.to_thread(self._require_service().share, pack_id, project_path=self.project_path)

    async def edit_context(self, record_id: str, text: str):
        return await asyncio.to_thread(self._require_service().edit_record, record_id, text)

    async def remove_context(self, record_id: str):
        return await asyncio.to_thread(self._require_service().remove_record, record_id)

    async def reset_context(self, audience_kind: str):
        return await asyncio.to_thread(
            self._require_service().reset_context,
            audience_kind,
            project_path=self.project_path,
        )

    @staticmethod
    def _matches_project(row: dict, project_path: str | None) -> bool:
        if not project_path:
            return True
        selected = str(Path(project_path).expanduser().resolve())
        scopes = [str(row.get(key) or "") for key in ("scope", "source_scope", "target_scope")]
        if any(scope.startswith("global:") for scope in scopes):
            return True
        paths = [str(row.get(key) or "") for key in ("project_path", "source_project_path", "target_project_path")]
        return any(path == selected for path in paths if path)

    @staticmethod
    def _group_conflicts(rows: list[dict]) -> list[dict]:
        grouped: dict[tuple[str, str], dict] = {}
        for row in rows:
            evidence = dict(row.get("evidence") or {})
            claim_key = str(evidence.get("claim_key") or row.get("relation_id") or "conflict")
            scope = str(row.get("source_scope") or row.get("target_scope") or "unknown")
            key = (scope, claim_key)
            group = grouped.setdefault(
                key,
                {
                    "view_kind": "intelligence",
                    "intelligence_kind": "conflict-group",
                    "group_id": "claim_" + hashlib.sha256(f"{scope}\n{claim_key}".encode()).hexdigest()[:16],
                    "claim_key": claim_key,
                    "claim_subject": evidence.get("subject") or claim_key.split("|", 1)[0],
                    "scope": scope,
                    "resolution_state": "suggested",
                    "confidence": 0.0,
                    "relation_ids": [],
                    "members": {},
                },
            )
            group["confidence"] = max(float(group["confidence"]), float(row.get("confidence") or 0.0))
            group["relation_ids"].append(str(row.get("relation_id") or ""))
            for side in ("source", "target"):
                identity = str(row.get(f"{side}_node_id") or "")
                group["members"].setdefault(
                    identity,
                    {
                        "node_id": identity,
                        "atom_id": row.get(f"{side}_atom_id"),
                        "text": row.get(f"{side}_text"),
                        "value": evidence.get(f"{side}_value"),
                        "memory_type": row.get(f"{side}_memory_type"),
                        "origin": row.get(f"{side}_origin"),
                    },
                )
        output = []
        for group in grouped.values():
            group["members"] = list(group["members"].values())
            group["relation_ids"] = [value for value in group["relation_ids"] if value]
            output.append(group)
        return sorted(output, key=lambda item: (str(item["scope"]), str(item["claim_subject"])))

    @staticmethod
    def _group_recent_sources(rows: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in rows:
            path = str(row.get("source_path") or row.get("source_title") or row.get("atom_id") or "unknown")
            group = grouped.setdefault(
                path,
                {
                    "view_kind": "intelligence",
                    "intelligence_kind": "recent-source",
                    "source_path": path,
                    "source_title": row.get("source_title") or Path(path).name,
                    "harness": row.get("harness"),
                    "scope": row.get("scope"),
                    "project_path": row.get("project_path"),
                    "activity_at": row.get("activity_at"),
                    "atom_count": 0,
                    "samples": [],
                },
            )
            group["atom_count"] += 1
            if str(row.get("activity_at") or "") > str(group.get("activity_at") or ""):
                group["activity_at"] = row.get("activity_at")
            if len(group["samples"]) < 3:
                group["samples"].append(
                    {
                        "atom_id": row.get("atom_id"),
                        "text": row.get("text"),
                        "memory_type": row.get("memory_type"),
                    }
                )
        return sorted(
            grouped.values(),
            key=lambda item: (str(item.get("activity_at") or ""), str(item.get("source_path") or "")),
            reverse=True,
        )

    async def memory_intelligence(
        self,
        *,
        view: str = "review",
        project_path: str | None = None,
        query: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """Return one paginated, consistently typed Intelligence view."""
        memory = self._require_memory()
        if view == "review":
            conflicts = await asyncio.to_thread(memory.conflicts, unresolved_only=True)
            rows = self._group_conflicts(
                [row for row in conflicts if self._matches_project(row, project_path)]
            )
        elif view == "recent":
            recent = await asyncio.to_thread(
                memory.recent,
                since=datetime.now(timezone.utc) - timedelta(days=7),
                limit=50_000,
            )
            rows = self._group_recent_sources(
                [row for row in recent if self._matches_project(row, project_path)]
            )
        elif view == "maintenance":
            orphans = await asyncio.to_thread(memory.orphans)
            rows = [
                dict(row, view_kind="intelligence", intelligence_kind="orphan")
                for row in orphans
                if self._matches_project(row, project_path)
            ]
        elif view == "history":
            relations = await asyncio.to_thread(memory.relations, None)
            rows = [
                dict(row, view_kind="intelligence", intelligence_kind="history")
                for row in relations
                if row.get("resolution_state") != "suggested" and self._matches_project(row, project_path)
            ]
        else:
            raise ValueError("intelligence view must be review, recent, maintenance, or history")

        if query:
            needle = query.casefold()
            rows = [
                row for row in rows
                if needle in " ".join(str(value) for value in row.values()).casefold()
            ]
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), total_pages)
        start = (page - 1) * page_size
        return {
            "items": rows[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_more": page < total_pages,
            "view": view,
        }

    async def memory_recent(self, since: datetime) -> list[dict]:
        return await asyncio.to_thread(self._require_memory().recent, since=since, limit=200)

    async def ingest_docs(self, path_or_url: str, progress_callback=None) -> int:
        progress = progress_callback or (lambda _name, _data: None)
        progress("prepare", {"detail": f"Resolving {path_or_url}"})
        docs = self._require_docs()
        if path_or_url.startswith(("http://", "https://")):
            progress("fetch", {"detail": "Fetching documentation pages"})
            total = await docs.ingest_url(path_or_url)
        else:
            progress("load", {"detail": "Loading local documentation files"})
            total = await docs.ingest(path_or_url)
        self._docs_source_rows = []
        self._docs_document_cache.clear()
        progress("index", {"detail": f"Indexed {total} document section(s)"})
        return total

    def _config_file(self) -> Path:
        return Path(self.config_path).expanduser() if self.config_path else Path.home() / ".docmancer" / "docmancer.yaml"

    async def capture_settings(self) -> dict[str, bool]:
        return dict(self._require_memory().config.capture.enabled)

    async def save_capture_settings(self, enabled: dict[str, bool]) -> Path:
        import yaml

        path = self._config_file()
        data = {}
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
        data["capture"] = {"enabled": {key: bool(value) for key, value in sorted(enabled.items())}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self._require_memory().config.capture.enabled = dict(enabled)
        return path

    async def consolidate(self, query: str | None, on_event=None) -> str:
        from docmancer.ai.memory_features import draft_to_markdown
        from docmancer.ai.openrouter_client import OpenRouterClient, openrouter_api_key
        from docmancer.memory.consolidation import consolidate_payload

        if not openrouter_api_key():
            raise ValueError("OPENROUTER_API_KEY is not set")
        atoms = self._require_memory().indexed_atoms(limit=100)
        if not atoms:
            raise ValueError("no indexed memory atoms are available")
        payload = [
            {"scope": atom.scope, "title": atom.title, "source_path": atom.source_path, "text": atom.text}
            for atom in atoms
        ]
        client = OpenRouterClient()
        try:
            await asyncio.to_thread(client.preflight)
            draft = await asyncio.to_thread(
                consolidate_payload,
                payload,
                instruction=query,
                client=client,
                model=None,
                budget=24_000,
                draft_quality="standard",
                max_output_tokens=8_000,
                concurrency=2,
                on_event=on_event,
            )
            return draft_to_markdown(draft, source_files=[atom.source_path for atom in atoms])
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    async def apply_memory(self, agent: str, draft: str | None = None) -> Path:
        from docmancer.cli.managed_block import upsert_block
        from docmancer.cli.memory_commands import (
            _APPLY_TARGETS, _MEMORY_BLOCK_BEGIN, _MEMORY_BLOCK_END, _apply_target_path, _render_atoms_for_apply,
        )

        if agent not in _APPLY_TARGETS:
            raise ValueError("unsupported apply target")
        body = draft or _render_atoms_for_apply(self._require_memory().indexed_atoms())
        target = _apply_target_path(agent, None)
        if target is None:
            raise ValueError("could not resolve apply target")
        await asyncio.to_thread(
            upsert_block, target, body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END, backup_policy="foreign-content"
        )
        return target

    async def resolve_memory_conflict(
        self,
        relation_id: str,
        resolution: str,
        *,
        winner: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._require_memory().resolve_relation,
            relation_id,
            resolution,
            winner=winner,
        )

    async def resolve_memory_conflict_group(
        self,
        relation_ids: list[str],
        resolution: str,
        *,
        winner: str | None = None,
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._require_memory().resolve_relation_group,
            relation_ids,
            resolution,
            winner=winner,
        )

    async def browse_memory_sources(
        self,
        *,
        kinds: tuple[str, ...],
        harness: str | None = None,
        scope_kind: str | None = None,
        project_path: str | None = None,
        updated_after: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        filters = MemorySourceFilters(
            kinds=kinds,
            harness=harness,
            scope_kind=scope_kind,
            project_path=project_path,
            updated_after=updated_after,
        )
        result = await asyncio.to_thread(
            self._require_memory().browse_sources,
            filters,
            page=page,
            page_size=page_size,
        )
        return asdict(result)

    async def get_memory_source(self, source_key: str) -> dict | None:
        result = await asyncio.to_thread(self._require_memory().get_indexed_source, source_key)
        return asdict(result) if result is not None else None

    async def get_live_source(self, source_key: str) -> dict:
        return await asyncio.to_thread(self._require_memory().live_source, source_key)

    async def edit_source(self, source_key: str, content: str, *, expected_hash: str) -> dict:
        result = await asyncio.to_thread(
            self._require_memory().edit_source,
            source_key,
            content,
            expected_hash=expected_hash,
        )
        return asdict(result)

    async def delete_source(self, source_key: str, *, expected_hash: str) -> str:
        return await asyncio.to_thread(
            self._require_memory().delete_source,
            source_key,
            expected_hash=expected_hash,
        )

    async def create_source(self, path: str, content: str) -> tuple[str, bool]:
        return await asyncio.to_thread(self._require_memory().create_source, path, content)

    async def search_memory_sources(
        self,
        text: str,
        *,
        kinds: tuple[str, ...],
        mode: str = "hybrid",
        harness: str | None = None,
        scope_kind: str | None = None,
        project_path: str | None = None,
        updated_after: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        filters = MemorySourceFilters(
            kinds=kinds,
            harness=harness,
            scope_kind=scope_kind,
            project_path=project_path,
            updated_after=updated_after,
        )
        started = monotonic()
        result = await asyncio.to_thread(
            self._require_memory().search_sources,
            text,
            filters,
            mode=mode,
            page=page,
            page_size=page_size,
        )
        self.last_latency = monotonic() - started
        return asdict(result)

    @staticmethod
    def _chunk_dict(chunk) -> dict:
        metadata = dict(chunk.metadata or {})
        return {
            "id": str(metadata.get("record_id") or metadata.get("atom_id") or f"{chunk.source}:{chunk.chunk_index}"),
            "text": chunk.text,
            "source": chunk.source,
            "chunk_index": chunk.chunk_index,
            "score": float(chunk.score or 0.0),
            "metadata": metadata,
        }

    async def query_memory(
        self,
        text: str,
        *,
        mode: str = "hybrid",
        scope: str | None = None,
        project_path: str | None = None,
        limit: int = 30,
    ) -> list[dict]:
        started = monotonic()
        chunks = await asyncio.to_thread(
            self._require_memory().query,
            text,
            mode=mode,
            scope=scope,
            project_path=project_path,
            limit=limit,
        )
        self.last_latency = monotonic() - started
        return [self._chunk_dict(chunk) for chunk in chunks]

    async def query_docs(self, text: str, *, expand: str | None = None, limit: int = 30) -> list[dict]:
        started = monotonic()
        chunks = await self._require_docs().query(text, expand=expand, limit=limit)
        self.last_latency = monotonic() - started
        results = [self._chunk_dict(chunk) for chunk in chunks]
        if not self._docs_source_rows:
            await self.docs_sources()
        for result in results:
            source = str(result.get("source") or "")
            matching = [row for row in self._docs_source_rows if source.startswith(str(row.get("source") or ""))]
            if matching:
                row = max(matching, key=lambda item: len(str(item.get("source") or "")))
                result["metadata"].setdefault("ingested_at", row.get("ingested_at"))
        return results

    async def memory_sources(self, *, live_preview: bool = True) -> list[dict]:
        return await asyncio.to_thread(self._require_memory().sources, live_preview=live_preview)

    async def docs_sources(self) -> list[dict]:
        docs = self._require_docs()
        method = getattr(docs, "list_grouped_sources_with_dates", None)
        if method is not None:
            self._docs_source_rows = await method()
            return self._docs_source_rows
        sources = await docs.list_sources()
        self._docs_source_rows = [{"source": source, "pages": 0, "sections": 0} for source in sources]
        return self._docs_source_rows

    def _tree_store(self):
        from docmancer.memory.tree.store import TreeStore

        return TreeStore(Path(self.project_path) / ".docmancer" / "tree")

    def _tree_entry_payload(self, entry, *, include_body: bool = True) -> dict:
        root = self._tree_store().root
        outline = []
        for line_number, line in enumerate(entry.body.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                if 1 <= level <= 6 and stripped[level:].startswith(" "):
                    outline.append({"level": level, "title": stripped[level:].strip(), "line": line_number})
        backlinks = []
        for candidate in self._tree_store().index.entries():
            if candidate.memory_id == entry.memory_id:
                continue
            if any(target in {entry.title, entry.address} for _kind, target in candidate.relations):
                backlinks.append({"address": candidate.address, "title": candidate.title})
        return {
            "address": entry.address,
            "memory_id": entry.memory_id,
            "title": entry.title,
            "path": entry.path.relative_to(root).as_posix(),
            "type": entry.type,
            "scope": entry.scope,
            "authority": entry.authority,
            "project_id": entry.project_id,
            "status": entry.status,
            "tags": list(entry.tags),
            "sources": list(entry.sources),
            "relations": [{"type": kind, "target": target} for kind, target in entry.relations],
            "backlinks": backlinks,
            "outline": outline,
            "content_hash": entry.content_hash,
            "revision_id": entry.revision_id,
            "allowed_actions": ["edit", "move", "duplicate", "trash", "open-editor"],
            **({"markdown": entry.body} if include_body else {}),
        }

    async def tree_root(self) -> dict:
        store = self._tree_store()
        entries = await asyncio.to_thread(store.index.entries)
        return {
            "scope": "project",
            "project_id": hashlib.sha256(self.project_path.encode()).hexdigest()[:16],
            "display_label": Path(self.project_path).name,
            "health": "ready",
            "count": len(entries),
            "allowed_actions": ["create", "reindex", "open-editor"],
        }

    async def tree_list(self) -> list[dict]:
        store = self._tree_store()
        entries = await asyncio.to_thread(store.index.entries)
        return [self._tree_entry_payload(entry, include_body=False) for entry in sorted(entries, key=lambda item: str(item.path))]

    async def tree_read(self, address: str) -> dict:
        entry = await asyncio.to_thread(self._tree_store().read, address)
        return self._tree_entry_payload(entry)

    async def tree_create(self, body: dict) -> dict:
        store = self._tree_store()
        entry = await asyncio.to_thread(
            store.write,
            relative_path=str(body["path"]),
            text=str(body["markdown"]),
            memory_type=str(body.get("type") or "fact"),
            scope="project",
            authority=str(body.get("authority") or "advisory"),
            project_id=str(body.get("project_id") or hashlib.sha256(self.project_path.encode()).hexdigest()[:16]),
            sources=list(body.get("sources") or []),
            tags=list(body.get("tags") or []),
            expect="absent",
        )
        return self._tree_entry_payload(entry)

    async def tree_mutate(self, action: str, body: dict) -> dict:
        store = self._tree_store()
        if action == "reindex":
            count = await asyncio.to_thread(store.rebuild_index)
            from docmancer.memory.tree.dense_index import TreeDenseIndex

            def rebuild_dense() -> dict:
                dense = TreeDenseIndex(store.root)
                try:
                    return dense.sync(store.index.entries())
                finally:
                    dense.close()

            return {"reindexed": count, "dense": await asyncio.to_thread(rebuild_dense)}
        address = str(body["address"])
        expected_hash = str(body.get("expected_hash") or "")
        if action == "edit":
            entry = await asyncio.to_thread(store.edit, address, text=str(body["markdown"]), expected_hash=expected_hash)
            return self._tree_entry_payload(entry)
        if action == "move":
            entry = await asyncio.to_thread(store.move, address, str(body["path"]), expected_hash=expected_hash)
            return self._tree_entry_payload(entry)
        if action == "duplicate":
            entry = await asyncio.to_thread(store.duplicate, address, str(body["path"]), expected_hash=expected_hash)
            return self._tree_entry_payload(entry)
        if action == "trash":
            token = await asyncio.to_thread(store.trash, address, expected_hash=expected_hash, actor_surface="web")
            return {"trashed": True, "restore_token": token}
        if action == "restore":
            entry = await asyncio.to_thread(store.restore, str(body["restore_token"]))
            return self._tree_entry_payload(entry)
        if action == "open-editor":
            entry = await asyncio.to_thread(store.read, address)
            from docmancer.memory.tree.editor import open_in_editor

            return await asyncio.to_thread(
                open_in_editor,
                entry.path,
                line=int(body["line"]) if body.get("line") else None,
                column=int(body["column"]) if body.get("column") else None,
                allowed_root=store.root,
            )
        raise ValueError(f"unsupported tree action {action!r}")

    async def inbox_files(self) -> list[dict]:
        inbox = Path(self.project_path) / ".docmancer" / "inbox"
        if not inbox.is_dir():
            return []
        rows = []
        for path in sorted(inbox.glob("*.md"), key=lambda item: item.stat().st_mtime_ns, reverse=True)[:500]:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            rows.append({
                "id": path.stem,
                "title": next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem),
                "preview": text[:1000],
                "captured_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "redaction_status": "applied",
                "curation_eligible": True,
            })
        return rows

    def _bounded_project_source(self, value: str) -> Path:
        project_root = Path(self.project_path).resolve()
        candidate = (project_root / value).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("source must stay inside the active project") from exc
        if not candidate.exists():
            raise ValueError("source does not exist inside the active project")
        return candidate

    async def harvest_tree(self, source: str, *, apply: bool = False) -> dict:
        """Preview or copy bounded project Markdown into the local inbox."""
        from docmancer.memory.tree.curation import CurationEngine

        candidate = self._bounded_project_source(source)
        files = [candidate] if candidate.is_file() else list(candidate.rglob("*.md"))
        files = sorted(
            path for path in files
            if path.is_file() and path.suffix.lower() == ".md"
            and ".docmancer/tree" not in path.as_posix()
        )[:500]
        before = {path: path.stat().st_mtime_ns for path in files}
        results: list[dict] = []
        engine = CurationEngine(self._tree_store(), Path(self.project_path) / ".docmancer" / "inbox")
        for path in files:
            row = {"source": str(path.relative_to(Path(self.project_path).resolve())), "status": "preview"}
            if apply:
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                if len(text.encode("utf-8")) > 1_000_000:
                    row["status"] = "skipped_too_large"
                else:
                    result = await asyncio.to_thread(engine.curate, text, source_path=path)
                    row.update(status=result.destination, inbox_path=str(result.inbox_path or ""))
            results.append(row)
        if any(path.stat().st_mtime_ns != before[path] for path in files):
            raise ValueError("a harvested source changed during the operation")
        return {"applied": apply, "count": len(results), "results": results}

    async def curate_inbox(self, inbox_id: str, relative_path: str, *, apply: bool = False) -> dict:
        """Preview a complete-file diff, then optionally curate one inbox file."""
        import difflib

        from docmancer.memory.tree.curation import CurationEngine

        if not inbox_id or Path(inbox_id).name != inbox_id:
            raise ValueError("inbox_id must be one inbox filename stem")
        if not relative_path.strip():
            raise ValueError("path is required")
        inbox = Path(self.project_path) / ".docmancer" / "inbox"
        source = inbox / f"{inbox_id}.md"
        if not source.is_file():
            raise ValueError("inbox item was not found")
        text = await asyncio.to_thread(source.read_text, encoding="utf-8")
        diff = "\n".join(difflib.unified_diff([], text.splitlines(), fromfile="/dev/null", tofile=relative_path, lineterm=""))
        payload: dict = {"applied": False, "source": source.name, "destination": relative_path, "diff": diff}
        if apply:
            result = await asyncio.to_thread(
                CurationEngine(self._tree_store(), inbox).curate,
                text,
                relative_path=relative_path,
                scope="project",
                project_id=hashlib.sha256(self.project_path.encode()).hexdigest()[:16],
                source_path=source,
            )
            payload.update(
                applied=True,
                outcome=result.destination,
                address=result.entry.address if result.entry else None,
                reason=result.reason,
            )
        return payload

    async def ask_tree(self, task: str, *, token_budget: int = 2000, agent: str = "web") -> dict:
        from docmancer.memory.tree.compiler import ContextRequest, compile_context

        store = self._tree_store()
        bundle = await asyncio.to_thread(
            compile_context,
            store.index,
            ContextRequest(task=task, project_path=self.project_path, agent=agent, token_budget=token_budget),
        )
        items = list(bundle.mandatory_policies) + list(bundle.curated_memory)
        return {
            "answer": None,
            "no_answer": not bool(items),
            "items": [asdict(item) for item in items],
            "token_estimate": bundle.token_estimate,
            "index_revision": bundle.index_revision,
            "timings": {},
        }

    async def get_docs_source(self, source_root: str) -> dict | None:
        if source_root in self._docs_document_cache:
            return self._docs_document_cache[source_root]
        method = getattr(self._require_docs(), "get_grouped_source_documents", None)
        if method is None:
            return None
        document = await method(source_root)
        if document is not None:
            self._docs_document_cache[source_root] = document
        return document

    async def status(self) -> dict:
        memory = self._require_memory()
        docs = self._require_docs()
        memory_status, docs_status = await asyncio.gather(
            asyncio.to_thread(memory.status),
            docs.collection_stats(),
        )
        return {
            "memory": memory_status,
            "last_sync": await asyncio.to_thread(memory.last_sync_stats),
            "docs": docs_status,
            "project": self.project_path,
            "context": await asyncio.to_thread(self._require_service().status, project_path=self.project_path),
        }

    async def sync(self, progress_callback=None) -> dict:
        return await asyncio.to_thread(
            self._require_service().sync,
            project_path=self.project_path,
            progress_callback=progress_callback,
        )

    async def audit(self) -> dict:
        source_state = await asyncio.to_thread(self._audit_source_signature)
        return await self._audit_for_source_state(source_state)

    async def hook_status(self) -> list[dict]:
        """Inspect automatic-context and capture hooks at user and project scopes."""
        return await asyncio.to_thread(self._hook_status)

    def _hook_status(self) -> list[dict]:
        locations = [
            ("claude-code", "user", Path.home() / ".claude" / "settings.json"),
            ("codex", "user", Path.home() / ".codex" / "hooks.json"),
        ]
        project = Path(self.project_path).expanduser().resolve() if self.project_path else None
        if project is not None:
            locations.extend(
                [
                    ("claude-code", "project", project / ".claude" / "settings.json"),
                    ("codex", "project", project / ".codex" / "hooks.json"),
                ]
            )
        rows = []
        for agent, scope, path in locations:
            data = {}
            error = None
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    error = str(exc)
            blob = json.dumps(data, sort_keys=True)
            hooks = data.get("hooks") if isinstance(data, dict) else {}
            events = sorted(str(event) for event in hooks) if isinstance(hooks, dict) else []
            rows.append(
                {
                    "agent": agent,
                    "scope": scope,
                    "path": str(path),
                    "exists": path.is_file(),
                    "recall": "memory hook-context" in blob,
                    "capture": "memory capture-hook" in blob,
                    "events": events,
                    "error": error,
                }
            )
        return rows

    async def audit_if_changed(self) -> dict | None:
        source_state = await asyncio.to_thread(self._audit_source_signature)
        if self._audit_report is not None and source_state == self._audit_source_state:
            return None
        return await self._audit_for_source_state(source_state)

    async def _audit_for_source_state(self, source_state: tuple[tuple[str, int, int, int], ...]) -> dict:
        entries = await asyncio.to_thread(self._require_memory().preview)
        report = await asyncio.to_thread(audit_secrets, entries)
        self._audit_source_state = source_state
        self._audit_report = report
        return report

    def _audit_source_signature(self) -> tuple[tuple[str, int, int, int], ...]:
        """Describe current source files without reading their contents."""
        memory = self._require_memory()
        state: dict[str, tuple[str, int, int, int]] = {}
        for row in memory.sources(live_preview=False):
            path = Path(str(row.get("path") or "")).expanduser()
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                parent_mtime = path.parent.stat().st_mtime_ns
            except OSError:
                continue
            resolved = str(path.resolve())
            state[resolved] = (resolved, stat.st_mtime_ns, stat.st_size, parent_mtime)
        return tuple(sorted(state.values()))

    async def cloud_status(self) -> dict:
        from docmancer.cli.cloud_commands import cloud_status

        root = Path(self._require_memory().db_path).parent
        return await asyncio.to_thread(cloud_status, root)

    async def cloud_conflicts(self) -> list[dict]:
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.outbox import CloudState

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        return await asyncio.to_thread(CloudState(config.paths.sync_state).conflicts)

    async def cloud_sync(self) -> dict:
        from docmancer.cloud.client import CloudClient
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.keystore import KeyStore
        from docmancer.cloud.sync import sync_once

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        account = config.account()
        keys = KeyStore()
        account_id = str(account.get("account_id") or "")
        token = await asyncio.to_thread(keys.token, account_id)
        if not token or not account.get("base_url") or not account.get("device_id"):
            raise ValueError("cloud session is incomplete; run `docmancer cloud connect`")
        client = CloudClient(
            str(account["base_url"]), token=token.decode("utf-8"),
            device_id=str(account["device_id"]),
            signing_private_key=keys.get(account_id, "device-signing-private"),
        )
        try:
            return await asyncio.to_thread(sync_once, client, root=root, keystore=keys)
        finally:
            await asyncio.to_thread(client.close)

    def _cloud_client(self):
        from docmancer.cloud.client import CloudClient
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.keystore import KeyStore

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        account = config.account()
        keys = KeyStore()
        account_id = str(account.get("account_id") or "")
        token = keys.token(account_id)
        if not token or not account.get("base_url") or not account.get("device_id") or not account.get("workspace_id"):
            raise ValueError("cloud session is incomplete; run `docmancer cloud connect`")
        client = CloudClient(
            str(account["base_url"]), token=token.decode("utf-8"),
            device_id=str(account["device_id"]),
            signing_private_key=keys.get(account_id, "device-signing-private"),
        )
        return client, str(account["workspace_id"])

    async def cloud_devices(self) -> list[dict]:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            value = await asyncio.to_thread(client.devices, workspace_id)
            return list(value.get("devices") or [])
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_approve_device(self, device_id: str, fingerprint: str) -> dict:
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.crypto import b64decode, b64encode, wrap_key
        from docmancer.cloud.keystore import KeyStore

        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            rows = list((await asyncio.to_thread(client.devices, workspace_id)).get("devices") or [])
            target = next(
                (row for row in rows if str(row.get("device_id") or row.get("id")) == device_id),
                None,
            )
            if not target or str(target.get("state")) != "pending":
                raise ValueError("pending device not found")
            if str(target.get("fingerprint")) != fingerprint:
                raise ValueError("device fingerprint does not match")
            box_public = target.get("box_public_key") or target.get("box_pubkey")
            if not box_public:
                raise ValueError("pending device has no box public key")
            root = Path(self._require_memory().db_path).parent
            config = CloudConfig(root)
            account = config.account()
            current = config.workspace(workspace_id)
            key_version = int((current[1] if current else {}).get("key_version") or 1)
            workspace_key = KeyStore().workspace_key(
                str(account["account_id"]), workspace_id, key_version,
            )
            if not workspace_key:
                raise ValueError("the current workspace key is unavailable on this device")
            return await asyncio.to_thread(
                client.approve_device,
                workspace_id,
                device_id,
                {
                    "wrapped_key": b64encode(wrap_key(workspace_key, b64decode(str(box_public)))),
                    "key_version": key_version,
                },
            )
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_revoke_device(self, device_id: str) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(client.revoke_device, workspace_id, device_id)
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_members(self) -> list[dict]:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            value = await asyncio.to_thread(client.members, workspace_id)
            return list(value.get("members") or [])
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_invite_member(self, email: str, role: str) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(
                client.invite_member, workspace_id, {"email": email, "role": role},
            )
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_policy(self) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(client.policy, workspace_id)
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_update_policy(self, policy_version: int, policy: dict) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(
                client.update_policy,
                workspace_id,
                {"policy_version": policy_version, "policy": policy},
            )
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_request_export(self) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(client.request_export, workspace_id)
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_delete_remote(self, confirmation: str) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(client.delete_remote, workspace_id, confirmation)
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_promotions(self) -> list[dict]:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            value = await asyncio.to_thread(client.promotion_proposals, workspace_id)
            return list(value.get("proposals") or [])
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_review_promotion(self, proposal_id: str, decision: str, *, text: str | None = None) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            payload = {"decision": decision}
            if text is not None:
                payload["text"] = text
            return await asyncio.to_thread(client.review_promotion, workspace_id, proposal_id, payload)
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_verify_recovery(self, key: str) -> None:
        import json
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.keystore import KeyStore
        from docmancer.cloud.recovery import verify_recovery

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        account = config.account()
        path = config.paths.root / "recovery-wrapper.json"
        if not path.is_file():
            raise ValueError("recovery wrapper is not cached on this device; use the CLI to download and verify it")
        workspace_key = await asyncio.to_thread(verify_recovery, key, json.loads(path.read_text(encoding="utf-8")), root=root)
        workspace = config.workspace(str(account["workspace_id"]))
        key_version = int((workspace[1] if workspace else {}).get("key_version") or 1)
        await asyncio.to_thread(KeyStore().set_workspace_key, str(account["account_id"]), str(account["workspace_id"]), workspace_key, key_version)

    async def cloud_report_audit(self) -> dict | None:
        from docmancer.cloud.audit import risk_metadata

        report = await self.audit_if_changed()
        if report is None:
            return None
        metadata = risk_metadata(report)
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            await asyncio.to_thread(client.report_audit_risk, workspace_id, metadata)
        finally:
            await asyncio.to_thread(client.close)
        return metadata

    async def cloud_resolve(self, conflict_id: int, strategy: str, *, text: str | None = None) -> dict:
        from docmancer.cloud.apply import resolve_conflict

        root = Path(self._require_memory().db_path).parent
        value = await asyncio.to_thread(resolve_conflict, conflict_id, strategy, root=root, text=text)
        await asyncio.to_thread(self._require_memory().sync)
        return value

    async def add(self, text: str, *, scope_kind: str = "global"):
        return await asyncio.to_thread(
            self._require_memory().add_record,
            text,
            scope_kind=scope_kind,
            project_path=self.project_path if scope_kind != "global" else None,
        )

    async def find_atom(self, identifier: str):
        return await asyncio.to_thread(self._require_memory().find_atom, identifier)

    async def edit(self, identifier: str, text: str):
        return await asyncio.to_thread(self._require_memory().edit_record, identifier, text)

    async def forget(self, identifier: str):
        return await asyncio.to_thread(self._require_memory().forget, identifier)

    async def promote(self, identifier: str):
        return await asyncio.to_thread(
            self._require_memory().promote,
            identifier,
            project_path=self.project_path,
        )

    async def clear_memory(self) -> list[Path]:
        return await asyncio.to_thread(self._require_memory().clear)

    async def doctor(self) -> dict:
        status = await self.status()
        config = Path(self.config_path).expanduser() if self.config_path else Path.home() / ".docmancer" / "docmancer.yaml"
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "terminal": os.getenv("TERM") or "unknown",
            "config": str(config),
            "config_exists": config.is_file(),
            "memory_db": status["memory"].get("db_path"),
            "memory_atoms": status["memory"].get("atoms", 0),
            "docs_sections": status["docs"].get("sections_count", 0),
        }


TuiBackend = LocalRuntime

__all__ = ["LocalRuntime", "TuiBackend"]
