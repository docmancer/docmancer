#!/usr/bin/env python3
"""Exercise Protocol v1 between two isolated local clients, with no server."""
from __future__ import annotations

import tempfile
from pathlib import Path

from docmancer.cloud.apply import apply_payload
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import random_key, signing_keypair
from docmancer.cloud.envelope import build_envelope, open_envelope
from docmancer.memory.records import MemoryRecordStore


def transfer(payload: dict, *, workspace_key: bytes, signing_private: bytes, signing_public: bytes) -> dict:
    envelope = build_envelope(
        payload, workspace_id="ws_local_smoke", device_id="device_a",
        workspace_key=workspace_key, signing_private_key=signing_private,
    )
    return open_envelope(envelope, workspace_key=workspace_key, signing_public_key=signing_public)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="docmancer-cloud-smoke-") as temporary:
        base = Path(temporary)
        root_a, root_b = base / "client-a", base / "client-b"
        project_a, project_b = base / "checkout-a", base / "checkout-b"
        project_a.mkdir(parents=True)
        project_b.mkdir(parents=True)
        store_a = MemoryRecordStore(root_a)
        project_id = CloudConfig(root_a).ensure_project(project_a)
        CloudConfig(root_b).link_project(project_id, project_b)
        workspace_key = random_key()
        signing_private, signing_public = signing_keypair()

        created = store_a.add("Local smoke create", scope_kind="project", project_path=project_a)
        assert apply_payload(
            transfer(created.to_revision_payload(), workspace_key=workspace_key, signing_private=signing_private, signing_public=signing_public),
            root=root_b,
        ) == "applied"

        edited = store_a.update_record(created, "Local smoke edit")
        assert apply_payload(
            transfer(edited.to_revision_payload(), workspace_key=workspace_key, signing_private=signing_private, signing_public=signing_public),
            root=root_b,
        ) == "applied"
        remote = MemoryRecordStore(root_b).find_record(created.record_id, project_paths=[project_b])
        assert remote is not None and remote.text == "Local smoke edit"

        tombstone = store_a.append_tombstone_revision(edited)
        assert apply_payload(
            transfer(tombstone, workspace_key=workspace_key, signing_private=signing_private, signing_public=signing_public),
            root=root_b,
        ) == "applied"
        assert MemoryRecordStore(root_b).find_record(created.record_id, project_paths=[project_b]) is None
        print("cloud local smoke: create, edit, encrypted transfer, and tombstone replay passed")


if __name__ == "__main__":
    main()
