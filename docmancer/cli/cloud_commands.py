"""Explicit cloud account, sync, device, recovery, and export commands."""
from __future__ import annotations

import json
import shutil
from copy import copy
from types import MethodType
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS
from docmancer.cloud.client import CloudClient
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64encode
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
    recovery = {"configured": False, "verified": False}
    if config.paths.recovery_status.is_file():
        try:
            recovery.update(json.loads(config.paths.recovery_status.read_text(encoding="utf-8")))
            recovery["configured"] = True
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "configured": config.enabled(),
        "account_id": account.get("account_id"),
        "workspace_id": account.get("workspace_id"),
        "device_id": account.get("device_id"),
        "base_url": account.get("base_url"),
        "continuous_audit": bool(workspace and workspace[1].get("continuous_audit")),
        "entitlement": read_entitlement(root=base).get("state", "unknown"),
        "recovery": recovery,
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
        raise click.ClickException("cloud session is incomplete; run `docmancer cloud connect`")
    return CloudClient(
        str(account["base_url"]), token=token.decode("utf-8"),
        device_id=str(account["device_id"]),
        signing_private_key=keys.get(account_id, "device-signing-private"),
    ), root, config, account, keys


def _resume_existing_connect(
    *,
    base_url: str,
    config: CloudConfig,
    account: dict,
    keys: KeyStore,
    root: Path,
) -> bool:
    from docmancer.cloud.connect import ConnectError, resume_existing_connect

    try:
        outcome = resume_existing_connect(
            base_url, config=config, account=account, keys=keys, root=root,
        )
    except ConnectError as exc:
        raise click.ClickException(str(exc)) from exc
    if outcome is None:
        return False
    click.echo(str(outcome.get("message") or ""))
    if outcome.get("state") == "resume_sync":
        _run_sync_command()
    return True


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, invoke_without_command=True, short_help="Manage optional encrypted cloud sync.")
@click.pass_context
def cloud_group(ctx: click.Context) -> None:
    """Manage opt-in end-to-end encrypted sync. Local memory remains free and available."""
    if ctx.invoked_subcommand is None:
        for key, item in cloud_status().items():
            click.echo(f"{key}: {item if item is not None else '-'}")


@cloud_group.command(cls=DocmancerCommand, short_help="Show local cloud state.", hidden=True)
@click.option("--json", "as_json", is_flag=True)
def status(as_json: bool) -> None:
    value = cloud_status()
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        click.echo(f"{key}: {item if item is not None else '-'}")


@cloud_group.command("connect", cls=DocmancerCommand, short_help="Connect encrypted cloud sync.")
@click.option("--base-url", default=None, help="Docmancer Cloud API base URL. Defaults to the hosted service.")
@click.option("--account-id", default=None, help="Required only with a static development token.")
@click.option("--workspace-id", default=None, help="Required only with a static development token.")
@click.option("--device-id", default=None)
@click.option("--token", default=None, hide_input=True, help="Static development token; omit for device-code login.")
@click.option("--device-code-timeout", type=int, default=300, show_default=True)
@click.option("--create-recovery", is_flag=True, help="Create and display a recovery key after connecting.")
@click.option("--recovery-key", default=None, hide_input=True, help="Verify an existing recovery key after connecting.")
def login(
    base_url: str | None,
    account_id: str | None,
    workspace_id: str | None,
    device_id: str | None,
    token: str | None,
    device_code_timeout: int,
    create_recovery: bool,
    recovery_key: str | None,
) -> None:
    from docmancer.cloud.config import default_cloud_base_url
    from docmancer.cloud.connect import (
        ConnectError,
        ConnectUsageError,
        await_authorization,
        connect_with_token,
        finish_connect,
        start_connect,
    )

    if create_recovery and recovery_key:
        raise click.UsageError("choose only one of --create-recovery or --recovery-key")
    resolved_base = (base_url or default_cloud_base_url()).rstrip("/")
    root, config, existing_account, keys = _context()

    try:
        if token is not None:
            outcome = connect_with_token(
                resolved_base,
                account_id=account_id or "",
                workspace_id=workspace_id or "",
                token=token,
                device_id=device_id,
                root=root,
                project_path=Path.cwd(),
                keys=keys,
            )
        else:
            if _resume_existing_connect(
                base_url=resolved_base, config=config, account=existing_account, keys=keys, root=root,
            ):
                return
            session = start_connect(
                resolved_base, root=root, project_path=Path.cwd(), device_id=device_id, keys=keys,
            )
            click.echo(f"Open {session.verification_uri} and enter code {session.user_code}.")
            result = await_authorization(session, timeout=device_code_timeout)
            outcome = finish_connect(
                session, result, workspace_id=workspace_id, choose_workspace=_prompt_for_workspace,
            )
    except ConnectUsageError as exc:
        raise click.UsageError(str(exc)) from exc
    except ConnectError as exc:
        raise click.ClickException(str(exc)) from exc

    if outcome["state"] == "pending_approval":
        click.echo(
            f"Registered pending device {outcome['device_id']}. "
            f"Approve this fingerprint from an existing device: {outcome['fingerprint']}"
        )
    else:
        _enqueue_current_project_or_warn(root, keys)
        click.echo(f"Connected device {outcome['device_id']}. Encrypted sync is enabled.")
    if create_recovery:
        _create_recovery()
    elif recovery_key:
        _verify_recovery(recovery_key)


