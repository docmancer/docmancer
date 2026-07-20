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


def test_team_subcommands_are_registered():
    result = CliRunner().invoke(cli, ["memory", "team", "--help"])
    assert result.exit_code == 0
    assert "import" in result.output
    assert "export" in result.output


def test_device_login_preserves_server_key_version(tmp_path, monkeypatch):
    from docmancer.cli import cloud_commands

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
    monkeypatch.setattr(cloud_commands, "CloudClient", Client)
    result = CliRunner().invoke(
        cli, ["cloud", "connect", "--base-url", "https://cloud.invalid"],
    )
    assert result.exit_code == 0, result.output
    account = config.account()
    assert account["workspace_id"] == "00000000-0000-4000-8000-000000000002"
    assert account["device_id"] == "00000000-0000-4000-8000-000000000003"
    assert keys.workspace_key(account["account_id"], account["workspace_id"], 3)
    assert config.workspace(account["workspace_id"])[1]["key_version"] == 3
