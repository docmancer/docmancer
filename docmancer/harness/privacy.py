"""Privacy controls for harvested harness memory.

Two layers ship before any user-facing sync: secret redaction on the content
of every entry, and an include/exclude filter matched on BOTH the entry path
and scope (the sensitive signal usually lives in the path, e.g. ``~/.ssh``,
``.env``, ``.aws``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch

from .base import MemoryEntry

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S{6,}"),
]

# Matched against BOTH the entry path and scope, so they fire on real layouts
# (the sensitive signal is usually in the path, e.g. ~/.ssh, .env, .aws).
_DEFAULT_EXCLUDES = ["*/.ssh/*", "*/.ssh*", "*.env*", "*credential*", "*/.aws/*", "*secret*"]


def redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


@dataclass
class PrivacyFilter:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def _targets(self, e: MemoryEntry) -> list[str]:
        path = e.path or ""
        scope = e.scope or ""
        return [path, path.lower(), scope, scope.lower()]

    def allows(self, e: MemoryEntry) -> bool:
        targets = self._targets(e)
        for pat in list(_DEFAULT_EXCLUDES) + list(self.exclude):
            if any(fnmatch(t, pat) for t in targets):
                return False
        if self.include:
            return any(fnmatch(t, pat) for t in targets for pat in self.include)
        return True

    def clean(self, e: MemoryEntry) -> MemoryEntry:
        e.content = redact_secrets(e.content)
        return e


__all__ = ["redact_secrets", "PrivacyFilter"]