def _prompt_for_workspace(rows: list[dict]) -> dict:
    if not click.get_text_stream("stdin").isatty():
        raise click.UsageError("multiple workspaces are available; pass --workspace-id")
    choices = {str(index): row for index, row in enumerate(rows, start=1)}
    for index, row in choices.items():
        click.echo(f"{index}: {row.get('name') or row.get('workspace_id')}")
    return choices[click.prompt("Select workspace", type=click.Choice(list(choices)))]



@cloud_group.command("disconnect", cls=DocmancerCommand, short_help="Disconnect cloud without deleting local memory.")
@click.option("--export", "export_destination", type=click.Path(path_type=Path), default=None, help="Export local Markdown records first.")
@click.option("--delete-remote", is_flag=True, help="Schedule server-held ciphertext for deletion first.")
@click.option("--confirm", default=None, help="Required as DELETE with --delete-remote.")
def logout(export_destination: Path | None, delete_remote: bool, confirm: str | None) -> None:
    if export_destination is not None:
        _export_local(export_destination)
    if delete_remote:
        _delete_remote(confirm or "")
    _root_path, config, account, keys = _context()
    account_id = str(account.get("account_id") or "")
    if account_id:
        keys.delete(account_id, "access-token")
    config.save_account(enabled=False)
    click.echo("Cloud session cleared. Local memory was not changed.")


@cloud_group.command(cls=DocmancerCommand, short_help="Show the current account and device.", hidden=True)
def whoami() -> None:
    value = cloud_status()
    click.echo(json.dumps({key: value[key] for key in ("account_id", "workspace_id", "device_id", "configured")}, indent=2))


@cloud_group.command(cls=DocmancerCommand, short_help="Enable queued encrypted sync.", hidden=True)
def enable() -> None:
    _root_path, config, account, keys = _context()
    if not account.get("account_id") or not keys.token(str(account["account_id"])):
        raise click.ClickException("login is required before cloud sync can be enabled")
    config.save_account(enabled=True)
    _enqueue_current_project(_root_path, keys)
    click.echo("Encrypted cloud sync enabled. Local features remain independent of this setting.")


@cloud_group.command(cls=DocmancerCommand, short_help="Pause remote transfer and keep local memory.", hidden=True)
def disable() -> None:
    _root_path, config, _account, _keys = _context()
    config.save_account(enabled=False)
    click.echo("Remote transfer disabled. Local memory was not changed.")


@cloud_group.command("sync", cls=DocmancerCommand, short_help="Push and pull encrypted revisions now.")
def sync_command() -> None:
    _run_sync_command()


def _run_sync_command() -> None:
    from docmancer.cloud.sync import sync_once
    from docmancer.cloud.crypto import b64decode, unwrap_key

    client, root, config, account, keys = _client()
    try:
        if not config.enabled():
            workspace_id = str(account["workspace_id"])
            device_id = str(account["device_id"])
            rows = list(client.devices(workspace_id).get("devices") or [])
            current = next(
                (row for row in rows if str(row.get("device_id") or row.get("id")) == device_id),
                None,
            )
            if not current or str(current.get("state")) != "approved":
                raise click.ClickException("this device is still pending approval")
            key_version = int(current.get("key_version") or 1)
            wrapped = client.key_wrapper(workspace_id, device_id, key_version)
            private_key = keys.get(str(account["account_id"]), "device-box-private")
            if not private_key:
                raise click.ClickException("device box private key is unavailable")
            workspace_key = unwrap_key(b64decode(str(wrapped["wrapped_key"])), private_key)
            keys.set_workspace_key(str(account["account_id"]), workspace_id, workspace_key, key_version=key_version)
            config.set_workspace(workspace_id, key_version=key_version)
            config.save_account(enabled=True)
            _enqueue_current_project_or_warn(root, keys)
        click.echo(json.dumps(sync_once(client, root=root, keystore=keys), indent=2, sort_keys=True))
    finally:
        client.close()


