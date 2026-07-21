"""Best-effort local mutation hooks. This module performs no network I/O."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import opaque_ref
from docmancer.cloud.envelope import build_envelope
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.outbox import CloudState


def enqueue_revision_if_enabled(
    payload: dict[str, Any],
    *,
    root: str | Path,
    keystore: KeyStore | None = None,
) -> bool:
    return bool(enqueue_revisions_if_enabled([payload], root=root, keystore=keystore))


def enqueue_revisions_if_enabled(
    payloads: Iterable[dict[str, Any]],
    *,
    root: str | Path,
    keystore: KeyStore | None = None,
) -> int:
    """Encrypt and queue many revisions with one config, key, and DB session."""
    config = CloudConfig(root)
    account = config.account()
    workspace = config.workspace()
    if not config.enabled() or workspace is None:
        return 0
    account_id = str(account.get("account_id") or "")
    device_id = str(account.get("device_id") or "")
    workspace_id = workspace[0]
    key_version = int(workspace[1].get("key_version") or 1)
    if not account_id or not device_id:
        return 0
    keys = keystore or KeyStore()
    workspace_key = keys.workspace_key(account_id, workspace_id)
    signing_private = keys.get(account_id, "device-signing-private")
    if not workspace_key or not signing_private:
        return 0
    state = CloudState(config.paths.sync_state)
    known_refs = state.known_revision_refs()

    def new_envelopes() -> Iterator[dict[str, Any]]:
        for payload in payloads:
            revision_ref = opaque_ref(
                str(payload["revision_id"]),
                workspace_key,
                workspace_id=workspace_id,
                kind="revision",
            )
            if revision_ref in known_refs:
                continue
            known_refs.add(revision_ref)
            yield build_envelope(
                payload,
                workspace_id=workspace_id,
                device_id=device_id,
                workspace_key=workspace_key,
                signing_private_key=signing_private,
                key_version=key_version,
            )

    return state.enqueue_many(new_envelopes())


__all__ = ["enqueue_revision_if_enabled", "enqueue_revisions_if_enabled"]
