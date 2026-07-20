"""Async, presentation-free facade used by the Textual application."""
from __future__ import annotations

import asyncio
import os
import platform
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from docmancer.memory.audit import audit_secrets
from docmancer.memory.sources import MemorySourceFilters


class TuiBackend:
    """Lazily construct and call Docmancer's blocking local agents."""

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
        }

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
        }

    async def sync(self, progress_callback=None) -> int:
        return await asyncio.to_thread(
            self._require_memory().sync,
            progress_callback=progress_callback,
        )

    async def audit(self) -> dict:
        source_state = await asyncio.to_thread(self._audit_source_signature)
        return await self._audit_for_source_state(source_state)

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
            raise ValueError("cloud session is incomplete; run `docmancer cloud login`")
        client = CloudClient(str(account["base_url"]), token=token.decode("utf-8"), device_id=str(account["device_id"]))
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
            raise ValueError("cloud session is incomplete; run `docmancer cloud login`")
        client = CloudClient(str(account["base_url"]), token=token.decode("utf-8"), device_id=str(account["device_id"]))
        return client, str(account["workspace_id"])

    async def cloud_devices(self) -> list[dict]:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            value = await asyncio.to_thread(client.devices, workspace_id)
            return list(value.get("devices") or [])
        finally:
            await asyncio.to_thread(client.close)

    async def cloud_approve_device(self, device_id: str, fingerprint: str) -> dict:
        client, workspace_id = await asyncio.to_thread(self._cloud_client)
        try:
            return await asyncio.to_thread(client.register_device, workspace_id, {"device_id": device_id, "fingerprint": fingerprint, "approved": True})
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
