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


def cloud_status(
    root: str | Path | None = None,
    *,
    check_keychain: bool = False,
) -> dict:
    """Return local Cloud metadata without unlocking Keychain by default."""
    base = Path(root) if root else _root()
    config = CloudConfig(base)
    state = CloudState(config.paths.sync_state)
    account = config.account()
    account_id = str(account.get("account_id") or "")
    workspace_id = str(account.get("workspace_id") or "")
    device_id = str(account.get("device_id") or "")
    registered = bool(account_id and workspace_id and device_id)
    paused = bool(account.get("paused"))
    device_identity_available: bool | None = None
    workspace_key_available: bool | None = None
    if check_keychain and account_id:
        keys = KeyStore()
        device_identity_available = all(
            keys.get(account_id, kind)
            for kind in (
                "device-signing-private",
                "device-signing-public",
                "device-box-private",
                "device-box-public",
            )
        )
        workspace_key_available = bool(
            workspace_id and keys.workspace_key(account_id, workspace_id)
        )
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
        "registered": registered,
        "connection_state": (
            "connected" if config.enabled()
            else "paused" if paused and registered
            else "pending_approval" if registered
            else "not_connected"
        ),
        "paused": paused,
        "account_id": account.get("account_id"),
        "workspace_id": account.get("workspace_id"),
        "device_id": account.get("device_id"),
        "base_url": account.get("base_url"),
        "local_keys": {
            "checked": check_keychain,
            "device_identity_available": device_identity_available,
            "workspace_key_available": workspace_key_available,
        },
        "continuous_audit": bool(workspace and workspace[1].get("continuous_audit")),
        "entitlement": read_entitlement(root=base).get("state", "unknown"),
        "recovery": recovery,
        **state.status(),
    }


def _print_cloud_status(value: dict) -> None:
    if not value.get("configured"):
        if value.get("paused") and value.get("registered"):
            click.echo("Personal Sync: paused on this device")
            click.echo(f"Workspace: {value.get('workspace_id') or 'unknown'}")
            click.echo(f"This device: {value.get('device_id') or 'unknown'}")
            click.echo("Next: run `docmancer cloud connect` to resume this device.")
            return
        if value.get("registered"):
            local_keys = value.get("local_keys") or {}
            click.echo("Personal Sync: device registered, awaiting approval")
            click.echo(f"Workspace: {value.get('workspace_id') or 'unknown'}")
            click.echo(f"This device: {value.get('device_id') or 'unknown'}")
            click.echo(
                "Local key material: "
                + (
                    "available"
                    if local_keys.get("workspace_key_available")
                    else "workspace key unavailable"
                    if local_keys.get("checked")
                    else "not checked (checked when a Cloud action needs it)"
                )
            )
            click.echo("Next: run `docmancer cloud connect` on a trusted machine and compare the pairing code.")
            return
        click.echo("Personal Sync: not connected")
        click.echo("Next: run `docmancer cloud connect` to connect this machine.")
        return

    recovery = value.get("recovery") if isinstance(value.get("recovery"), dict) else {}
    if recovery.get("protection") == "device_replacement":
        recovery_label = "replacement ready"
    elif recovery.get("verified"):
        recovery_label = "decrypt only"
    elif recovery.get("configured"):
        recovery_label = "configured, not verified"
    else:
        recovery_label = "not configured"

    pending = int(value.get("pending") or 0)
    conflicts = int(value.get("conflicts") or 0)
    cursor = value.get("cursor")
    entitlement = str(value.get("entitlement") or "unknown").replace("_", " ").title()

    click.echo("Personal Sync: connected")
    click.echo(f"Account: {value.get('account_id') or 'unknown'}")
    click.echo(f"Workspace: {value.get('workspace_id') or 'unknown'}")
    click.echo(f"This device: {value.get('device_id') or 'unknown'}")
    click.echo(f"Plan: {entitlement}")
    click.echo(f"Recovery: {recovery_label}")
    click.echo(f"Sync queue: {pending:,} pending, {conflicts:,} conflicts")
    click.echo(f"Last sync cursor: {cursor or 'none yet'}")
    click.echo(f"Continuous audit: {'on' if value.get('continuous_audit') else 'off'}")

    if pending:
        click.echo("Next: run `docmancer cloud sync` to send the queued encrypted revisions.")
    elif conflicts:
        click.echo("Next: resolve the reported sync conflicts before relying on this machine's state.")
    elif not cursor:
        click.echo("Automatic sync has not completed yet. Use `docmancer cloud sync` to retry.")
    else:
        click.echo("Status: setup is complete and the local sync queue is clear.")

    if not recovery.get("configured"):
        click.echo(
            "Recommended: create a recovery kit from Cloud settings. Without one, the workspace "
            "key cannot be reconstructed if every connected device is lost."
        )


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
    recovery_key: str | None = None,
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
    if outcome.get("state") == "pending_approval" and recovery_key:
        _verify_recovery(recovery_key, approve_pending=True)
        click.echo("Recovery approved this machine. Downloading encrypted memory now.")
        _run_sync_command()
        return True
    if outcome.get("state") == "already_connected":
        _offer_pending_device_approval(outcome)
    if outcome.get("state") == "resume_sync":
        _run_sync_command()
    return True


