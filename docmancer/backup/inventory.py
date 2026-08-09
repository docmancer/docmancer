"""Read-only portable artifact inventory through registered harnesses."""
from __future__ import annotations

import hashlib
import platform
import uuid
from pathlib import Path

from docmancer.harness import all_harnesses, default_home

from .models import InventoryResult


def source_device_id(home: Path) -> str:
    marker = home / ".docmancer" / "device-id"
    if marker.is_file():
        try:
            value = marker.read_text(encoding="utf-8").strip()
            return str(uuid.UUID(value))
        except (OSError, ValueError):
            pass
    # Inventory is read-only, so do not create the durable marker here. The
    # machine-derived fallback is only used until the first backup persists it.
    seed = f"{platform.node()}\0{home.resolve()}"
    return str(uuid.UUID(hashlib.sha256(seed.encode()).hexdigest()[:32]))


def ensure_source_device_id(home: Path) -> str:
    marker = home / ".docmancer" / "device-id"
    value = source_device_id(home)
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(value + "\n", encoding="utf-8")
        marker.chmod(0o600)
    return value


def inventory(
    *,
    home: Path | None = None,
    agents: set[str] | None = None,
    include_projects: set[str] | None = None,
    exclude_projects: set[str] | None = None,
    include_attachments: bool = False,
    config=None,
) -> InventoryResult:
    resolved = Path(home or default_home()).expanduser().resolve()
    artifacts = []
    excluded = []
    selected = {value.casefold() for value in agents or set()}
    for harness in all_harnesses(resolved, config=config):
        adapter = harness.backup_adapter()
        if adapter is None or (selected and harness.name.casefold() not in selected):
            continue
        found, skipped = adapter.inventory(
            include_projects=include_projects,
            exclude_projects=exclude_projects,
            include_attachments=include_attachments,
        )
        artifacts.extend(found)
        excluded.extend(skipped)
    return InventoryResult(
        artifacts=sorted(artifacts, key=lambda item: (item.agent, item.logical_path)),
        excluded=excluded,
        source_device_id=source_device_id(resolved),
        source_home=resolved,
    )


__all__ = ["ensure_source_device_id", "inventory", "source_device_id"]
