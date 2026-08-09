from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from nacl.signing import SigningKey

from docmancer.backup.adapters import claude_slug_for_path
from docmancer.backup.archive import create_archive, materialize_artifact, open_archive
from docmancer.backup.inventory import inventory
from docmancer.backup.restore import plan_restore, restore_archive, rollback_restore


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _source_home(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "old-home"
    project = tmp_path / "old-project"
    project.mkdir()
    claude = home / ".claude" / "projects" / claude_slug_for_path(str(project)) / "session.jsonl"
    _write_jsonl(claude, [
        {"type": "user", "cwd": str(project), "message": "use sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"},
        {"type": "assistant", "cwd": str(project), "message": "The project decision is SQLite."},
    ])
    _write_jsonl(home / ".codex" / "sessions" / "2026" / "rollout.jsonl", [
        {"type": "user", "cwd": str(project), "content": "Remember that releases need a smoke test."},
    ])
    (home / ".claude" / "CLAUDE.md").parent.mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "CLAUDE.md").write_text("# Instructions\n\nUse full sentences.\n", encoding="utf-8")
    (home / ".claude.json").write_text(json.dumps({
        "projects": {str(project): {"mcpServers": {"demo": {"command": "demo", "env": {"TOKEN": "secret"}}}}},
        "oauthToken": "must-not-leave",
    }), encoding="utf-8")
    return home, project, claude


def test_inventory_uses_registered_adapters_and_project_filters(tmp_path: Path) -> None:
    home, project, _session = _source_home(tmp_path)
    _write_jsonl(home / ".claude" / "history.jsonl", [{"project": str(project), "display": "private prompt"}])
    _write_jsonl(home / ".codex" / "history.jsonl", [{"session_id": "one", "text": "private prompt"}])
    found = inventory(home=home)
    assert {artifact.agent for artifact in found.artifacts} == {"claude-code", "codex"}
    assert any(artifact.category == "session" for artifact in found.artifacts)
    excluded = inventory(home=home, exclude_projects={str(project)})
    assert not any(artifact.category == "session" and artifact.project_root == str(project) for artifact in excluded.artifacts)
    protected_paths = {artifact.source_path for artifact in excluded.artifacts}
    assert home / ".claude" / "history.jsonl" not in protected_paths
    assert home / ".codex" / "history.jsonl" not in protected_paths
    assert home / ".claude.json" not in protected_paths
    assert {item["reason"] for item in excluded.excluded} >= {
        "mixed-project-history-withheld",
        "mixed-project-registry-withheld",
    }
    assert not (home / ".docmancer").exists(), "inventory must remain read-only"


def test_archive_round_trip_masks_records_and_preserves_unknown_fields(tmp_path: Path) -> None:
    home, _project, _session = _source_home(tmp_path)
    found = inventory(home=home)
    archive_path = tmp_path / "history.dmbak"
    created = create_archive(found, archive_path, passphrase="correct horse battery staple")
    assert created["artifacts"] == len(found.artifacts)
    manifest, keys = open_archive(archive_path, passphrase="correct horse battery staple")
    with zipfile.ZipFile(archive_path) as archive:
        claude_session = next(row for row in manifest["artifacts"] if row["agent"] == "claude-code" and row["category"] == "session")
        data = materialize_artifact(archive, claude_session, manifest, keys).decode("utf-8")
    assert "sk-ant-" not in data
    records = [json.loads(line) for line in data.splitlines()]
    assert records[0]["type"] == "user"
    assert records[0]["message"] == "use [REDACTED]"
    assert records[1]["message"] == "The project decision is SQLite."
    root_config = next(row for row in manifest["artifacts"] if row["relative_path"] == ".claude.json")
    with zipfile.ZipFile(archive_path) as archive:
        config = json.loads(materialize_artifact(archive, root_config, manifest, keys))
    assert "oauthToken" not in config
    assert config["projects"][str(_project)]["mcpServers"]["demo"]["env"] == {}


