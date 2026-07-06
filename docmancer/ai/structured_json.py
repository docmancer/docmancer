"""Shared helpers for schema-constrained provider output."""
from __future__ import annotations

import json
from typing import Any

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 180


def schema_name(response_format) -> str:
    return getattr(response_format, "__name__", "DocmancerResponse")


def _strict_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        normalized = {key: _strict_schema(value) for key, value in schema.items()}
        if normalized.get("type") == "object":
            normalized["additionalProperties"] = False
            properties = normalized.get("properties")
            if isinstance(properties, dict):
                normalized["required"] = list(properties)
        return normalized
    if isinstance(schema, list):
        return [_strict_schema(item) for item in schema]
    return schema


def json_schema(response_format) -> dict[str, Any]:
    schema = response_format.model_json_schema()
    return _strict_schema(schema)


def json_instruction(response_format) -> str:
    schema = json.dumps(json_schema(response_format), separators=(",", ":"))
    return (
        "Return only valid JSON matching this JSON schema. Do not wrap it in "
        f"markdown fences.\n\n{schema}"
    )


def strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def validate_json_text(text: str, response_format):
    return response_format.model_validate_json(strip_json_fences(text))


__all__ = [
    "DEFAULT_PROVIDER_TIMEOUT_SECONDS",
    "json_instruction",
    "json_schema",
    "schema_name",
    "strip_json_fences",
    "validate_json_text",
]
