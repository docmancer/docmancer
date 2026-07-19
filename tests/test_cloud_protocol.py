from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from docmancer.cloud.apply import apply_envelopes, apply_payload, resolve_conflict
from docmancer.cloud.client import CloudClient, ProtocolTooOldError, RateLimitedError
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, b64encode, box_keypair, random_key, signing_keypair, unwrap_key, wrap_key
from docmancer.cloud.envelope import build_envelope, open_envelope
from docmancer.cloud.keystore import KeyStore, MemorySecretBackend
from docmancer.cloud.lifecycle import enqueue_revision_if_enabled
from docmancer.cloud.migrate import migrate_records
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.recovery import create_recovery, verify_recovery
from docmancer.cloud.serialize import build_record_payload, canonicalize, revision_id
from docmancer.cloud.snapshot import build_snapshot, open_snapshot
from docmancer.cloud.sync import sync_once
from docmancer.memory.records import MemoryRecordStore


def payload(**updates):
    values = {
        "record_id": "record-1", "text": "Use the portable project identity.",
        "memory_type": "decision", "tags": ["cloud", "protocol"],
        "origin_kind": "manual", "origin_harness": "docmancer", "scope_kind": "global",
        "project_id": None, "created_at": "2026-07-19T10:00:00+00:00",
        "updated_at": "2026-07-19T10:00:00+00:00",
    }
    values.update(updates)
    return build_record_payload(**values)


def test_revision_identity_is_canonical_and_detects_changes():
    first = payload(tags=["protocol", "cloud"])
    second = payload(tags=["cloud", "protocol"])
    assert canonicalize(first) == canonicalize(second)
    assert first["revision_id"] == second["revision_id"] == revision_id(first)
    assert payload(text="Changed")["revision_id"] != first["revision_id"]


def test_checked_cross_language_protocol_vector():
    vector = json.loads((Path(__file__).parent / "fixtures/cloud/protocol-v1-python-ts.json").read_text(encoding="utf-8"))
    assert canonicalize(vector["payload"]).decode("utf-8") == vector["canonical_utf8"]
    assert revision_id(vector["payload"]) == vector["revision_id"]
    rebuilt = build_envelope(
        vector["payload"], workspace_id="ws_0001", device_id="dev_0001",
        workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_private_key=b64decode(vector["signing_private_key_b64"]),
        _nonce=b64decode(vector["envelope"]["nonce"]),
    )
    assert rebuilt == vector["envelope"]
    assert open_envelope(
        vector["envelope"], workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_public_key=b64decode(vector["signing_public_key_b64"]),
    ) == vector["payload"]


def test_envelope_round_trip_and_tamper_detection():
    signing_private, signing_public = signing_keypair()
    workspace_key = random_key()
    envelope = build_envelope(payload(), workspace_id="ws_1", device_id="dev_1", workspace_key=workspace_key, signing_private_key=signing_private)
    assert "Use the portable" not in json.dumps(envelope)
    assert open_envelope(envelope, workspace_key=workspace_key, signing_public_key=signing_public) == payload()
    envelope["ciphertext"] = envelope["ciphertext"][:-1] + ("A" if envelope["ciphertext"][-1] != "A" else "B")
    with pytest.raises(Exception):
        open_envelope(envelope, workspace_key=workspace_key, signing_public_key=signing_public)


def test_key_store_and_sealed_box_use_no_plaintext_file():
    backend = MemorySecretBackend()
    store = KeyStore(backend)
    keys = store.ensure_device_keys("acct")
    workspace_key = random_key()
    store.set_workspace_key("acct", "ws", workspace_key)
    assert store.workspace_key("acct", "ws") == workspace_key
    assert unwrap_key(wrap_key(workspace_key, keys["box_public"]), keys["box_private"]) == workspace_key
    assert store.fingerprint(keys["signing_public"]).count(":") == 7


def test_outbox_is_idempotent_and_cursor_is_explicit(tmp_path):
    state = CloudState(tmp_path / "state.sqlite3")
    signing_private, _ = signing_keypair()
    envelope = build_envelope(payload(), workspace_id="ws", device_id="dev", workspace_key=random_key(), signing_private_key=signing_private)
    assert state.enqueue(envelope)
    assert not state.enqueue(envelope)
    assert state.status()["pending"] == 1
    first = state.idempotency_key("push")
    assert state.idempotency_key("push") == first
    state.set_meta("cursor", "cur_1")
    assert state.status()["cursor"] == "cur_1"
    state.acknowledge([envelope["revision_ref"]])
    assert state.status()["pending"] == 0


