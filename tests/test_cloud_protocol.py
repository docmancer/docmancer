from __future__ import annotations

import json
import hashlib
from pathlib import Path

import httpx
import pytest

from docmancer.cloud.apply import apply_envelopes, apply_payload, resolve_conflict
from docmancer.cloud.client import CloudClient, ProtocolError, ProtocolTooOldError, RateLimitedError
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, b64encode, box_keypair, random_key, signing_keypair, unwrap_key, wrap_key
from docmancer.cloud.envelope import build_envelope, open_envelope
from docmancer.cloud.entitlement import cache_entitlement, remote_transfer_allowed
from docmancer.cloud.keystore import KeyStore, MemorySecretBackend
from docmancer.cloud.lifecycle import (
    enqueue_revision_if_enabled,
    enqueue_revisions_if_enabled,
)
from docmancer.cloud.migrate import migrate_records
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.recovery import (
    _approval_message,
    create_recovery,
    recovery_approval,
    verify_recovery,
)
from docmancer.cloud.serialize import build_graph_payload, build_record_payload, canonicalize, revision_id
from docmancer.cloud.snapshot import build_snapshot, open_snapshot
from docmancer.cloud.sync import (
    _PUSH_BATCH_BYTES,
    _pull_all,
    _push_batches,
    _push_pending,
    sync_once,
)
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
    associated = {key: vector["envelope"][key] for key in ("algorithm", "key_version", "kind", "protocol_version", "record_ref", "revision_ref", "workspace_id")}
    aad = canonicalize(associated)
    assert b64encode(aad) == vector["associated_data_b64"]
    signature_input = b"docmancer-envelope-v1\0" + aad + b"\0" + b64decode(vector["envelope"]["nonce"]) + b64decode(vector["envelope"]["ciphertext"])
    assert hashlib.sha256(signature_input).hexdigest() == vector["signature_input_sha256"]
    rebuilt = build_envelope(
        vector["payload"], workspace_id=vector["envelope"]["workspace_id"],
        device_id=vector["envelope"]["created_by_device_id"],
        workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_private_key=b64decode(vector["signing_private_key_b64"]),
        _nonce=b64decode(vector["envelope"]["nonce"]),
        _envelope_id=vector["envelope"]["envelope_id"],
        _client_created_at=vector["envelope"]["client_created_at"],
    )
    assert rebuilt == vector["envelope"]
    assert open_envelope(
        vector["envelope"], workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_public_key=b64decode(vector["signing_public_key_b64"]),
    ) == vector["payload"]


def test_checked_cross_language_tree_protocol_vector():
    vector = json.loads(
        (Path(__file__).parent / "fixtures/cloud/protocol-v3-tree-python-ts.json").read_text(
            encoding="utf-8"
        )
    )
    associated = {
        key: vector["envelope"][key]
        for key in (
            "algorithm", "key_version", "kind", "protocol_version",
            "record_ref", "revision_ref", "workspace_id",
        )
    }
    aad = canonicalize(associated)
    signature_input = (
        b"docmancer-envelope-v3\0"
        + aad
        + b"\0"
        + b64decode(vector["envelope"]["nonce"])
        + b64decode(vector["envelope"]["ciphertext"])
    )
    assert canonicalize(vector["payload"]).decode() == vector["canonical_utf8"]
    assert b64encode(aad) == vector["associated_data_b64"]
    assert hashlib.sha256(signature_input).hexdigest() == vector["signature_input_sha256"]
    rebuilt = build_envelope(
        vector["payload"],
        workspace_id=vector["envelope"]["workspace_id"],
        device_id=vector["envelope"]["created_by_device_id"],
        workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_private_key=b64decode(vector["signing_private_key_b64"]),
        _nonce=b64decode(vector["envelope"]["nonce"]),
        _envelope_id=vector["envelope"]["envelope_id"],
        _client_created_at=vector["envelope"]["client_created_at"],
    )
    assert rebuilt == vector["envelope"]
    assert open_envelope(
        vector["envelope"],
        workspace_key=b64decode(vector["workspace_key_b64"]),
        signing_public_key=b64decode(vector["signing_public_key_b64"]),
    ) == vector["payload"]
    assert "/Users/" not in json.dumps(vector["envelope"])


def test_envelope_round_trip_and_tamper_detection():
    signing_private, signing_public = signing_keypair()
    workspace_key = random_key()
    envelope = build_envelope(payload(), workspace_id="ws_1", device_id="dev_1", workspace_key=workspace_key, signing_private_key=signing_private)
    assert "Use the portable" not in json.dumps(envelope)
    assert open_envelope(envelope, workspace_key=workspace_key, signing_public_key=signing_public) == payload()
    envelope["ciphertext"] = envelope["ciphertext"][:-1] + ("A" if envelope["ciphertext"][-1] != "A" else "B")
    with pytest.raises(Exception):
        open_envelope(envelope, workspace_key=workspace_key, signing_public_key=signing_public)


