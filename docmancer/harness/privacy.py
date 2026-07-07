"""Privacy controls for harvested harness memory.

Two layers ship before any user-facing sync: secret redaction on the content
of every entry, and an include/exclude filter matched on BOTH the entry path
and scope (the sensitive signal usually lives in the path, e.g. ``~/.ssh``,
``.env``, ``.aws``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

from .base import MemoryEntry
from .secrets import redact_secrets

# Matched against BOTH the entry path and scope, so they fire on real layouts
# (the sensitive signal is usually in the path, e.g. ~/.ssh, .env, .aws).
_DEFAULT_EXCLUDES = ["*/.ssh/*", "*/.ssh*", "*.env*", "*credential*", "*/.aws/*", "*secret*"]

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
