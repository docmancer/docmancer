"""Local-only recovery kits and recovery-authorised device enrolment."""
from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import (
    b64decode,
    b64encode,
    decrypt,
    encrypt,
    hkdf,
    sign,
)
from nacl.signing import SigningKey


def _encode_key(key: bytes) -> str:
    raw = base64.b32encode(key).decode("ascii").rstrip("=")
    return "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))


def _decode_key(value: str) -> bytes:
    raw = "".join(character for character in value.upper() if character.isalnum())
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def _derive(root_key: bytes, workspace_id: str, purpose: bytes) -> bytes:
    return hkdf(
        root_key,
        salt=workspace_id.encode("utf-8"),
        info=b"docmancer-recovery/v2/" + purpose,
    )


def _approval_message(
    *,
    workspace_id: str,
    device_id: str,
    sign_public_key: str,
    box_public_key: str,
    wrapped_key: str,
    key_version: int,
    nonce: str,
    expires_at: str,
) -> bytes:
    values = (
        "docmancer-recovery-v2",
        workspace_id,
        device_id,
        sign_public_key,
        box_public_key,
        wrapped_key,
        str(key_version),
        nonce,
        expires_at,
    )
    return ("\n".join(values) + "\n").encode("utf-8")


def create_recovery(
    workspace_id: str,
    workspace_key: bytes,
    *,
    root: str | Path,
    key_version: int = 1,
) -> tuple[str, dict]:
    """Create a v2 wrapper and prove locally that it can be opened.

    The hosted service receives only ciphertext and an Ed25519 verification
    key. The one recovery root derives separate encryption and signing keys.
    """
    recovery_key = os.urandom(32)
    wrapping_key = _derive(recovery_key, workspace_id, b"workspace-key")
    signing_seed = _derive(recovery_key, workspace_id, b"device-approval")
    nonce, ciphertext = encrypt(
        workspace_key,
        wrapping_key,
        aad=workspace_id.encode("utf-8"),
    )
    wrapper = {
        "version": 2,
        "workspace_id": workspace_id,
        "key_version": int(key_version),
        "nonce": b64encode(nonce),
        "ciphertext": b64encode(ciphertext),
        "recovery_verify_key": b64encode(bytes(SigningKey(signing_seed).verify_key)),
    }
    # This replaces the old retyping gate with an actual cryptographic
    # self-test before the wrapper is accepted or uploaded.
    recovered = decrypt(
        b64decode(wrapper["ciphertext"]),
        wrapping_key,
        nonce=b64decode(wrapper["nonce"]),
        aad=workspace_id.encode("utf-8"),
    )
    if recovered != workspace_key:
        raise ValueError("recovery kit self-test failed")
    config = CloudConfig(root)
    config.paths.recovery_status.parent.mkdir(parents=True, exist_ok=True)
    config.paths.recovery_status.write_text(
        json.dumps(
            {
                "version": 2,
                "workspace_id": workspace_id,
                "key_version": int(key_version),
                "verified": True,
                "protection": "device_replacement",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return _encode_key(recovery_key), wrapper


def verify_recovery(value: str, wrapper: dict, *, root: str | Path) -> bytes:
    key = _decode_key(value)
    workspace_id = str(wrapper["workspace_id"])
    wrapping_key = (
        _derive(key, workspace_id, b"workspace-key")
        if int(wrapper.get("version") or 1) >= 2
        else key
    )
    workspace_key = decrypt(
        b64decode(wrapper["ciphertext"]),
        wrapping_key,
        nonce=b64decode(wrapper["nonce"]),
        aad=workspace_id.encode("utf-8"),
    )
    path = CloudConfig(root).paths.recovery_status
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": int(wrapper.get("version") or 1),
                "workspace_id": workspace_id,
                "key_version": int(wrapper.get("key_version") or 1),
                "verified": True,
                "protection": (
                    "device_replacement"
                    if int(wrapper.get("version") or 1) >= 2
                    else "decrypt_only"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_key


def recovery_approval(
    value: str,
    wrapper: dict,
    *,
    device_id: str,
    sign_public_key: str,
    box_public_key: str,
    wrapped_key: str,
    key_version: int,
    now: datetime | None = None,
) -> dict:
    """Sign one short-lived replacement-device approval with a v2 kit."""
    if int(wrapper.get("version") or 1) < 2 or not wrapper.get("recovery_verify_key"):
        raise ValueError(
            "this older recovery key can decrypt data but cannot approve a new device; "
            "upgrade recovery protection from an approved device"
        )
    root_key = _decode_key(value)
    workspace_id = str(wrapper["workspace_id"])
    issued = now or datetime.now(timezone.utc)
    expires_at = (issued + timedelta(minutes=5)).isoformat(timespec="seconds")
    nonce = secrets.token_urlsafe(24)
    message = _approval_message(
        workspace_id=workspace_id,
        device_id=device_id,
        sign_public_key=sign_public_key,
        box_public_key=box_public_key,
        wrapped_key=wrapped_key,
        key_version=key_version,
        nonce=nonce,
        expires_at=expires_at,
    )
    signing_seed = _derive(root_key, workspace_id, b"device-approval")
    return {
        "wrapped_key": wrapped_key,
        "key_version": int(key_version),
        "nonce": nonce,
        "expires_at": expires_at,
        "recovery_signature": b64encode(sign(message, signing_seed)),
    }


__all__ = [
    "create_recovery",
    "recovery_approval",
    "verify_recovery",
]
