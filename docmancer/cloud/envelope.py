"""Encrypted, signed Protocol v1 record envelopes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from docmancer.cloud import PROTOCOL_VERSION
from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt, opaque_ref, sign, verify
from docmancer.cloud.serialize import (
    canonicalize,
    validate_graph_payload,
    validate_record_payload,
    validate_tree_payload,
)


def build_envelope(
    payload: Mapping[str, Any], *, workspace_id: str, device_id: str,
    workspace_key: bytes, signing_private_key: bytes, key_version: int = 1,
    _nonce: bytes | None = None,
    _envelope_id: str | None = None,
    _client_created_at: str | None = None,
) -> dict[str, Any]:
    protocol_version = int(payload.get("schema_version") or 1)
    if protocol_version == 3:
        record = validate_tree_payload(payload)
        kind = "tree_tombstone" if record["deleted"] else f"{record['object_kind']}_revision"
        object_id = record["file_id"]
    elif protocol_version == 2:
        record = validate_graph_payload(payload)
        kind = f"{record['object_kind']}_revision"
        object_id = record["object_id"]
    else:
        record = validate_record_payload(payload)
        kind = "record_tombstone" if record["deleted"] else "record_revision"
        object_id = record["record_id"]
    record_ref = opaque_ref(
        object_id, workspace_key, workspace_id=workspace_id, kind="record"
    )
    revision_ref = opaque_ref(
        record["revision_id"], workspace_key, workspace_id=workspace_id, kind="revision"
    )
    parent_refs = [
        opaque_ref(parent, workspace_key, workspace_id=workspace_id, kind="revision")
        for parent in record["parent_revision_ids"]
    ]
    associated = {
        "algorithm": "xchacha20poly1305-ietf",
        "key_version": int(key_version),
        "kind": kind,
        "protocol_version": protocol_version,
        "record_ref": record_ref,
        "revision_ref": revision_ref,
        "workspace_id": workspace_id,
    }
    aad = canonicalize(associated)
    nonce, ciphertext = encrypt(canonicalize(record), workspace_key, aad=aad, nonce=_nonce)
    body = {
        "protocol_version": protocol_version,
        "workspace_id": workspace_id,
        "envelope_id": _envelope_id or str(uuid.uuid4()),
        "record_ref": record_ref,
        "revision_ref": revision_ref,
        "parent_refs": parent_refs,
        "kind": kind,
        "key_version": int(key_version),
        "algorithm": "xchacha20poly1305-ietf",
        "nonce": b64encode(nonce),
        "ciphertext": b64encode(ciphertext),
        "created_by_device_id": device_id,
        "signature": "",
        "client_created_at": _client_created_at
        or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    signature_input = (
        f"docmancer-envelope-v{protocol_version}\0".encode("ascii")
        + aad
        + b"\0"
        + nonce
        + ciphertext
    )
    body["signature"] = b64encode(sign(signature_input, signing_private_key))
    return body


def open_envelope(
    envelope: Mapping[str, Any], *, workspace_key: bytes, signing_public_key: bytes,
) -> dict[str, Any]:
    required = {
        "protocol_version", "workspace_id", "envelope_id", "record_ref",
        "revision_ref", "parent_refs", "kind", "key_version", "algorithm",
        "nonce", "ciphertext", "created_by_device_id", "signature",
        "client_created_at",
    }
    if set(envelope) != required:
        raise ValueError("invalid cloud envelope fields")
    protocol_version = int(envelope["protocol_version"])
    if protocol_version not in {1, 2, 3}:
        raise ValueError("unsupported cloud protocol version")
    associated = {
        key: envelope[key]
        for key in (
            "algorithm", "key_version", "kind", "protocol_version",
            "record_ref", "revision_ref", "workspace_id",
        )
    }
    aad = canonicalize(associated)
    nonce = b64decode(str(envelope["nonce"]))
    ciphertext = b64decode(str(envelope["ciphertext"]))
    signature_input = f"docmancer-envelope-v{protocol_version}\0".encode("ascii") + aad + b"\0" + nonce + ciphertext
    verify(signature_input, b64decode(str(envelope["signature"])), signing_public_key)
    plaintext = decrypt(
        ciphertext, workspace_key, nonce=nonce, aad=aad,
    )
    raw_payload = json.loads(plaintext)
    payload = (
        validate_tree_payload(raw_payload)
        if protocol_version == 3
        else validate_graph_payload(raw_payload)
        if protocol_version == 2
        else validate_record_payload(raw_payload)
    )
    workspace_id = str(envelope["workspace_id"])
    object_id = payload["file_id"] if protocol_version == 3 else payload["object_id"] if protocol_version == 2 else payload["record_id"]
    if envelope["record_ref"] != opaque_ref(
        object_id, workspace_key, workspace_id=workspace_id, kind="record"
    ):
        raise ValueError("cloud envelope record ref mismatch")
    if envelope["revision_ref"] != opaque_ref(
        payload["revision_id"], workspace_key, workspace_id=workspace_id, kind="revision"
    ):
        raise ValueError("cloud envelope revision ref mismatch")
    expected_parents = [
        opaque_ref(parent, workspace_key, workspace_id=workspace_id, kind="revision")
        for parent in payload["parent_revision_ids"]
    ]
    if list(envelope["parent_refs"]) != expected_parents:
        raise ValueError("cloud envelope parent refs mismatch")
    expected_kind = (
        "tree_tombstone" if protocol_version == 3 and payload["deleted"]
        else f"{payload['object_kind']}_revision" if protocol_version == 3
        else
        f"{payload['object_kind']}_revision"
        if protocol_version == 2
        else "record_tombstone" if payload["deleted"] else "record_revision"
    )
    if envelope["kind"] != expected_kind:
        raise ValueError("cloud envelope kind mismatch")
    return payload


__all__ = ["build_envelope", "open_envelope"]