def _offer_pending_device_approval(outcome: dict) -> None:
    """Turn `cloud connect` on a trusted machine into the approval surface."""
    from docmancer.cloud.connect import pairing_phrase
    from docmancer.cloud.crypto import b64decode, b64encode, wrap_key

    pending = list(outcome.get("pending_devices") or [])
    if not pending:
        return
    if len(pending) > 1:
        click.echo(
            f"{len(pending)} machines are waiting for approval. Use the advanced "
            "`docmancer cloud devices` command to choose one."
        )
        return
    row = pending[0]
    device_id = str(row.get("device_id") or row.get("id") or "")
    fingerprint = str(row.get("fingerprint") or "")
    phrase = pairing_phrase(fingerprint)
    click.echo(f"Another machine is waiting. Pairing code: {phrase}")
    if not click.get_text_stream("stdin").isatty():
        click.echo("Run `docmancer cloud connect` interactively on this trusted machine to approve it.")
        return
    if not click.confirm("Does this code match the new machine? Approve it"):
        return
    client, _root_path, config, account, keys = _client()
    workspace_id = str(account["workspace_id"])
    account_id = str(account["account_id"])
    workspace = config.workspace(workspace_id)
    key_version = int((workspace[1] if workspace else {}).get("key_version") or 1)
    workspace_key = keys.workspace_key(account_id, workspace_id, key_version)
    box_public = row.get("box_public_key") or row.get("box_pubkey")
    if not workspace_key or not box_public:
        client.close()
        raise click.ClickException("the trusted machine cannot prepare this device's key wrapper")
    try:
        client.approve_device(
            workspace_id,
            device_id,
            {
                "wrapped_key": b64encode(
                    wrap_key(workspace_key, b64decode(str(box_public)))
                ),
                "key_version": key_version,
            },
        )
    finally:
        client.close()
    click.echo("Machine approved. Rerun `docmancer cloud connect` there to finish restoration.")


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, invoke_without_command=True, short_help="Manage optional encrypted cloud sync.")
@click.pass_context
def cloud_group(ctx: click.Context) -> None:
    """Manage opt-in end-to-end encrypted sync. Local memory remains free and available."""
    if ctx.invoked_subcommand is None:
        _print_cloud_status(cloud_status())


@cloud_group.command(cls=DocmancerCommand, short_help="Show local cloud state.")
@click.option("--json", "as_json", is_flag=True)
@click.option(
    "--check-keychain",
    is_flag=True,
    help="Verify stored Cloud keys now. This may show a macOS Keychain prompt.",
)
def status(as_json: bool, check_keychain: bool) -> None:
    value = cloud_status(check_keychain=check_keychain)
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    _print_cloud_status(value)


