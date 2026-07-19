from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, b64encode, random_key, wrap_key
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
    workspace_key = random_key()

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
                "account_id": "acct", "workspace_id": "ws", "access_token": "token",
                "workspace_key_wrapper": b64encode(wrap_key(workspace_key, self.box_public)),
                "key_version": 3,
            }

        def close(self):
            pass

    monkeypatch.setattr(cloud_commands, "_context", lambda: (tmp_path, config, {}, keys))
    monkeypatch.setattr(cloud_commands, "CloudClient", Client)
    result = CliRunner().invoke(
        cli, ["cloud", "login", "--base-url", "https://cloud.invalid", "--device-id", "dev"],
    )
    assert result.exit_code == 0, result.output
    assert keys.workspace_key("acct", "ws", 3) == workspace_key
    assert config.workspace("ws")[1]["key_version"] == 3
