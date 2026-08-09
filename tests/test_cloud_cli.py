from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode
from docmancer.cloud.keystore import KeyStore, MemorySecretBackend


def test_cloud_commands_are_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["cloud", "status", "--json"])
    assert result.exit_code == 0
    assert '"configured": false' in result.output


def test_cloud_status_explains_the_next_step(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))

    result = CliRunner().invoke(cli, ["cloud", "status"])

    assert result.exit_code == 0
    assert "Personal Sync: not connected" in result.output
    assert "docmancer cloud connect" in result.output
    assert '"configured"' not in result.output


def test_cloud_status_exposes_pending_registration_without_reading_keychain(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands

    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=False,
        account_id="account-1",
        workspace_id="workspace-1",
        device_id="device-1",
        base_url="https://cloud.invalid",
    )
    backend = MemorySecretBackend()
    keys = KeyStore(backend)
    keys.set_token("account-1", "token")
    keys.ensure_device_keys("account-1")
    keys.set_workspace_key("account-1", "workspace-1", b"w" * 32)
    monkeypatch.setattr(cloud_commands, "KeyStore", lambda: keys)

    value = cloud_commands.cloud_status(tmp_path)
    result = CliRunner().invoke(cli, ["cloud", "status"])

    assert value["registered"] is True
    assert value["connection_state"] == "pending_approval"
    assert value["local_keys"] == {
        "checked": False,
        "device_identity_available": None,
        "workspace_key_available": None,
    }
    assert result.exit_code == 0
    assert "device registered, awaiting approval" in result.output
    assert "Local key material: not checked" in result.output
    assert "trusted machine" in result.output


def test_cloud_status_checks_keychain_only_when_explicitly_requested(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands

    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id="account-1",
        workspace_id="workspace-1",
        device_id="device-1",
    )
    keys = KeyStore(MemorySecretBackend())
    keys.ensure_device_keys("account-1")
    keys.set_workspace_key("account-1", "workspace-1", b"w" * 32)
    monkeypatch.setattr(cloud_commands, "KeyStore", lambda: keys)

    value = cloud_commands.cloud_status(tmp_path, check_keychain=True)

    assert value["local_keys"] == {
        "checked": True,
        "device_identity_available": True,
        "workspace_key_available": True,
    }


def test_cloud_status_summarises_connected_state(monkeypatch):
    from docmancer.cli import cloud_commands

    monkeypatch.setattr(
        cloud_commands,
        "cloud_status",
        lambda **_kwargs: {
            "configured": True,
            "account_id": "account-1",
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "continuous_audit": False,
            "entitlement": "trial",
            "recovery": {"configured": True, "verified": True},
            "pending": 7650,
            "conflicts": 0,
            "cursor": None,
        },
    )

    result = CliRunner().invoke(cli, ["cloud", "status"])

    assert result.exit_code == 0
    assert "Personal Sync: connected" in result.output
    assert "Recovery: decrypt only" in result.output
    assert "Sync queue: 7,650 pending, 0 conflicts" in result.output
    assert "Last sync cursor: none yet" in result.output
    assert "Next: run `docmancer cloud sync`" in result.output
    assert '"pending"' not in result.output


def test_cloud_estimate_reports_size_limits_and_does_not_sync(monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import estimate as estimate_module

    class Client:
        def entitlement(self, _workspace_id):
            return {"status": "active", "can_push": True}

        def close(self):
            pass

    monkeypatch.setattr(
        cloud_commands,
        "_client",
        lambda: (
            Client(),
            object(),
            object(),
            {"workspace_id": "workspace-1"},
            object(),
        ),
    )
    monkeypatch.setattr(
        estimate_module,
        "estimate_sync",
        lambda **_kwargs: {
            "plan": {"key": "sync", "status": "active", "can_push": True},
            "estimate": {
                "total_envelopes": 3,
                "upload_batches": 1,
                "upload_request_bytes": 2400,
                "encrypted_envelope_bytes": 2200,
                "encrypted_ciphertext_bytes": 1500,
                "new_plaintext_bytes": 1200,
                "existing_queued_envelopes": 1,
                "new_envelopes": 2,
            },
            "limits": {
                "source": "service",
                "sync_storage_bytes": None,
                "max_envelope_bytes": 1_200_000,
                "max_batch_bytes": 8_000_000,
                "max_batch_count": 100,
                "client_batch_target_bytes": 6_000_000,
                "backup_storage_bytes": 1_000_000_000,
            },
            "by_kind": {"record_revision": {"envelopes": 2}},
            "issues": [],
        },
    )

    result = CliRunner().invoke(cli, ["cloud", "estimate"])

    assert result.exit_code == 0
    assert "Will send: 3 encrypted envelope(s) in 1 request(s)" in result.output
    assert "Estimated upload: 2.4 KB" in result.output
    assert "no stored-memory quota" in result.output
    assert "Agent backup storage: 1 GB (separate from Personal Sync)" in result.output
    assert "Nothing was queued or uploaded" in result.output


def test_cloud_disable_does_not_remove_local_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))
    memory = tmp_path / "memories" / "keep.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("keep", encoding="utf-8")
    result = CliRunner().invoke(cli, ["cloud", "disable"])
    assert result.exit_code == 0
    assert memory.read_text(encoding="utf-8") == "keep"