def test_codex_toml_is_sanitised_structurally_and_merges_destination_first(tmp_path: Path, monkeypatch) -> None:
    import tomllib

    home, _project, _session = _source_home(tmp_path)
    config = home / ".codex" / "config.toml"
    config.write_text(
        '[mcp_servers.demo]\ncommand = "demo"\n[mcp_servers.demo.env]\nTOKEN = "private-value"\n',
        encoding="utf-8",
    )
    archive_path = tmp_path / "settings.dmbak"
    create_archive(inventory(home=home), archive_path, passphrase="toml-passphrase")
    restored_home = tmp_path / "restored-home"
    restored_config = restored_home / ".codex" / "config.toml"
    restored_config.parent.mkdir(parents=True)
    restored_config.write_text('[mcp_servers.local]\ncommand = "local"\n', encoding="utf-8")
    monkeypatch.setattr("docmancer.backup.restore.running_agents", lambda: [])

    result = restore_archive(
        archive_path,
        passphrase="toml-passphrase",
        home=restored_home,
        mappings={str(_project): _project},
    )
    assert result["conflicts"] == 0
    value = tomllib.loads(restored_config.read_text(encoding="utf-8"))
    assert value["mcp_servers"]["local"]["command"] == "local"
    assert value["mcp_servers"]["demo"]["env"] == {}
    assert any("env:TOKEN" in item for item in result["reconfiguration"])


def test_wrong_passphrase_or_corrupt_archive_fails_closed(tmp_path: Path) -> None:
    home, _project, _session = _source_home(tmp_path)
    archive_path = tmp_path / "history.dmbak"
    create_archive(inventory(home=home), archive_path, passphrase="right-passphrase")
    with pytest.raises(ValueError, match="wrong or the archive is corrupt"):
        open_archive(archive_path, passphrase="wrong-passphrase")


