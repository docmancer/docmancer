"""OS keyring backed secret storage for cloud credentials and keys."""
from __future__ import annotations

from typing import Protocol

import keyring

import hashlib

from docmancer.cloud.crypto import b64decode, b64encode, box_keypair, signing_keypair


SERVICE = "docmancer-cloud"


class SecretBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class MemorySecretBackend:
    """Explicit in-memory backend for tests and ephemeral integrations."""
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class KeyStore:
    def __init__(
        self,
        backend: SecretBackend | None = None,
        *,
        service: str = SERVICE,
    ) -> None:
        self.backend = backend or keyring
        self.service = service

    def _name(self, account_id: str, kind: str) -> str:
        return f"{account_id}:{kind}"

    def get(self, account_id: str, kind: str) -> bytes | None:
        value = self.backend.get_password(self.service, self._name(account_id, kind))
        return b64decode(value) if value else None

    def set(self, account_id: str, kind: str, value: bytes) -> None:
        self.backend.set_password(self.service, self._name(account_id, kind), b64encode(value))

    def delete(self, account_id: str, kind: str) -> None:
        try:
            self.backend.delete_password(self.service, self._name(account_id, kind))
        except keyring.errors.PasswordDeleteError:
            pass

    def ensure_device_keys(self, account_id: str) -> dict[str, bytes]:
        signing_private = self.get(account_id, "device-signing-private")
        signing_public = self.get(account_id, "device-signing-public")
        box_private = self.get(account_id, "device-box-private")
        box_public = self.get(account_id, "device-box-public")
        if not signing_private or not signing_public:
            signing_private, signing_public = signing_keypair()
            self.set(account_id, "device-signing-private", signing_private)
            self.set(account_id, "device-signing-public", signing_public)
        if not box_private or not box_public:
            box_private, box_public = box_keypair()
            self.set(account_id, "device-box-private", box_private)
            self.set(account_id, "device-box-public", box_public)
        return {
            "signing_private": signing_private,
            "signing_public": signing_public,
            "box_private": box_private,
            "box_public": box_public,
        }

    @staticmethod
    def fingerprint(public_key: bytes) -> str:
        digest = hashlib.sha256(public_key).hexdigest().upper()
        return ":".join(digest[index:index + 4] for index in range(0, 32, 4))

    def workspace_key(self, account_id: str, workspace_id: str, key_version: int | None = None) -> bytes | None:
        suffix = f":v{int(key_version)}" if key_version is not None else ""
        return self.get(account_id, f"workspace:{workspace_id}{suffix}")

    def set_workspace_key(self, account_id: str, workspace_id: str, value: bytes, key_version: int | None = None) -> None:
        self.set(account_id, f"workspace:{workspace_id}", value)
        if key_version is not None:
            self.set(account_id, f"workspace:{workspace_id}:v{int(key_version)}", value)

    def token(self, account_id: str) -> bytes | None:
        return self.get(account_id, "access-token")

    def set_token(self, account_id: str, value: str) -> None:
        self.set(account_id, "access-token", value.encode("utf-8"))


__all__ = ["KeyStore", "MemorySecretBackend", "SecretBackend", "SERVICE"]
