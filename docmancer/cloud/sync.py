"""Explicit push/pull coordinator."""
from __future__ import annotations

import json
from pathlib import Path

from docmancer.cloud.apply import apply_envelopes
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.entitlement import cache_entitlement, remote_transfer_allowed


_PUSH_BATCH_SIZE = 100
_PUSH_BATCH_BYTES = 6_000_000
_MAX_ENVELOPE_BYTES = 1_200_000
_PULL_PAGE_SIZE = 500
_MAX_PULL_PAGES = 100


def _push_batches(
    envelopes: list[dict],
    *,
    cursor: int,
    protocol_version: int,
) -> list[list[dict]]:
    """Split one protocol group below both the count and request-byte limits."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    for envelope in envelopes:
        candidate = [*current, envelope]
        encoded_bytes = encoded_request_bytes(
            candidate,
            cursor=cursor,
            protocol_version=protocol_version,
        )
        if encoded_bytes <= _PUSH_BATCH_BYTES:
            current = candidate
            continue
        if not current:
            raise ValueError(
                "one encrypted revision exceeds the safe cloud request size; "
                "the encrypted outbox was preserved"
            )
        batches.append(current)
        single_bytes = encoded_request_bytes(
            [envelope],
            cursor=cursor,
            protocol_version=protocol_version,
        )
        if single_bytes > _PUSH_BATCH_BYTES:
            raise ValueError(
                "one encrypted revision exceeds the safe cloud request size; "
                "the encrypted outbox was preserved"
            )
        current = [envelope]
    if current:
        batches.append(current)
    return batches


def encoded_request_bytes(
    envelopes: list[dict], *, cursor: int, protocol_version: int,
) -> int:
    """Return the UTF-8 JSON size sent to the sync push endpoint."""
    return len(
        json.dumps(
            {
                "protocol_version": protocol_version,
                "base_cursor": cursor,
                "device_ack_cursor": cursor,
                "envelopes": envelopes,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _push_pending(client, *, state: CloudState, workspace_id: str, cursor: int) -> int:
    """Drain the durable outbox in bounded, single-protocol batches."""
    pushed = 0
    while pending := state.pending(limit=_PUSH_BATCH_SIZE):
        batches: dict[int, list[dict]] = {}
        for envelope in pending:
            batches.setdefault(int(envelope.get("protocol_version") or 1), []).append(envelope)
        acknowledged_this_round = 0
        for version, protocol_batch in sorted(batches.items()):
            for batch in _push_batches(
                protocol_batch,
                cursor=cursor,
                protocol_version=version,
            ):
                operation = f"push:v{version}"
                response = client.push(
                    workspace_id,
                    batch,
                    idempotency_key=state.idempotency_key(operation),
                    cursor=cursor,
                    protocol_version=version,
                )
                newly_accepted = {str(value) for value in response.get("accepted", [])}
                accepted_ids = set(newly_accepted)
                accepted_ids.update(str(value) for value in response.get("already_present", []))
                acknowledged_refs = [
                    str(envelope["revision_ref"])
                    for envelope in batch
                    if str(envelope.get("envelope_id")) in accepted_ids
                ]
                state.acknowledge(acknowledged_refs)
                state.clear_idempotency_key(operation)
                acknowledged_this_round += len(acknowledged_refs)
                pushed += len(newly_accepted)
                rejected = list(response.get("rejected") or [])
                if rejected:
                    codes = sorted({str(item.get("code") or "UNKNOWN") for item in rejected})
                    raise ValueError(
                        f"cloud rejected {len(rejected)} encrypted envelope(s): {', '.join(codes)}"
                    )
        if acknowledged_this_round == 0:
            raise ValueError("cloud push made no progress; encrypted outbox was preserved")
    return pushed


def _pull_all(client, *, workspace_id: str, cursor: str | None) -> tuple[list[dict], str]:
    """Fetch every available encrypted page before one durable apply/reindex."""
    envelopes: list[dict] = []
    current = str(cursor or "0")
    for _page in range(_MAX_PULL_PAGES):
        response = client.pull(workspace_id, cursor=current, limit=_PULL_PAGE_SIZE)
        page = list(response.get("envelopes") or [])
        next_cursor = str(response.get("cursor", current))
        envelopes.extend(page)
        if not response.get("has_more"):
            return envelopes, next_cursor
        if not page or next_cursor == current:
            raise ValueError("cloud pull made no progress; local cursor was not advanced")
        current = next_cursor
    raise ValueError("cloud pull exceeded the safe page limit")


def _refresh_workspace_metadata(client, *, config, account: dict, keys: KeyStore, workspace_id: str, metadata: dict) -> dict:
    """Refresh approved device keys and the current wrapped workspace key."""
    from docmancer.cloud.crypto import b64decode, unwrap_key

    response = client.devices(workspace_id)
    rows = list(response.get("devices") or [])
    signing_keys: dict[str, str] = {}
    box_keys: dict[str, str] = {}
    approved_rows: list[dict] = []
    for row in rows:
        state = str(row.get("state") or "approved")
        if state != "approved" or row.get("approved") is False:
            continue
        approved_rows.append(row)
        device_id = str(row.get("device_id") or row.get("id") or "")
        signing_key = row.get("signing_public_key") or row.get("sign_public_key")
        box_key = row.get("box_public_key") or row.get("box_pubkey")
        if device_id and signing_key:
            signing_keys[device_id] = str(signing_key)
        if device_id and box_key:
            box_keys[device_id] = str(box_key)

    current_key_version = int(
        response.get("current_key_version")
        or response.get("key_version")
        or max((int(row.get("key_version") or 0) for row in approved_rows), default=0)
        or metadata.get("key_version")
        or 1
    )
    account_id = str(account["account_id"])
    device_id = str(account["device_id"])
    if keys.workspace_key(account_id, workspace_id, current_key_version) is None:
        wrapper = client.key_wrapper(workspace_id, device_id, current_key_version)
        wrapped_key = wrapper.get("wrapped_key") or wrapper.get("workspace_key_wrapper")
        box_private = keys.get(account_id, "device-box-private")
        if not wrapped_key or not box_private:
            raise ValueError(f"workspace key version {current_key_version} is unavailable on this device")
        workspace_key = unwrap_key(b64decode(str(wrapped_key)), box_private)
        keys.set_workspace_key(account_id, workspace_id, workspace_key, key_version=current_key_version)

    updates = {"key_version": current_key_version}
    if signing_keys:
        updates["device_public_keys"] = signing_keys
    if box_keys:
        updates["device_box_public_keys"] = box_keys
    config.set_workspace(workspace_id, **updates)
    return {**metadata, **updates}


def sync_once(client, *, root: str | Path, keystore: KeyStore | None = None) -> dict:
    config = CloudConfig(root)
    account = config.account()
    workspace = config.workspace()
    if not config.enabled() or workspace is None:
        raise ValueError("cloud sync is not configured; run `docmancer cloud connect`")
    account_id = str(account["account_id"])
    workspace_id, metadata = workspace
    keys = keystore or KeyStore()
    metadata = _refresh_workspace_metadata(
        client, config=config, account=account, keys=keys,
        workspace_id=workspace_id, metadata=metadata,
    )
    current_key_version = int(metadata.get("key_version") or 1)
    workspace_key = keys.workspace_key(account_id, workspace_id, current_key_version) or keys.workspace_key(account_id, workspace_id)
    if not workspace_key:
        raise ValueError("workspace key is unavailable on this device")
    state = CloudState(config.paths.sync_state)
    from docmancer.cloud.connect import enqueue_project
    from docmancer.cloud.tree_sync import (
        queue_machine_tree_changes,
        queue_tree_changes,
    )

    projection_count = 0
    for project_id in config.workspaces().get("projects", {}):
        mapping = config.mapping_status(str(project_id))
        if mapping["state"] != "mapped":
            continue
        enqueue_project(
            Path(root),
            keys,
            Path(mapping["paths"][0]),
            db_path=Path(root) / "memory.db",
        )
        projection_count += 1

    tree_changes = queue_machine_tree_changes(root=root, keystore=keys)
    for project_id, row in config.workspaces().get("projects", {}).items():
        mapping = config.mapping_status(str(project_id))
        if mapping["state"] == "mapped":
            update = queue_tree_changes(mapping["paths"][0], root=root, keystore=keys)
            tree_changes = {
                "changed": tree_changes["changed"] + update["changed"],
                "queued": tree_changes["queued"] + update["queued"],
            }
    entitlement = cache_entitlement(client.entitlement(workspace_id), root=root)
    can_push = remote_transfer_allowed(entitlement)
    if metadata.get("policy_enabled"):
        from docmancer.cloud.policy import apply_policy

        acknowledgement = apply_policy(client.policy(workspace_id), root=root)
        client.acknowledge_policy(workspace_id, acknowledgement)
    pushed = 0
    if can_push:
        pushed = _push_pending(
            client,
            state=state,
            workspace_id=workspace_id,
            cursor=int(state.get_meta("cursor") or 0),
        )
    envelopes, pull_cursor = _pull_all(
        client,
        workspace_id=workspace_id,
        cursor=state.get_meta("cursor"),
    )
    public_keys = {
        str(device_id): __import__("docmancer.cloud.crypto", fromlist=["b64decode"]).b64decode(value)
        for device_id, value in dict(metadata.get("device_public_keys") or {}).items()
    }
    key_versions = {
        version: value for version in range(1, current_key_version + 1)
        if (value := keys.workspace_key(account_id, workspace_id, version)) is not None
    }
    key_versions.setdefault(current_key_version, workspace_key)
    applied = apply_envelopes(
        envelopes,
        root=root,
        workspace_key=key_versions,
        device_public_keys=public_keys,
        cursor=pull_cursor,
    )
    return {
        "pushed": pushed,
        "paused": not can_push,
        "projection_snapshots": projection_count,
        "tree_changes": tree_changes,
        **applied,
        **state.status(),
    }


__all__ = ["sync_once"]
