"""Canonical Protocol v1 record serialization and revision identity."""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785


PAYLOAD_SCHEMA_VERSION = 1
GRAPH_PAYLOAD_SCHEMA_VERSION = 2
GRAPH_OBJECT_KINDS = {"atom", "relation", "override", "pack"}
TREE_PAYLOAD_SCHEMA_VERSION = 3
TREE_OBJECT_KINDS = {"tree_file", "team_file"}
TREE_METADATA_FIELDS = {
    "title", "scope", "authority", "status", "tags", "sources",
    "generated", "publication_state", "exclusion_count", "approver_id",
}
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
    if payload["scope_kind"] not in {"global", "project"}:
        raise ValueError("invalid record payload scope_kind")
    if payload["scope_kind"] == "project" and not payload["project_id"]:
        raise ValueError("project record payloads require project_id")
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


def build_graph_payload(
    *,
    object_kind: str,
    object_id: str,
    data: Mapping[str, Any],
    updated_at: str,
    parent_revision_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build one canonical Protocol v2 encrypted graph object."""
    if object_kind not in GRAPH_OBJECT_KINDS:
        raise ValueError("invalid graph object_kind")
    payload: dict[str, Any] = {
        "schema_version": GRAPH_PAYLOAD_SCHEMA_VERSION,
        "object_kind": object_kind,
        "object_id": str(object_id),
        "revision_id": "",
        "parent_revision_ids": [str(value) for value in parent_revision_ids],
        "data": dict(data),
        "updated_at": str(updated_at),
    }
    payload["revision_id"] = revision_id(payload)
    return payload


def validate_graph_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version", "object_kind", "object_id", "revision_id",
        "parent_revision_ids", "data", "updated_at",
    }
    if set(payload) != expected:
        raise ValueError("invalid graph payload fields")
    if int(payload["schema_version"]) != GRAPH_PAYLOAD_SCHEMA_VERSION:
        raise ValueError("unsupported graph payload schema_version")
    if payload["object_kind"] not in GRAPH_OBJECT_KINDS:
        raise ValueError("invalid graph object_kind")
    if not isinstance(payload["data"], dict) or not isinstance(payload["parent_revision_ids"], list):
        raise ValueError("invalid graph payload data")
    if payload["revision_id"] != revision_id(payload):
        raise ValueError("graph revision_id does not match its canonical payload")
    return dict(payload)


def build_tree_payload(
    *,
    object_kind: str,
    file_id: str,
    project_id: str,
    relative_path: str,
    markdown: str,
    metadata: Mapping[str, Any],
    updated_at: str,
    parent_revision_ids: list[str] | tuple[str, ...] = (),
    deleted: bool = False,
) -> dict[str, Any]:
    safe_metadata = {key: metadata[key] for key in sorted(metadata) if key in TREE_METADATA_FIELDS}
    payload: dict[str, Any] = {
        "schema_version": TREE_PAYLOAD_SCHEMA_VERSION,
        "object_kind": object_kind,
        "file_id": str(file_id),
        "project_id": str(project_id),
        "relative_path": str(relative_path).replace("\\", "/"),
        "revision_id": "",
        "parent_revision_ids": [str(value) for value in parent_revision_ids],
        "markdown": "" if deleted else str(markdown),
        "content_hash": hashlib.sha256(("" if deleted else str(markdown)).encode()).hexdigest(),
        "metadata": safe_metadata,
        "updated_at": str(updated_at),
        "deleted": bool(deleted),
    }
    payload["revision_id"] = revision_id(payload)
    return validate_tree_payload(payload)


def validate_tree_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version", "object_kind", "file_id", "project_id",
        "relative_path", "revision_id", "parent_revision_ids", "markdown",
        "content_hash", "metadata", "updated_at", "deleted",
    }
    if set(payload) != expected:
        raise ValueError("invalid tree payload fields")
    if int(payload["schema_version"]) != TREE_PAYLOAD_SCHEMA_VERSION:
        raise ValueError("unsupported tree payload schema_version")
    if payload["object_kind"] not in TREE_OBJECT_KINDS:
        raise ValueError("invalid tree payload object_kind")
    path = str(payload["relative_path"])
    parts = path.replace("\\", "/").split("/")
    if not path or path.startswith(("/", "\\")) or ".." in parts or any(":" in part for part in parts):
        raise ValueError("tree payload path must be relative and portable")
    if not str(payload["project_id"]).startswith("prj_"):
        raise ValueError("tree payload requires a stable project_id")
    metadata = payload["metadata"]
    if not isinstance(metadata, dict) or set(metadata) - TREE_METADATA_FIELDS:
        raise ValueError("tree payload metadata contains unlisted fields")
    markdown = str(payload["markdown"])
    if bool(payload["deleted"]) and markdown:
        raise ValueError("tree tombstones cannot contain markdown")
    if payload["content_hash"] != hashlib.sha256(markdown.encode()).hexdigest():
        raise ValueError("tree payload content_hash mismatch")
    if not isinstance(payload["parent_revision_ids"], list):
        raise ValueError("tree payload parent_revision_ids must be a list")
    if payload["revision_id"] != revision_id(payload):
        raise ValueError("tree payload revision_id mismatch")
    return dict(payload)


__all__ = [
    "PAYLOAD_FIELDS",
    "PAYLOAD_SCHEMA_VERSION",
    "GRAPH_PAYLOAD_SCHEMA_VERSION",
    "GRAPH_OBJECT_KINDS",
    "TREE_OBJECT_KINDS",
    "TREE_PAYLOAD_SCHEMA_VERSION",
    "TREE_METADATA_FIELDS",
    "build_graph_payload",
    "build_record_payload",
    "canonicalize",
    "revision_id",
    "validate_record_payload",
    "validate_graph_payload",
    "build_tree_payload",
    "validate_tree_payload",
]