def _enqueue_current_project(root: Path, keys: KeyStore) -> None:
    from docmancer.cloud.connect import enqueue_project

    enqueue_project(root, keys, Path.cwd())


def _enqueue_current_project_or_warn(root: Path, keys: KeyStore) -> bool:
    try:
        _enqueue_current_project(root, keys)
    except Exception as exc:  # noqa: BLE001 - connection remains valid when local queueing fails
        click.echo(
            f"Connected, but existing memory could not be queued: {exc}. Run `docmancer cloud sync` to retry.",
            err=True,
        )
        return False
    return True


@cloud_group.command(cls=DocmancerCommand, short_help="Map a portable project ID to a local path.", hidden=True)
@click.argument("path", type=click.Path(path_type=Path, file_okay=False, resolve_path=True))
@click.option("--project-id", default=None)
def link(path: Path, project_id: str | None) -> None:
    _root_path, config, _account, _keys = _context()
    project_id = project_id or config.ensure_project(path)
    config.link_project(project_id, path)
    click.echo(f"{project_id} -> {path}")


@cloud_group.command(cls=DocmancerCommand, short_help="List, approve, or revoke registered devices.")
@click.option("--approve", "approve_id", default=None, metavar="DEVICE_ID")
@click.option("--revoke", "revoke_id", default=None, metavar="DEVICE_ID")
@click.option("--fingerprint", default=None, help="Fingerprint confirmed out of band for --approve.")
@click.option("--yes", is_flag=True, help="Skip the revocation confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Print the device list as JSON.")
def devices(
    approve_id: str | None,
    revoke_id: str | None,
    fingerprint: str | None,
    yes: bool,
    as_json: bool,
) -> None:
    if approve_id and revoke_id:
        raise click.UsageError("choose only one of --approve or --revoke")
    if approve_id:
        if not fingerprint:
            raise click.UsageError("--fingerprint is required with --approve")
        _approve_device(approve_id, fingerprint)
        return
    if revoke_id:
        _revoke_device(revoke_id, yes=yes)
        return
    client, _root_path, config, account, _keys = _client()
    try:
        value = client.devices(str(account["workspace_id"]))
        if as_json:
            click.echo(json.dumps(value, indent=2, sort_keys=True))
            return
        _print_devices(
            list(value.get("devices") or []),
            current_device_id=str(account.get("device_id") or ""),
        )
    finally:
        client.close()


def _print_devices(rows: list[dict], *, current_device_id: str) -> None:
    if not rows:
        click.echo("No device registrations found.")
        return
    ordered = sorted(
        rows,
        key=lambda row: (
            {"approved": 0, "pending": 1, "revoked": 2}.get(str(row.get("state")), 3),
            str(row.get("created_at") or ""),
        ),
    )
    for index, row in enumerate(ordered):
        device_id = str(row.get("device_id") or row.get("id") or "unknown")
        marker = " (this device)" if device_id == current_device_id else ""
        if index:
            click.echo()
        click.echo(f"{str(row.get('state') or 'unknown').upper()}{marker}")
        click.echo(f"  device_id:   {device_id}")
        click.echo(f"  fingerprint: {row.get('fingerprint') or '-'}")
        click.echo(f"  key_version: {row.get('key_version') or 0}")
        click.echo(f"  last_seen:   {row.get('last_seen') or 'never'}")
        click.echo(f"  enrolled:    {row.get('created_at') or 'unknown'}")


@cloud_group.group(cls=DocmancerGroup, short_help="Approve or revoke devices.", hidden=True)
def device() -> None:
    pass


@device.command(cls=DocmancerCommand, hidden=True)
@click.argument("device_id")
@click.option("--fingerprint", required=True, help="Fingerprint confirmed out of band.")
def approve(device_id: str, fingerprint: str) -> None:
    _approve_device(device_id, fingerprint)


