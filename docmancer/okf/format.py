"""Core primitives for Google's Open Knowledge Format (OKF) v0.1.

OKF represents knowledge as a directory of markdown files with YAML
frontmatter. The only required frontmatter field is ``type``; the reserved
recommended fields are ``title``, ``description``, ``resource``, ``tags``, and
``timestamp``. Producers may add their own keys, which consumers must
preserve. Reserved filenames are ``index.md`` (directory listing) and
``log.md`` (change history).

Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import yaml

OKF_VERSION = "0.1"

# Reserved filenames carry special meaning and are not concept documents.
RESERVED_FILENAMES = ("index.md", "log.md")

# The reserved frontmatter fields, in the order OKF presents them. ``type`` is
# required; the rest are recommended. Unknown keys are emitted afterwards.
RESERVED_FIELDS = ("type", "title", "description", "resource", "tags", "timestamp")

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _is_empty(value: Any) -> bool:
    """A value is dropped from frontmatter when it carries no information."""
    if value is None:
        return True
    if isinstance(value, (str, list, tuple, dict)) and len(value) == 0:
        return True
    return False


def dump_frontmatter(fields: Mapping[str, Any], body: str = "") -> str:
    """Render a markdown document with a YAML frontmatter block.

    Keys whose value is ``None`` or empty (empty string/list/dict) are dropped.
    Reserved fields are emitted first in spec order, then any extension keys in
    their given order. The returned string is ``---\\n<yaml>---\\n<body>``.
    """
    cleaned = {k: v for k, v in fields.items() if not _is_empty(v)}

    ordered: dict[str, Any] = {}
    for key in RESERVED_FIELDS:
        if key in cleaned:
            ordered[key] = cleaned[key]
    for key, value in cleaned.items():
        if key not in ordered:
            ordered[key] = value

    yaml_text = yaml.safe_dump(
        ordered, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    body = body or ""
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{yaml_text}---\n{body}"


def is_okf_bundle(path) -> bool:
    """True when ``path`` is a directory whose root ``index.md`` declares OKF.

    Detection is conservative: a plain directory of markdown files (no root
    ``index.md`` with an ``okf_version`` field) is not treated as a bundle.
    """
    from pathlib import Path

    root = Path(path)
    index = root / "index.md"
    if not root.is_dir() or not index.is_file():
        return False
    fields, _ = parse_frontmatter(index.read_text(encoding="utf-8"))
    return bool(fields.get("okf_version"))


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into ``(frontmatter_dict, body)``.

    A document without a leading frontmatter block yields ``({}, text)``.
    Malformed YAML is tolerated and yields an empty dict (the spec asks
    consumers to be lenient).
    """
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text[match.end() :]
    fields = loaded if isinstance(loaded, dict) else {}
    return fields, text[match.end() :]
