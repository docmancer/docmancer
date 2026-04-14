from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
import click
from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.cli.commands import _split_pack_ref


class FakeRegistry:
    url = "https://registry.example.com"
    cache_dir = ""
    auth_path = ""
    timeout = 1


class FakeConfig:
    def __init__(self, packs=None):
        self.packs = packs or {}
        self.registry = FakeRegistry()
        self.index = type("Index", (), {"db_path": ":memory:", "extracted_dir": ""})()


def test_registry_commands_are_lazy_imported():
    content = Path("docmancer/cli/commands.py").read_text()
    top_level = content.split("def _registry_client", 1)[0]
    assert "from docmancer.core.registry_client import" not in top_level
    assert "from docmancer.core.auth import" not in top_level


def test_registry_page_url_can_be_used_as_pack_ref():
    assert _split_pack_ref("https://www.docmancer.dev/registry/certifi") == ("certifi", None)
    assert _split_pack_ref("https://www.docmancer.dev/registry/certifi?version=2026.01.01") == ("certifi", "2026.01.01")


def test_pull_manifest_partial_failure(monkeypatch):
    config = FakeConfig({"react": "18.2", "missing": "1.0"})

    def fake_pull_one(_config, ref, _community, _force):
        if ref.startswith("missing"):
            raise click.ClickException("boom")
        return {"name": "react", "version": "18.2", "trust_tier": "official", "sections_count": 10, "total_tokens": 100}

    monkeypatch.setattr("docmancer.cli.commands._load_config", lambda _path: config)
    monkeypatch.setattr("docmancer.cli.commands._resolve_config_file", lambda _path: Path("docmancer.yaml"))
    monkeypatch.setattr("docmancer.cli.commands._pull_one", fake_pull_one)
    result = CliRunner().invoke(cli, ["pull"])
    assert result.exit_code != 0
    assert "react@18.2" in result.output
    assert "missing@1.0" in result.output


def test_pull_save_updates_manifest(tmp_path, monkeypatch):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text("index:\n  db_path: .docmancer/docmancer.db\n")
    config = FakeConfig()

    monkeypatch.setattr("docmancer.cli.commands._load_config", lambda _path: config)
    monkeypatch.setattr("docmancer.cli.commands._resolve_config_file", lambda _path: config_file)
    monkeypatch.setattr(
        "docmancer.cli.commands._pull_one",
        lambda *_args, **_kwargs: {"name": "react", "version": "18.2", "trust_tier": "official", "sections_count": 10, "total_tokens": 100},
    )
    result = CliRunner().invoke(cli, ["pull", "react", "--save"])
    assert result.exit_code == 0
    assert yaml.safe_load(config_file.read_text())["packs"]["react"] == "18.2"


def test_auth_status_degrades_without_token(monkeypatch):
    monkeypatch.setattr("docmancer.cli.commands._load_config", lambda _path: FakeConfig())
    with patch("docmancer.core.auth.load_auth_token", return_value=None):
        result = CliRunner().invoke(cli, ["auth", "status"])
    assert result.exit_code == 0
    assert "Not authenticated." in result.output


def test_pull_trust_gating(monkeypatch, tmp_path):
    from docmancer.core.registry_models import DownloadInfo

    class FakeClient:
        def get_pack_detail(self, name, version):
            return {"name": name, "latest_version": "1.0", "trust_tier": "community"}

        def get_download_info(self, name, version):
            return DownloadInfo(
                name=name,
                version=version or "1.0",
                download_url="https://registry.example.com/packs/demo/1.0/demo-1.0.docmancer-pack",
                archive_sha256="abc123",
                index_db_sha256="def456",
                file_size_bytes=1024,
            )

        def download_archive(self, url, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake")
            return path

    monkeypatch.setattr("docmancer.cli.commands._registry_client", lambda _config: FakeClient())
    monkeypatch.setattr(
        "docmancer.cli.commands._install_downloaded_pack",
        lambda *_args, **_kwargs: {"name": "demo", "version": "1.0", "trust_tier": "community", "sections_count": 1, "total_tokens": 1},
    )
    fake_config = FakeConfig()
    fake_config.registry.cache_dir = str(tmp_path / "cache")
    monkeypatch.setattr("docmancer.cli.commands._load_config", lambda _path: fake_config)
    monkeypatch.setattr("docmancer.cli.commands._resolve_config_file", lambda _path: Path("docmancer.yaml"))
    with patch("docmancer.core.sqlite_store.SQLiteStore.get_installed_pack", return_value=None):
        result = CliRunner().invoke(cli, ["pull", "demo"])
        assert result.exit_code != 0
        assert "Community pack blocked" in result.output

        result = CliRunner().invoke(cli, ["pull", "demo", "--community"])
        assert result.exit_code == 0
        assert "demo@1.0" in result.output


def test_doctor_registry_degradation(monkeypatch):
    fake_config = FakeConfig()
    fake_agent = MagicMock()
    fake_agent.collection_stats.return_value = {"sources_count": 0, "sections_count": 0, "extracted_dir": ""}
    monkeypatch.setattr("docmancer.cli.commands._load_config", lambda _path: fake_config)
    monkeypatch.setattr("docmancer.cli.commands._get_agent_class", lambda: lambda config: fake_agent)
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "local CLI unaffected" in result.output
