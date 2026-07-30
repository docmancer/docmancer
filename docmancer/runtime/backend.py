"""Async presentation-independent facade shared by every local interface."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import sys
import threading
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
        self._library_catalog_instance: Any | None = None
        self._library_rebuild_task: asyncio.Task | None = None
        self._library_rebuild_error: str | None = None
        self._library_bootstrap_checked = False
        self._library_rebuild_started_at: str | None = None
        self._library_rebuild_finished_at: str | None = None
        self._memory_refresh_task: asyncio.Task | None = None
        self._memory_refresh_error: str | None = None
        self._memory_refresh_started_at: str | None = None
        self._memory_refresh_finished_at: str | None = None
        self._memory_refreshed = False
        self._tree_store_instance: Any | None = None
        self._shared_memory_cache: dict | None = None
        self._shared_memory_cache_at = 0.0
        self._shared_memory_refresh_task: asyncio.Task | None = None
        self._delivery_cache: list[dict] | None = None
        self._delivery_cache_at = 0.0
        self._provider_model_refresh_tasks: dict[str, asyncio.Task] = {}
        self.model_label = "local"
        self.initializing = False
        self.initialization_error: str | None = None
        self.initialized_at: str | None = None

    async def initialize(self) -> dict:
        if self.ready:
            return {"ready": True}
        self.initializing = True
        self.initialization_error = None
        try:
            self.memory, self.docs = await asyncio.gather(
                asyncio.to_thread(self._make_memory),
                asyncio.to_thread(self._make_docs),
            )
            from docmancer.memory.service import MemoryService

            self.service = MemoryService(self.memory)
            self.ready = True
            self.initialized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            embeddings = getattr(getattr(self.memory, "config", None), "embeddings", None)
            self.model_label = str(getattr(embeddings, "provider", None) or getattr(embeddings, "model", None) or "local")
            # Counts are presentation data, not a readiness prerequisite.
            return {"ready": True}
        except Exception as exc:
            self.initialization_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.initializing = False

    def readiness(self) -> dict:
        """Report startup state without constructing a backend or reading an index."""
        return {
            "ready": self.ready,
            "initializing": self.initializing,
            "error": self.initialization_error,
            "initialized_at": self.initialized_at,
            "memory_refresh": self.memory_refresh_status(),
            "library_index": self.library_index_status(),
        }

    def schedule_memory_refresh(self) -> asyncio.Task | None:
        """Queue a non-blocking evidence-index refresh for the local web app.

        Canonical synthesis and generated-artifact maintenance are
        intentionally not part of this task. The web app serves the latest
        committed index immediately.
        """
        if self._memory_refresh_task is not None and not self._memory_refresh_task.done():
            return self._memory_refresh_task

        async def refresh() -> None:
            self._memory_refresh_started_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            self._memory_refresh_error = None
            try:
                from docmancer.memory.laptop import migrate_canonical_scaffold

                await asyncio.to_thread(migrate_canonical_scaffold)
                self._memory_refreshed = bool(
                    await asyncio.to_thread(self._require_memory().refresh_if_changed)
                )
            except Exception as exc:  # noqa: BLE001 - keep the last committed index usable
                self._memory_refresh_error = f"{type(exc).__name__}: {exc}"
            finally:
                self._memory_refresh_finished_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )
                self._schedule_shared_memory_refresh()
                self._schedule_library_rebuild()

        self._memory_refresh_task = asyncio.create_task(
            refresh(), name="docmancer-memory-refresh"
        )
        return self._memory_refresh_task

    def memory_refresh_status(self) -> dict:
        task = self._memory_refresh_task
        return {
            "running": bool(task is not None and not task.done()),
            "refreshed": self._memory_refreshed,
            "started_at": self._memory_refresh_started_at,
            "finished_at": self._memory_refresh_finished_at,
            "error": self._memory_refresh_error,
        }

    def library_index_status(self) -> dict:
        task = self._library_rebuild_task
        return {
            "running": bool(task is not None and not task.done()),
            "started_at": self._library_rebuild_started_at,
            "finished_at": self._library_rebuild_finished_at,
            "error": self._library_rebuild_error,
        }

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
        memory_status, docs_status, source_rows = await asyncio.gather(
            asyncio.to_thread(memory.status),
            docs.collection_stats(),
            asyncio.to_thread(memory.sources, live_preview=False),
        )
        memory_kinds = {"agent-memory", "docmancer-memory", "team-memory"}
        instruction_kinds = {"instructions", "rules"}
        memory_count = sum(1 for row in source_rows if str(row.get("type") or "") in memory_kinds)
        instruction_count = sum(1 for row in source_rows if str(row.get("type") or "") in instruction_kinds)
        return {
            "memory": memory_count,
            "instructions": instruction_count,
            "atoms": int(memory_status.get("atoms") or 0),
            "docs": int(docs_status.get("sources_count") or 0),
            "intelligence": int(memory_status.get("conflicts") or 0),
            "context": len(self._require_service().list_context(project_path=self.project_path)),
            "sources": memory_count + instruction_count,
        }

    def _reconciler(self):
        from docmancer.memory.laptop import LaptopMemoryReconciler

        return LaptopMemoryReconciler(self._require_memory())

    async def canonical_status(self) -> dict:
        """Status of every canonical section. Never calls a provider."""
        return await asyncio.to_thread(self._reconciler().status)

    async def canonical_section(self, section: str) -> dict:
        return await asyncio.to_thread(self._reconciler().read_section, section)

    async def canonical_set_pinned(self, section: str, pinned: str, expect: str | None) -> dict:
        """Replace one section's pinned zone. The generated zone is untouched."""
        return await asyncio.to_thread(
            lambda: self._reconciler().set_pinned(section, pinned, expect=expect)
        )

    async def canonical_refresh(self, *, deterministic: bool = False) -> dict:
        return await asyncio.to_thread(
            lambda: self._reconciler().reconcile(use_provider=not deterministic, force=True)
        )

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

    async def common_memory(self) -> list[dict]:
        return await asyncio.to_thread(
            self._require_memory().common_memory,
            project_path=self.project_path,
        )

    async def context_delivery(self) -> list[dict]:
        if self._delivery_cache is not None and monotonic() - self._delivery_cache_at < 30:
            return self._delivery_cache
        setup = await self.agent_setup_plan()
        result = [
            {
                **item,
                "agent": item["id"],
                "status": "delivered" if item.get("last_successful_recall") else "not-observed",
            }
            for item in setup["items"]
        ]
        self._delivery_cache = result
        self._delivery_cache_at = monotonic()
        return result

    @staticmethod
    def _scaffold_folders(paths: list[str], required: tuple[str, ...]) -> list[dict]:
        folders = set(required)
        for value in paths:
            parts = Path(value).parts[:-1]
            folders.update(
                Path(*parts[:index]).as_posix()
                for index in range(1, len(parts) + 1)
            )
        return [
            {
                "path": path,
                "name": Path(path).name,
                "parent": Path(path).parent.as_posix()
                if Path(path).parent.as_posix() != "."
                else "",
            }
            for path in sorted(folders)
        ]

    def _invalidate_shared_memory_cache(self) -> None:
        self._shared_memory_cache = None
        self._shared_memory_cache_at = 0.0

    def _schedule_shared_memory_refresh(self) -> None:
        if self._shared_memory_refresh_task and not self._shared_memory_refresh_task.done():
            return

        async def refresh() -> None:
            try:
                result = await self._build_shared_memory()
                self._shared_memory_cache = result
                self._shared_memory_cache_at = monotonic()
            except Exception:
                # Keep serving the last valid snapshot.
                return

        self._shared_memory_refresh_task = asyncio.create_task(
            refresh(), name="docmancer-shared-memory-refresh"
        )

    async def shared_memory(self) -> dict:
        """Serve the last tree snapshot immediately and refresh it in place."""
        if self._shared_memory_cache is not None:
            if monotonic() - self._shared_memory_cache_at > 10:
                self._schedule_shared_memory_refresh()
            return self._shared_memory_cache
        result = await self._build_shared_memory()
        self._shared_memory_cache = result
        self._shared_memory_cache_at = monotonic()
        return result

    async def _build_shared_memory(self) -> dict:
        """Return both canonical trees as compact filesystem metadata."""
        from docmancer.memory.laptop import laptop_memory_root
        from docmancer.memory.tree.project import PROJECT_SCAFFOLD_FOLDERS
        from docmancer.memory.tree.store import TreeStore

        machine_store = TreeStore(laptop_memory_root() / "tree")
        project_store = self._tree_store()
        machine_entries, project_entries = await asyncio.gather(
            asyncio.to_thread(machine_store.index.entries),
            asyncio.to_thread(project_store.index.entries),
        )

        legacy_count = sum(
            1
            for entry in machine_entries
            if str(entry.path.relative_to(machine_store.root)).startswith("context/")
        )
        migrated_destinations = {
            relative
            for relative in (
                "profile/about.md",
                "profile/preferences.md",
                "principles/working-style.md",
                "projects/active.md",
                "README.md",
            )
            if (machine_store.root / relative).is_file()
        }
        legacy_names = {
            "about.md": "profile/about.md",
            "preferences.md": "profile/preferences.md",
            "working-principles.md": "principles/working-style.md",
            "active-projects.md": "projects/active.md",
            "canonical-memory.md": "README.md",
        }
        machine_entries = [
            entry
            for entry in machine_entries
            if not str(entry.path.relative_to(machine_store.root)).startswith("context/")
            and not (
                entry.path.parent == machine_store.root
                and legacy_names.get(entry.path.name) in migrated_destinations
            )
        ]

        def root_payload(store, entries, *, key: str, label: str, folders: tuple[str, ...]):
            paths = [entry.path.relative_to(store.root).as_posix() for entry in entries]
            return {
                "key": key,
                "label": label,
                "path": str(store.root),
                "count": len(entries),
                "folders": self._scaffold_folders(paths, folders),
                "files": [
                    {
                        **self._tree_entry_payload(
                            entry,
                            include_body=False,
                            backlinks=self._tree_backlinks(entries),
                            root=store.root,
                        ),
                        "root": key,
                        "path": entry.path.relative_to(store.root).as_posix(),
                    }
                    for entry in sorted(entries, key=lambda item: str(item.path))
                ],
            }

        return {
            "scaffold_version": 1,
            "roots": [
                root_payload(
                    machine_store,
                    machine_entries,
                    key="machine",
                    label="This machine",
                    folders=("profile", "principles", "projects", "shared"),
                ),
                root_payload(
                    project_store,
                    project_entries,
                    key="project",
                    label=Path(self.project_path).name,
                    folders=PROJECT_SCAFFOLD_FOLDERS,
                ),
            ],
            "legacy_generated_files": legacy_count,
        }

    async def shared_memory_read(self, address: str) -> dict:
        from docmancer.memory.laptop import laptop_memory_root
        from docmancer.memory.tree.store import TreeStore

        for key, store in (
            ("project", self._tree_store()),
            ("machine", TreeStore(laptop_memory_root() / "tree")),
        ):
            entries = await asyncio.to_thread(store.index.entries)
            entry = next((item for item in entries if item.address == address), None)
            if entry is not None:
                return {
                    **self._tree_entry_payload(
                        entry,
                        backlinks=self._tree_backlinks(entries),
                        root=store.root,
                    ),
                    "root": key,
                    "path": entry.path.relative_to(store.root).as_posix(),
                }
        from docmancer.memory.tree.errors import AddressNotFoundError

        raise AddressNotFoundError(address)

    async def agent_projection(self, agent: str, *, token_budget: int = 2_000) -> dict:
        from docmancer.mcp.tree_tools import context_projection

        return await asyncio.to_thread(
            context_projection,
            agent=agent,
            project_path=self.project_path,
            token_budget=token_budget,
        )

    async def _raw_context_delivery(self) -> list[dict]:
        from docmancer.memory.delivery import delivery_matrix
        from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

        hooks = await self.hook_status()
        projections = {
            agent: str(projection_path(agent))
            for agent in PROJECTION_TARGETS
            if projection_path(agent).is_file()
        }
        return delivery_matrix(
            self.project_path,
            hook_rows=hooks,
            projections=projections,
        )

    async def decision_journal(
        self,
        *,
        file_id: str | None = None,
        operation: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        from docmancer.memory.tree.journal import DecisionJournal

        return await asyncio.to_thread(
            DecisionJournal(self._tree_store().root).events,
            file_id=file_id,
            operation=operation,
            limit=limit,
        )

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
        self._schedule_library_rebuild()
        return total

    def _config_file(self) -> Path:
        return Path(self.config_path).expanduser() if self.config_path else Path.home() / ".docmancer" / "docmancer.yaml"

    async def capture_settings(self) -> dict[str, bool]:
        return dict(self._require_memory().config.capture.enabled)

    async def save_capture_settings(self, enabled: dict[str, bool]) -> Path:
        import os
        import tempfile
        import yaml
        from filelock import FileLock

        path = self._config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path) + ".lock", timeout=10)
        temporary: Path | None = None
        with lock:
            data = {}
            if path.is_file():
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    data = loaded
            data["capture"] = {
                "enabled": {key: bool(value) for key, value in sorted(enabled.items())}
            }
            content = yaml.safe_dump(data, sort_keys=False)
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary = Path(handle.name)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        self._require_memory().config.capture.enabled = dict(enabled)
        return path

    async def provider_catalog(self) -> list[dict]:
        from docmancer.ai.providers.catalog import PROVIDERS
        from docmancer.ai.providers.factory import provider_status

        config = self._require_memory().config.providers
        return await asyncio.to_thread(
            lambda: [provider_status(spec.id, config=config) for spec in PROVIDERS]
        )

    def _provider_model_cache_path(self) -> Path:
        return Path(self.project_path) / ".docmancer" / "index" / "provider-models.json"

    @staticmethod
    def _generation_model(model_id: str) -> bool:
        lowered = model_id.casefold()
        excluded = (
            "embedding", "embed-", "moderation", "whisper", "transcri",
            "tts", "speech", "dall-e", "image", "rerank", "reranker",
            "guard", "safety", "vision-embedding",
        )
        return bool(model_id.strip()) and not any(token in lowered for token in excluded)

    @staticmethod
    def _fallback_provider_models(provider_id: str) -> list[str]:
        return {
            "openrouter": [
                "openai/gpt-5-mini", "anthropic/claude-sonnet-4.5",
                "google/gemini-2.5-flash", "openai/gpt-4.1-mini",
            ],
            "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4.1"],
            "anthropic": [
                "claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-3-5",
            ],
            "google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
            "groq": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"],
            "deepseek": ["deepseek-chat", "deepseek-reasoner"],
            "xai": ["grok-3-mini", "grok-3", "grok-4"],
            "cohere": ["command-a-03-2025", "command-r-plus-08-2024", "command-r-08-2024"],
            "ollama": ["llama3.2", "qwen3", "gemma3"],
        }.get(provider_id, [])

    def _read_provider_model_cache(self) -> dict:
        path = self._provider_model_cache_path()
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_provider_model_cache(self, value: dict) -> None:
        path = self._provider_model_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _discover_provider_models(self, provider_id: str) -> list[str]:
        import httpx

        from docmancer.ai.providers.catalog import get_provider
        from docmancer.ai.providers.credentials import resolve_credential

        spec = get_provider(provider_id)
        config = self._require_memory().config.providers
        credential = resolve_credential(spec)
        if spec.auth_kind == "api_key" and not credential.value:
            raise ValueError(f"{spec.label} needs a configured key before its live model catalog can be loaded")
        base_url = str(config.base_urls.get(provider_id) or spec.base_url)
        for suffix in ("/chat/completions", "/messages", "/chat"):
            if base_url.endswith(suffix):
                models_url = base_url[: -len(suffix)] + "/models"
                break
        else:
            models_url = base_url.rstrip("/") + "/models"
        headers = {"Accept": "application/json"}
        if credential.value:
            if provider_id == "anthropic":
                headers.update({
                    "x-api-key": credential.value,
                    "anthropic-version": "2023-06-01",
                })
            else:
                headers["Authorization"] = f"Bearer {credential.value}"
        with httpx.Client(timeout=20.0) as client:
            response = client.get(models_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        raw_items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list) and isinstance(payload, dict):
            raw_items = payload.get("models")
        if not isinstance(raw_items, list):
            raise ValueError(f"{spec.label} returned an unsupported model catalog")
        model_ids = []
        for item in raw_items:
            if isinstance(item, str):
                model_id = item
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("name") or "")
                if model_id.startswith("models/"):
                    model_id = model_id.split("/", 1)[1]
            else:
                continue
            if self._generation_model(model_id):
                model_ids.append(model_id)
        if not model_ids:
            raise ValueError(f"{spec.label} returned no generation models")
        return sorted(set(model_ids), key=str.casefold)

    async def provider_models(self, provider_id: str, *, refresh: bool = False) -> dict:
        """Return a searchable generation-model catalog with stale fallback."""
        from docmancer.ai.providers.catalog import get_provider
        from docmancer.ai.providers.factory import provider_status

        spec = get_provider(provider_id)
        config = self._require_memory().config.providers
        status = provider_status(provider_id, config=config)
        configured = config.models.get(provider_id)
        cache = await asyncio.to_thread(self._read_provider_model_cache)
        cached = cache.get(provider_id) if isinstance(cache.get(provider_id), dict) else {}
        cached_items = [
            str(item) for item in cached.get("items", [])
            if isinstance(item, str) and self._generation_model(item)
        ]
        fetched_at = str(cached.get("fetched_at") or "")
        fresh = False
        if fetched_at:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
                fresh = age < timedelta(hours=1)
            except ValueError:
                fresh = False

        error = ""
        live_items: list[str] = []
        should_fetch = refresh or not fresh
        if should_fetch:
            try:
                live_items = await asyncio.to_thread(self._discover_provider_models, provider_id)
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                cache[provider_id] = {"items": live_items, "fetched_at": fetched_at}
                await asyncio.to_thread(self._write_provider_model_cache, cache)
            except Exception as exc:
                error = str(exc)
        source_items = live_items or cached_items or self._fallback_provider_models(provider_id)
        ordered = list(dict.fromkeys(
            item for item in [configured, spec.default_model, *source_items]
            if item and self._generation_model(str(item))
        ))
        preferred = {value for value in (configured, spec.default_model) if value}
        records = [
            {
                "id": model_id,
                "label": model_id,
                "source": "configured" if model_id == configured else "recommended" if model_id in preferred else "provider",
            }
            for model_id in ordered[:2]
        ]
        existing = {str(item["id"]) for item in records}
        records.extend(
            {"id": model_id, "label": model_id, "source": "provider" if live_items or cached_items else "fallback"}
            for model_id in sorted(ordered, key=str.casefold)
            if model_id not in existing
        )
        return {
            "provider": provider_id,
            "source": spec.models_source,
            "items": records,
            "state": "ready" if live_items or fresh else "stale" if cached_items else "fallback",
            "fetched_at": fetched_at,
            "stale": bool(cached_items and not fresh and not live_items),
            "refresh_error": error,
            "provider_ready": str(status.get("key_state") or "") != "missing",
        }

    async def provider_key(
        self,
        provider_id: str,
        value: str,
        *,
        validate: bool = False,
    ) -> dict:
        from docmancer.ai.providers.catalog import get_provider
        from docmancer.ai.providers.credentials import ProviderKeyStore
        from docmancer.ai.providers.factory import provider_client, provider_status

        spec = get_provider(provider_id)
        if spec.auth_kind != "api_key":
            raise ValueError(f"{spec.label} does not use an API key")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("key cannot be empty")
        if validate:
            client = provider_client(
                provider_id,
                config=self._require_memory().config.providers,
                api_key_override=cleaned,
            )
            await asyncio.to_thread(client.preflight)
        store = ProviderKeyStore()
        await asyncio.to_thread(store.set, provider_id, cleaned)
        return provider_status(
            provider_id,
            config=self._require_memory().config.providers,
            store=store,
        )

    async def remove_provider_key(self, provider_id: str) -> dict:
        from docmancer.ai.providers.credentials import ProviderKeyStore
        from docmancer.ai.providers.factory import provider_status

        store = ProviderKeyStore()
        await asyncio.to_thread(store.delete, provider_id)
        return provider_status(
            provider_id,
            config=self._require_memory().config.providers,
            store=store,
        )

    async def test_provider(self, provider_id: str) -> dict:
        from docmancer.ai.providers.factory import provider_client

        client = provider_client(
            provider_id,
            config=self._require_memory().config.providers,
        )
        await asyncio.to_thread(client.preflight)
        return {
            "ready": True,
            "provider": provider_id,
            "model": client.model,
        }

    async def ai_defaults(self) -> dict:
        config = self._require_memory().config.providers
        return {
            "default_llm": config.default_llm,
            "models": dict(config.models),
            "base_urls": dict(config.base_urls),
            "preference": config.preference,
            "output_mode": config.output_mode,
            "generation": {
                key: item.model_dump()
                for key, item in config.generation.items()
            },
        }

    async def save_ai_defaults(self, value: dict) -> Path:
        from docmancer.ai.providers.catalog import get_provider
        from docmancer.cli.provider_commands import _atomic_update

        provider_id = str(value.get("default_llm") or "").strip()
        if provider_id:
            get_provider(provider_id)
        output_mode = str(value.get("output_mode") or "normal")
        if output_mode not in {"concise", "normal", "thorough"}:
            raise ValueError("output_mode must be concise, normal, or thorough")
        preference = str(value.get("preference") or "")
        models = value.get("models") or {}
        base_urls = value.get("base_urls") or {}
        if not isinstance(models, dict) or not isinstance(base_urls, dict):
            raise ValueError("models and base_urls must be objects")
        path = self._config_file()

        def transform(data: dict) -> None:
            providers = data.setdefault("providers", {})
            providers.update({
                "default_llm": provider_id or "openrouter",
                "models": {str(key): str(item) for key, item in models.items()},
                "base_urls": {str(key): str(item) for key, item in base_urls.items()},
                "preference": preference,
                "output_mode": output_mode,
            })

        await asyncio.to_thread(_atomic_update, path, transform)
        config = self._require_memory().config.providers
        config.default_llm = provider_id or "openrouter"
        config.models = {str(key): str(item) for key, item in models.items()}
        config.base_urls = {str(key): str(item) for key, item in base_urls.items()}
        config.preference = preference
        config.output_mode = output_mode
        return path

    async def agent_settings(self) -> dict:
        """Return the one human-facing Docmancer agent configuration."""
        defaults = await self.ai_defaults()
        path = self._config_file()
        data: dict[str, Any] = {}
        if path.is_file():
            import yaml

            loaded = await asyncio.to_thread(yaml.safe_load, path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("agent"), dict):
                data = dict(loaded["agent"])
        generation = defaults.get("generation", {})
        selected = str(defaults.get("default_llm") or "openrouter")
        selected_generation = generation.get("ask", {}) if isinstance(generation, dict) else {}
        return {
            "name": "Docmancer",
            "instructions": str(data.get("instructions") or defaults.get("preference") or (
                "Help me understand what my coding agents know, preserve source attribution, "
                "and carry useful context safely between agents. Be direct, practical, and honest "
                "about uncertainty."
            )),
            "provider": selected,
            "model": defaults.get("models", {}).get(selected),
            "output_mode": str(data.get("output_mode") or defaults.get("output_mode") or "normal"),
            "reasoning_effort": str(data.get("reasoning_effort") or "medium"),
            "max_output_tokens": int(data.get("max_output_tokens") or selected_generation.get("max_output_tokens") or 4096),
            "context_budget": int(data.get("context_budget") or 12000),
            "top_p": float(data.get("top_p") or selected_generation.get("top_p") or 0.95),
            "safeguards": [
                "Source attribution stays visible.",
                "Sensitive findings are masked before display.",
                "Destructive changes require explicit confirmation.",
                "Local data stays on this machine unless you enable encrypted sync.",
            ],
        }

    async def save_agent_settings(self, value: dict) -> Path:
        from docmancer.cli.provider_commands import _atomic_update

        instructions = str(value.get("instructions") or "").strip()
        if not instructions:
            raise ValueError("agent instructions cannot be empty")
        effort = str(value.get("reasoning_effort") or "medium")
        if effort not in {"low", "medium", "high"}:
            raise ValueError("reasoning_effort must be low, medium, or high")
        max_output = max(256, min(65536, int(value.get("max_output_tokens") or 4096)))
        context_budget = max(1000, min(1000000, int(value.get("context_budget") or 12000)))
        top_p = max(0.01, min(1.0, float(value.get("top_p") or 0.95)))
        output_mode = str(value.get("output_mode") or "normal")
        if output_mode not in {"concise", "normal", "thorough"}:
            raise ValueError("output_mode must be concise, normal, or thorough")
        path = self._config_file()

        def transform(data: dict) -> None:
            data["agent"] = {
                "instructions": instructions,
                "reasoning_effort": effort,
                "max_output_tokens": max_output,
                "context_budget": context_budget,
                "top_p": top_p,
                "output_mode": output_mode,
            }
            providers = data.setdefault("providers", {})
            providers["preference"] = instructions
            providers["output_mode"] = output_mode
            generation = providers.setdefault("generation", {})
            ask = generation.setdefault("ask", {})
            ask.update({
                "reasoning_effort": effort,
                "max_output_tokens": max_output,
                "top_p": top_p,
            })

        await asyncio.to_thread(_atomic_update, path, transform)
        config = self._require_memory().config.providers
        config.preference = instructions
        config.output_mode = output_mode
        from docmancer.core.config import GenerationRoleConfig

        config.generation["ask"] = GenerationRoleConfig(
            reasoning_effort=effort,
            max_output_tokens=max_output,
            top_p=top_p,
        )
        return path

    async def agent_setup_plan(self) -> dict:
        from docmancer.cli.commands import _detect_setup_targets
        from docmancer.harness.integration_status import inspect_integrations
        from docmancer.harness.setup_plan import build_setup_confirmation

        detected, hooks, deliveries = await asyncio.gather(
            asyncio.to_thread(_detect_setup_targets),
            self.hook_status(),
            self._raw_context_delivery(),
        )
        items = await asyncio.to_thread(
            inspect_integrations,
            detected_targets=detected,
            hook_rows=hooks,
            delivery_rows=deliveries,
        )
        recommended = [
            str(item["id"])
            for item in items
            if item["detected"] and item.get("action_kind") == "automatic"
        ]
        return {
            "items": items,
            "recommended": recommended,
            "confirmation": build_setup_confirmation(
                recommended,
                index_memory=True,
                recall_hooks=True,
                capture_hooks=True,
            ),
            "commands": {
                "setup": "docmancer setup --yes",
                "all": "docmancer setup --all --yes",
                "context_preview": "docmancer context refresh --dry-run",
                "context_build": "docmancer context refresh",
            },
        }

    async def run_agent_setup(
        self,
        targets: list[str],
        *,
        capture_hooks: bool = True,
        confirmed: bool = False,
        progress_callback=None,
    ) -> dict:
        from docmancer.cli.commands import INSTALL_TARGETS
        from docmancer.harness.setup_plan import build_setup_confirmation, normalize_setup_targets

        progress = progress_callback or (lambda _name, _data: None)
        selected = normalize_setup_targets(targets)
        unknown = [item for item in selected if item not in INSTALL_TARGETS]
        if unknown:
            raise ValueError(f"unsupported agent integration: {', '.join(unknown)}")
        if not selected:
            raise ValueError("select at least one coding agent")
        if not confirmed:
            raise ValueError("setup confirmation is required")
        confirmation = build_setup_confirmation(
            selected,
            index_memory=True,
            recall_hooks=True,
            capture_hooks=capture_hooks,
        )

        async def run(args: list[str], label: str) -> str:
            progress("setup", {"detail": label})
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "docmancer",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await process.communicate()
            text = output.decode("utf-8", errors="replace")
            if process.returncode:
                raise RuntimeError(text.strip() or f"{label} failed")
            return text

        setup_args = ["setup", "--yes"]
        for target in selected:
            setup_args.extend(["--agent", target])
        setup_args.append("--capture-hooks")
        if self.config_path:
            setup_args.extend(["--config", str(self.config_path)])
        output = [await run(setup_args, "Indexing memory and installing Docmancer skills")]
        progress("done", {"detail": "Docmancer is connected to the selected agents"})
        verified = await self.agent_setup_plan()
        selected_families = {
            "codex" if target in {"codex", "codex-app", "codex-desktop"} else target
            for target in selected
        }
        selected_states = [
            item for item in verified["items"]
            if str(item["id"]) in selected_families
        ]
        self._delivery_cache = None
        self._delivery_cache_at = 0.0
        self._schedule_library_rebuild()
        return {
            "targets": selected,
            "recall_hooks": True,
            "capture_hooks": capture_hooks,
            "confirmation": confirmation,
            "items": selected_states,
            "verified": all(
                item["integration_state"] == "manual-step"
                or (
                    item["integration_state"] == "connected"
                    and not item.get("recall_setup_required")
                )
                for item in selected_states
            ),
            "output": "\n".join(output)[-12000:],
        }

    async def distillation_preview(self) -> dict:
        """Plan an AI Context build without calling a provider or writing files."""
        memory = self._require_memory()
        defaults, providers, status, sources, plan = await asyncio.gather(
            self.ai_defaults(),
            self.provider_catalog(),
            asyncio.to_thread(memory.status),
            asyncio.to_thread(memory.sources, live_preview=False),
            asyncio.to_thread(self._context_engine().build, dry_run=True),
        )
        provider_id = str(defaults.get("default_llm") or "openrouter")
        provider = next((row for row in providers if row.get("id") == provider_id), {})
        models = defaults.get("models") if isinstance(defaults.get("models"), dict) else {}
        return {
            "available": str(provider.get("key_state") or "") != "missing",
            "status": "ready" if str(provider.get("key_state") or "") != "missing" else "provider-required",
            "atoms": int(status.get("atoms") or 0),
            "sources": len(sources),
            "provider": provider_id,
            "provider_label": provider.get("label") or provider_id.replace("-", " ").title(),
            "model": (
                getattr(
                    getattr(self._require_memory().config, "distillation", None),
                    "model",
                    None,
                )
                or models.get(provider_id)
            ),
            "provider_ready": str(provider.get("key_state") or "") != "missing",
            "clusters": int(plan.get("clusters") or 0),
            "estimated_provider_calls": int(plan.get("estimated_provider_calls") or 0),
            "estimated_input_tokens": int(plan.get("estimated_input_tokens") or 0),
            "estimated_output_tokens": int(plan.get("estimated_output_tokens") or 0),
            "estimated_cost_usd": plan.get("estimated_cost_usd"),
            "revision_id": plan.get("revision_id"),
            "writes": list(plan.get("writes") or []),
            "outputs": [
                "Personal defaults",
                "Project decisions",
                "Preferences and working rules",
                "Team context",
            ],
            "message": (
                "Ready to build readable Context with the selected provider."
                if str(provider.get("key_state") or "") != "missing"
                else "Configure this provider before starting AI distillation."
            ),
            "privacy_note": (
                "Only the evidence needed for each Context topic is sent to the selected provider. "
                "Credentials remain in the operating-system keyring."
            ),
        }

    def _context_engine(self):
        from docmancer.memory.context_engine import ContextEngine

        return ContextEngine(self.project_path, agent=self._require_memory())

    async def _humanize_context_topics(self, topics: list[dict]) -> list[dict]:
        atoms = await asyncio.to_thread(self._require_memory().indexed_atoms)
        by_address: dict[str, Any] = {}
        for atom in atoms:
            by_address[f"memory://atom/{atom.atom_id}"] = atom
            if atom.record_id:
                by_address[f"memory://record/{atom.record_id}"] = atom
        humanized = []
        for topic in topics:
            source_rows = []
            for address in topic.get("source_addresses") or topic.get("member_addresses") or []:
                atom = by_address.get(str(address))
                if atom is None:
                    continue
                source_rows.append({
                    "title": Path(str(atom.source_path or "")).name or str(atom.title or "Memory source"),
                    "agent": str(atom.harness or "Unknown agent").replace("-", " ").title(),
                    "project": str(atom.scope or "").split(":", 1)[-1] or Path(self.project_path).name,
                    "scope": str(atom.scope or ""),
                    "updated_at": atom.timestamp,
                })
            unique_sources = list({
                (row["title"], row["agent"], row["project"], row["scope"], row["updated_at"]): row
                for row in source_rows
            }.values())
            summary = str(topic.get("summary") or topic.get("text") or "").strip()
            title = str(topic.get("topic_label") or topic.get("title") or "").strip()
            if topic.get("synthesized") and topic.get("body"):
                body = str(topic["body"])
                if not title:
                    title = next(
                        (
                            line.lstrip("#").strip()
                            for line in body.splitlines()
                            if line.strip().startswith("#")
                        ),
                        "",
                    )
                if not summary:
                    summary = self._readable_markdown_preview(body, limit=720)
            humanized.append({
                **{
                    key: value for key, value in topic.items()
                    if key not in {"source_addresses", "member_addresses", "artifact_path", "path", "artifact_hash", "body"}
                },
                "title": title or "Knowledge topic",
                "summary": summary,
                "sources": unique_sources,
                "source_count": len(unique_sources) or int(topic.get("member_count") or len(source_rows)),
                "has_readable_summary": bool(summary),
                "diagnostics": {
                    "cluster_id": topic.get("cluster_id"),
                    "source_addresses": list(topic.get("source_addresses") or []),
                    "artifact_path": topic.get("artifact_path") or topic.get("path"),
                },
            })
        return humanized

    async def context_artifact(self) -> dict:
        engine = self._context_engine()
        latest, revisions = await asyncio.gather(
            asyncio.to_thread(engine.latest),
            asyncio.to_thread(engine.revisions),
        )
        if latest is not None:
            latest = dict(latest)
            latest["topics"] = await self._humanize_context_topics(list(latest.get("topics") or []))
        return {
            "available": latest is not None,
            "current": latest,
            "revisions": revisions,
            "delivery": await self.context_delivery(),
        }

    async def refresh_context(
        self,
        *,
        provider: str = "none",
        model: str | None = None,
        mode: str = "normal",
        full: bool = False,
        dry_run: bool = False,
        progress_callback=None,
    ) -> dict:
        from docmancer.ai.providers.factory import provider_client

        progress = progress_callback or (lambda _name, _data: None)
        progress("plan", {"detail": "Building the Context refresh plan"})
        client = None
        if provider != "none" and not dry_run:
            distillation_model = getattr(
                getattr(self._require_memory().config, "distillation", None),
                "model",
                None,
            )
            client = provider_client(
                provider,
                config=self._require_memory().config.providers,
                model=model or distillation_model,
            )
        result = await asyncio.to_thread(
            self._context_engine().build,
            client=client,
            dry_run=dry_run,
            full=full,
            mode=mode,
        )
        progress(
            "complete",
            {
                "detail": "Context plan ready" if dry_run else "Context revision ready",
                "revision_id": result.get("revision_id"),
            },
        )
        return result

    async def context_diff(self, left: str, right: str | None = None) -> dict:
        engine = self._context_engine()
        before = await asyncio.to_thread(engine.revision, left)
        after = (
            await asyncio.to_thread(engine.revision, right)
            if right
            else await asyncio.to_thread(engine.latest)
        )
        if after is None:
            raise ValueError("no current Context revision exists")
        before_topics = {row["cluster_id"]: row for row in before.get("topics", [])}
        after_topics = {row["cluster_id"]: row for row in after.get("topics", [])}
        shared = set(before_topics).intersection(after_topics)
        return {
            "from": before["revision_id"],
            "to": after["revision_id"],
            "added_clusters": sorted(set(after_topics) - set(before_topics)),
            "removed_clusters": sorted(set(before_topics) - set(after_topics)),
            "changed_clusters": sorted(
                cluster_id
                for cluster_id in shared
                if before_topics[cluster_id].get("artifact_hash")
                != after_topics[cluster_id].get("artifact_hash")
            ),
        }

    async def rollback_context(self, revision_id: str) -> dict:
        return await asyncio.to_thread(self._context_engine().rollback, revision_id)

    async def adopt_context(
        self,
        cluster_id: str,
        *,
        destination: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._context_engine().adopt,
            cluster_id,
            destination=destination,
        )

    async def retire_context(self, cluster_id: str) -> dict:
        return await asyncio.to_thread(self._context_engine().retire, cluster_id)

    async def consolidate(self, query: str | None, on_event=None) -> str:
        from docmancer.ai.memory_features import draft_to_markdown
        from docmancer.ai.providers.factory import provider_client
        from docmancer.memory.consolidation import consolidate_payload

        atoms = self._require_memory().indexed_atoms(limit=100)
        if not atoms:
            raise ValueError("no indexed memory atoms are available")
        payload = [
            {"scope": atom.scope, "title": atom.title, "source_path": atom.source_path, "text": atom.text}
            for atom in atoms
        ]
        providers = self._require_memory().config.providers
        client = provider_client(providers.default_llm, config=providers)
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
        from docmancer._version import __version__
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
            upsert_block,
            target,
            body,
            begin=_MEMORY_BLOCK_BEGIN,
            end=_MEMORY_BLOCK_END,
            backup_policy="foreign-content",
            version=__version__,
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

    async def query_docs(
        self,
        text: str,
        *,
        expand: str | None = None,
        limit: int = 30,
        source: str | None = None,
    ) -> list[dict]:
        started = monotonic()
        filters = None
        if source:
            document = await self.get_docs_source(source)
            page_sources = [
                str(page.get("source") or "")
                for page in (document or {}).get("pages", [])
                if str(page.get("source") or "")
            ]
            filters = {"source": {"in": page_sources}} if page_sources else {"source": {"in": []}}
        query_options: dict[str, Any] = {"expand": expand, "limit": limit}
        if filters is not None:
            query_options["filters"] = filters
        chunks = await self._require_docs().query(text, **query_options)
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

    def _library_catalog(self):
        if self._library_catalog_instance is None:
            from docmancer.web.library_catalog import LibraryCatalog

            path = Path(self.project_path) / ".docmancer" / "index" / "library.sqlite"
            self._library_catalog_instance = LibraryCatalog(path)
        return self._library_catalog_instance

    @staticmethod
    def _readable_markdown_preview(body: str, *, limit: int = 360) -> str:
        import re

        lines = []
        in_frontmatter = body.startswith("---\n")
        for line in body.splitlines():
            stripped = line.strip()
            if in_frontmatter:
                if stripped == "---" and lines:
                    in_frontmatter = False
                elif stripped == "---":
                    lines.append("")
                continue
            if not stripped or stripped.startswith(("#", "<!--")):
                continue
            if stripped.startswith(("-", "*", ">")):
                stripped = stripped[1:].strip()
            lines.append(stripped)
            if len(" ".join(lines)) >= limit:
                break
        preview = " ".join(lines).strip()
        preview = re.sub(r"memory://atom/[A-Za-z0-9._:-]+", "indexed memory source", preview)
        preview = re.sub(
            r"(?:[A-Za-z]:\\|/)(?:Users|home|var|private|tmp)[\\/][^\s`\"')\],;]+",
            "a local file",
            preview,
        )
        return preview[:limit]

    @staticmethod
    def _human_scope_label(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        prefix, separator, detail = raw.partition(":")
        if not separator:
            return raw.replace("-", " ").title()
        if prefix == "project":
            project_name = Path(detail.rstrip("/\\")).name.replace("_", " ").replace("-", " ")
            return f"Project: {project_name or 'local project'}"
        return prefix.replace("-", " ").title()

    async def _library_records(self) -> list[dict]:
        from docmancer.memory.sources import memory_source_key

        store = self._tree_store()
        memory = self._require_memory()
        self._require_docs()
        tree_entries, evidence, docs = await asyncio.gather(
            asyncio.to_thread(store.index.entries),
            asyncio.to_thread(memory.sources, live_preview=False),
            self.docs_sources(),
        )
        records: list[dict] = []
        for entry in tree_entries:
            relative = entry.path.relative_to(store.root)
            if relative.parts and relative.parts[0] == "context":
                continue
            if (
                relative.as_posix() == "context.md"
                and not entry.sources
                and entry.title.strip() == "Project context"
                and self._readable_markdown_preview(entry.body).strip()
                == "Curated project memory lives in this tree."
            ):
                continue
            records.append({
                "corpus": "memory",
                "record_id": entry.memory_id,
                "title": entry.title,
                "summary": self._readable_markdown_preview(entry.body),
                "kind": entry.type,
                "agent": "",
                "project_label": Path(self.project_path).name,
                "scope_label": self._human_scope_label(entry.scope),
                "updated_at": str(entry.updated_at or ""),
                "source_count": len(entry.sources),
                "section_count": 0,
                "content_fingerprint": entry.content_hash,
                "detail_key": entry.address,
            })
        for row in evidence:
            source_key = memory_source_key(
                harness=str(row.get("agent") or "unknown"),
                scope=str(row.get("scope") or "unknown"),
                kind=str(row.get("type") or "agent-memory"),
                path=str(row.get("path") or ""),
            )
            path = Path(str(row.get("path") or ""))
            records.append({
                "corpus": "evidence",
                "record_id": source_key,
                "title": str(row.get("title") or path.name or "Agent evidence"),
                "summary": f"{int(row.get('atoms') or 0):,} indexed memory atoms from {str(row.get('agent') or 'an agent')}.",
                "kind": str(row.get("type") or "agent-memory"),
                "agent": str(row.get("agent") or ""),
                "project_label": path.parent.name if path.parent.name else Path(self.project_path).name,
                "scope_label": self._human_scope_label(row.get("scope")),
                "updated_at": str(row.get("updated_at") or ""),
                "source_count": int(row.get("atoms") or 0),
                "section_count": 0,
                "content_fingerprint": "",
                "detail_key": source_key,
            })
        for row in docs:
            source = str(row.get("source") or "")
            record_id = "docs_" + hashlib.sha256(source.encode()).hexdigest()[:24]
            records.append({
                "corpus": "docs",
                "record_id": record_id,
                "title": str(row.get("title") or source or "Documentation"),
                "summary": f"{int(row.get('pages') or 0):,} pages and {int(row.get('sections') or 0):,} searchable sections.",
                "kind": "documentation",
                "agent": "",
                "project_label": "",
                "scope_label": "Reference",
                "updated_at": str(row.get("ingested_at") or ""),
                "source_count": int(row.get("pages") or 0),
                "section_count": int(row.get("sections") or 0),
                "content_fingerprint": "",
                "detail_key": source,
            })
        return records

    async def rebuild_library_catalog(self) -> dict:
        records = await self._library_records()
        return await asyncio.to_thread(self._library_catalog().replace, records)

    def _schedule_library_rebuild(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._library_rebuild_task and not self._library_rebuild_task.done():
            return
        self._library_bootstrap_checked = True
        async def rebuild() -> None:
            self._library_rebuild_started_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            self._library_rebuild_error = None
            try:
                await self.rebuild_library_catalog()
            except Exception as exc:  # The last valid catalog remains usable.
                self._library_rebuild_error = str(exc)
            finally:
                self._library_rebuild_finished_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )

        self._library_rebuild_task = loop.create_task(rebuild())

    async def library(
        self,
        *,
        corpus: str,
        query: str = "",
        cursor: str | None = None,
        limit: int = 30,
    ) -> dict:
        if corpus not in {"memory", "evidence", "docs"}:
            raise ValueError("Library corpus must be memory, evidence, or docs")
        catalog = self._library_catalog()
        if not self._library_bootstrap_checked:
            self._library_bootstrap_checked = True
            self._schedule_library_rebuild()
        result = await asyncio.to_thread(
            catalog.list,
            corpus=corpus,
            query=query,
            cursor=cursor,
            limit=limit,
        )
        if corpus == "memory":
            result["items"] = [
                item for item in result["items"]
                if not (
                    str(item.get("title") or "").strip().casefold() == "project context"
                    and str(item.get("summary") or "").strip()
                    == "Curated project memory lives in this tree."
                )
            ]
        task = self._library_rebuild_task
        has_records = await asyncio.to_thread(catalog.has_records)
        result["index_state"] = (
            "building" if task and not task.done()
            else "error" if self._library_rebuild_error
            else "ready"
        )
        result["refreshing"] = bool(task and not task.done() and has_records)
        if self._library_rebuild_error:
            result["refresh_error"] = self._library_rebuild_error
        return result

    async def library_detail(self, corpus: str, record_id: str) -> dict | None:
        catalog_item = await asyncio.to_thread(self._library_catalog().record, corpus, record_id)
        if not catalog_item:
            return None
        detail_key = str(catalog_item["detail_key"])
        if corpus == "memory":
            item = await self.tree_read(detail_key)
            source_count = len(item.get("sources") or [])
            return {
                "record_id": record_id,
                "title": catalog_item["title"],
                "summary": self._readable_markdown_preview(str(item.get("markdown") or ""), limit=1200),
                "kind": item["type"],
                "scope_label": catalog_item["scope_label"],
                "source_count": source_count,
                "provenance_label": (
                    f"{source_count} source{'s' if source_count != 1 else ''}"
                    if source_count
                    else "Created directly in curated memory"
                ),
                "access_surfaces": [
                    "Library",
                    "Docmancer Ask",
                    "Connected coding agents",
                ],
                "diagnostics": {
                    "address": item["address"],
                    "content_hash": item["content_hash"],
                    "revision_id": item["revision_id"],
                },
            }
        if corpus == "evidence":
            item = await self.get_memory_source(detail_key)
            if item is None:
                return None
            return {
                "record_id": record_id,
                "title": catalog_item["title"],
                "summary": self._readable_markdown_preview(str(item.get("content") or ""), limit=1200),
                "kind": item.get("kind"),
                "agent": item.get("harness"),
                "scope_label": catalog_item["scope_label"],
                "source_count": item.get("atom_count"),
                "diagnostics": {
                    "source_key": item.get("source_key"),
                    "path": item.get("path"),
                    "source_hash": item.get("source_hash"),
                },
            }
        item = await self.get_docs_source(detail_key)
        if item is None:
            return None
        pages = list(item.get("pages") or [])
        row = next(
            (value for value in self._docs_source_rows if str(value.get("source") or "") == detail_key),
            {},
        )
        formats = sorted({
            str(page.get("format") or "")
            for page in pages
            if str(page.get("format") or "")
        })
        origin = detail_key
        if origin.startswith(("http://", "https://")):
            from urllib.parse import urlsplit

            parts = urlsplit(origin)
            origin_label = parts.netloc or origin
        else:
            origin_label = Path(origin).name or "Local documentation"
        return {
            "record_id": record_id,
            "title": catalog_item["title"],
            "summary": (
                f"Searchable technical reference with {int(row.get('sections') or sum(len(page.get('sections') or []) for page in pages)):,} indexed sections."
            ),
            "kind": "documentation",
            "source_count": len(pages),
            "page_count": int(row.get("pages") or len(pages)),
            "section_count": int(row.get("sections") or sum(len(page.get("sections") or []) for page in pages)),
            "formats": list(row.get("formats") or formats),
            "origin": origin,
            "origin_label": origin_label,
            "ingested_at": str(row.get("ingested_at") or max((str(page.get("ingested_at") or "") for page in pages), default="")),
            "last_indexed_at": str(row.get("ingested_at") or ""),
            "refresh_state": "current",
            "access_surfaces": [
                "Library documentation search",
                "docmancer docs query",
                "Connected coding agents using the Docmancer skill",
            ],
            "context_policy": "Documentation stays separate from personal memory and is not automatically injected into Context.",
            "diagnostics": {"source": detail_key},
        }

    def _tree_store(self):
        from docmancer.memory.tree.store import TreeStore

        if self._tree_store_instance is None:
            self._tree_store_instance = TreeStore(Path(self.project_path) / ".docmancer" / "tree")
        return self._tree_store_instance

    @staticmethod
    def _tree_backlinks(entries) -> dict[str, list[dict]]:
        targets: dict[str, str] = {}
        for entry in entries:
            targets[entry.title] = entry.memory_id
            targets[entry.address] = entry.memory_id
        backlinks: dict[str, list[dict]] = {entry.memory_id: [] for entry in entries}
        for candidate in entries:
            for _kind, target in candidate.relations:
                target_id = targets.get(target)
                if target_id and target_id != candidate.memory_id:
                    backlinks[target_id].append({
                        "address": candidate.address,
                        "title": candidate.title,
                    })
        return backlinks

    def _tree_entry_payload(
        self,
        entry,
        *,
        include_body: bool = True,
        backlinks: dict[str, list[dict]] | None = None,
        root: Path | None = None,
    ) -> dict:
        root = root or self._tree_store().root
        outline = []
        for line_number, line in enumerate(entry.body.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                if 1 <= level <= 6 and stripped[level:].startswith(" "):
                    outline.append({"level": level, "title": stripped[level:].strip(), "line": line_number})
        return {
            "address": entry.address,
            "memory_id": entry.memory_id,
            "title": entry.title,
            "path": entry.path.relative_to(root).as_posix(),
            "editor_path": str(entry.path.resolve()),
            "type": entry.type,
            "scope": entry.scope,
            "authority": entry.authority,
            "project_id": entry.project_id,
            "status": entry.status,
            "tags": list(entry.tags),
            "sources": list(entry.sources),
            "relations": [{"type": kind, "target": target} for kind, target in entry.relations],
            "backlinks": (backlinks or {}).get(entry.memory_id, []),
            "outline": outline,
            "content_hash": entry.content_hash,
            "revision_id": entry.revision_id,
            "curation_origin": entry.curation_origin,
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
        backlink_map = self._tree_backlinks(entries)
        return [
            self._tree_entry_payload(entry, include_body=False, backlinks=backlink_map)
            for entry in sorted(entries, key=lambda item: str(item.path))
        ]

    async def tree_read(self, address: str) -> dict:
        store = self._tree_store()
        entries = await asyncio.to_thread(store.index.entries)
        entry = next((item for item in entries if item.address == address), None)
        if entry is None:
            entry = await asyncio.to_thread(store.read, address)
        return self._tree_entry_payload(entry, backlinks=self._tree_backlinks(entries))

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
            actor_surface="web",
            actor_harness=str(body.get("agent") or "web"),
        )
        self._invalidate_shared_memory_cache()
        self._schedule_library_rebuild()
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

            result = {"reindexed": count, "dense": await asyncio.to_thread(rebuild_dense)}
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
            return result
        address = str(body["address"])
        expected_hash = str(body.get("expected_hash") or "")
        if action == "edit":
            entry = await asyncio.to_thread(
                store.edit,
                address,
                text=str(body["markdown"]),
                expected_hash=expected_hash,
                actor_surface="web",
                actor_harness=str(body.get("agent") or "web"),
            )
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
            return self._tree_entry_payload(entry)
        if action == "move":
            entry = await asyncio.to_thread(
                store.move,
                address,
                str(body["path"]),
                expected_hash=expected_hash,
                actor_surface="web",
                actor_harness=str(body.get("agent") or "web"),
            )
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
            return self._tree_entry_payload(entry)
        if action == "duplicate":
            entry = await asyncio.to_thread(
                store.duplicate,
                address,
                str(body["path"]),
                expected_hash=expected_hash,
                actor_surface="web",
                actor_harness=str(body.get("agent") or "web"),
            )
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
            return self._tree_entry_payload(entry)
        if action == "trash":
            token = await asyncio.to_thread(
                store.trash,
                address,
                expected_hash=expected_hash,
                actor_surface="web",
                actor_harness=str(body.get("agent") or "web"),
            )
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
            return {"trashed": True, "restore_token": token}
        if action == "restore":
            entry = await asyncio.to_thread(
                store.restore,
                str(body["restore_token"]),
                actor_surface="web",
                actor_harness=str(body.get("agent") or "web"),
            )
            self._invalidate_shared_memory_cache()
            self._schedule_library_rebuild()
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
                "path": str(path.resolve()),
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

    async def harvest_tree(self, source: str = "", *, apply: bool = False) -> dict:
        """Preview registered project sources or an explicit project path."""
        from docmancer.memory.tree.curation import CurationEngine
        from docmancer.memory.tree.harvest import discover_project_harvest_sources, markdown_files

        selection = "explicit"
        registered = []
        if source.strip():
            roots = [self._bounded_project_source(source)]
        else:
            selection = "current-project"
            registered = discover_project_harvest_sources(
                self.project_path,
                config=getattr(self._require_memory().config, "discovery", None),
            )
            roots = [path for item in registered for path in item.files]
        files = [
            path for path in markdown_files(roots)
            if ".docmancer/tree" not in path.as_posix()
        ]
        before = {path: path.stat().st_mtime_ns for path in files}
        results: list[dict] = []
        engine = CurationEngine(self._tree_store(), Path(self.project_path) / ".docmancer" / "inbox")
        for path in files:
            try:
                display_path = str(path.relative_to(Path(self.project_path).resolve()))
            except ValueError:
                display_path = str(path)
            row = {"source": display_path, "status": "preview"}
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
        if apply:
            self._schedule_library_rebuild()
        return {
            "applied": apply,
            "selection": selection,
            "registered_sources": [
                {
                    "harness": item.harness,
                    "root": str(item.root),
                    "scope": item.scope,
                    "file_count": len(item.files),
                }
                for item in registered
            ],
            "count": len(results),
            "results": results,
        }

    async def import_markdown(self, source: str, *, apply: bool = True) -> dict:
        """Preview or copy one explicitly selected Markdown path."""
        value = source.strip()
        if not value:
            raise ValueError("source is required")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.project_path) / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            raise ValueError("source does not exist")
        project_tree = Path(self.project_path).resolve() / ".docmancer" / "tree"
        if candidate == project_tree or project_tree in candidate.parents:
            raise ValueError("the curated tree cannot be imported into its own inbox")

        from docmancer.memory.tree.curation import CurationEngine
        from docmancer.memory.tree.harvest import markdown_files

        files = markdown_files([candidate])
        before = {path: (path.stat().st_mtime_ns, path.stat().st_size) for path in files}
        results = []
        engine = CurationEngine(self._tree_store(), Path(self.project_path) / ".docmancer" / "inbox")
        for path in files:
            row = {"source": str(path), "status": "preview"}
            if apply:
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                if len(text.encode("utf-8")) > 1_000_000:
                    row["status"] = "skipped_too_large"
                else:
                    result = await asyncio.to_thread(engine.curate, text, source_path=path)
                    row.update(status=result.destination, inbox_path=str(result.inbox_path or ""))
            results.append(row)
        if any((path.stat().st_mtime_ns, path.stat().st_size) != before[path] for path in files):
            raise ValueError("an imported source changed during the operation")
        if apply:
            self._schedule_library_rebuild()
        return {
            "imported": apply,
            "selection": "explicit",
            "count": len(results),
            "results": results,
        }

    def _allowed_markdown_path(self, value: str) -> Path:
        candidate = Path(value).expanduser().resolve()
        if candidate.suffix.lower() not in {".md", ".markdown", ".mdc"} or not candidate.is_file():
            raise ValueError("only existing Markdown files can be opened")
        project = Path(self.project_path).resolve()
        local_state = Path.home() / ".docmancer"
        within_project = candidate == project or project in candidate.parents
        within_local_state = candidate == local_state or local_state in candidate.parents
        indexed = self._require_memory().is_indexed_source_path(candidate)
        docs_indexed = False
        for row in self._docs_source_rows:
            raw = str(row.get("source") or "")
            if not raw or raw.startswith(("http://", "https://")):
                continue
            source = Path(raw).expanduser().resolve()
            if source == candidate or (source.is_dir() and source in candidate.parents):
                docs_indexed = True
                break
        if not (within_project or within_local_state or indexed or docs_indexed):
            raise ValueError("file is outside the active project and is not an indexed source")
        return candidate

    async def available_editors(self, path: str) -> list[dict]:
        from docmancer.memory.tree.editor import available_editors

        candidate = self._allowed_markdown_path(path)
        return await asyncio.to_thread(available_editors, candidate)

    async def open_markdown_file(
        self,
        path: str,
        *,
        editor_id: str,
        line: int | None = None,
        column: int | None = None,
    ) -> dict:
        from docmancer.memory.tree.editor import open_in_editor

        candidate = self._allowed_markdown_path(path)
        return await asyncio.to_thread(
            open_in_editor,
            candidate,
            editor_id=editor_id,
            line=line,
            column=column,
        )

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
            self._schedule_library_rebuild()
        return payload

    async def ask_tree(
        self,
        task: str,
        *,
        token_budget: int = 4000,
        agent: str = "web",
        answer: bool | None = None,
        mode: str = "normal",
        on_delta=None,
        action_enabled: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
        pending_action_request: str | None = None,
        action_clarification_count: int = 0,
        mutation_disabled_reason: str | None = None,
    ) -> dict:
        from docmancer.memory.ask import ask
        from docmancer.memory.actions import MemoryActionEngine, is_mutation_request

        continued_request = str(pending_action_request or "").strip()
        action_task = (
            f"{continued_request}\n\nUser clarification: {task}"
            if continued_request
            else task
        )
        mutation_request = bool(is_mutation_request(task) or continued_request)
        action_result = None
        if mutation_request and action_enabled:
            action_result = await asyncio.to_thread(
                MemoryActionEngine(
                    self.project_path,
                    memory_agent=self._require_memory(),
                ).plan,
                action_task,
                history=conversation_history,
            )
        bundle = await asyncio.to_thread(
            ask,
            task,
            project_path=self.project_path,
            token_budget=token_budget,
            agent_name=agent,
            surface="web",
            integration_mode="workbench-preview",
            answer=False if mutation_request else answer,
            answer_mode=mode,
            on_delta=None if mutation_request else on_delta,
        )
        items = [
            *bundle["mandatory_policies"],
            *bundle["curated_memory"],
            *bundle["relevant_evidence"],
        ]
        result = {
            "answer": bundle.get("answer"),
            "no_answer": not bool(items),
            "items": items,
            "mandatory_policies": bundle["mandatory_policies"],
            "curated_memory": bundle["curated_memory"],
            "relevant_evidence": bundle["relevant_evidence"],
            "token_estimate": bundle["token_estimate"],
            "index_revision": bundle["index_revision"],
            "refresh": bundle["refresh"],
            "answer_unavailable": bundle.get("answer_unavailable"),
            "timings": {},
        }
        if mutation_request:
            if mutation_disabled_reason:
                result["answer"] = {
                    "text": mutation_disabled_reason,
                    "provider": None,
                    "model": None,
                }
            elif action_result is not None:
                if (
                    action_result.get("kind") == "clarification"
                    and action_clarification_count >= 1
                ):
                    action_result = {
                        **action_result,
                        "kind": "unavailable",
                        "message": (
                            "I could not turn the clarification into one safe file proposal. "
                            "Shared Memory is unchanged. Restate the request with one exact target, "
                            "or use the explicit memory editor."
                        ),
                    }
                result["answer"] = {
                    "text": str(action_result.get("message") or ""),
                    "provider": action_result.get("provider"),
                    "model": action_result.get("model"),
                }
                result["action"] = action_result.get("proposal")
                action_kind = str(action_result.get("kind") or "")
                result["action_kind"] = action_kind
                retryable_action = action_kind == "clarification" or (
                    action_kind == "unavailable"
                    and action_clarification_count == 0
                )
                result["action_request"] = (
                    continued_request or task
                    if retryable_action
                    else None
                )
                result["action_clarification_count"] = (
                    action_clarification_count + 1
                    if retryable_action
                    else 0
                )
        return result

    async def execute_memory_action(
        self,
        proposal: dict[str, Any],
        *,
        actor_surface: str,
    ) -> dict:
        from docmancer.memory.actions import MemoryActionEngine

        result = await asyncio.to_thread(
            MemoryActionEngine(
                self.project_path,
                memory_agent=self._require_memory(),
            ).execute,
            proposal,
            actor_surface=actor_surface,
        )
        self._invalidate_shared_memory_cache()
        self._schedule_library_rebuild()
        return result

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
            "memory_refresh": self.memory_refresh_status(),
            "last_sync": await asyncio.to_thread(memory.last_sync_stats),
            "docs": docs_status,
            "project": self.project_path,
            "context": await asyncio.to_thread(self._require_service().status, project_path=self.project_path),
        }

    async def sync(self, progress_callback=None) -> dict:
        result = await asyncio.to_thread(
            self._require_service().sync,
            project_path=self.project_path,
            progress_callback=progress_callback,
        )
        self._schedule_library_rebuild()
        return result

    async def audit(self) -> dict:
        source_state = await asyncio.to_thread(self._audit_source_signature)
        return await self._audit_for_source_state(source_state)

    async def hook_status(self) -> list[dict]:
        """Inspect automatic-context and capture hooks at user and project scopes."""
        return await asyncio.to_thread(self._hook_status)

    def _hook_status(self) -> list[dict]:
        from docmancer.memory.delivery import inspect_hook_status

        return inspect_hook_status(self.project_path)

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
        from docmancer.cloud.config import CloudConfig

        root = Path(self._require_memory().db_path).parent
        value = await asyncio.to_thread(cloud_status, root)
        config = CloudConfig(root)
        project_id = await asyncio.to_thread(config.ensure_project, self.project_path)
        value["project_mapping"] = config.mapping_status(project_id)
        return value

    async def team_file(
        self,
        *,
        domain: str = "standards",
        apply: bool = False,
        approved: bool = False,
        approver_id: str | None = None,
    ) -> dict:
        """Preview or approve one privacy-filtered generated Team file."""
        from docmancer.cloud.team_files import generate_team_file

        root = Path(self._require_memory().db_path).parent
        result = await asyncio.to_thread(
            generate_team_file,
            self.project_path,
            domain=domain,
            apply=apply,
            approved=approved,
            approver_id=approver_id,
            root=root,
        )
        if apply and result.get("published"):
            from docmancer.cloud.config import CloudConfig
            from docmancer.cloud.crypto import opaque_ref
            from docmancer.cloud.keystore import KeyStore
            from docmancer.cloud.outbox import CloudState

            config = CloudConfig(root)
            account = config.account()
            workspace = config.workspace()
            keys = KeyStore()
            if workspace is not None:
                workspace_id = workspace[0]
                workspace_key = keys.workspace_key(str(account["account_id"]), workspace_id)
                if workspace_key:
                    revision_ref = opaque_ref(
                        str(result["revision_id"]),
                        workspace_key,
                        workspace_id=workspace_id,
                        kind="revision",
                    )
                    state = CloudState(config.paths.sync_state)
                    envelope = next(
                        (
                            item for item in state.pending()
                            if item.get("revision_ref") == revision_ref
                            and item.get("kind") == "team_file_revision"
                        ),
                        None,
                    )
                    if envelope:
                        client, selected_workspace = await asyncio.to_thread(self._cloud_client)
                        try:
                            result["proposal"] = await asyncio.to_thread(
                                client.create_promotion,
                                selected_workspace,
                                {
                                    **envelope,
                                    "approval_scope": "complete_file",
                                    "privacy_attestation": {
                                        "local_checks_passed": True,
                                        "selected_count": int(result["selected_count"]),
                                        "exclusion_count": len(result["excluded"]),
                                    },
                                },
                            )
                        finally:
                            await asyncio.to_thread(client.close)
        result["cloud"] = await self.cloud_status()
        return result

    async def team_file_transition(
        self,
        *,
        domain: str,
        outcome: str,
        approver_id: str | None = None,
    ) -> dict:
        from docmancer.cloud.team_files import transition_team_file

        memory = self._require_memory()
        return await asyncio.to_thread(
            transition_team_file,
            self.project_path,
            domain=domain,
            outcome=outcome,
            approver_id=approver_id,
            root=Path(memory.db_path).parent,
        )

    async def cloud_conflicts(self) -> list[dict]:
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.outbox import CloudState

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        return await asyncio.to_thread(CloudState(config.paths.sync_state).conflicts)

    async def cloud_connect(
        self,
        *,
        base_url: str | None = None,
        create_recovery: bool = False,
        progress: Callable[[str, dict], None] | None = None,
    ) -> dict:
        """Drive device-code login end to end, reporting each stage as it happens."""
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.connect import (
            ConnectCancelled,
            await_authorization,
            enqueue_project,
            finish_connect,
            resume_existing_connect,
            start_connect,
        )
        from docmancer.cloud.keystore import KeyStore

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        if config.enabled():
            raise ValueError("this device is already connected to Docmancer Cloud")

        emit = progress or (lambda stage, data: None)
        cancel = threading.Event()
        self._cloud_connect_cancel = cancel

        def run() -> dict:
            keys = KeyStore()
            resumed = resume_existing_connect(
                base_url or "",
                config=config,
                account=config.account(),
                keys=keys,
                root=root,
                on_event=emit,
            ) if base_url else None
            if resumed is not None:
                return resumed
            session = start_connect(
                base_url,
                root=root,
                project_path=self.project_path,
                keys=keys,
                on_event=emit,
            )
            result = await_authorization(
                session, on_event=emit, should_cancel=cancel.is_set,
            )
            outcome = finish_connect(session, result, on_event=emit)
            if outcome["state"] == "connected":
                try:
                    enqueue_project(root, keys, self.project_path)
                except Exception as exc:  # noqa: BLE001 - the connection is valid even if queueing fails
                    outcome["queue_warning"] = (
                        f"Connected, but existing memory could not be queued: {exc}. Run sync to retry."
                    )
            if create_recovery:
                outcome["recovery_key"] = self._cloud_create_recovery(root, keys, outcome["workspace_id"])
            return outcome

        try:
            return await asyncio.to_thread(run)
        except ConnectCancelled:
            raise
        finally:
            self._cloud_connect_cancel = None

    def _cloud_create_recovery(self, root: Path, keys, workspace_id: str) -> str:
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.recovery import create_recovery

        config = CloudConfig(root)
        account = config.account()
        workspace_key = keys.workspace_key(str(account.get("account_id") or ""), workspace_id)
        if not workspace_key:
            raise ValueError("a local workspace key is required to create a recovery key")
        recovery_key, wrapper = create_recovery(workspace_id, workspace_key, root=root)
        (config.paths.root / "recovery-wrapper.json").write_text(
            json.dumps(wrapper, indent=2) + "\n", encoding="utf-8",
        )
        try:
            client, _workspace = self._cloud_client()
            try:
                client.upload_recovery_wrapper(workspace_id, wrapper)
            finally:
                client.close()
        except Exception:  # noqa: BLE001 - the wrapper is saved locally regardless
            pass
        return recovery_key

    def cloud_cancel_connect(self) -> dict:
        cancel = getattr(self, "_cloud_connect_cancel", None)
        if cancel is None:
            return {"cancelled": False, "reason": "no_attempt_in_flight"}
        cancel.set()
        return {"cancelled": True}

    async def cloud_disconnect(self) -> dict:
        """Clear the local cloud session without touching local memory."""
        from docmancer.cloud.config import CloudConfig
        from docmancer.cloud.keystore import KeyStore

        root = Path(self._require_memory().db_path).parent
        config = CloudConfig(root)
        account = config.account()
        keys = KeyStore()
        account_id = str(account.get("account_id") or "")
        if account_id:
            await asyncio.to_thread(keys.delete, account_id, "access-token")
        await asyncio.to_thread(config.save_account, enabled=False)
        return {"disconnected": True}

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
            payload = {"decision": decision, "approval_scope": "complete_file"}
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
