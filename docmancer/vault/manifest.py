from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContentKind(str, Enum):
    raw = "raw"
    wiki = "wiki"
    output = "output"
    asset = "asset"


class SourceType(str, Enum):
    web = "web"
    markdown = "markdown"
    pdf = "pdf"
    local_file = "local_file"
    image = "image"


class IndexState(str, Enum):
    pending = "pending"
    indexed = "indexed"
    stale = "stale"
    failed = "failed"


class ManifestEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    path: str
    kind: ContentKind
    source_type: SourceType
    content_hash: str = ""
    index_state: IndexState = IndexState.pending
    added_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    source_url: str | None = None
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class VaultManifest:
    def __init__(self, manifest_path: Path) -> None:
        self._manifest_path = manifest_path
        self._entries: dict[str, ManifestEntry] = {}

    @property
    def entries(self) -> dict[str, ManifestEntry]:
        return dict(self._entries)

    def load(self) -> None:
        if not self._manifest_path.exists():
            self._entries = {}
            return
        data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        raw_entries = data.get("entries", {})
        self._entries = {
            entry_id: ManifestEntry.model_validate(entry_data)
            for entry_id, entry_data in raw_entries.items()
        }

    def save(self) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": {
                entry_id: entry.model_dump()
                for entry_id, entry in self._entries.items()
            },
        }
        self._manifest_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def add(self, entry: ManifestEntry) -> ManifestEntry:
        self._entries[entry.id] = entry
        return entry

    def get_by_id(self, entry_id: str) -> ManifestEntry | None:
        return self._entries.get(entry_id)

    def get_by_path(self, path: str) -> ManifestEntry | None:
        for entry in self._entries.values():
            if entry.path == path:
                return entry
        return None

    def remove(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    def update_hash(self, entry_id: str, content_hash: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        self._entries[entry_id] = entry.model_copy(
            update={"content_hash": content_hash, "updated_at": _utc_now()}
        )
        return True

    def set_index_state(self, entry_id: str, state: IndexState) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        self._entries[entry_id] = entry.model_copy(
            update={"index_state": state, "updated_at": _utc_now()}
        )
        return True

    def all_entries(self) -> list[ManifestEntry]:
        return list(self._entries.values())
