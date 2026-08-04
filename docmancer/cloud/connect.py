"""UI-agnostic device-code connect flow shared by the CLI and the local web API.

The CLI command and the local HTTP API both drive the same three steps:
``start_connect`` obtains a user code, ``await_authorization`` polls until the
browser authorizes it, and ``finish_connect`` registers the workspace and
persists local state. Nothing here prints or prompts; callers observe progress
through callbacks so the same implementation can back a terminal or a browser.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from docmancer.cloud.client import (
    AuthenticationError,
    CloudClient,
    CloudError,
    validate_cloud_base_url,
)
from docmancer.cloud.config import CloudConfig, default_cloud_base_url
from docmancer.cloud.crypto import (
    b64decode,
    b64encode,
    box_keypair,
    random_key,
    signing_keypair,
    unwrap_key,
    wrap_key,
)
from docmancer.cloud.keystore import KeyStore


class ConnectError(Exception):
    """Connect could not proceed for an operational reason."""


class ConnectUsageError(ConnectError):
    """The caller supplied missing or incompatible options."""


class ConnectTimeout(ConnectError):
    """The user did not authorize the device before the deadline."""


class ConnectCancelled(ConnectError):
    """The caller abandoned the attempt before it was authorized."""


ProgressCallback = Callable[[str, dict[str, Any]], None]
WorkspaceChooser = Callable[[list[dict]], dict]

DEVICE_CODE_TIMEOUT = 300


def _noop(stage: str, data: dict[str, Any]) -> None:
    return None


def memory_root() -> Path:
    from docmancer.memory import default_memory_db

    return Path(default_memory_db()).parent


def _fingerprint(signing_public: bytes) -> str:
    return "docmancer-" + hashlib.sha256(signing_public).hexdigest()[:32]


def _canonical_uuid(value: Any, message: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ConnectError(message) from exc


def _cloud_base_url(value: str) -> str:
    try:
        return validate_cloud_base_url(value)
    except ValueError as exc:
        raise ConnectUsageError(str(exc)) from exc


@dataclass
class ConnectSession:
    """One in-flight device-code attempt against a single base URL."""

    base_url: str
    root: Path
    project_path: Path
    device_id: str
    signing_private: bytes
    signing_public: bytes
    box_private: bytes
    box_public: bytes
    keys: KeyStore
    existing_account_id: str = ""
    reused_identity: bool = False
    device_code: str = ""
    user_code: str = ""
    verification_uri: str = ""
    interval: int = 3
    expires_in: int = DEVICE_CODE_TIMEOUT

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.signing_public)


def resume_existing_connect(
    base_url: str,
    *,
    config: CloudConfig,
    account: dict,
    keys: KeyStore,
    root: Path,
    on_event: ProgressCallback | None = None,
) -> dict | None:
    """Return a terminal state when this device is already registered, else None."""
    emit = on_event or _noop
    base_url = _cloud_base_url(base_url)
    account_id = str(account.get("account_id") or "")
    workspace_id = str(account.get("workspace_id") or "")
    device_id = str(account.get("device_id") or "")
    token = keys.token(account_id) if account_id else None
    if not account_id or not workspace_id or not device_id or not token:
        return None
    configured_url = str(account.get("base_url") or "").rstrip("/")
    if configured_url and configured_url != base_url.rstrip("/"):
        raise ConnectError(
            f"this device is already associated with {configured_url}; disconnect it before changing servers"
        )

    client = CloudClient(
        base_url,
        token=token.decode("utf-8"),
        device_id=device_id,
        signing_private_key=keys.get(account_id, "device-signing-private"),
    )
    try:
        rows = list(client.devices(workspace_id).get("devices") or [])
    except AuthenticationError:
        return None
    except CloudError as exc:
        raise ConnectError(f"could not verify the existing cloud device: {exc}") from exc
    finally:
        client.close()

    current = next(
        (row for row in rows if str(row.get("device_id") or row.get("id")) == device_id),
        None,
    )
    if not current:
        raise ConnectError(
            "the configured cloud device is missing on the server; recover the workspace before registering another device"
        )
    state = str(current.get("state") or "pending")
    if state == "revoked":
        raise ConnectError(
            "the configured cloud device is revoked; recover the workspace before registering another device"
        )
    result = {
        "account_id": account_id,
        "workspace_id": workspace_id,
        "device_id": device_id,
        "fingerprint": str(current.get("fingerprint") or "unknown"),
    }
    if state != "approved":
        result["state"] = "pending_approval"
        result["message"] = (
            f"Device {device_id} is already pending approval. Confirm fingerprint: {result['fingerprint']}"
        )
        emit("pending_approval", result)
        return result
    if config.enabled():
        result["state"] = "already_connected"
        result["message"] = (
            f"Device {device_id} is already connected. Run `docmancer cloud sync` to transfer changes."
        )
        emit("already_connected", result)
        return result

    result["state"] = "resume_sync"
    result["message"] = f"Device {device_id} is approved. Completing the existing connection."
    emit("resume_sync", result)
    return result


def start_connect(
    base_url: str | None = None,
    *,
    root: Path | None = None,
    project_path: Path | None = None,
    device_id: str | None = None,
    keys: KeyStore | None = None,
    on_event: ProgressCallback | None = None,
) -> ConnectSession:
    """Begin device-code login and return a session carrying the user code."""
    emit = on_event or _noop
    resolved_base = _cloud_base_url(base_url or default_cloud_base_url())
    resolved_root = Path(root) if root is not None else memory_root()
    config = CloudConfig(resolved_root)
    account = config.account()
    keys = keys if keys is not None else KeyStore()

    existing_account_id = str(account.get("account_id") or "")
    existing_device_id = str(account.get("device_id") or "")
    existing_identity = None
    if existing_account_id and existing_device_id:
        existing_identity = {
            "signing_private": keys.get(existing_account_id, "device-signing-private"),
            "signing_public": keys.get(existing_account_id, "device-signing-public"),
            "box_private": keys.get(existing_account_id, "device-box-private"),
            "box_public": keys.get(existing_account_id, "device-box-public"),
        }
        if not all(existing_identity.values()):
            raise ConnectError(
                "the previous cloud device identity is incomplete; restore it from recovery before registering another device"
            )
    if device_id and existing_device_id and device_id != existing_device_id:
        raise ConnectUsageError("a device ID cannot replace an existing local cloud device")
    resolved_device_id = _canonical_uuid(
        device_id or existing_device_id or str(uuid.uuid4()),
        "the device ID must be a canonical UUID",
    )

    if existing_identity:
        signing_private = existing_identity["signing_private"]
        signing_public = existing_identity["signing_public"]
        box_private = existing_identity["box_private"]
        box_public = existing_identity["box_public"]
    else:
        signing_private, signing_public = signing_keypair()
        box_private, box_public = box_keypair()

    session = ConnectSession(
        base_url=resolved_base,
        root=resolved_root,
        project_path=Path(project_path) if project_path is not None else Path.cwd(),
        device_id=resolved_device_id,
        signing_private=signing_private,
        signing_public=signing_public,
        box_private=box_private,
        box_public=box_public,
        keys=keys,
        existing_account_id=existing_account_id,
        reused_identity=existing_identity is not None,
    )

    client = CloudClient(resolved_base, token="", device_id=resolved_device_id)
    try:
        started = client.start_device_login({
            "device_id": resolved_device_id,
            "signing_public_key": b64encode(signing_public),
            "box_public_key": b64encode(box_public),
        })
    except CloudError as exc:
        raise ConnectError(f"could not reach {resolved_base}: {exc}") from exc
    finally:
        client.close()

    session.device_code = str(started.get("device_code") or "")
    session.user_code = str(started.get("user_code") or "")
    session.verification_uri = str(started.get("verification_uri") or "")
    session.interval = max(1, int(started.get("interval") or 3))
    session.expires_in = int(started.get("expires_in") or DEVICE_CODE_TIMEOUT)
    if not session.device_code or not session.user_code:
        raise ConnectError("cloud did not return a device code")

    emit("device_code", {
        "user_code": session.user_code,
        "verification_uri": session.verification_uri,
        "expires_in": session.expires_in,
        "interval": session.interval,
    })
    return session


def await_authorization(
    session: ConnectSession,
    *,
    timeout: int = DEVICE_CODE_TIMEOUT,
    on_event: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    """Poll until the browser authorizes the device, then return the token payload."""
    emit = on_event or _noop
    cancelled = should_cancel or (lambda: False)
    deadline = monotonic() + max(1, timeout)
    client = CloudClient(session.base_url, token="", device_id=session.device_id)
    try:
        while True:
            if cancelled():
                raise ConnectCancelled("the connection attempt was cancelled")
            result = client.poll_device_login(session.device_code)
            if result.get("access_token"):
                emit("authorized", {"device_id": session.device_id})
                return dict(result)
            code = result.get("code")
            if code not in {"AUTHORIZATION_PENDING", "SLOW_DOWN"}:
                raise ConnectError(str(result.get("message") or "device login failed"))
            if monotonic() >= deadline:
                raise ConnectTimeout(
                    "device login timed out before the code was entered; start the connection again"
                )
            emit("pending", {"code": code})
            sleep(session.interval + (2 if code == "SLOW_DOWN" else 0))
    finally:
        client.close()


def finish_connect(
    session: ConnectSession,
    result: dict,
    *,
    workspace_id: str | None = None,
    choose_workspace: WorkspaceChooser | None = None,
    on_event: ProgressCallback | None = None,
) -> dict:
    """Register or join the workspace, persist local state, and return the outcome."""
    emit = on_event or _noop
    config = CloudConfig(session.root)
    keys = session.keys

    account_id = _canonical_uuid(result.get("account_id"), "cloud returned an invalid account UUID")
    device_id = session.device_id
    signing_private = session.signing_private
    signing_public = session.signing_public
    box_private = session.box_private
    box_public = session.box_public
    if session.reused_identity and account_id != session.existing_account_id:
        device_id = str(uuid.uuid4())
        signing_private, signing_public = signing_keypair()
        box_private, box_public = box_keypair()

    token = str(result.get("access_token") or "")
    if not token:
        raise ConnectError("cloud did not return an access token")
    for kind, value in {
        "device-signing-private": signing_private,
        "device-signing-public": signing_public,
        "device-box-private": box_private,
        "device-box-public": box_public,
    }.items():
        keys.set(account_id, kind, value)

    device_keys = {"signing_public": signing_public, "box_public": box_public}
    fingerprint = _fingerprint(signing_public)
    pending_approval = False
    key_version = 1

    authenticated = CloudClient(
        session.base_url, token=token, device_id=device_id, signing_private_key=signing_private,
    )
    try:
        rows = list(authenticated.workspaces().get("workspaces") or [])
        if workspace_id:
            selected = next(
                (row for row in rows if str(row.get("workspace_id")) == workspace_id),
                None,
            )
            if selected is None:
                raise ConnectError("the requested workspace is not available to this account")
        elif not rows:
            selected = None
        elif len(rows) == 1:
            selected = rows[0]
        elif choose_workspace is not None:
            selected = choose_workspace(rows)
        else:
            raise ConnectUsageError(
                "multiple workspaces are available; choose one explicitly"
            )

        if selected is None:
            workspace_key = random_key()
            created = authenticated.create_workspace({
                "kind": "personal",
                "device": {
                    "sign_pubkey": b64encode(signing_public),
                    "box_pubkey": b64encode(box_public),
                    "fingerprint": fingerprint,
                },
                "wrapped_key": b64encode(wrap_key(workspace_key, box_public)),
            })
            workspace_id = _canonical_uuid(
                created.get("workspace_id"), "cloud returned invalid workspace bootstrap UUIDs"
            )
            device_id = _canonical_uuid(
                created.get("device_id"), "cloud returned invalid workspace bootstrap UUIDs"
            )
            key_version = int(created.get("current_key_version") or 1)
            emit("workspace_ready", {"workspace_id": workspace_id, "created": True})
        else:
            workspace_id = _canonical_uuid(
                selected.get("workspace_id"), "cloud returned an invalid workspace UUID"
            )
            key_version = int(selected.get("current_key_version") or 1)
            devices = list(authenticated.devices(workspace_id).get("devices") or [])
            current = next(
                (row for row in devices if str(row.get("device_id") or row.get("id")) == device_id),
                None,
            )
            if current:
                server_signing = current.get("signing_public_key") or current.get("sign_public_key")
                server_box = current.get("box_public_key") or current.get("box_pubkey")
                if server_signing != b64encode(signing_public) or server_box != b64encode(box_public):
                    raise ConnectError(
                        "the server device ID belongs to different local keys; refusing to replace either identity"
                    )
                fingerprint = str(current.get("fingerprint") or fingerprint)
                state = str(current.get("state") or "pending")
                if state == "revoked":
                    raise ConnectError(
                        "the existing local device is revoked; recover the workspace before registering a replacement"
                    )
                pending_approval = state != "approved"
                workspace_key = keys.workspace_key(account_id, workspace_id, key_version) or b""
                if not pending_approval and not workspace_key:
                    wrapper = authenticated.key_wrapper(workspace_id, device_id, key_version)
                    workspace_key = unwrap_key(b64decode(str(wrapper["wrapped_key"])), box_private)
            else:
                registered = authenticated.register_device(workspace_id, {
                    "sign_pubkey": b64encode(signing_public),
                    "box_pubkey": b64encode(box_public),
                    "fingerprint": fingerprint,
                })
                device_id = _canonical_uuid(
                    registered.get("device_id"), "cloud returned an invalid device UUID"
                )
                workspace_key = b""
                pending_approval = True
            emit("workspace_ready", {"workspace_id": workspace_id, "created": False})
    except CloudError as exc:
        raise ConnectError(str(exc)) from exc
    finally:
        authenticated.close()

    return _persist(
        config=config,
        keys=keys,
        account_id=account_id,
        workspace_id=str(workspace_id),
        device_id=device_id,
        base_url=session.base_url,
        device_keys=device_keys,
        workspace_key=workspace_key,
        key_version=key_version,
        pending_approval=pending_approval,
        fingerprint=fingerprint,
        project_path=session.project_path,
        token=token,
        on_event=emit,
    )


def connect_with_token(
    base_url: str,
    *,
    account_id: str,
    workspace_id: str,
    token: str,
    device_id: str | None = None,
    root: Path | None = None,
    project_path: Path | None = None,
    keys: KeyStore | None = None,
    on_event: ProgressCallback | None = None,
) -> dict:
    """Connect using a static development token instead of device-code login."""
    emit = on_event or _noop
    resolved_root = Path(root) if root is not None else memory_root()
    resolved_base = _cloud_base_url(base_url)
    config = CloudConfig(resolved_root)
    account = config.account()
    keys = keys if keys is not None else KeyStore()

    if not account_id or not workspace_id:
        raise ConnectUsageError("an account ID and workspace ID are required with a static token")
    try:
        account_id = str(uuid.UUID(account_id))
        workspace_id = str(uuid.UUID(workspace_id))
    except ValueError as exc:
        raise ConnectUsageError("the account ID and workspace ID must be canonical UUIDs") from exc

    existing_device_id = str(account.get("device_id") or "")
    if device_id and existing_device_id and device_id != existing_device_id:
        raise ConnectUsageError("a device ID cannot replace an existing local cloud device")
    resolved_device_id = _canonical_uuid(
        device_id or existing_device_id or str(uuid.uuid4()),
        "the device ID must be a canonical UUID",
    )

    device_keys = keys.ensure_device_keys(account_id)
    existing_workspace = config.workspace(workspace_id)
    key_version = int((existing_workspace[1] if existing_workspace else {}).get("key_version") or 1)
    workspace_key = (
        keys.workspace_key(account_id, workspace_id, key_version)
        or keys.workspace_key(account_id, workspace_id)
        or random_key()
    )
    return _persist(
        config=config,
        keys=keys,
        account_id=account_id,
        workspace_id=workspace_id,
        device_id=resolved_device_id,
        base_url=resolved_base,
        device_keys=device_keys,
        workspace_key=workspace_key,
        key_version=key_version,
        pending_approval=False,
        fingerprint=_fingerprint(device_keys["signing_public"]),
        project_path=Path(project_path) if project_path is not None else Path.cwd(),
        token=token,
        on_event=emit,
    )


def _persist(
    *,
    config: CloudConfig,
    keys: KeyStore,
    account_id: str,
    workspace_id: str,
    device_id: str,
    base_url: str,
    device_keys: dict,
    workspace_key: bytes,
    key_version: int,
    pending_approval: bool,
    fingerprint: str,
    project_path: Path,
    token: str | None = None,
    on_event: ProgressCallback,
) -> dict:
    if token is not None:
        keys.set_token(account_id, token)
    if workspace_key:
        keys.set_workspace_key(account_id, workspace_id, workspace_key, key_version=key_version)
    config.save_account(
        enabled=not pending_approval,
        account_id=account_id,
        workspace_id=workspace_id,
        device_id=device_id,
        base_url=base_url,
    )
    config.set_workspace(
        workspace_id,
        key_version=key_version,
        device_public_keys={device_id: b64encode(device_keys["signing_public"])},
        device_box_public_keys={device_id: b64encode(device_keys["box_public"])},
    )
    config.ensure_project(project_path)
    outcome = {
        "state": "pending_approval" if pending_approval else "connected",
        "account_id": account_id,
        "workspace_id": workspace_id,
        "device_id": device_id,
        "base_url": base_url,
        "fingerprint": fingerprint,
        "key_version": key_version,
    }
    on_event(outcome["state"], outcome)
    return outcome


def enqueue_project(
    root: Path,
    keys: KeyStore,
    project_path: Path,
    *,
    db_path: str | Path | None = None,
) -> None:
    """Queue existing durable and reconciled memory for the first encrypted push."""
    from docmancer.cloud.lifecycle import enqueue_revisions_if_enabled
    from docmancer.cloud.migrate import migrate_records
    from docmancer.cloud.serialize import build_graph_payload
    from docmancer.memory.graph import MemoryGraphStore
    from docmancer.memory.records import MemoryRecordStore

    migrate_records(root=root, project_paths=[project_path])
    store = MemoryRecordStore(root)
    revisions = (
        revision
        for record in store.records(project_paths=[project_path])
        for revision in store.revisions(record.record_id)
    )
    enqueue_revisions_if_enabled(revisions, root=root, keystore=keys)

    # Existing harvested memory already lives in the graph projection when a
    # user enables Cloud. Connecting must queue that corpus too: otherwise the
    # documented connect-then-sync path transfers authored records and mapped
    # tree files but silently leaves pre-existing agent memory on this device.
    graph = MemoryGraphStore(db_path or root / "memory.db")
    graph_payloads = (
        build_graph_payload(**item) for item in graph.cloud_objects()
    )
    enqueue_revisions_if_enabled(graph_payloads, root=root, keystore=keys)


__all__ = [
    "ConnectCancelled",
    "ConnectError",
    "ConnectSession",
    "ConnectTimeout",
    "ConnectUsageError",
    "DEVICE_CODE_TIMEOUT",
    "await_authorization",
    "connect_with_token",
    "enqueue_project",
    "finish_connect",
    "memory_root",
    "resume_existing_connect",
    "start_connect",
]