def test_protocol_v2_graph_envelope_round_trip_and_local_projection(tmp_path):
    graph_payload = build_graph_payload(
        object_kind="relation",
        object_id="rel_123",
        data={
            "relation_id": "rel_123",
            "relation_type": "contradicts",
            "source_node_id": "node:a",
            "target_node_id": "node:b",
            "resolution_state": "suggested",
        },
        updated_at="2026-07-20T10:00:00+00:00",
    )
    signing_private, signing_public = signing_keypair()
    workspace_key = random_key()
    envelope = build_envelope(
        graph_payload,
        workspace_id="00000000-0000-4000-8000-000000000001",
        device_id="00000000-0000-4000-8000-000000000002",
        workspace_key=workspace_key,
        signing_private_key=signing_private,
    )

    assert envelope["protocol_version"] == 2
    assert envelope["kind"] == "relation_revision"
    assert open_envelope(
        envelope, workspace_key=workspace_key, signing_public_key=signing_public
    ) == graph_payload
    assert apply_payload(graph_payload, root=tmp_path) == "applied"
    assert apply_payload(graph_payload, root=tmp_path) == "duplicate"


def test_protocol_v2_pack_envelope_contains_no_context_plaintext(tmp_path):
    pack_payload = build_graph_payload(
        object_kind="pack",
        object_id="personal-defaults",
        data={
            "pack_id": "personal-defaults",
            "name": "Personal defaults",
            "audience_kind": "personal",
            "applicability_kind": "global",
            "status": "active",
            "record_ids": ["record-typescript"],
            "created_at": "2026-07-20T10:00:00+00:00",
            "updated_at": "2026-07-20T10:00:00+00:00",
            "revision_id": "pack_local",
            "parent_revision_ids": [],
            "schema_version": 1,
        },
        updated_at="2026-07-20T10:00:00+00:00",
    )
    private, public = signing_keypair()
    key = random_key()
    envelope = build_envelope(
        pack_payload,
        workspace_id="00000000-0000-4000-8000-000000000001",
        device_id="00000000-0000-4000-8000-000000000002",
        workspace_key=key,
        signing_private_key=private,
    )
    encoded = json.dumps(envelope)
    assert envelope["kind"] == "pack_revision"
    assert "Personal defaults" not in encoded
    assert "record-typescript" not in encoded
    assert open_envelope(envelope, workspace_key=key, signing_public_key=public) == pack_payload


def test_client_rejects_mixed_protocol_push_batches():
    client = CloudClient("https://cloud.invalid", token="token", device_id="00000000-0000-4000-8000-000000000002")
    with pytest.raises(ProtocolError, match="cannot mix protocol versions"):
        client.push("workspace", [{"protocol_version": 1}, {"protocol_version": 2}])
    client.close()


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
    assert not state.enqueue(envelope)


def test_cloud_push_drains_every_bounded_protocol_batch(tmp_path):
    state = CloudState(tmp_path / "cloud-state.sqlite3")
    for index in range(235):
        state.enqueue(
            {
                "revision_ref": f"revision-{index}",
                "envelope_id": f"envelope-{index}",
                "protocol_version": 1 if index % 2 else 2,
            }
        )

    class Client:
        def __init__(self):
            self.batches = []

        def push(
            self,
            _workspace_id,
            envelopes,
            *,
            idempotency_key,
            cursor,
            protocol_version,
        ):
            assert idempotency_key
            assert cursor == 7
            assert len(envelopes) <= 100
            assert {item["protocol_version"] for item in envelopes} == {
                protocol_version
            }
            self.batches.append((protocol_version, len(envelopes)))
            return {
                "accepted": [item["envelope_id"] for item in envelopes],
                "already_present": [],
                "rejected": [],
            }

    client = Client()
    assert _push_pending(
        client,
        state=state,
        workspace_id="workspace",
        cursor=7,
    ) == 235
    assert state.status()["pending"] == 0
    assert sum(size for _version, size in client.batches) == 235


