"""Encrypted, signed Protocol v1 record envelopes."""
from __future__ import annotations

import json
from typing import Any, Mapping

from docmancer.cloud import PROTOCOL_VERSION
from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt, opaque_ref, sign, verify
from docmancer.cloud.serialize import canonicalize, validate_record_payload


def build_envelope(
    payload: Mapping[str, Any], *, workspace_id: str, device_id: str,
    workspace_key: bytes, signing_private_key: bytes, key_version: int = 1,
    _nonce: bytes | None = None,
) -> dict[str, Any]:
    record = validate_record_payload(payload)
    header = {
        "protocol_version": PROTOCOL_VERSION,
        "workspace_id": workspace_id,
        "device_id": device_id,
        "key_version": int(key_version),
        "record_ref": opaque_ref(record["record_id"], workspace_key, kind="rec"),
        "revision_ref": opaque_ref(record["revision_id"], workspace_key, kind="rev"),
    }
    aad = canonicalize(header)
    nonce, ciphertext = encrypt(canonicalize(record), workspace_key, aad=aad, nonce=_nonce)
    body = {**header, "nonce": b64encode(nonce), "ciphertext": b64encode(ciphertext)}
    body["signature"] = b64encode(sign(canonicalize(body), signing_private_key))
    return body


def open_envelope(
    envelope: Mapping[str, Any], *, workspace_key: bytes, signing_public_key: bytes,
) -> dict[str, Any]:
    required = {"protocol_version", "workspace_id", "device_id", "key_version", "record_ref", "revision_ref", "nonce", "ciphertext", "signature"}
    if set(envelope) != required:
        raise ValueError("invalid cloud envelope fields")
    if str(envelope["protocol_version"]) != PROTOCOL_VERSION:
        raise ValueError("unsupported cloud protocol version")
    unsigned = {key: envelope[key] for key in envelope if key != "signature"}
    verify(canonicalize(unsigned), b64decode(str(envelope["signature"])), signing_public_key)
    header = {key: envelope[key] for key in ("protocol_version", "workspace_id", "device_id", "key_version", "record_ref", "revision_ref")}
    plaintext = decrypt(
        b64decode(str(envelope["ciphertext"])), workspace_key,
        nonce=b64decode(str(envelope["nonce"])), aad=canonicalize(header),
    )
    payload = validate_record_payload(json.loads(plaintext))
    if envelope["record_ref"] != opaque_ref(payload["record_id"], workspace_key, kind="rec"):
        raise ValueError("cloud envelope record ref mismatch")
    if envelope["revision_ref"] != opaque_ref(payload["revision_id"], workspace_key, kind="rev"):
        raise ValueError("cloud envelope revision ref mismatch")
    return payload


__all__ = ["build_envelope", "open_envelope"]