def test_restore_rewrites_only_structured_paths_and_quarantines_conflicts(tmp_path: Path, monkeypatch) -> None:
    old_home, old_project, _session = _source_home(tmp_path)
    archive_path = tmp_path / "history.dmbak"
    create_archive(inventory(home=old_home), archive_path, passphrase="restore-passphrase")
    new_home = tmp_path / "new-home"
    new_project = tmp_path / "new-project"
    new_project.mkdir()
    mappings = {str(old_project): new_project}
    preview = plan_restore(archive_path, passphrase="restore-passphrase", home=new_home, mappings=mappings)
    assert preview["counts"]["unmapped"] == 0
    monkeypatch.setattr("docmancer.backup.restore.running_agents", lambda: [])
    restored = restore_archive(archive_path, passphrase="restore-passphrase", home=new_home, mappings=mappings)
    assert restored["status"] == "structurally-valid"
    restored_session = new_home / ".claude" / "projects" / claude_slug_for_path(str(new_project)) / "session.jsonl"
    rows = [json.loads(line) for line in restored_session.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["cwd"] == str(new_project)
    assert str(old_project) not in rows[0]["cwd"]
    registry = json.loads((new_home / ".claude.json").read_text(encoding="utf-8"))
    assert str(new_project) in registry["projects"]
    assert str(old_project) not in registry["projects"]

    # A divergent same-ID history is never overwritten.
    restored_session.write_text('{"type":"user","message":"local fork"}\n', encoding="utf-8")
    old = restored_session.stat().st_mtime - 5
    import os
    os.utime(restored_session, (old, old))
    second = restore_archive(archive_path, passphrase="restore-passphrase", home=new_home, mappings=mappings)
    assert second["status"] == "partial"
    assert "local fork" in restored_session.read_text(encoding="utf-8")
    assert second["conflicts"] >= 1


def test_content_defined_chunking_reuses_tail_after_insertion(tmp_path: Path) -> None:
    from docmancer.backup.chunking import iter_content_defined_chunks

    base = (b'{"type":"message","content":"same repetitive transcript row"}\n' * 100_000)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_bytes(base)
    second.write_bytes(base[:500_000] + b'{"type":"user","content":"inserted"}\n' + base[500_000:])
    left = {__import__("hashlib").sha256(chunk).hexdigest() for chunk in iter_content_defined_chunks(first)}
    right = {__import__("hashlib").sha256(chunk).hexdigest() for chunk in iter_content_defined_chunks(second)}
    assert len(left & right) >= max(1, len(left) - 3)


def test_recovery_kit_is_rewrapped_across_workspace_key_rotation(tmp_path: Path) -> None:
    from docmancer.cloud.recovery import create_recovery, rewrap_recovery, verify_recovery

    workspace = "00000000-0000-4000-8000-000000000099"
    old_key = b"o" * 32
    new_key = b"n" * 32
    kit, wrapper = create_recovery(workspace, old_key, root=tmp_path, key_version=1)
    rotated = rewrap_recovery(
        kit,
        wrapper,
        previous_workspace_key=old_key,
        workspace_key=new_key,
        key_version=2,
    )
    assert rotated["recovery_verify_key"] == wrapper["recovery_verify_key"]
    assert rotated["key_version"] == 2
    assert verify_recovery(kit, rotated, root=tmp_path) == new_key


def test_cloud_upload_and_download_reuse_the_local_archive_restore_format(tmp_path: Path, monkeypatch) -> None:
    from docmancer.backup.cloud import download_cloud_backup, upload_cloud_backup

    home, _project, _session = _source_home(tmp_path)
    signing = SigningKey.generate()
    workspace_key = b"w" * 32
    ref_key = b"r" * 32
    account = {
        "account_id": "00000000-0000-4000-8000-000000000010",
        "workspace_id": "00000000-0000-4000-8000-000000000020",
        "device_id": "00000000-0000-4000-8000-000000000030",
        "key_version": 1,
    }

    class Keys:
        def workspace_key(self, _account, _workspace, _version):
            return workspace_key

        def set(self, *_args):
            return None

    class Client:
        def __init__(self):
            self.stage = None
            self.uploads = {}
            self.snapshot = None

        def stage_backup(self, _workspace, payload):
            self.stage = payload
            return {"stage_id": "00000000-0000-4000-8000-000000000040", "missing_refs": [row["ref"] for row in payload["chunks"]]}

        def entitlement(self, _workspace):
            return {"can_push": True}

        def lookup_backup_chunks(self, _workspace, _chunks):
            return {"descriptors": []}

        def upload_backup_chunk(self, _workspace, _stage, reference, ciphertext):
            self.uploads[reference] = ciphertext

        def commit_backup(self, workspace, _stage):
            self.snapshot = {
                "snapshot_id": self.stage["snapshot_id"], "workspace_id": workspace,
                "source_device_id": self.stage["source_device_id"], "key_version": 1,
                "manifest_nonce": self.stage["manifest_nonce"],
                "manifest_ciphertext": self.stage["manifest_ciphertext"],
                "manifest_signature": self.stage["manifest_signature"],
                "artifact_count": self.stage["artifact_count"], "logical_bytes": self.stage["logical_bytes"],
                "compressed_bytes": self.stage["compressed_bytes"], "chunk_count": len(self.stage["chunks"]),
                "created_at": "2026-08-07T00:00:00Z",
            }
            return {"snapshot": self.snapshot}

        def backups(self, _workspace):
            return {"snapshots": [self.snapshot]}

        def devices(self, _workspace):
            from docmancer.cloud.crypto import b64encode
            return {"devices": [{"device_id": account["device_id"], "sign_public_key": b64encode(bytes(signing.verify_key))}]}

        def backup_chunk(self, _workspace, _snapshot, reference):
            from docmancer.cloud.crypto import b64encode
            descriptor = next(row for row in self.stage["chunks"] if row["ref"] == reference)
            return {"descriptor": descriptor, "ciphertext": b64encode(self.uploads[reference])}

        def close(self):
            return None

    client = Client()
    monkeypatch.setattr(
        "docmancer.backup.cloud._context",
        lambda: (object(), account, Keys(), client, workspace_key, bytes(signing), ref_key),
    )
    uploaded = upload_cloud_backup(inventory(home=home))
    assert uploaded["uploaded_chunks"] > 0
    local = tmp_path / "downloaded.dmbak"
    download_cloud_backup(local, passphrase="download-passphrase")
    manifest, _keys = open_archive(local, passphrase="download-passphrase")
    assert manifest["format"] == "docmancer-backup-v1"
    assert manifest["totals"]["artifacts"] == len(inventory(home=home).artifacts)


def test_unknown_compression_dictionary_fails_with_a_format_error() -> None:
    from docmancer.backup.chunking import compress, decompress

    packed = compress(b"portable agent history")
    with pytest.raises(ValueError, match="unsupported backup compression dictionary"):
        decompress(packed, dictionary="agent-jsonl-unknown-v99")


def test_out_of_band_attachments_require_explicit_inventory_flag(tmp_path: Path) -> None:
    home, _project, _session = _source_home(tmp_path)
    attachment = home / ".codex" / "attachments" / "image.bin"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"\x89PNG\r\n\x1a\n" + b"image" * 100)

    assert attachment not in {item.source_path for item in inventory(home=home).artifacts}
    included = inventory(home=home, include_attachments=True)
    selected = next(item for item in included.artifacts if item.source_path == attachment)
    assert selected.content_kind == "binary"
    assert selected.attachments is True