def test_cloud_connect_is_idempotent_for_an_existing_device(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import connect as connect_module

    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id="00000000-0000-4000-8000-000000000001",
        workspace_id="00000000-0000-4000-8000-000000000002",
        device_id="00000000-0000-4000-8000-000000000003",
        base_url="https://cloud.invalid",
    )
    keys = KeyStore(MemorySecretBackend())
    keys.set_token("00000000-0000-4000-8000-000000000001", "token")
    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def devices(self, _workspace_id):
            return {
                "devices": [
                    {
                        "device_id": "00000000-0000-4000-8000-000000000003",
                        "state": "approved",
                    }
                ]
            }

        def close(self):
            pass

    monkeypatch.setattr(
        cloud_commands,
        "_context",
        lambda: (tmp_path, config, config.account(), keys),
    )
    monkeypatch.setattr(connect_module, "CloudClient", Client)

    result = CliRunner().invoke(
        cli,
        ["cloud", "connect", "--base-url", "https://cloud.invalid"],
    )

    assert result.exit_code == 0
    assert "is connected" in result.output
    assert "Open " not in result.output
    assert config.account()["device_id"] == "00000000-0000-4000-8000-000000000003"


def test_cloud_connect_resumes_the_same_pending_device(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import connect as connect_module

    account_id = "00000000-0000-4000-8000-000000000001"
    workspace_id = "00000000-0000-4000-8000-000000000002"
    device_id = "00000000-0000-4000-8000-000000000003"
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=False,
        account_id=account_id,
        workspace_id=workspace_id,
        device_id=device_id,
        base_url="https://cloud.invalid",
    )
    keys = KeyStore(MemorySecretBackend())
    keys.set_token(account_id, "token")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def devices(self, _workspace_id):
            return {
                "devices": [
                    {
                        "device_id": device_id,
                        "state": "pending",
                        "fingerprint": "docmancer-existing",
                    }
                ]
            }

        def close(self):
            pass

    monkeypatch.setattr(
        cloud_commands,
        "_context",
        lambda: (tmp_path, config, config.account(), keys),
    )
    monkeypatch.setattr(connect_module, "CloudClient", Client)

    result = CliRunner().invoke(
        cli,
        ["cloud", "connect", "--base-url", "https://cloud.invalid"],
    )

    assert result.exit_code == 0
    assert "waiting for approval" in result.output
    assert "dawn willow juniper reed" in result.output
    assert config.account()["device_id"] == device_id


def test_cloud_connect_recovers_an_already_registered_pending_device(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import connect as connect_module

    account_id = "00000000-0000-4000-8000-000000000001"
    workspace_id = "00000000-0000-4000-8000-000000000002"
    device_id = "00000000-0000-4000-8000-000000000003"
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=False,
        account_id=account_id,
        workspace_id=workspace_id,
        device_id=device_id,
        base_url="https://cloud.invalid",
    )
    keys = KeyStore(MemorySecretBackend())
    keys.set_token(account_id, "token")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def devices(self, _workspace_id):
            return {
                "devices": [
                    {
                        "device_id": device_id,
                        "state": "pending",
                        "fingerprint": "docmancer-existing",
                    }
                ]
            }

        def close(self):
            pass

    recovered: list[tuple[str, bool]] = []
    synced: list[bool] = []
    monkeypatch.setattr(
        cloud_commands,
        "_context",
        lambda: (tmp_path, config, config.account(), keys),
    )
    monkeypatch.setattr(connect_module, "CloudClient", Client)
    monkeypatch.setattr(
        cloud_commands,
        "_verify_recovery",
        lambda key, *, approve_pending=False: recovered.append((key, approve_pending)),
    )
    monkeypatch.setattr(cloud_commands, "_run_sync_command", lambda: synced.append(True))

    result = CliRunner().invoke(
        cli,
        [
            "cloud",
            "connect",
            "--base-url",
            "https://cloud.invalid",
            "--recovery-key",
            "offline-kit",
        ],
    )

    assert result.exit_code == 0
    assert recovered == [("offline-kit", True)]
    assert synced == [True]
    assert "Recovery approved this machine" in result.output


