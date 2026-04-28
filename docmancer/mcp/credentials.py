"""Credential resolution per spec 2.8.7 / D18.

Order: per-call override > process env > agent-config env (fed via env at
serve time) > user-managed env file. OS keychain stubbed for v1.1.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docmancer.mcp import paths

DOCMANCER_AUTH_KEY = "_docmancer_auth"


@dataclass
class CredentialResult:
    value: str | None
    source: str  # "per_call" | "env" | "secrets_file" | "missing"
    checked: list[str]


def resolve(
    package: str,
    scheme: dict[str, Any],
    args: dict[str, Any] | None = None,
) -> CredentialResult:
    """Resolve a credential for one auth scheme.

    `scheme` is the contract entry, e.g. `{"type": "bearer", "env": "EXAMPLE_API_KEY"}`.
    Optional `args` lets the agent pass `_docmancer_auth.{name}` per call.
    """
    env_name = scheme.get("env")
    scheme_name = scheme.get("name") or env_name or "default"
    checked: list[str] = []

    # 1. Per-call override
    if args:
        override = args.get(DOCMANCER_AUTH_KEY) or {}
        if isinstance(override, dict) and scheme_name in override:
            return CredentialResult(str(override[scheme_name]), "per_call", checked)
        checked.append(f"per_call:{DOCMANCER_AUTH_KEY}.{scheme_name}")

    # 2. Process env (covers shell-launched and agent-config env block,
    # since the agent injects env into our subprocess environment)
    if env_name:
        checked.append(f"env:{env_name}")
        value = os.environ.get(env_name)
        if value:
            return CredentialResult(value, "env", checked)

    # 3. User-managed env file
    env_file = paths.secrets_env_file(package)
    checked.append(f"file:{env_file}")
    if env_file.exists() and env_name:
        value = _parse_env_file(env_file).get(env_name)
        if value:
            return CredentialResult(value, "secrets_file", checked)

    # 4. OS keychain (stub)
    checked.append("keychain:stub")

    return CredentialResult(None, "missing", checked)


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        out[key.strip()] = value
    return out


@dataclass
class AuthMaterial:
    """Resolved credentials carried into the executor.

    OpenAPI `apiKey` schemes can declare `in: header | query | cookie`. The
    runtime must place the resolved value in the matching slot or auth fails.
    """

    headers: dict[str, str]
    params: dict[str, str]
    cookies: dict[str, str]
    missing: list[str]


def build_auth(
    package: str,
    auth: dict[str, Any],
    args: dict[str, Any] | None = None,
) -> AuthMaterial:
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    cookies: dict[str, str] = {}
    missing: list[str] = []
    for scheme in auth.get("schemes", []):
        result = resolve(package, scheme, args)
        if result.value is None:
            missing.append(scheme.get("name") or scheme.get("env") or scheme.get("type", "?"))
            continue
        scheme_type = (scheme.get("type") or "").lower()
        if scheme_type == "bearer":
            headers[scheme.get("header", "Authorization")] = f"Bearer {result.value}"
            continue
        if scheme_type == "oauth2":
            headers[scheme.get("header", "Authorization")] = f"Bearer {result.value}"
            continue
        if scheme_type in {"apikey", "api_key"}:
            location = (scheme.get("in") or "header").lower()
            # `name` is the OpenAPI param name (e.g. `api_key`); `header` is set by the
            # compiler for header schemes. Prefer `name` for query/cookie placement.
            param_name = scheme.get("name") or scheme.get("header") or "X-API-Key"
            if location == "query":
                params[param_name] = result.value
            elif location == "cookie":
                cookies[param_name] = result.value
            else:
                headers[scheme.get("header") or param_name] = result.value
            continue
        # Unknown scheme type: best-effort header placement (preserves prior behavior).
        headers[scheme.get("header", "Authorization")] = result.value
    return AuthMaterial(headers=headers, params=params, cookies=cookies, missing=missing)


def build_auth_headers(
    package: str,
    auth: dict[str, Any],
    args: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Backward-compat shim: returns header-shaped credentials + missing list."""
    material = build_auth(package, auth, args)
    return material.headers, material.missing
