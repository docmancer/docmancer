"""Explicit cloud account, sync, device, recovery, and export commands."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS
from docmancer.cloud.client import CloudClient
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64encode, random_key
from docmancer.cloud.entitlement import read_entitlement
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.outbox import CloudState


def _root() -> Path:
    from docmancer.memory import default_memory_db
    return Path(default_memory_db()).parent


def cloud_status(root: str | Path | None = None) -> dict:
    base = Path(root) if root else _root()
    config = CloudConfig(base)
    state = CloudState(config.paths.sync_state)
    account = config.account()
    workspace = config.workspace()
    return {
        "configured": config.enabled(),
        "account_id": account.get("account_id"),
        "workspace_id": account.get("workspace_id"),
        "device_id": account.get("device_id"),
        "base_url": account.get("base_url"),
        "continuous_audit": bool(workspace and workspace[1].get("continuous_audit")),
        "entitlement": read_entitlement(root=base).get("state", "unknown"),
        **state.status(),
    }


def _context() -> tuple[Path, CloudConfig, dict, KeyStore]:
    root = _root()
    config = CloudConfig(root)
    account = config.account()
    return root, config, account, KeyStore()


def _client() -> tuple[CloudClient, Path, CloudConfig, dict, KeyStore]:
    root, config, account, keys = _context()
    account_id = str(account.get("account_id") or "")
    token = keys.token(account_id)
    if not account_id or not token or not account.get("base_url") or not account.get("device_id"):
        raise click.ClickException("cloud session is incomplete; run `docmancer cloud login`")
    return CloudClient(str(account["base_url"]), token=token.decode("utf-8"), device_id=str(account["device_id"])), root, config, account, keys


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage optional encrypted cloud sync.")
def cloud_group() -> None:
    """Manage opt-in end-to-end encrypted sync. Local memory remains free and available."""


@cloud_group.command(cls=DocmancerCommand, short_help="Show local cloud state.")
@click.option("--json", "as_json", is_flag=True)
def status(as_json: bool) -> None:
    value = cloud_status()
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        click.echo(f"{key}: {item if item is not None else '-'}")


@cloud_group.command(cls=DocmancerCommand, short_help="Store an authenticated cloud session.")
@click.option("--base-url", required=True, help="Docmancer Cloud API base URL.")
@click.option("--account-id", default=None, help="Required only with a static development token.")
@click.option("--workspace-id", default=None, help="Required only with a static development token.")
@click.option("--device-id", default=None)
@click.option("--token", default=None, hide_input=True, help="Static development token; omit for device-code login.")
@click.option("--device-code-timeout", type=int, default=300, show_default=True)
def login(base_url: str, account_id: str | None, workspace_id: str | None, device_id: str | None, token: str | None, device_code_timeout: int) -> None:
    import time
    from docmancer.cloud.crypto import b64decode, box_keypair, signing_keypair, unwrap_key, wrap_key

    root, config, _account, keys = _context()
    device_id = device_id or f"dev_{uuid.uuid4().hex}"
    needs_key_registration = False
    key_version = 1
    if token is None:
        signing_private, signing_public = signing_keypair()
        box_private, box_public = box_keypair()
        client = CloudClient(base_url, token="", device_id=device_id)
        try:
            started = client.start_device_login({
                "device_id": device_id,
                "signing_public_key": b64encode(signing_public),
                "box_public_key": b64encode(box_public),
            })
            click.echo(f"Open {started.get('verification_uri')} and enter code {started.get('user_code')}.")
            deadline = time.monotonic() + max(1, device_code_timeout)
            interval = max(1, int(started.get("interval") or 3))
            while True:
                result = client.poll_device_login(str(started["device_code"]))
                if result.get("access_token"):
                    break
                if result.get("code") not in {"AUTHORIZATION_PENDING", "SLOW_DOWN"}:
                    raise click.ClickException(str(result.get("message") or "device login failed"))
                if time.monotonic() >= deadline:
                    raise click.ClickException("device login timed out")
                time.sleep(interval + (2 if result.get("code") == "SLOW_DOWN" else 0))
        finally:
            client.close()
        account_id = str(result["account_id"])
        workspace_id = str(result["workspace_id"])
        token = str(result["access_token"])
        for kind, value in {
            "device-signing-private": signing_private, "device-signing-public": signing_public,
            "device-box-private": box_private, "device-box-public": box_public,
        }.items():
            keys.set(account_id, kind, value)
        device_keys = {"signing_public": signing_public, "box_public": box_public}
        workspace_key = (
            unwrap_key(b64decode(str(result["workspace_key_wrapper"])), box_private)
            if result.get("workspace_key_wrapper") else random_key()
        )
        key_version = int(
            result.get("current_key_version")
            or result.get("key_version")
            or result.get("workspace_key_version")
            or 1
        )
        needs_key_registration = not bool(result.get("workspace_key_wrapper"))
    else:
        if not account_id or not workspace_id:
            raise click.UsageError("--account-id and --workspace-id are required with --token")
        device_keys = keys.ensure_device_keys(account_id)
        existing_workspace = config.workspace(workspace_id)
        key_version = int((existing_workspace[1] if existing_workspace else {}).get("key_version") or 1)
        workspace_key = keys.workspace_key(account_id, workspace_id, key_version) or keys.workspace_key(account_id, workspace_id) or random_key()
    assert account_id is not None and workspace_id is not None and token is not None
    keys.set_token(account_id, token)
    keys.set_workspace_key(account_id, workspace_id, workspace_key, key_version=key_version)
    config.save_account(enabled=False, account_id=account_id, workspace_id=workspace_id, device_id=device_id, base_url=base_url)
    config.set_workspace(
        workspace_id, key_version=key_version,
        device_public_keys={device_id: b64encode(device_keys["signing_public"])},
        device_box_public_keys={device_id: b64encode(device_keys["box_public"])},
    )
    if needs_key_registration:
        authenticated = CloudClient(base_url, token=token, device_id=device_id)
        try:
            authenticated.register_device(workspace_id, {
                "device_id": device_id,
                "signing_public_key": b64encode(device_keys["signing_public"]),
                "box_public_key": b64encode(device_keys["box_public"]),
                "workspace_key_wrapper": b64encode(wrap_key(workspace_key, device_keys["box_public"])),
            })
        finally:
            authenticated.close()
    click.echo(f"Authenticated device {device_id}. Run `docmancer cloud recovery create`, then enable sync.")


@cloud_group.command(cls=DocmancerCommand, short_help="Clear the cloud session without deleting local memory.")
def logout() -> None:
    _root_path, config, account, keys = _context()
    account_id = str(account.get("account_id") or "")
    if account_id:
        keys.delete(account_id, "access-token")
    config.save_account(enabled=False)
    click.echo("Cloud session cleared. Local memory was not changed.")


@cloud_group.command(cls=DocmancerCommand, short_help="Show the current account and device.")
def whoami() -> None:
    value = cloud_status()
    click.echo(json.dumps({key: value[key] for key in ("account_id", "workspace_id", "device_id", "configured")}, indent=2))


@cloud_group.command(cls=DocmancerCommand, short_help="Enable queued encrypted sync.")
def enable() -> None:
    _root_path, config, account, keys = _context()
    if not account.get("account_id") or not keys.token(str(account["account_id"])):
        raise click.ClickException("login is required before cloud sync can be enabled")
    from docmancer.cloud.migrate import migrate_records
    from docmancer.cloud.lifecycle import enqueue_revision_if_enabled
    from docmancer.memory.records import MemoryRecordStore

    config.save_account(enabled=True)
    migrate_records(root=_root_path, project_paths=[Path.cwd()])
    store = MemoryRecordStore(_root_path)
    for record in store.records(project_paths=[Path.cwd()]):
        for revision in store.revisions(record.record_id):
            enqueue_revision_if_enabled(revision, root=_root_path, keystore=keys)
    click.echo("Encrypted cloud sync enabled. Local features remain independent of this setting.")


@cloud_group.command(cls=DocmancerCommand, short_help="Pause remote transfer and keep local memory.")
def disable() -> None:
    _root_path, config, _account, _keys = _context()
    config.save_account(enabled=False)
    click.echo("Remote transfer disabled. Local memory was not changed.")


@cloud_group.command("sync", cls=DocmancerCommand, short_help="Push and pull encrypted revisions now.")
def sync_command() -> None:
    from docmancer.cloud.sync import sync_once

    client, root, _config, _account, keys = _client()
    try:
        click.echo(json.dumps(sync_once(client, root=root, keystore=keys), indent=2, sort_keys=True))
    finally:
        client.close()


@cloud_group.command(cls=DocmancerCommand, short_help="Map a portable project ID to a local path.")
@click.argument("path", type=click.Path(path_type=Path, file_okay=False, resolve_path=True))
@click.option("--project-id", default=None)
def link(path: Path, project_id: str | None) -> None:
    _root_path, config, _account, _keys = _context()
    project_id = project_id or config.ensure_project(path)
    config.link_project(project_id, path)
    click.echo(f"{project_id} -> {path}")


@cloud_group.command(cls=DocmancerCommand, short_help="List registered devices.")
def devices() -> None:
    client, _root_path, config, account, _keys = _client()
    try:
        click.echo(json.dumps(client.devices(str(account["workspace_id"])), indent=2, sort_keys=True))
    finally:
        client.close()


@cloud_group.group(cls=DocmancerGroup, short_help="Approve or revoke devices.")
def device() -> None:
    pass


@device.command(cls=DocmancerCommand)
@click.argument("device_id")
@click.option("--fingerprint", required=True, help="Fingerprint confirmed out of band.")
def approve(device_id: str, fingerprint: str) -> None:
    client, _root_path, _config, account, _keys = _client()
    try:
        result = client.register_device(str(account["workspace_id"]), {"device_id": device_id, "fingerprint": fingerprint, "approved": True})
        click.echo(json.dumps(result, indent=2))
    finally:
        client.close()


@device.command(cls=DocmancerCommand)
@click.argument("device_id")
@click.option("--yes", is_flag=True)
def revoke(device_id: str, yes: bool) -> None:
    from docmancer.cloud.crypto import b64decode
    from docmancer.cloud.rotation import prepare_rotation

    if not yes:
        click.confirm(f"Revoke device {device_id} and require key rotation?", abort=True)
    client, _root_path, config, account, keys = _client()
    try:
        workspace_id = str(account["workspace_id"])
        device_rows = list(client.devices(workspace_id).get("devices") or [])
        remaining = {
            str(row["device_id"]): b64decode(str(row["box_public_key"]))
            for row in device_rows
            if str(row.get("device_id")) != device_id and row.get("approved", True) and row.get("box_public_key")
        }
        if not remaining:
            raise click.ClickException("cannot revoke the last decrypting device")
        current = config.workspace(workspace_id)
        key_version = int((current[1] if current else {}).get("key_version") or 1) + 1
        workspace_key, rotation = prepare_rotation(remaining, key_version=key_version)
        revoked = client.revoke_device(workspace_id, device_id)
        rotated = client.rotate_key(workspace_id, rotation)
        keys.set_workspace_key(str(account["account_id"]), workspace_id, workspace_key, key_version=key_version)
        config.set_workspace(workspace_id, key_version=key_version)
        click.echo(json.dumps({"revocation": revoked, "rotation": rotated}, indent=2))
    finally:
        client.close()


@cloud_group.command(cls=DocmancerCommand, short_help="List unresolved local sync conflicts.")
@click.option("--json", "as_json", is_flag=True)
def conflicts(as_json: bool) -> None:
    root = _root()
    rows = CloudState(CloudConfig(root).paths.sync_state).conflicts()
    if as_json:
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        click.echo("No unresolved conflicts.")
    for row in rows:
        click.echo(f"{row['conflict_id']}  {row['reason']}  local={row['local_revision_id'] or '-'} remote={row['remote_revision_id']}")


@cloud_group.command(cls=DocmancerCommand, short_help="Resolve a local conflict explicitly.")
@click.argument("conflict_id", type=int)
@click.option("--strategy", type=click.Choice(["keep-left", "keep-right", "keep-both", "manual"]), required=True)
@click.option("--text", default=None, help="Replacement text for manual resolution.")
def resolve(conflict_id: int, strategy: str, text: str | None) -> None:
    from docmancer.cloud.apply import resolve_conflict

    if strategy == "manual" and not text:
        raise click.UsageError("--text is required with --strategy manual")
    state = CloudState(CloudConfig(_root()).paths.sync_state)
    rows = [row for row in state.conflicts() if row["conflict_id"] == conflict_id]
    if not rows:
        raise click.ClickException("unresolved conflict not found")
    try:
        resolve_conflict(conflict_id, strategy, root=_root(), text=text)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Conflict {conflict_id} marked {strategy}.")


@cloud_group.command("_devsync", cls=DocmancerCommand, hidden=True)
def devsync() -> None:
    """Run one static-token development sync cycle."""
    sync_command.callback() if hasattr(sync_command, "callback") else sync_command()


@cloud_group.group(cls=DocmancerGroup, short_help="Create and verify a recovery key.")
def recovery() -> None:
    pass


@recovery.command("create", cls=DocmancerCommand)
def recovery_create() -> None:
    from docmancer.cloud.recovery import create_recovery

    root, config, account, keys = _context()
    workspace_id = str(account.get("workspace_id") or "")
    workspace_key = keys.workspace_key(str(account.get("account_id") or ""), workspace_id)
    if not workspace_id or not workspace_key:
        raise click.ClickException("login and a local workspace key are required")
    recovery_key, wrapper = create_recovery(workspace_id, workspace_key, root=root)
    wrapper_path = config.paths.root / "recovery-wrapper.json"
    wrapper_path.write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")
    click.echo("Store this recovery key offline. It will not be shown again:")
    click.echo(recovery_key)
    try:
        client, _root_path, _config, _account, _keys = _client()
        try:
            client.upload_recovery_wrapper(workspace_id, wrapper)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Recovery wrapper is saved locally but was not uploaded: {exc}", err=True)
    click.echo("Run `docmancer cloud recovery verify` before enrolling another device.")


@recovery.command("verify", cls=DocmancerCommand)
@click.option("--key", prompt=True, hide_input=True)
def recovery_verify(key: str) -> None:
    from docmancer.cloud.recovery import verify_recovery

    root, config, account, keys = _context()
    wrapper_path = config.paths.root / "recovery-wrapper.json"
    if not wrapper_path.is_file():
        client, _root_path, _config, _account, _keys = _client()
        try:
            wrapper = client.recovery_wrapper(str(account["workspace_id"]))
        finally:
            client.close()
    else:
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    workspace_key = verify_recovery(key, wrapper, root=root)
    workspace = config.workspace(str(account["workspace_id"]))
    key_version = int((workspace[1] if workspace else {}).get("key_version") or 1)
    keys.set_workspace_key(str(account["account_id"]), str(account["workspace_id"]), workspace_key, key_version=key_version)
    click.echo("Recovery key verified.")


@cloud_group.command("export", cls=DocmancerCommand, short_help="Export local memory without contacting the server.")
@click.argument("destination", type=click.Path(path_type=Path))
def export_command(destination: Path) -> None:
    from docmancer.memory.records import MemoryRecordStore

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    store = MemoryRecordStore(_root())
    count = 0
    for record in store.records(project_paths=[Path.cwd()]):
        source = Path(record.source_path)
        target = destination / f"{record.record_id}.md"
        shutil.copy2(source, target)
        count += 1
    click.echo(f"Exported {count} local record(s) to {destination}")


@cloud_group.command("delete-remote", cls=DocmancerCommand, short_help="Delete server ciphertext and keep local memory.")
@click.option("--confirm", required=True, help="Type DELETE to confirm.")
def delete_remote(confirm: str) -> None:
    if confirm != "DELETE":
        raise click.UsageError("--confirm must be DELETE")
    client, _root_path, _config, account, _keys = _client()
    try:
        click.echo(json.dumps(client.delete_remote(str(account["workspace_id"]), confirm), indent=2))
    finally:
        client.close()


__all__ = ["cloud_group", "cloud_status"]