def test_lifecycle_queue_is_local_ciphertext_only(tmp_path):
    config = CloudConfig(tmp_path)
    config.save_account(enabled=True, account_id="acct", workspace_id="ws", device_id="dev")
    config.set_workspace("ws", key_version=1)
    keys = KeyStore(MemorySecretBackend())
    device = keys.ensure_device_keys("acct")
    keys.set_workspace_key("acct", "ws", random_key(), key_version=1)
    assert enqueue_revision_if_enabled(payload(), root=tmp_path, keystore=keys)
    pending = CloudState(config.paths.sync_state).pending()
    assert len(pending) == 1
    assert "portable project identity" not in json.dumps(pending)
    assert pending[0]["key_version"] == 1
    assert device["signing_private"] not in config.paths.sync_state.read_bytes()


def test_unmapped_project_never_falls_back_to_global(tmp_path):
    remote = payload(scope_kind="project", project_id="prj_remote")
    assert apply_payload(remote, root=tmp_path) == "deferred"
    state = CloudState(CloudConfig(tmp_path).paths.sync_state)
    assert state.conflicts()[0]["reason"] == "unmapped_project"
    assert MemoryRecordStore(tmp_path).find_record("record-1") is None


def test_legacy_project_record_gains_portable_identity(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = tmp_path / "memories" / "legacy.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nrecord_id: legacy\ntype: fact\ntags: []\norigin: manual\n"
        f"scope_kind: project\nproject_path: {project}\ncreated_at: '2026-01-01T00:00:00+00:00'\n"
        "updated_at: '2026-01-01T00:00:00+00:00'\nharness: docmancer\nsource_path: ''\n"
        "schema_version: 1\nsession_id: null\npromoted_from: null\n---\n\nLegacy project memory\n",
        encoding="utf-8",
    )
    record = MemoryRecordStore(tmp_path).read_record(path)
    assert record is not None
    assert record.project_id is None
    assert not CloudConfig(tmp_path).paths.workspaces.exists()
    assert record.revision_id.startswith("rev_")
    result = migrate_records(root=tmp_path, project_paths=[project])
    assert result["records"] == 1
    migrated = MemoryRecordStore(tmp_path).read_record(path)
    assert migrated is not None and migrated.project_id.startswith("prj_")
    assert MemoryRecordStore(tmp_path).revisions("legacy")


def test_unmapped_envelope_is_retried_after_project_link(tmp_path):
    signing_private, signing_public = signing_keypair()
    workspace_key = random_key()
    remote = payload(scope_kind="project", project_id="prj_remote")
    envelope = build_envelope(
        remote, workspace_id="ws", device_id="peer", workspace_key=workspace_key,
        signing_private_key=signing_private,
    )

    first = apply_envelopes(
        [envelope], root=tmp_path, workspace_key=workspace_key,
        device_public_keys={"peer": signing_public}, cursor="cur_1",
    )
    state = CloudState(CloudConfig(tmp_path).paths.sync_state)
    assert first["deferred"] == 1
    assert state.get_meta("cursor") is None
    assert not state.is_applied(envelope["revision_ref"])

    project = tmp_path / "project"
    project.mkdir()
    CloudConfig(tmp_path).link_project("prj_remote", project)
    second = apply_envelopes(
        [envelope], root=tmp_path, workspace_key=workspace_key,
        device_public_keys={"peer": signing_public}, cursor="cur_1",
    )
    assert second["applied"] == 1
    assert state.get_meta("cursor") == "cur_1"
    assert state.conflicts() == []
    assert MemoryRecordStore(tmp_path).find_record("record-1", project_paths=[project]) is not None


def test_project_conflict_resolution_requires_live_mapping(tmp_path):
    remote = payload(scope_kind="project", project_id="prj_missing")
    assert apply_payload(remote, root=tmp_path) == "deferred"
    conflict_id = CloudState(CloudConfig(tmp_path).paths.sync_state).conflicts()[0]["conflict_id"]
    with pytest.raises(ValueError, match="cloud link"):
        resolve_conflict(conflict_id, "keep-right", root=tmp_path)
    assert MemoryRecordStore(tmp_path).revisions("record-1") == []


def test_append_revision_loads_existing_ids_once_per_store(tmp_path, monkeypatch):
    store = MemoryRecordStore(tmp_path)
    calls = 0
    original = store.revisions

    def counted(record_id):
        nonlocal calls
        calls += 1
        return original(record_id)

    monkeypatch.setattr(store, "revisions", counted)
    for index in range(20):
        store.append_revision(payload(updated_at=f"2026-07-19T10:00:{index:02d}+00:00"))
    assert calls == 1


