"""Workspace key rotation helpers."""
from __future__ import annotations

from docmancer.cloud.crypto import b64encode, random_key, wrap_key


def prepare_rotation(device_box_public_keys: dict[str, bytes], *, key_version: int) -> tuple[bytes, dict]:
    workspace_key = random_key()
    wrappers = {
        device_id: b64encode(wrap_key(workspace_key, public_key))
        for device_id, public_key in sorted(device_box_public_keys.items())
    }
    return workspace_key, {"key_version": int(key_version), "wrappers": wrappers}


__all__ = ["prepare_rotation"]
