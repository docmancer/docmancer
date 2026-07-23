"""Structured, agent-recoverable errors shared across the tree package
(checklist A.13).

Every error names the failed safe target, states the likely cause, states
whether retry is safe, and (where applicable) names the exact next call or
argument shape to try. Messages never include secrets, raw stack traces, or
paths outside the caller's own request.
"""
from __future__ import annotations


class TreeError(Exception):
    """Base class. ``retry_safe`` and ``likely_cause`` are always set."""

    retry_safe: bool = False
    likely_cause: str = ""


class AddressNotFoundError(TreeError):
    retry_safe = True

    def __init__(self, address: str) -> None:
        self.address = address
        self.likely_cause = "No memory file in the tree matches this address."
        self.next_action = "Call search_memory with a broader query, or list the tree to find the right address."
        super().__init__(f"no memory found for address {address!r}")


class AmbiguousAddressError(TreeError):
    retry_safe = True

    def __init__(self, address: str, candidates: list[str]) -> None:
        self.address = address
        self.candidates = candidates
        self.likely_cause = "More than one memory file matches this title or path."
        self.next_action = "Retry read_memory with one of the returned candidate addresses."
        super().__init__(f"address {address!r} is ambiguous; candidates: {candidates}")


class StaleWriteError(TreeError):
    retry_safe = True

    def __init__(self, address: str, expected_hash: str | None, actual_hash: str) -> None:
        self.address = address
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.likely_cause = "The file changed on disk since expected_hash was read."
        self.next_action = f"Re-read {address} to get the current content_hash, then retry the write with it."
        super().__init__(
            f"expected content hash {expected_hash!r} does not match current hash "
            f"{actual_hash!r} for {address}; re-read and retry"
        )


class AlreadyExistsError(TreeError):
    retry_safe = False

    def __init__(self, address: str) -> None:
        self.address = address
        self.likely_cause = "A create-only write targeted a path that already has a file."
        self.next_action = f"Use edit_memory with the current content_hash to update {address}, or choose a different path."
        super().__init__(f"a memory file already exists at {address!r}; create-only write refused")


class ForbiddenPathError(TreeError):
    retry_safe = False

    def __init__(self, path: str) -> None:
        self.path = path
        self.likely_cause = "The requested path resolves outside the allowed memory root."
        self.next_action = "Use a path relative to the project's own memory root; cross-project or absolute paths are never accepted."
        super().__init__(f"path escapes the allowed memory root: {path!r}")


class ForbiddenScopeError(TreeError):
    retry_safe = False

    def __init__(self, requested_scope: str, allowed_scopes: set[str]) -> None:
        self.requested_scope = requested_scope
        self.allowed_scopes = allowed_scopes
        self.likely_cause = "The requested scope is not permitted for this caller or store."
        self.next_action = f"Use one of the allowed scopes: {sorted(allowed_scopes)}."
        super().__init__(f"scope {requested_scope!r} is not permitted; allowed: {sorted(allowed_scopes)}")


class InvalidFrontmatterFieldError(TreeError):
    retry_safe = False

    def __init__(self, field: str, value: object, allowed: set[str]) -> None:
        self.field = field
        self.value = value
        self.allowed = allowed
        self.likely_cause = f"{field}={value!r} is not one of the allowed values."
        self.next_action = f"Use one of: {sorted(allowed)}."
        super().__init__(f"invalid {field}={value!r}; allowed: {sorted(allowed)}")
