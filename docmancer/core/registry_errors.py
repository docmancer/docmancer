from __future__ import annotations


class RegistryError(Exception):
    code = "registry_error"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code is not None:
            self.code = code
        super().__init__(message)


class RegistryUnreachable(RegistryError):
    code = "registry_unreachable"

    def __init__(self, registry_url: str, reason: str):
        self.registry_url = registry_url
        self.reason = reason
        super().__init__(f"Registry unreachable: {registry_url} ({reason})")


class PackNotFound(RegistryError):
    code = "pack_not_found"

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Pack not found: {name}")


class VersionNotFound(RegistryError):
    code = "version_not_found"

    def __init__(self, name: str, version: str, available: list[str] | None = None):
        self.name = name
        self.version = version
        self.available = available or []
        super().__init__(f"Version not found: {name}@{version}")


class AuthRequired(RegistryError):
    code = "auth_required"

    def __init__(self, message: str = "Authentication required. Run: docmancer auth login"):
        super().__init__(message)


class AuthExpired(RegistryError):
    code = "auth_expired"

    def __init__(self):
        super().__init__("Token expired or invalid. Run: docmancer auth login")


class ProRequired(RegistryError):
    code = "pro_required"

    def __init__(self, feature: str, free_alternative: str | None = None):
        self.feature = feature
        self.free_alternative = free_alternative
        msg = f"Pro required for {feature}."
        if free_alternative:
            msg += f" Free alternative: {free_alternative}"
        super().__init__(msg)


class CommunityPackBlocked(RegistryError):
    code = "community_pack_blocked"

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Community pack blocked: {name}. Re-run with --community to allow it.")


class ChecksumMismatch(RegistryError):
    code = "checksum_mismatch"

    def __init__(self, name: str, version: str, expected: str, actual: str):
        self.name = name
        self.version = version
        self.expected = expected
        self.actual = actual
        super().__init__(f"Checksum mismatch for {name}@{version}: expected {expected}, got {actual}")


class IncompatiblePack(RegistryError):
    code = "incompatible_pack"

    def __init__(self, name: str, required_version: str, installed_version: str):
        self.name = name
        self.required_version = required_version
        self.installed_version = installed_version
        super().__init__(f"Incompatible pack {name}: requires {required_version}, installed {installed_version}")


class RateLimited(RegistryError):
    code = "rate_limited"

    def __init__(self, retry_after: int | None = None):
        self.retry_after = retry_after
        super().__init__("Registry rate limit exceeded.")


class ServerError(RegistryError):
    code = "server_error"

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"Registry server error: HTTP {status_code}")