def test_sync_refreshes_peer_keys_and_rotated_workspace_key(tmp_path):
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True, account_id="acct", workspace_id="ws", device_id="local",
        base_url="https://cloud.invalid",
    )
    config.set_workspace("ws", key_version=1)
    keys = KeyStore(MemorySecretBackend())
    local_keys = keys.ensure_device_keys("acct")
    keys.set_token("acct", "token")
    keys.set_workspace_key("acct", "ws", random_key(), key_version=1)
    peer_private, peer_public = signing_keypair()
    rotated_key = random_key()
    envelope = build_envelope(
        payload(), workspace_id="ws", device_id="peer", workspace_key=rotated_key,
        signing_private_key=peer_private, key_version=2,
    )

    class Client:
        def devices(self, _workspace_id):
            return {
                "current_key_version": 2,
                "devices": [
                    {
                        "device_id": "local", "state": "approved", "key_version": 2,
                        "signing_public_key": b64encode(local_keys["signing_public"]),
                        "box_public_key": b64encode(local_keys["box_public"]),
                    },
                    {
                        "device_id": "peer", "state": "approved", "key_version": 2,
                        "signing_public_key": b64encode(peer_public),
                    },
                ],
            }

        def key_wrapper(self, _workspace_id, _device_id, _key_version):
            return {"wrapped_key": b64encode(wrap_key(rotated_key, local_keys["box_public"]))}

        def entitlement(self):
            return {"state": "active"}

        def latest_snapshot(self, _workspace_id):
            raise RuntimeError("no snapshot")

        def pull(self, _workspace_id, *, cursor=None):
            return {"envelopes": [envelope], "cursor": "cur_2"}

    result = sync_once(Client(), root=tmp_path, keystore=keys)
    assert result["applied"] == 1
    assert keys.workspace_key("acct", "ws", 2) == rotated_key
    workspace = config.workspace("ws")[1]
    assert workspace["key_version"] == 2
    assert set(workspace["device_public_keys"]) == {"local", "peer"}


def test_remote_lineage_apply_and_conflict(tmp_path):
    store = MemoryRecordStore(tmp_path)
    local = store.add("First", record_id="same")
    child = payload(
        record_id="same", text="Second", created_at=local.created_at,
        parent_revision_ids=[local.revision_id], updated_at="2026-07-19T12:00:00+00:00",
    )
    assert apply_payload(child, root=tmp_path) == "applied"
    assert store.find_record("same").text == "Second"
    branch = payload(record_id="same", text="Other", created_at=local.created_at, updated_at="2026-07-19T12:01:00+00:00")
    assert apply_payload(branch, root=tmp_path) == "conflict"
    from docmancer.cloud.apply import resolve_conflict

    conflict_id = CloudState(CloudConfig(tmp_path).paths.sync_state).conflicts()[0]["conflict_id"]
    merged = resolve_conflict(conflict_id, "keep-both", root=tmp_path)
    assert set(merged["parent_revision_ids"]) == {child["revision_id"], branch["revision_id"]}
    assert "Second" in merged["text"] and "Other" in merged["text"]


def test_recovery_and_snapshot_round_trip(tmp_path):
    workspace_key = random_key()
    recovery_key, wrapper = create_recovery("ws", workspace_key, root=tmp_path)
    assert verify_recovery(recovery_key, wrapper, root=tmp_path) == workspace_key
    MemoryRecordStore(tmp_path).add("Snapshot me")
    snapshot = build_snapshot(root=tmp_path, workspace_id="ws", workspace_key=workspace_key, cursor="5")
    opened = open_snapshot(snapshot, workspace_key=workspace_key)
    assert opened["cursor"] == "5"
    assert opened["heads"][0]["text"] == "Snapshot me"


def test_client_headers_and_typed_non_destructive_errors():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.headers)
        return httpx.Response(429, json={"code": "RATE_LIMITED"})

    client = CloudClient("https://cloud.invalid", token="token", device_id="dev", transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimitedError):
        client.push("ws", [])
    assert seen["x-docmancer-protocol"] == "1"
    assert seen["x-docmancer-device-id"] == "dev"
    assert seen["x-docmancer-client-version"]

    client = CloudClient(
        "https://cloud.invalid", token="token", device_id="dev",
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json={"code": "PROTOCOL_TOO_OLD"})),
    )
    with pytest.raises(ProtocolTooOldError):
        client.pull("ws")


def test_device_login_pending_response_is_typed_without_failure():
    client = CloudClient(
        "https://cloud.invalid", token="", device_id="dev",
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json={"code": "AUTHORIZATION_PENDING"})),
    )
    assert client.poll_device_login("code")["code"] == "AUTHORIZATION_PENDING"