def test_cloud_push_splits_large_envelopes_below_the_request_byte_limit(tmp_path):
    state = CloudState(tmp_path / "cloud-state.sqlite3")
    for index in range(4):
        state.enqueue(
            {
                "revision_ref": f"revision-{index}",
                "envelope_id": f"envelope-{index}",
                "protocol_version": 3,
                "ciphertext": "x" * 2_500_000,
            }
        )

    class Client:
        def __init__(self):
            self.batches = []

        def push(
            self,
            _workspace_id,
            envelopes,
            *,
            idempotency_key,
            cursor,
            protocol_version,
        ):
            payload_bytes = len(
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
            assert payload_bytes <= _PUSH_BATCH_BYTES
            assert idempotency_key
            self.batches.append(len(envelopes))
            return {
                "accepted": [item["envelope_id"] for item in envelopes],
                "already_present": [],
                "rejected": [],
            }

    client = Client()
    assert _push_pending(
        client,
        state=state,
        workspace_id="workspace",
        cursor=0,
    ) == 4
    assert client.batches == [2, 2]
    assert state.status()["pending"] == 0


def test_cloud_push_preserves_an_individually_oversized_envelope():
    envelope = {
        "revision_ref": "revision-large",
        "envelope_id": "envelope-large",
        "protocol_version": 3,
        "ciphertext": "x" * _PUSH_BATCH_BYTES,
    }
    with pytest.raises(ValueError, match="exceeds the safe cloud request size"):
        _push_batches([envelope], cursor=0, protocol_version=3)


def test_cloud_pull_fetches_every_page_before_apply():
    class Client:
        def __init__(self):
            self.cursors = []

        def pull(self, _workspace_id, *, cursor, limit):
            self.cursors.append((cursor, limit))
            if cursor == "4":
                return {
                    "envelopes": [{"revision_ref": "r5"}],
                    "cursor": "5",
                    "has_more": False,
                }
            return {
                "envelopes": [
                    {"revision_ref": f"r{index}"} for index in range(1, 5)
                ],
                "cursor": "4",
                "has_more": True,
            }

    client = Client()
    envelopes, cursor = _pull_all(client, workspace_id="workspace", cursor=None)
    assert [item["revision_ref"] for item in envelopes] == [
        "r1",
        "r2",
        "r3",
        "r4",
        "r5",
    ]
    assert cursor == "5"
    assert client.cursors == [("0", 500), ("4", 500)]


def test_server_trial_entitlement_allows_push_and_normalizes_cache(tmp_path):
    entitlement = cache_entitlement(
        {
            "status": "trialing",
            "can_push": True,
            "can_pull": True,
            "can_export": True,
        },
        root=tmp_path,
    )
    assert entitlement["state"] == "trial"
    assert remote_transfer_allowed(entitlement)


def test_expired_entitlement_blocks_push_without_blocking_pull(tmp_path):
    entitlement = cache_entitlement(
        {
            "status": "past_due",
            "can_push": False,
            "can_pull": True,
            "can_export": True,
        },
        root=tmp_path,
    )
    assert entitlement["state"] == "past_due"
    assert not remote_transfer_allowed(entitlement)


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


def test_lifecycle_bulk_queue_skips_known_revisions(tmp_path):
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id="acct",
        workspace_id="ws",
        device_id="dev",
    )
    config.set_workspace("ws", key_version=1)
    keys = KeyStore(MemorySecretBackend())
    keys.ensure_device_keys("acct")
    keys.set_workspace_key("acct", "ws", random_key(), key_version=1)
    first = payload(record_id="record-1")
    second = payload(record_id="record-2", text="Keep encrypted sync idempotent.")

    assert enqueue_revisions_if_enabled(
        [first, second, first], root=tmp_path, keystore=keys
    ) == 2
    state = CloudState(config.paths.sync_state)
    queued = state.pending()
    assert len(queued) == 2
    state.acknowledge([item["revision_ref"] for item in queued])
    assert enqueue_revisions_if_enabled(
        [first, second], root=tmp_path, keystore=keys
    ) == 0


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

        def entitlement(self, _workspace_id):
            return {
                "status": "trialing",
                "can_push": True,
                "can_pull": True,
                "can_export": True,
            }

        def latest_snapshot(self, _workspace_id):
            raise RuntimeError("no snapshot")

        def pull(self, _workspace_id, *, cursor=None, limit=250):
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
    recovery_key, wrapper = create_recovery(
        "ws", workspace_key, root=tmp_path, key_version=3
    )
    assert wrapper["version"] == 2
    assert wrapper["key_version"] == 3
    assert verify_recovery(recovery_key, wrapper, root=tmp_path) == workspace_key
    MemoryRecordStore(tmp_path).add("Snapshot me")
    snapshot = build_snapshot(root=tmp_path, workspace_id="ws", workspace_key=workspace_key, cursor="5")
    opened = open_snapshot(snapshot, workspace_key=workspace_key)
    assert opened["cursor"] == "5"
    assert opened["heads"][0]["text"] == "Snapshot me"


