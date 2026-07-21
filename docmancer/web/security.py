"""Browser-session security for the loopback web application."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from starlette.datastructures import Headers


SESSION_COOKIE = "docmancer_session"
MAX_REQUEST_BYTES = 2 * 1024 * 1024


@dataclass
class BrowserSession:
    token_hash: str
    csrf_token: str


@dataclass
class LoopbackSecurity:
    port: int
    bootstrap_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    bootstrap_used: bool = False
    sessions: dict[str, BrowserSession] = field(default_factory=dict)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def exchange_bootstrap(self, supplied: str) -> tuple[str, str] | None:
        if self.bootstrap_used or not hmac.compare_digest(supplied, self.bootstrap_token):
            return None
        self.bootstrap_used = True
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        self.sessions[digest] = BrowserSession(token_hash=digest, csrf_token=csrf_token)
        return session_token, csrf_token

    def session(self, headers: Headers, cookies: dict[str, str]) -> BrowserSession | None:
        token = cookies.get(SESSION_COOKIE)
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self.sessions.get(digest)

    def valid_host(self, headers: Headers) -> bool:
        return (headers.get("host") or "") in self.allowed_hosts

    def valid_mutation(self, headers: Headers, session: BrowserSession) -> bool:
        origin = headers.get("origin")
        csrf = headers.get("x-docmancer-csrf")
        return origin == self.origin and bool(csrf) and hmac.compare_digest(csrf, session.csrf_token)


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; "
        "font-src 'self'; frame-ancestors 'none'; img-src 'self' data:; "
        "object-src 'none'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


__all__ = [
    "BrowserSession",
    "LoopbackSecurity",
    "MAX_REQUEST_BYTES",
    "SECURITY_HEADERS",
    "SESSION_COOKIE",
]
