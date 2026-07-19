"""Canonical Protocol v1 record serialization and revision identity."""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785


PAYLOAD_SCHEMA_VERSION = 1
PAYLOAD_FIELDS = (
    "schema_version",
    "record_id",
    "revision_id",
    "parent_revision_ids",
    "text",
    "memory_type",
    "tags",
    "origin",
    "scope_kind",
    "project_id",
    "created_at",
    "updated_at",
    "deleted",
)


def canonicalize(value: Any) -> bytes:
    """Return RFC 8785 JSON Canonicalization Scheme bytes."""
    return rfc8785.dumps(value)


def _revision_digest(payload_without_revision_id: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonicalize(dict(payload_without_revision_id))).digest()
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    return f"rev_{encoded}"


def revision_id(payload: Mapping[str, Any]) -> str:
    """Derive the immutable revision id from a Protocol v1 payload."""
    material = dict(payload)
    material.pop("revision_id", None)
    return _revision_digest(material)


def build_record_payload(
    *,
    record_id: str,
    text: str,
    memory_type: str,
    tags: list[str] | tuple[str, ...],
    origin_kind: str,
    origin_harness: str,
    scope_kind: str,
    project_id: str | None,
    created_at: str,
    updated_at: str,
    parent_revision_ids: list[str] | tuple[str, ...] = (),
    deleted: bool = False,
    revision: str | None = None,
) -> dict[str, Any]:
    """Build a validated, deterministic Protocol v1 plaintext payload."""
    payload: dict[str, Any] = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "record_id": str(record_id),
        "revision_id": "",
        "parent_revision_ids": [str(value) for value in parent_revision_ids],
        "text": "" if deleted else str(text),
        "memory_type": str(memory_type),
        "tags": sorted({str(tag) for tag in tags if str(tag)}),
        "origin": {"kind": str(origin_kind), "harness": str(origin_harness)},
        "scope_kind": str(scope_kind),
        "project_id": str(project_id) if project_id else None,
        "created_at": str(created_at),
        "updated_at": str(updated_at),
        "deleted": bool(deleted),
    }
    computed = revision_id(payload)
    if revision is not None and revision != computed:
        raise ValueError("record revision_id does not match its canonical payload")
    payload["revision_id"] = computed
    return payload


def validate_record_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate shape and revision identity without accepting extra fields."""
    keys = set(payload)
    expected = set(PAYLOAD_FIELDS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"invalid record payload fields; missing={missing}, extra={extra}")
    if int(payload["schema_version"]) != PAYLOAD_SCHEMA_VERSION:
        raise ValueError("unsupported record payload schema_version")
    if payload["scope_kind"] not in {"global", "project", "team"}:
        raise ValueError("invalid record payload scope_kind")
    if payload["scope_kind"] in {"project", "team"} and not payload["project_id"]:
        raise ValueError("project and team record payloads require project_id")
    if payload["scope_kind"] == "global" and payload["project_id"] is not None:
        raise ValueError("global record payloads cannot carry project_id")
    if not isinstance(payload["parent_revision_ids"], list):
        raise ValueError("parent_revision_ids must be a list")
    if bool(payload["deleted"]) and payload["text"] != "":
        raise ValueError("deleted record payloads cannot contain text")
    expected_revision = revision_id(payload)
    if payload["revision_id"] != expected_revision:
        raise ValueError("record revision_id does not match its canonical payload")
    return dict(payload)


__all__ = [
    "PAYLOAD_FIELDS",
    "PAYLOAD_SCHEMA_VERSION",
    "build_record_payload",
    "canonicalize",
    "revision_id",
    "validate_record_payload",
]