def test_v2_recovery_signs_a_short_lived_device_approval(tmp_path):
    from docmancer.cloud.crypto import b64decode, verify

    recovery_key, wrapper = create_recovery(
        "workspace", random_key(), root=tmp_path, key_version=2
    )
    approval = recovery_approval(
        recovery_key,
        wrapper,
        device_id="device",
        sign_public_key="sign-public",
        box_public_key="box-public",
        wrapped_key="wrapped",
        key_version=2,
    )
    message = _approval_message(
        workspace_id="workspace",
        device_id="device",
        sign_public_key="sign-public",
        box_public_key="box-public",
        wrapped_key="wrapped",
        key_version=2,
        nonce=approval["nonce"],
        expires_at=approval["expires_at"],
    )
    verify(
        message,
        b64decode(approval["recovery_signature"]),
        b64decode(wrapper["recovery_verify_key"]),
    )


def test_client_headers_and_typed_non_destructive_errors():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.headers)
        return httpx.Response(429, json={"code": "RATE_LIMITED"})

    device_id = "00000000-0000-4000-8000-000000000002"
    workspace_id = "00000000-0000-4000-8000-000000000001"
    signing_private, _signing_public = signing_keypair()
    client = CloudClient(
        "https://cloud.invalid", token="token", device_id=device_id,
        signing_private_key=signing_private, transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RateLimitedError):
        client.push(workspace_id, [])
    assert seen["x-docmancer-protocol"] == "1"
    assert seen["x-docmancer-device-id"] == device_id
    assert seen["x-docmancer-client-version"]
    assert seen["x-docmancer-device-signature"]
    assert seen["x-docmancer-device-nonce"]
    assert seen["x-docmancer-device-body-sha256"]

    client = CloudClient(
        "https://cloud.invalid", token="token", device_id=device_id,
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json={"code": "PROTOCOL_TOO_OLD"})),
    )
    with pytest.raises(ProtocolTooOldError):
        client.pull(workspace_id)

    with pytest.raises(ProtocolError, match="canonical UUID"):
        CloudClient("https://cloud.invalid", token="token", device_id="dev_legacy")


def test_cloud_client_requires_https_except_for_loopback():
    device_id = "00000000-0000-4000-8000-000000000002"
    with pytest.raises(ValueError, match="must use HTTPS"):
        CloudClient("http://api.example.test", token="token", device_id=device_id)

    client = CloudClient("http://127.0.0.1:3001", token="token", device_id=device_id)
    client.close()


def test_cloud_client_rejects_credentials_query_and_fragment():
    device_id = "00000000-0000-4000-8000-000000000002"
    with pytest.raises(ValueError, match="without credentials"):
        CloudClient("https://user:pass@api.example.test", token="token", device_id=device_id)
    with pytest.raises(ValueError, match="query string or fragment"):
        CloudClient("https://api.example.test?token=secret", token="token", device_id=device_id)


def test_device_login_pending_response_is_typed_without_failure():
    client = CloudClient(
        "https://cloud.invalid", token="", device_id="00000000-0000-4000-8000-000000000002",
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json={"code": "AUTHORIZATION_PENDING"})),
    )
    assert client.poll_device_login("code")["code"] == "AUTHORIZATION_PENDING"


def test_python_cloud_routes_are_declared_by_sibling_openapi():
    """Catch transport drift when the client and cloud repos are checked out together."""
    import re

    client_path = Path(__file__).parents[1] / "docmancer" / "cloud" / "client.py"
    openapi_path = Path(__file__).parents[2] / "website" / "packages" / "protocol" / "openapi.yaml"
    if not openapi_path.exists():
        pytest.skip("website platform monorepo sibling checkout is unavailable")
    client_source = client_path.read_text(encoding="utf-8")
    openapi_source = openapi_path.read_text(encoding="utf-8")
    declared = set(re.findall(r"^  (/v1/[^:]+):$", openapi_source, re.MULTILINE))
    called = set(re.findall(r'[f]?"(/v1/[^"?]+)', client_source))
    called.discard("/v1/workspaces/")
    replacements = {
        "{workspace_id}": "{workspaceId}",
        "{device_id}": "{deviceId}",
        "{proposal_id}": "{proposalId}",
        "{job_id}": "{jobId}",
    }
    normalized = set()
    for path in called:
        for source, target in replacements.items():
            path = path.replace(source, target)
        normalized.add(path)
    assert normalized <= declared, f"Python cloud routes missing from OpenAPI: {sorted(normalized - declared)}"