def test_cloud_devices_lists_fingerprints_and_revokes_one_device(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import connect as connect_module

    account_id = "00000000-0000-4000-8000-000000000001"
    workspace_id = "00000000-0000-4000-8000-000000000002"
    local_device_id = "00000000-0000-4000-8000-000000000003"
    remote_device_id = "00000000-0000-4000-8000-000000000004"
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id=account_id,
        workspace_id=workspace_id,
        device_id=local_device_id,
        base_url="https://cloud.invalid",
    )
    rows = [
        {
            "device_id": local_device_id,
            "state": "approved",
            "fingerprint": "docmancer-local",
            "key_version": 1,
            "last_seen": "2026-07-21T08:00:00Z",
            "created_at": "2026-07-20T08:00:00Z",
        },
        {
            "device_id": remote_device_id,
            "state": "approved",
            "fingerprint": "browser-remote",
            "key_version": 1,
            "last_seen": None,
            "created_at": "2026-07-21T08:00:00Z",
        },
    ]

    class Client:
        def devices(self, _workspace_id):
            return {"devices": rows}

        def revoke_device(self, _workspace_id, device_id):
            assert device_id == remote_device_id
            return {"device_id": device_id, "state": "revoked"}

        def close(self):
            pass

    client = Client()
    monkeypatch.setattr(
        cloud_commands,
        "_client",
        lambda: (client, tmp_path, config, config.account(), KeyStore(MemorySecretBackend())),
    )

    listed = CliRunner().invoke(cli, ["cloud", "devices"])
    assert listed.exit_code == 0, listed.output
    assert "APPROVED (this device)" in listed.output
    assert "docmancer-local" in listed.output
    assert "browser-remote" in listed.output
    assert remote_device_id in listed.output

    revoked = CliRunner().invoke(
        cli, ["cloud", "devices", "--revoke", remote_device_id, "--yes"]
    )
    assert revoked.exit_code == 0, revoked.output
    assert '"state": "revoked"' in revoked.output


def test_device_login_preserves_server_key_version(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands
    from docmancer.cloud import connect as connect_module

    config = CloudConfig(tmp_path)
    keys = KeyStore(MemorySecretBackend())
    class Client:
        def __init__(self, *_args, **_kwargs):
            self.box_public = None

        def start_device_login(self, request):
            self.box_public = b64decode(request["box_public_key"])
            return {
                "verification_uri": "https://cloud.invalid/device",
                "user_code": "CODE", "device_code": "device-code", "interval": 1,
            }

        def poll_device_login(self, _device_code):
            return {
                "account_id": "00000000-0000-4000-8000-000000000001",
                "access_token": "token",
            }

        def workspaces(self):
            return {"workspaces": []}

        def create_workspace(self, request):
            assert request["kind"] == "personal"
            assert request["device"]["sign_pubkey"]
            assert request["device"]["box_pubkey"]
            assert request["wrapped_key"]
            return {
                "workspace_id": "00000000-0000-4000-8000-000000000002",
                "device_id": "00000000-0000-4000-8000-000000000003",
                "current_key_version": 3,
            }

        def close(self):
            pass

    monkeypatch.setattr(cloud_commands, "_context", lambda: (tmp_path, config, {}, keys))
    monkeypatch.setattr(connect_module, "CloudClient", Client)
    result = CliRunner().invoke(
        cli, ["cloud", "connect", "--base-url", "https://cloud.invalid"],
    )
    assert result.exit_code == 0, result.output
    account = config.account()
    assert account["workspace_id"] == "00000000-0000-4000-8000-000000000002"
    assert account["device_id"] == "00000000-0000-4000-8000-000000000003"
    assert keys.workspace_key(account["account_id"], account["workspace_id"], 3)
    assert config.workspace(account["workspace_id"])[1]["key_version"] == 3
