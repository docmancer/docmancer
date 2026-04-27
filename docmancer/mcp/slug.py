"""Tool-name slug generation per spec D15."""
from __future__ import annotations

import re

_FIELD_SEP = "__"


def version_slug(version: str) -> str:
    return re.sub(r"[.\-/]", "_", version)


def package_slug(package: str) -> str:
    return re.sub(r"[.\-/]", "_", package)


def tool_name(package: str, version: str, operation_id: str) -> str:
    return f"{package_slug(package)}{_FIELD_SEP}{version_slug(version)}{_FIELD_SEP}{operation_id}"


def split_tool_name(name: str) -> tuple[str, str, str] | None:
    parts = name.split(_FIELD_SEP)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]
