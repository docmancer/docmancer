"""Encrypted, allowlisted local action relay for Docmancer Cloud."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt, sign, verify
from docmancer.cloud.serialize import canonicalize


RELAY_VERSION = 1
RELAY_PREFIX = b"docmancer-local-relay-v1\0"


def relay_header(job: dict) -> dict:
    return {
        "relay_version": RELAY_VERSION,
        "request_id": str(job["request_id"]),
        "workspace_id": str(job["workspace_id"]),
        "source_device_id": str(job["source_device_id"]),
        "target_device_id": str(job["target_device_id"]),
        "key_version": int(job["key_version"]),
        "expires_at": _canonical_timestamp(job["expires_at"]),
    }


def _canonical_timestamp(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("relay timestamp must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _associated_data(header: dict, direction: str) -> bytes:
    return canonicalize({"direction": direction, **header})


def _signature_input(header: dict, direction: str, nonce: bytes, ciphertext: bytes) -> bytes:
    return RELAY_PREFIX + _associated_data(header, direction) + b"\0" + nonce + ciphertext


def decrypt_request(job: dict, workspace_key: bytes, source_signing_public: bytes) -> dict:
    header = relay_header(job)
    nonce = b64decode(str(job["request_nonce"]))
    ciphertext = b64decode(str(job["request_ciphertext"]))
    verify(
        _signature_input(header, "request", nonce, ciphertext),
        b64decode(str(job["request_signature"])),
        source_signing_public,
    )
    plaintext = decrypt(
        ciphertext,
        workspace_key,
        nonce=nonce,
        aad=_associated_data(header, "request"),
    )
    value = json.loads(plaintext)
    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        raise ValueError("relay request payload is invalid")
    if not isinstance(value.get("arguments", {}), dict):
        raise ValueError("relay request arguments must be an object")
    return value


def encrypt_result(
    job: dict,
    payload: dict,
    workspace_key: bytes,
    device_signing_private: bytes,
) -> dict:
    header = relay_header(job)
    nonce, ciphertext = encrypt(
        canonicalize(payload),
        workspace_key,
        aad=_associated_data(header, "result"),
    )
    signature = sign(
        _signature_input(header, "result", nonce, ciphertext),
        device_signing_private,
    )
    return {
        "state": "completed" if payload.get("ok") else "failed",
        "response_nonce": b64encode(nonce),
        "response_ciphertext": b64encode(ciphertext),
        "response_signature": b64encode(signature),
    }


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def _call(backend: Any, method: str, arguments: dict) -> Any:
    method_arguments = dict(arguments)
    if "kinds" in method_arguments:
        method_arguments["kinds"] = tuple(str(item) for item in method_arguments["kinds"])
    for name in ("updated_after", "since"):
        if name in method_arguments:
            method_arguments[name] = _datetime(method_arguments[name])
    return await getattr(backend, method)(**method_arguments)


ActionHandler = Callable[[Any, dict], Awaitable[Any]]


def _method(name: str) -> ActionHandler:
    async def invoke(backend: Any, arguments: dict) -> Any:
        return await _call(backend, name, arguments)

    return invoke


# The browser sends only these stable identifiers. It cannot name Python
# methods, modules, files, or shell commands directly.
RELAY_ACTIONS: dict[str, tuple[ActionHandler, bool]] = {
    "context.list": (_method("context"), False),
    "context.distill": (_method("distill_context"), False),
    "context.review": (_method("review_context"), True),
    "context.add": (_method("add_context"), True),
    "context.share": (_method("share_context"), True),
    "context.edit": (_method("edit_context"), True),
    "intelligence.list": (_method("memory_intelligence"), False),
    "intelligence.resolve": (_method("resolve_memory_conflict"), True),
    "intelligence.resolve_group": (_method("resolve_memory_conflict_group"), True),
    "memory.recent": (_method("memory_recent"), False),
    "memory.query": (_method("query_memory"), False),
    "memory.add": (_method("add"), True),
    "memory.edit": (_method("edit"), True),
    "memory.promote": (_method("promote"), True),
    "sources.browse": (_method("browse_memory_sources"), False),
    "sources.get": (_method("get_memory_source"), False),
    "sources.live": (_method("get_live_source"), False),
    "sources.search": (_method("search_memory_sources"), False),
    "sources.create": (_method("create_source"), True),
    "audit.secrets": (_method("audit"), False),
    "audit.hooks": (_method("hook_status"), False),
    "docs.list": (_method("docs_sources"), False),
    "docs.get": (_method("get_docs_source"), False),
    "docs.query": (_method("query_docs"), False),
    "docs.ingest": (_method("ingest_docs"), True),
    "settings.capture.get": (_method("capture_settings"), False),
    "settings.capture.set": (_method("save_capture_settings"), True),
    "maintenance.consolidate": (_method("consolidate"), True),
    "status": (_method("status"), False),
    "sync": (_method("sync"), True),
    "doctor": (_method("doctor"), False),
}

CLI_ONLY_ACTIONS = {
    "context.remove": "Run `docmancer memory remove <id>` locally.",
    "context.reset": "Open `docmancer` locally and reset the selected context from the Context screen.",
    "memory.forget": "Run `docmancer memory forget <id> --dry-run`, then repeat without `--dry-run` after review.",
    "memory.clear_index": "Open `docmancer` locally and clear the rebuildable index from Maintenance.",
    "sources.edit": "Edit the source locally, then run `docmancer sync --project \"$PWD\"`.",
    "sources.delete": "Delete the source locally, then run `docmancer sync --project \"$PWD\"`.",
    "maintenance.apply": "Open `docmancer` locally, review the draft, then run `/apply <agent>`.",
}


async def dispatch(backend: Any, action: str, arguments: dict, *, allow_writes: bool) -> Any:
    if action in CLI_ONLY_ACTIONS:
        raise PermissionError(
            f"relay action is CLI-only because it can remove or overwrite local state. {CLI_ONLY_ACTIONS[action]}"
        )
    entry = RELAY_ACTIONS.get(action)
    if entry is None:
        raise ValueError("relay action is not allowlisted")
    handler, writes = entry
    if writes and not allow_writes:
        raise PermissionError(
            "relay action changes local state; restart with --allow-writes to approve local mutations"
        )
    return _json_safe(await handler(backend, arguments))


async def process_one(
    client: Any,
    backend: Any,
    *,
    workspace_id: str,
    device_id: str,
    workspace_key: bytes,
    signing_private: bytes,
    device_public_keys: dict[str, bytes],
    allow_writes: bool,
) -> dict | None:
    job = await asyncio.to_thread(client.claim_relay_job, workspace_id)
    if not job:
        return None
    if str(job.get("target_device_id")) != device_id:
        raise ValueError("relay target device mismatch")
    try:
        expiry = _datetime(job.get("expires_at"))
        if expiry is None or expiry.timestamp() <= datetime.now(expiry.tzinfo).timestamp():
            raise ValueError("relay request expired")
        source_id = str(job["source_device_id"])
        source_public = device_public_keys.get(source_id)
        if not source_public:
            raise ValueError("relay source device signing key is unavailable")
        request = decrypt_request(job, workspace_key, source_public)
        result = await dispatch(
            backend,
            str(request["action"]),
            dict(request.get("arguments") or {}),
            allow_writes=allow_writes,
        )
        payload = {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - encrypted failure belongs to the requesting browser
        payload = {"ok": False, "error": str(exc)}
    response = encrypt_result(job, payload, workspace_key, signing_private)
    return await asyncio.to_thread(
        client.complete_relay_job,
        workspace_id,
        str(job["id"]),
        response,
    )


async def serve(
    client: Any,
    backend: Any,
    *,
    workspace_id: str,
    device_id: str,
    workspace_key: bytes,
    signing_private: bytes,
    device_public_keys: dict[str, bytes],
    allow_writes: bool,
    once: bool = False,
    poll_seconds: float = 2.0,
    on_result: Callable[[dict], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    await backend.initialize()
    while True:
        try:
            result = await process_one(
                client,
                backend,
                workspace_id=workspace_id,
                device_id=device_id,
                workspace_key=workspace_key,
                signing_private=signing_private,
                device_public_keys=device_public_keys,
                allow_writes=allow_writes,
            )
        except Exception as exc:  # noqa: BLE001 - keep the long-running relay available
            result = None
            if on_error:
                on_error(exc)
        if result and on_result:
            on_result(result)
        if once:
            return
        await asyncio.sleep(max(0.25, poll_seconds))


__all__ = [
    "CLI_ONLY_ACTIONS",
    "RELAY_ACTIONS",
    "decrypt_request",
    "dispatch",
    "encrypt_result",
    "process_one",
    "relay_header",
    "serve",
]