def _approve_device(device_id: str, fingerprint: str) -> None:
    from docmancer.cloud.crypto import b64decode, wrap_key

    client, _root_path, config, account, keys = _client()
    try:
        workspace_id = str(account["workspace_id"])
        rows = list(client.devices(workspace_id).get("devices") or [])
        target = next(
            (row for row in rows if str(row.get("device_id") or row.get("id")) == device_id),
            None,
        )
        if target is None or str(target.get("state")) != "pending":
            raise click.ClickException("pending device not found")
        if str(target.get("fingerprint")) != fingerprint:
            raise click.ClickException("device fingerprint does not match")
        box_public = target.get("box_public_key") or target.get("box_pubkey")
        if not box_public:
            raise click.ClickException("pending device has no box public key")
        current = config.workspace(workspace_id)
        key_version = int((current[1] if current else {}).get("key_version") or 1)
        workspace_key = keys.workspace_key(str(account["account_id"]), workspace_id, key_version)
        if not workspace_key:
            raise click.ClickException("the current workspace key is unavailable on this device")
        result = client.approve_device(
            workspace_id,
            device_id,
            {
                "wrapped_key": b64encode(wrap_key(workspace_key, b64decode(str(box_public)))),
                "key_version": key_version,
            },
        )
        click.echo(json.dumps(result, indent=2))
    finally:
        client.close()


@device.command(cls=DocmancerCommand)
@click.argument("device_id")
@click.option("--yes", is_flag=True)
def revoke(device_id: str, yes: bool) -> None:
    _revoke_device(device_id, yes=yes)


def _revoke_device(device_id: str, *, yes: bool) -> None:
    client, _root_path, config, account, _keys = _client()
    try:
        workspace_id = str(account["workspace_id"])
        rows = list(client.devices(workspace_id).get("devices") or [])
        target = next(
            (row for row in rows if str(row.get("device_id") or row.get("id")) == device_id),
            None,
        )
        if target is None:
            raise click.ClickException("device registration not found")
        if str(target.get("state")) == "revoked":
            click.echo(f"Device {device_id} is already revoked.")
            return
        fingerprint = str(target.get("fingerprint") or "unknown")
        if not yes and not click.confirm(
            f"Revoke device {device_id} ({fingerprint})? It will lose future Cloud sync access"
        ):
            raise click.Abort()
        result = client.revoke_device(workspace_id, device_id)
        if device_id == str(account.get("device_id") or ""):
            config.save_account(enabled=False)
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        if device_id == str(account.get("device_id") or ""):
            click.echo("This local device is now disconnected. Local memory and cached keys were kept.")
    finally:
        client.close()


@cloud_group.command(cls=DocmancerCommand, short_help="List unresolved local sync conflicts.", hidden=True)
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


@cloud_group.command(cls=DocmancerCommand, short_help="Resolve a local conflict explicitly.", hidden=True)
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
    _run_sync_command()


@cloud_group.group(cls=DocmancerGroup, short_help="Create and verify a recovery key.", hidden=True)
def recovery() -> None:
    pass


@recovery.command("create", cls=DocmancerCommand)
def recovery_create() -> None:
    _create_recovery()


def _create_recovery() -> None:
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
    _verify_recovery(key)


def _verify_recovery(key: str) -> None:
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


@cloud_group.command("export", cls=DocmancerCommand, short_help="Export local memory without contacting the server.", hidden=True)
@click.argument("destination", type=click.Path(path_type=Path))
def export_command(destination: Path) -> None:
    _export_local(destination)


def _export_local(destination: Path) -> None:
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


@cloud_group.command("delete-remote", cls=DocmancerCommand, short_help="Schedule server ciphertext deletion and keep local memory.", hidden=True)
@click.option("--confirm", required=True, help="Type DELETE to confirm.")
def delete_remote(confirm: str) -> None:
    _delete_remote(confirm)


def _delete_remote(confirm: str) -> None:
    if confirm != "DELETE":
        raise click.UsageError("--confirm must be DELETE")
    client, _root_path, _config, account, _keys = _client()
    try:
        click.echo(json.dumps(client.delete_remote(str(account["workspace_id"]), confirm), indent=2))
    finally:
        client.close()


def _compatibility_alias(command: click.Command, name: str, replacement: str) -> None:
    alias = copy(command)
    alias.name = name
    alias.hidden = True
    original_invoke = alias.invoke

    def invoke(self, ctx: click.Context):
        click.echo(f"Deprecated: `docmancer cloud {name}` moved to `{replacement}`.", err=True)
        return original_invoke(ctx)

    alias.invoke = MethodType(invoke, alias)
    cloud_group.add_command(alias, name)


_compatibility_alias(login, "login", "docmancer cloud connect")
_compatibility_alias(logout, "logout", "docmancer cloud disconnect")


__all__ = ["cloud_group", "cloud_status"]
