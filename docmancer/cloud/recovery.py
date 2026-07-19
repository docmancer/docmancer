"""One-time recovery-key ceremony and local verification state."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt


def _encode_key(key: bytes) -> str:
    raw = base64.b32encode(key).decode("ascii").rstrip("=")
    return "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))


def _decode_key(value: str) -> bytes:
    raw = "".join(character for character in value.upper() if character.isalnum())
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def create_recovery(workspace_id: str, workspace_key: bytes, *, root: str | Path) -> tuple[str, dict]:
    recovery_key = os.urandom(32)
    nonce, ciphertext = encrypt(workspace_key, recovery_key, aad=workspace_id.encode("utf-8"))
    wrapper = {"version": 1, "workspace_id": workspace_id, "nonce": b64encode(nonce), "ciphertext": b64encode(ciphertext)}
    config = CloudConfig(root)
    config.paths.recovery_status.parent.mkdir(parents=True, exist_ok=True)
    config.paths.recovery_status.write_text(json.dumps({"version": 1, "workspace_id": workspace_id, "verified": False}, indent=2) + "\n", encoding="utf-8")
    return _encode_key(recovery_key), wrapper


def verify_recovery(value: str, wrapper: dict, *, root: str | Path) -> bytes:
    key = _decode_key(value)
    workspace_id = str(wrapper["workspace_id"])
    workspace_key = decrypt(b64decode(wrapper["ciphertext"]), key, nonce=b64decode(wrapper["nonce"]), aad=workspace_id.encode("utf-8"))
    path = CloudConfig(root).paths.recovery_status
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "workspace_id": workspace_id, "verified": True}, indent=2) + "\n", encoding="utf-8")
    return workspace_key


__all__ = ["create_recovery", "verify_recovery"]
