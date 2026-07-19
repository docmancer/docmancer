"""Best-effort local mutation hooks. This module performs no network I/O."""
from __future__ import annotations

from pathlib import Path

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.envelope import build_envelope
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.outbox import CloudState


def enqueue_revision_if_enabled(payload: dict, *, root: str | Path, keystore: KeyStore | None = None) -> bool:
    config = CloudConfig(root)
    account = config.account()
    workspace = config.workspace()
    if not config.enabled() or workspace is None:
        return False
    account_id = str(account.get("account_id") or "")
    device_id = str(account.get("device_id") or "")
    workspace_id = workspace[0]
    key_version = int(workspace[1].get("key_version") or 1)
    if not account_id or not device_id:
        return False
    keys = keystore or KeyStore()
    workspace_key = keys.workspace_key(account_id, workspace_id)
    signing_private = keys.get(account_id, "device-signing-private")
    if not workspace_key or not signing_private:
        return False
    envelope = build_envelope(
        payload, workspace_id=workspace_id, device_id=device_id,
        workspace_key=workspace_key, signing_private_key=signing_private, key_version=key_version,
    )
    return CloudState(config.paths.sync_state).enqueue(envelope)


__all__ = ["enqueue_revision_if_enabled"]
