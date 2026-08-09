"""Streaming secret masking and portable configuration sanitisation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from docmancer.harness.secrets import detect_secrets, redact_secrets

from .models import ArtifactSpec, PreparedArtifact


_SECRET_KEYS = {
    "accesstoken", "access_token", "apikey", "api_key", "auth", "authorization",
    "credential", "credentials", "password", "privatekey", "private_key",
    "refresh_token", "refreshtoken", "secret", "sessiontoken", "session_token", "token",
}
_CLAUDE_ROOT_PORTABLE = {
    "projects", "mcpservers", "preferences", "settings", "keybindings",
    "permissions", "hooks",
}
_INLINE_ATTACHMENT_KEYS = {"attachment", "attachments", "data", "image", "images", "source"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat_identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _redact_string(value: str) -> tuple[str, int]:
    findings = detect_secrets(value)
    return (redact_secrets(value), len(findings)) if findings else (value, 0)


def _looks_inline_binary(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("data:image/") or stripped.startswith("data:application/octet-stream"):
        return True
    if len(stripped) < 4096:
        return False
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
    return set(stripped[:8192]) <= alphabet


def _sanitize_value(
    value: Any,
    *,
    include_attachments: bool,
    parent_key: str = "",
    findings: list[str],
    omissions: list[str],
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "").replace(" ", "")
            if normalized in _SECRET_KEYS:
                findings.append(str(key))
                continue
            if normalized == "env" and isinstance(child, dict):
                # Keep the valid configuration shape while leaving withheld
                # values genuinely unset on the restored machine.
                result[str(key)] = {}
                findings.extend(f"env:{name}" for name in child)
                continue
            result[str(key)] = _sanitize_value(
                child,
                include_attachments=include_attachments,
                parent_key=str(key),
                findings=findings,
                omissions=omissions,
            )
        return result
    if isinstance(value, list):
        return [
            _sanitize_value(
                child,
                include_attachments=include_attachments,
                parent_key=parent_key,
                findings=findings,
                omissions=omissions,
            )
            for child in value
        ]
    if isinstance(value, str):
        if not include_attachments and parent_key.casefold() in _INLINE_ATTACHMENT_KEYS and _looks_inline_binary(value):
            omissions.append(parent_key)
            return "[DOCMANCER_ATTACHMENT_OMITTED]"
        redacted, count = _redact_string(value)
        if count:
            findings.extend([parent_key or "string"] * count)
        return redacted
    return value


def _sanitize_jsonl(source: Path, destination: Path, *, include_attachments: bool) -> list[dict[str, Any]]:
    transformed_records = 0
    secret_count = 0
    attachment_count = 0
    invalid_records = 0
    byte_offset = 0
    affected_offsets: list[int] = []
    reconfiguration: set[str] = set()
    with source.open("rb") as incoming, destination.open("wb") as outgoing:
        for raw in incoming:
            offset = byte_offset
            byte_offset += len(raw)
            try:
                text = raw.decode("utf-8")
                value = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                invalid_records += 1
                marker = {
                    "type": "docmancer_omitted_record",
                    "reason": "invalid-jsonl-record",
                    "source_sha256": hashlib.sha256(raw.rstrip(b"\r\n")).hexdigest(),
                }
                outgoing.write(json.dumps(marker, separators=(",", ":")).encode("utf-8") + b"\n")
                continue
            findings: list[str] = []
            omissions: list[str] = []
            cleaned = _sanitize_value(
                value,
                include_attachments=include_attachments,
                findings=findings,
                omissions=omissions,
            )
            if findings or omissions:
                reconfiguration.update(findings)
                transformed_records += 1
                secret_count += len(findings)
                attachment_count += len(omissions)
                affected_offsets.append(offset)
                outgoing.write(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            else:
                outgoing.write(raw)
    rows = []
    if transformed_records:
        rows.append({
            "kind": "jsonl-record-sanitisation",
            "records": transformed_records,
            "secret_findings": secret_count,
            "attachments_omitted": attachment_count,
            "record_offsets": affected_offsets[:1000],
            "offsets_truncated": len(affected_offsets) > 1000,
            "reconfiguration": sorted(reconfiguration)[:1000],
        })
    if invalid_records:
        rows.append({"kind": "invalid-jsonl-records-omitted", "records": invalid_records})
    return rows


def _sanitize_json(source: Path, destination: Path, *, include_attachments: bool) -> list[dict[str, Any]]:
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"cannot safely parse portable JSON settings: {source}") from exc
    omitted_root_keys: list[str] = []
    if source.name == ".claude.json" and isinstance(value, dict):
        portable = {}
        for key, child in value.items():
            if str(key).casefold() in _CLAUDE_ROOT_PORTABLE:
                portable[key] = child
            else:
                omitted_root_keys.append(str(key))
        value = portable
    findings: list[str] = []
    omissions: list[str] = []
    cleaned = _sanitize_value(
        value,
        include_attachments=include_attachments,
        findings=findings,
        omissions=omissions,
    )
    destination.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return [{
        "kind": "structured-config-sanitisation",
        "secret_findings": len(findings),
        "reconfiguration": sorted(set(findings)),
        "attachments_omitted": len(omissions),
        "root_keys_omitted": omitted_root_keys,
    }]


def _sanitize_toml(source: Path, destination: Path, *, include_attachments: bool) -> list[dict[str, Any]]:
    try:
        value = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise RuntimeError(f"cannot safely parse portable TOML settings: {source}") from exc
    findings: list[str] = []
    omissions: list[str] = []
    cleaned = _sanitize_value(
        value,
        include_attachments=include_attachments,
        findings=findings,
        omissions=omissions,
    )
    destination.write_text(tomli_w.dumps(cleaned), encoding="utf-8")
    return [{
        "kind": "structured-config-sanitisation",
        "secret_findings": len(findings),
        "reconfiguration": sorted(set(findings)),
        "attachments_omitted": len(omissions),
        "root_keys_omitted": [],
    }]


def _sanitize_text(source: Path, destination: Path) -> list[dict[str, Any]]:
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"cannot safely read portable text artifact: {source}") from exc
    findings = detect_secrets(text)
    destination.write_text(redact_secrets(text) if findings else text, encoding="utf-8")
    return ([{"kind": "text-secret-redaction", "secret_findings": len(findings)}] if findings else [])


def prepare_artifact(spec: ArtifactSpec, temporary_root: Path, *, include_attachments: bool) -> PreparedArtifact:
    before = _stat_identity(spec.source_path)
    source_hash = _sha256(spec.source_path)
    destination = temporary_root / hashlib.sha256(spec.logical_path.encode("utf-8")).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if spec.content_kind == "jsonl":
        transformations = _sanitize_jsonl(spec.source_path, destination, include_attachments=include_attachments)
    elif spec.content_kind == "json":
        transformations = _sanitize_json(spec.source_path, destination, include_attachments=include_attachments)
    elif spec.content_kind == "toml":
        transformations = _sanitize_toml(spec.source_path, destination, include_attachments=include_attachments)
    elif spec.content_kind == "binary":
        if not include_attachments:
            raise RuntimeError(f"binary attachment was not explicitly included: {spec.source_path}")
        shutil.copyfile(spec.source_path, destination)
        transformations = []
    else:
        transformations = _sanitize_text(spec.source_path, destination)
    after = _stat_identity(spec.source_path)
    if before != after or source_hash != _sha256(spec.source_path):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"source changed during backup: {spec.source_path}")
    portable_hash = _sha256(destination)
    destination.chmod(0o600)
    return PreparedArtifact(
        spec=spec,
        portable_path=destination,
        source_size=before[0],
        source_hash=source_hash,
        portable_size=destination.stat().st_size,
        portable_hash=portable_hash,
        transformations=transformations,
        source_stat=before,
    )


__all__ = ["prepare_artifact"]