@cloud_group.command("rotate-key", cls=DocmancerCommand, short_help="Rotate encrypted Cloud data to a new workspace key.")
@click.option("--yes", is_flag=True, help="Confirm the rotation after the recovery kit is verified.")
def rotate_key(yes: bool) -> None:
    """Atomically wrap a new key for every approved device and recovery."""
    from docmancer.cloud.crypto import b64decode
    from docmancer.cloud.recovery import rewrap_recovery
    from docmancer.cloud.rotation import prepare_rotation

    client, root, config, account, keys = _client()
    workspace_id = str(account["workspace_id"])
    account_id = str(account["account_id"])
    current = config.workspace(workspace_id)
    current_version = int(
        account.get("key_version")
        or (current[1] if current else {}).get("key_version")
        or 1
    )
    previous_key = keys.workspace_key(account_id, workspace_id, current_version)
    if previous_key is None:
        client.close()
        raise click.ClickException("the current workspace key is unavailable on this device")
    local = cloud_status(root)
    if int(local.get("pending") or 0):
        client.close()
        raise click.ClickException("sync pending encrypted revisions before rotating the workspace key")
    try:
        snapshots = list(client.backups(workspace_id).get("snapshots") or [])
        if snapshots:
            raise click.ClickException(
                "workspace-key rotation is unavailable while agent backups exist; "
                "historical-key migration must land before rotation can be safe"
            )
        devices = [
            row
            for row in list(client.devices(workspace_id).get("devices") or [])
            if str(row.get("state") or "") == "approved"
        ]
        public_keys = {
            str(row.get("device_id") or row.get("id")): b64decode(
                str(row.get("box_public_key") or row.get("box_pubkey") or "")
            )
            for row in devices
        }
        if not public_keys:
            raise click.ClickException("no approved devices are available for key rotation")
        stored_wrapper = client.recovery_wrapper(workspace_id)
        new_version = current_version + 1
        new_key, prepared = prepare_rotation(public_keys, key_version=new_version)
        recovery_key = click.prompt("Recovery kit", hide_input=True)
        try:
            recovery_wrapper = rewrap_recovery(
                recovery_key,
                stored_wrapper,
                previous_workspace_key=previous_key,
                workspace_key=new_key,
                key_version=new_version,
            )
        except (KeyError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        if not yes and not click.confirm(
            f"Rotate workspace key from version {current_version} to {new_version} for {len(public_keys)} approved device(s)?",
            default=False,
        ):
            raise click.Abort()
        result = client.rotate_workspace_key(
            workspace_id,
            {
                "key_version": new_version,
                "wrappers": [
                    {"device_id": device_id, "wrapped_key": wrapped_key}
                    for device_id, wrapped_key in prepared["wrappers"].items()
                ],
                "recovery_wrapper": recovery_wrapper,
            },
        )
        keys.set_workspace_key(account_id, workspace_id, new_key, key_version=new_version)
        config.set_workspace(workspace_id, key_version=new_version)
        config.save_account(key_version=new_version)
        wrapper_path = config.paths.root / "recovery-wrapper.json"
        wrapper_path.write_text(json.dumps(recovery_wrapper, indent=2) + "\n", encoding="utf-8")
        click.echo(
            f"Workspace key rotated to version {new_version}. Existing older snapshots remain restorable until each source device creates a new backup."
        )
        if result.get("workspace"):
            click.echo(f"Workspace: {workspace_id}")
    finally:
        client.close()


@cloud_group.command("connect", cls=DocmancerCommand, short_help="Connect, approve, or recover a Personal Sync device.")
@click.option("--base-url", default=None, help="Docmancer Cloud API base URL. Defaults to the hosted service.")
@click.option("--account-id", default=None, help="Required only with a static development token.")
@click.option("--workspace-id", default=None, help="Required only with a static development token.")
@click.option("--device-id", default=None)
@click.option("--token", default=None, hide_input=True, help="Static development token; omit for device-code login.")
@click.option("--device-code-timeout", type=int, default=300, show_default=True)
@click.option(
    "--create-recovery/--no-create-recovery",
    default=True,
    hidden=True,
    help="Create and display a recovery kit after connecting.",
)
@click.option("--recover", is_flag=True, help="Recover a replacement device using an offline recovery kit.")
@click.option("--recovery-key", default=None, hidden=True)
def login(
    base_url: str | None,
    account_id: str | None,
    workspace_id: str | None,
    device_id: str | None,
    token: str | None,
    device_code_timeout: int,
    create_recovery: bool,
    recover: bool,
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

    if recover and recovery_key:
        raise click.UsageError("choose only one of --recover or --recovery-key")
    if recover:
        recovery_key = click.prompt("Recovery kit", hide_input=True)
    if recovery_key:
        # --create-recovery now defaults on, so only an explicit pairing is a usage error.
        source = click.get_current_context().get_parameter_source("create_recovery")
        if create_recovery and source is not click.core.ParameterSource.DEFAULT:
            raise click.UsageError("choose only one of --create-recovery or --recovery-key")
        create_recovery = False
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
                recovery_key=recovery_key,
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

    pending = outcome["state"] == "pending_approval"
    if pending:
        click.echo(f"Registered this machine as a pending device ({outcome['device_id']}).")
        from docmancer.cloud.connect import pairing_phrase

        click.echo(f"Pairing code: {pairing_phrase(str(outcome['fingerprint']))}")
    else:
        _enqueue_current_project_or_warn(root, keys)
        click.echo(f"Connected this machine ({outcome['device_id']}). Encrypted sync is enabled.")
    if create_recovery:
        if pending:
            click.echo(
                "Approve the matching pairing code on an existing machine, or rerun "
                "`docmancer cloud connect --recover` with your recovery kit."
            )
        else:
            try:
                _create_recovery()
            except click.ClickException as exc:
                # The device is connected either way, so this must not fail the command.
                click.echo(
                    f"Connected, but no recovery kit was created: {exc.format_message()}. "
                    "Open Cloud settings to create a replacement recovery kit.",
                    err=True,
                )
    elif recovery_key:
        _verify_recovery(recovery_key, approve_pending=pending)
        if pending:
            click.echo("Recovery approved this machine. Downloading encrypted memory now.")
            _run_sync_command()

    if not pending:
        click.echo("Running the first encrypted sync.")
        try:
            _run_sync_command()
        except click.ClickException as exc:
            click.echo(
                f"Connected successfully, but the first sync needs a retry: {exc.format_message()}",
                err=True,
            )


def _prompt_for_workspace(rows: list[dict]) -> dict:
    if not click.get_text_stream("stdin").isatty():
        raise click.UsageError("multiple workspaces are available; pass --workspace-id")
    choices = {str(index): row for index, row in enumerate(rows, start=1)}
    for index, row in choices.items():
        click.echo(f"{index}: {row.get('name') or row.get('workspace_id')}")
    return choices[click.prompt("Select workspace", type=click.Choice(list(choices)))]



@cloud_group.command("pause", cls=DocmancerCommand, short_help="Pause transfer and retain this device's Cloud identity.")
def pause() -> None:
    _root_path, config, account, _keys = _context()
    if not account.get("workspace_id"):
        raise click.ClickException("this machine is not connected to Personal Sync")
    config.save_account(enabled=False, paused=True)
    click.echo("Personal Sync paused on this device. Local memory and Cloud credentials were kept.")


@cloud_group.command("disconnect", cls=DocmancerCommand, short_help="Revoke and forget this Cloud device without deleting local memory.")
@click.option("--export", "export_destination", type=click.Path(path_type=Path), default=None, help="Export local Markdown records first.")
@click.option("--delete-remote", is_flag=True, help="Schedule server-held ciphertext for deletion first.")
@click.option("--confirm", default=None, help="Required as DELETE with --delete-remote.")
def logout(export_destination: Path | None, delete_remote: bool, confirm: str | None) -> None:
    from docmancer.cloud.lifecycle import forget_local_cloud

    if export_destination is not None:
        _export_local(export_destination)
    if delete_remote:
        _delete_remote(confirm or "")
    client, _root_path, config, account, keys = _client()
    try:
        client.revoke_device(str(account["workspace_id"]), str(account["device_id"]))
    finally:
        client.close()
    forget_local_cloud(config, account, keys)
    click.echo("Cloud device revoked and local Cloud credentials removed. Local memory was not changed.")


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
    click.echo("Deprecated: `docmancer cloud disable` moved to `docmancer cloud pause`.", err=True)
    _root_path, config, _account, _keys = _context()
    config.save_account(enabled=False, paused=True)
    click.echo("Personal Sync paused on this device. Local memory and Cloud credentials were kept.")


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "No quota"
    amount = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1000 or candidate == units[-1]:
            break
        amount /= 1000
    return (
        f"{amount:.0f} {unit}"
        if amount >= 10 or unit == "B" or amount.is_integer()
        else f"{amount:.1f} {unit}"
    )


def _print_sync_estimate(value: dict) -> None:
    plan = value["plan"]
    estimate = value["estimate"]
    limits = value["limits"]
    click.echo("Personal Sync upload estimate")
    click.echo(
        f"Plan: {str(plan['key']).title()} ({str(plan['status']).replace('_', ' ')})"
    )
    click.echo(
        f"Upload access: {'allowed' if plan['can_push'] else 'not allowed on the current plan'}"
    )
    click.echo(
        f"Will send: {estimate['total_envelopes']:,} encrypted envelope(s) "
        f"in {estimate['upload_batches']:,} request(s)"
    )
    click.echo(f"Estimated upload: {_format_bytes(estimate['upload_request_bytes'])}")
    click.echo(
        "Encrypted envelopes: "
        f"{_format_bytes(estimate['encrypted_envelope_bytes'])} "
        f"({_format_bytes(estimate['encrypted_ciphertext_bytes'])} ciphertext)"
    )
    click.echo(
        f"New local plaintext represented: {_format_bytes(estimate['new_plaintext_bytes'])}"
    )
    click.echo(
        f"Queue: {estimate['existing_queued_envelopes']:,} already queued, "
        f"{estimate['new_envelopes']:,} newly detected"
    )
    if value.get("by_kind"):
        kinds = ", ".join(
            f"{kind} {row['envelopes']:,}"
            for kind, row in sorted(value["by_kind"].items())
        )
        click.echo(f"New data by type: {kinds}")
    limit_source = str(limits.get("source") or "client_defaults").replace("_", " ")
    click.echo(f"Limits ({limit_source})")
    sync_quota = limits.get("sync_storage_bytes")
    click.echo(
        "  Stored Personal Sync data: "
        + ("no stored-memory quota" if sync_quota is None else _format_bytes(sync_quota))
    )
    click.echo(f"  One encrypted envelope: {_format_bytes(limits['max_envelope_bytes'])}")
    click.echo(
        f"  One upload request: {_format_bytes(limits['max_batch_bytes'])}, "
        f"up to {limits['max_batch_count']:,} envelopes"
    )
    click.echo(
        f"  Client batching target: {_format_bytes(limits['client_batch_target_bytes'])}"
    )
    click.echo(
        f"  Agent backup storage: {_format_bytes(limits['backup_storage_bytes'])} "
        "(separate from Personal Sync)"
    )
    if value.get("issues"):
        for issue in value["issues"]:
            click.echo(f"Warning: {issue}", err=True)
    else:
        click.echo("Result: this upload fits the current transfer limits.")
    click.echo("Nothing was queued or uploaded.")


@cloud_group.command(
    "estimate",
    cls=DocmancerCommand,
    short_help="Estimate the next encrypted sync upload.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the full estimate as JSON.")
def estimate_command(as_json: bool) -> None:
    """Size changed memory, encryption overhead, requests, and plan limits.

    Includes the durable record history, memory atoms and relationships,
    machine and mapped-project tree files, and anything already in the local
    encrypted outbox. It reads Cloud keys because it builds real envelopes in
    memory, but it does not queue or upload them.
    """
    from docmancer.cloud.estimate import estimate_sync

    client, root, _config, account, keys = _client()
    try:
        entitlement = client.entitlement(str(account["workspace_id"]))
        value = estimate_sync(root=root, keystore=keys, entitlement=entitlement)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        client.close()
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    _print_sync_estimate(value)


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


@cloud_group.command(cls=DocmancerCommand, short_help="List, approve, or revoke registered devices.", hidden=True)
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


@device.command(cls=DocmancerCommand, hidden=True, short_help="Approve a pending device after verifying its fingerprint.")
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


@device.command(cls=DocmancerCommand, short_help="Revoke a device's future Cloud access.")
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


@cloud_group.group(cls=DocmancerGroup, short_help="Manage legacy recovery operations.", hidden=True)
def recovery() -> None:
    pass


@recovery.command("create", cls=DocmancerCommand, short_help="Create and upload a self-tested recovery kit wrapper.")
def recovery_create() -> None:
    _create_recovery()


def _create_recovery() -> None:
    from docmancer.cloud.recovery import create_recovery

    root, config, account, keys = _context()
    workspace_id = str(account.get("workspace_id") or "")
    workspace_key = keys.workspace_key(str(account.get("account_id") or ""), workspace_id)
    if not workspace_id or not workspace_key:
        raise click.ClickException("login and a local workspace key are required")
    workspace = config.workspace(workspace_id)
    key_version = int((workspace[1] if workspace else {}).get("key_version") or 1)
    recovery_key, wrapper = create_recovery(
        workspace_id,
        workspace_key,
        root=root,
        key_version=key_version,
    )
    wrapper_path = config.paths.root / "recovery-wrapper.json"
    wrapper_path.write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")
    click.echo("Save this recovery kit offline. It will not be shown again:")
    click.echo(recovery_key)
    try:
        client, _root_path, _config, _account, _keys = _client()
        try:
            client.upload_recovery_wrapper(workspace_id, wrapper)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Recovery wrapper is saved locally but was not uploaded: {exc}", err=True)
    click.echo("Recovery protection was cryptographically self-tested on this machine.")


@recovery.command("verify", cls=DocmancerCommand, short_help="Verify a recovery kit against the stored wrapper.")
@click.option("--key", prompt=True, hide_input=True)
def recovery_verify(key: str) -> None:
    _verify_recovery(key)


def _verify_recovery(key: str, *, approve_pending: bool = False) -> None:
    from docmancer.cloud.crypto import b64encode, wrap_key
    from docmancer.cloud.recovery import recovery_approval, verify_recovery

    root, config, account, keys = _context()
    workspace_id = str(account["workspace_id"])
    wrapper_path = config.paths.root / "recovery-wrapper.json"
    if not wrapper_path.is_file():
        client, _root_path, _config, _account, _keys = _client()
        try:
            wrapper = client.recovery_wrapper(str(account["workspace_id"]))
        finally:
            client.close()
    else:
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    if str(wrapper.get("workspace_id") or "") != workspace_id:
        raise click.ClickException("this recovery kit belongs to a different workspace")
    account_id = str(account["account_id"])
    device_id = str(account["device_id"])
    workspace_key = verify_recovery(key, wrapper, root=root)
    workspace = config.workspace(workspace_id)
    key_version = int(
        wrapper.get("key_version")
        or (workspace[1] if workspace else {}).get("key_version")
        or 1
    )
    if approve_pending:
        sign_public = keys.get(account_id, "device-signing-public")
        box_public = keys.get(account_id, "device-box-public")
        if not sign_public or not box_public:
            raise click.ClickException("this machine's device identity is incomplete")
        wrapped_key = b64encode(wrap_key(workspace_key, box_public))
        try:
            approval = recovery_approval(
                key,
                wrapper,
                device_id=device_id,
                sign_public_key=b64encode(sign_public),
                box_public_key=b64encode(box_public),
                wrapped_key=wrapped_key,
                key_version=key_version,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        client, _root_path, _config, _account, _keys = _client()
        try:
            client.recover_device(workspace_id, device_id, approval)
        finally:
            client.close()
    keys.set_workspace_key(
        account_id,
        workspace_id,
        workspace_key,
        key_version=key_version,
    )
    config.set_workspace(workspace_id, key_version=key_version)
    if approve_pending:
        config.save_account(enabled=True)
    click.echo("Recovery kit verified locally.")


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
