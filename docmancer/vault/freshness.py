"""Scan-on-query freshness gate for vault read commands."""

from __future__ import annotations

import time
from pathlib import Path

from docmancer.vault.manifest import VaultManifest
from docmancer.vault.scanner import ScanResult, _SUPPORTED_EXTENSIONS, _SKIP_SCAN_DIRS, scan_vault


# Module-level cache of last auto-scan time to enforce cooldown across calls
# within the same process (CLI session).
_last_auto_scan_ts: float = 0.0


def needs_scan(
    vault_root: Path,
    manifest: VaultManifest,
    scan_dirs: list[str],
    cooldown_seconds: int = 30,
) -> bool:
    """Check whether a scan is needed before a query.

    Returns True if any file under *scan_dirs* has been modified since the last
    scan.  Respects a cooldown period to avoid repeated filesystem walks during
    rapid-fire queries.
    """
    global _last_auto_scan_ts

    now = time.time()
    if cooldown_seconds > 0 and (now - _last_auto_scan_ts) < cooldown_seconds:
        return False

    # Determine the latest updated_at across all manifest entries as a proxy
    # for "last scan time".  Fall back to 0 so the first scan always triggers.
    last_scan_epoch = 0.0
    for entry in manifest.all_entries():
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(entry.updated_at)
            entry_ts = dt.timestamp()
            if entry_ts > last_scan_epoch:
                last_scan_epoch = entry_ts
        except (ValueError, TypeError):
            pass

    # If manifest is empty, a scan is definitely needed
    if last_scan_epoch == 0.0 and not manifest.all_entries():
        return True

    for dir_name in scan_dirs:
        scan_path = vault_root / dir_name
        if not scan_path.is_dir():
            continue
        for file_path in scan_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                continue
            # Skip hidden/internal directories
            try:
                relative = file_path.relative_to(vault_root)
            except ValueError:
                continue
            if any(part in _SKIP_SCAN_DIRS or part.startswith(".") for part in relative.parts):
                continue
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue
            if mtime > last_scan_epoch:
                return True

    return False


def auto_scan_if_needed(
    vault_root: Path,
    scan_dirs: list[str],
    manifest: VaultManifest,
    cooldown_seconds: int = 30,
) -> ScanResult | None:
    """Run an incremental scan if the vault has changed since the last scan.

    Returns the ScanResult if a scan ran, or None if no scan was needed.
    The manifest is saved after a successful scan.
    """
    global _last_auto_scan_ts

    if not needs_scan(vault_root, manifest, scan_dirs, cooldown_seconds):
        return None

    result = scan_vault(vault_root, manifest, scan_dirs)
    _last_auto_scan_ts = time.time()

    # Index new/changed files
    if result.added or result.updated:
        from docmancer.vault.operations import sync_vault_index

        sync_vault_index(
            vault_root,
            manifest,
            added_paths=result.added,
            updated_paths=result.updated,
            removed_paths=result.removed,
        )

    manifest.save()
    return result


def reset_cooldown() -> None:
    """Reset the cooldown timer (useful for testing)."""
    global _last_auto_scan_ts
    _last_auto_scan_ts = 0.0