def test_completed_restore_can_be_rolled_back(tmp_path: Path, monkeypatch) -> None:
    old_home, old_project, _session = _source_home(tmp_path)
    archive_path = tmp_path / "rollback.dmbak"
    create_archive(inventory(home=old_home), archive_path, passphrase="rollback-passphrase")
    new_home = tmp_path / "new-home"
    monkeypatch.setattr("docmancer.backup.restore.running_agents", lambda: [])
    restored = restore_archive(
        archive_path,
        passphrase="rollback-passphrase",
        home=new_home,
        mappings={str(old_project): old_project},
    )
    assert (new_home / ".claude" / "CLAUDE.md").is_file()
    rolled_back = rollback_restore(str(restored["snapshot_id"]), home=new_home)
    assert rolled_back["removed"] > 0
    assert not (new_home / ".claude" / "CLAUDE.md").exists()


def test_running_agent_detection_sees_node_based_claude_code(monkeypatch) -> None:
    from types import SimpleNamespace
    from docmancer.backup.restore import running_agents

    monkeypatch.setattr("docmancer.backup.restore._ancestors", lambda: {1, 2})
    monkeypatch.setattr("docmancer.backup.restore.getpass.getuser", lambda: "gaurang")
    monkeypatch.setattr(
        "docmancer.backup.restore.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="123 gaurang node /opt/lib/node_modules/@anthropic-ai/claude-code/cli.js\n"
        ),
    )
    assert running_agents()[0]["pid"] == 123


def test_quarantine_relative_paths_reject_traversal() -> None:
    from docmancer.backup.restore import _safe_relative

    with pytest.raises(ValueError, match="unsafe backup logical path"):
        _safe_relative("../../outside", label="logical path")


def test_connected_workspace_without_backup_entitlement_falls_back_to_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from docmancer.cli.__main__ import cli

    home, _project, _session = _source_home(tmp_path)
    monkeypatch.setattr("docmancer.backup.cloud.cloud_connected", lambda: True)
    monkeypatch.setattr("docmancer.backup.cloud.cloud_backup_entitled", lambda: False)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["backup", "--home", str(home), "--yes"],
            input="local-passphrase\nlocal-passphrase\n",
        )
        assert result.exit_code == 0, result.output
        assert list(Path.cwd().glob("docmancer-backup-*.dmbak"))
