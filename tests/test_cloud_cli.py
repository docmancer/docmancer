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
    assert "already connected" in result.output
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
    assert "already pending approval" in result.output
    assert "docmancer-existing" in result.output
    assert config.account()["device_id"] == device_id


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
