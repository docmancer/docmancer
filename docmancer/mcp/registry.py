"""Registry clients for installing local API MCP packs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from docmancer.mcp import paths

ARTIFACT_FILES = [
    "contract.json",
    "tools.curated.json",
    "tools.full.json",
    "auth.schema.json",
    "provenance.json",
]

ARTIFACT_TYPE_BY_FILE = {
    "contract.json": "typed_contract",
    "tools.curated.json": "mcp_tools_curated",
    "tools.full.json": "mcp_tools_full",
    "auth.schema.json": "auth_schema",
    "provenance.json": "provenance",
}

DEFAULT_REGISTRY_API_URL = "https://docmancer.dev"


class RegistryClient:
    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        raise NotImplementedError

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        return None


class LocalRegistry(RegistryClient):
    """Reads cached or developer-supplied packs from the local registry dir."""

    def __init__(self, root: Path | None = None):
        self._root = root if root is not None else paths.registry_dir()

    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        path = self._root / f"{package}@{version}" / artifact
        if not path.exists():
            raise FileNotFoundError(
                f"{artifact} not found for {package}@{version} in local registry {self._root}"
            )
        return path.read_bytes()

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        manifest_path = self._root / f"{package}@{version}" / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            return None
        sha_map = data.get("sha256") or {}
        return sha_map.get(artifact) if isinstance(sha_map, dict) else None


class HostedRegistry(RegistryClient):
    """Fetches precompiled artifacts from a hosted registry API.

    The default points at docmancer.dev so user installs are zero-config.
    DOCMANCER_REGISTRY_API_URL remains as a developer override for staging.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self._base_url = (
            base_url
            or os.environ.get("DOCMANCER_REGISTRY_API_URL")
            or DEFAULT_REGISTRY_API_URL
        ).rstrip("/")
        self._timeout = timeout
        self._sha: dict[tuple[str, str, str], str] = {}

    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        artifact_type = ARTIFACT_TYPE_BY_FILE.get(artifact)
        if not artifact_type:
            raise FileNotFoundError(f"Unknown registry artifact: {artifact}")
        meta_url = f"{self._base_url}/v1-packs-get-artifact?{urlencode({'name': package, 'version': version, 'type': artifact_type})}"
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            meta = client.get(meta_url)
            if meta.status_code == 404:
                raise FileNotFoundError(f"{package}@{version} not found in hosted registry")
            meta.raise_for_status()
            payload = meta.json()
            download_url = payload.get("download_url")
            if not download_url:
                raise FileNotFoundError(f"Hosted registry did not return a download URL for {artifact}")
            body = client.get(download_url)
            body.raise_for_status()
        data = body.content
        expected = payload.get("sha256")
        if expected:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"SHA-256 mismatch for {artifact}: expected {expected}, got {actual}"
                )
            self._sha[(package, version, artifact)] = expected
        return data

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        return self._sha.get((package, version, artifact))


class KnownOpenAPIRegistry(RegistryClient):
    """Builds known public API packs locally when precompiled artifacts are absent."""

    STRIPE_OPENAPI_URL = "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json"

    def __init__(self, cache_root: Path | None = None, timeout: float = 60.0):
        self._cache_root = cache_root if cache_root is not None else paths.registry_dir()
        self._timeout = timeout

    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        if package != "stripe":
            raise FileNotFoundError(
                f"No built-in OpenAPI fallback is available for {package}@{version}"
            )
        pkg_dir = self._cache_root / f"{package}@{version}"
        if not (pkg_dir / "contract.json").exists():
            self._build_stripe(version, pkg_dir)
        path = pkg_dir / artifact
        if not path.exists():
            raise FileNotFoundError(f"{artifact} not generated for {package}@{version}")
        return path.read_bytes()

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        return LocalRegistry(self._cache_root).expected_sha256(package, version, artifact)

    def _build_stripe(self, version: str, pkg_dir: Path) -> None:
        source_url = os.environ.get("DOCMANCER_STRIPE_OPENAPI_URL", self.STRIPE_OPENAPI_URL)
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.get(source_url)
            response.raise_for_status()
        source = response.content
        spec = json.loads(source)
        source_sha = hashlib.sha256(source).hexdigest()
        build_openapi_pack(
            package="stripe",
            version=version,
            spec=spec,
            output_dir=pkg_dir,
            source_url=source_url,
            source_sha256=source_sha,
            overrides=stripe_overrides(version),
            curated_ids=STRIPE_CURATED_IDS,
        )


class CompositeRegistry(RegistryClient):
    """Try local cache, hosted registry, then known-source compilation."""

    def __init__(self, registries: list[RegistryClient]):
        self._registries = registries
        self._used: RegistryClient | None = None

    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        errors: list[str] = []
        for registry in self._registries:
            try:
                data = registry.fetch(package, version, artifact)
                self._used = registry
                return data
            except FileNotFoundError as exc:
                errors.append(str(exc))
                continue
            except httpx.HTTPError as exc:
                errors.append(str(exc))
                continue
        detail = "; ".join(e for e in errors if e)
        raise FileNotFoundError(
            f"Pack {package}@{version} is not available locally, from the hosted registry, "
            f"or from a known OpenAPI fallback. {detail}"
        )

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        if self._used is None:
            return None
        return self._used.expected_sha256(package, version, artifact)


def default_registry() -> RegistryClient:
    registries: list[RegistryClient] = [
        LocalRegistry(),
        HostedRegistry(),
        KnownOpenAPIRegistry(),
    ]
    return CompositeRegistry(registries)


def build_openapi_pack(
    *,
    package: str,
    version: str,
    spec: dict[str, Any],
    output_dir: Path,
    source_url: str | None,
    source_sha256: str | None,
    overrides: dict[str, Any] | None = None,
    curated_ids: list[str] | None = None,
) -> None:
    overrides = overrides or {}
    contract = compile_openapi(spec, package, version, source_url, source_sha256, overrides)
    curated = select_curated(contract, curated_ids)
    contract["curation"] = curated
    curated_artifact, full_artifact = emit_tool_artifacts(contract, curated)
    artifacts = {
        "contract.json": contract,
        "tools.curated.json": curated_artifact,
        "tools.full.json": full_artifact,
        "auth.schema.json": contract["auth"],
        "provenance.json": {
            "package": package,
            "version": version,
            "source": contract["source"],
            "source_url": source_url,
            "source_sha256": source_sha256,
            "compiled_at": _now_iso(),
            "compiler": "docmancer.builtin_openapi",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    sha_map: dict[str, str] = {}
    size_map: dict[str, int] = {}
    for filename, payload in artifacts.items():
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        _atomic_write(output_dir / filename, body)
        sha_map[filename] = hashlib.sha256(body).hexdigest()
        size_map[filename] = len(body)
    manifest = {
        "package": package,
        "version": version,
        "generated_at": _now_iso(),
        "sha256": sha_map,
        "size_bytes": size_map,
    }
    _atomic_write(output_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())


def compile_openapi(
    spec: dict[str, Any],
    package: str,
    version: str,
    source_url: str | None,
    source_sha256: str | None,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    schemas = (spec.get("components") or {}).get("schemas") or {}
    security_schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    base_url = _pick_base_url(spec)
    auth = _build_auth(security_schemes, overrides)
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        common_params = item.get("parameters") or []
        for method in ("get", "put", "post", "delete", "patch", "head", "options"):
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = _operation_id(package, method, path, op, seen)
            seen.add(op_id)
            param_dicts = _normalize_params(_merge_params(common_params, op.get("parameters") or []), schemas)
            body_dicts, encoding = _normalize_body(op.get("requestBody"), schemas, overrides, op_id)
            params = param_dicts + body_dicts
            op_meta = {
                "method": method.upper(),
                "path": path,
                "security": op.get("security", spec.get("security") or []),
                "x_idempotent": op.get("x-idempotent"),
                "rate_limit": op.get("x-rate-limit"),
            }
            operations.append({
                "id": op_id,
                "summary": op.get("summary") or op.get("description", "")[:200],
                "description": op.get("description"),
                "executor": "http",
                "http": {
                    "method": method.upper(),
                    "path": path,
                    "base_url": base_url,
                    "encoding": encoding,
                },
                "params": params,
                "inputSchema": _build_input_schema(params),
                "returns": _normalize_responses(op.get("responses") or {}, schemas),
                "safety": _derive_safety(op_meta),
                "examples": _extract_examples(op),
            })
    contract: dict[str, Any] = {
        "docmancer_contract_version": "1",
        "package": package,
        "version": version,
        "source": {
            "kind": "openapi",
            "url": source_url,
            "sha256": source_sha256,
            "fetched_at": _now_iso(),
            "openapi_version": spec.get("openapi") or spec.get("swagger"),
        },
        "auth": auth,
        "operations": operations,
        "schemas": schemas,
    }
    if spec.get("webhooks"):
        contract["webhooks"] = spec["webhooks"]
    return contract


def stripe_overrides(version: str) -> dict[str, Any]:
    return {
        "auth": {
            "required_headers": {"Stripe-Version": version},
            "idempotency_header": "Idempotency-Key",
            "schemes": [{
                "name": "stripe",
                "type": "bearer",
                "header": "Authorization",
                "env": "STRIPE_API_KEY",
            }],
        },
        "default_encoding": "form",
    }


STRIPE_CURATED_IDS = [
    "payment_intents_create",
    "payment_intents_retrieve",
    "payment_intents_list",
    "payment_intents_update",
    "payment_intents_capture",
    "payment_intents_cancel",
    "payment_intents_confirm",
    "customers_create",
    "customers_retrieve",
    "customers_list",
    "customers_update",
    "customers_delete",
    "charges_retrieve",
    "charges_list",
    "subscriptions_create",
    "subscriptions_retrieve",
    "subscriptions_list",
    "subscriptions_update",
    "subscriptions_cancel",
    "invoices_create",
    "invoices_retrieve",
    "invoices_list",
    "invoices_finalize",
    "refunds_create",
    "refunds_retrieve",
    "refunds_list",
    "balance_retrieve",
    "balance_transactions_list",
]


def emit_tool_artifacts(
    contract: dict[str, Any],
    curation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    full_tools = [_tool_entry(op) for op in contract.get("operations", [])]
    full = {"package": contract.get("package"), "version": contract.get("version"), "tools": full_tools}
    curated_ids = curation.get("operation_ids") or [t["operation_id"] for t in full_tools[:30]]
    order = {oid: i for i, oid in enumerate(curated_ids)}
    curated_set = set(curated_ids)
    curated_tools = [t for t in full_tools if t["operation_id"] in curated_set]
    curated_tools.sort(key=lambda t: order.get(t["operation_id"], 9999))
    curated = {
        "package": contract.get("package"),
        "version": contract.get("version"),
        "curation": curation,
        "tools": curated_tools,
    }
    return curated, full


def select_curated(contract: dict[str, Any], override_ids: list[str] | None) -> dict[str, Any]:
    operations = contract.get("operations") or []
    valid_ids = {op.get("id") for op in operations}
    picked = [oid for oid in (override_ids or []) if oid in valid_ids]
    if picked:
        return {"operation_ids": picked, "source": "builtin", "generated_at": _now_iso()}
    return {
        "operation_ids": [op["id"] for op in operations[:30]],
        "source": "heuristic",
        "generated_at": _now_iso(),
    }


def _tool_entry(op: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": op.get("id"),
        "description": op.get("description") or op.get("summary") or "",
        "safety": op.get("safety", {}),
        "executor": op.get("executor", "http"),
        "inputSchema": op.get("inputSchema", {"type": "object"}),
    }


def _operation_id(package: str, method: str, path: str, op: dict[str, Any], seen: set[str]) -> str:
    if package == "stripe":
        derived = _stripe_operation_id(method, path)
        if derived:
            return _unique(derived, seen)
    raw = op.get("operationId")
    if raw:
        base = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").lower()
    else:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").lower()
        base = f"{method.lower()}_{slug}"
    return _unique(base, seen)


def _stripe_operation_id(method: str, path: str) -> str | None:
    method = method.lower()
    parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
    if parts and parts[0] == "v1":
        parts = parts[1:]
    if not parts:
        return None
    resource = "_".join(parts)
    has_path_param = "{" in path
    if resource == "balance" and method == "get":
        return "balance_retrieve"
    action = {
        "get": "retrieve" if has_path_param else "list",
        "post": "update" if has_path_param else "create",
        "delete": "delete",
    }.get(method)
    if path.endswith("/capture"):
        action = "capture"
        resource = "_".join(parts[:-1])
    elif path.endswith("/cancel"):
        action = "cancel"
        resource = "_".join(parts[:-1])
    elif path.endswith("/confirm"):
        action = "confirm"
        resource = "_".join(parts[:-1])
    elif path.endswith("/finalize"):
        action = "finalize"
        resource = "_".join(parts[:-1])
    return f"{resource}_{action}" if action else None


def _unique(base: str, seen: set[str]) -> str:
    if base not in seen:
        return base
    i = 2
    while f"{base}_{i}" in seen:
        i += 1
    return f"{base}_{i}"


def _pick_base_url(spec: dict[str, Any]) -> str:
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        return servers[0].get("url", "")
    return ""


def _build_auth(security_schemes: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    if "auth" in overrides:
        return dict(overrides["auth"])
    schemes: list[dict[str, Any]] = []
    for name, ss in security_schemes.items():
        if not isinstance(ss, dict):
            continue
        kind = (ss.get("type") or "").lower()
        if kind == "http" and (ss.get("scheme") or "").lower() == "bearer":
            schemes.append({"name": name, "type": "bearer", "header": "Authorization", "env": _guess_env(name)})
        elif kind == "apikey":
            schemes.append({
                "name": name,
                "type": "apikey",
                "header": ss.get("name", "X-API-Key"),
                "in": ss.get("in", "header"),
                "env": _guess_env(name),
            })
    return {"schemes": schemes}


def _guess_env(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return cleaned if cleaned.endswith(("_KEY", "_TOKEN")) else f"{cleaned}_API_KEY"


def _merge_params(common: list[Any], op_params: list[Any]) -> list[Any]:
    seen = {(p.get("name"), p.get("in")) for p in op_params if isinstance(p, dict)}
    out = list(op_params)
    for p in common:
        if isinstance(p, dict) and (p.get("name"), p.get("in")) not in seen:
            out.append(p)
    return out


def _normalize_params(params: list[Any], schemas: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in params:
        if not isinstance(p, dict):
            continue
        location = p.get("in")
        if location == "cookie":
            continue
        schema = _resolve_ref(p.get("schema") or {}, schemas)
        out.append({
            "name": p.get("name"),
            "in": location,
            "type": schema.get("type", "string"),
            "required": bool(p.get("required")),
            "description": p.get("description"),
            "schema": schema,
        })
    return out


def _normalize_body(
    request_body: Any,
    schemas: dict[str, Any],
    overrides: dict[str, Any],
    op_id: str,
) -> tuple[list[dict[str, Any]], str]:
    encoding = _override_for(overrides, "operations", op_id, "encoding") or overrides.get("default_encoding")
    if not isinstance(request_body, dict):
        return [], encoding or "json"
    content = request_body.get("content") or {}
    media = content.get("application/json") or content.get("application/x-www-form-urlencoded") or content.get("multipart/form-data") or {}
    schema = _resolve_ref(media.get("schema") or {}, schemas)
    out: list[dict[str, Any]] = []
    for name, prop_schema in (schema.get("properties") or {}).items():
        prop_schema = _resolve_ref(prop_schema, schemas)
        out.append({
            "name": name,
            "in": "body",
            "type": prop_schema.get("type", "object"),
            "required": name in set(schema.get("required") or []),
            "description": prop_schema.get("description"),
            "schema": prop_schema,
        })
    return out, encoding or _pick_encoding(content)


def _pick_encoding(content: dict[str, Any]) -> str:
    if "application/x-www-form-urlencoded" in content:
        return "form"
    if "multipart/form-data" in content:
        return "multipart"
    return "json"


def _normalize_responses(responses: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    for code in ("200", "201", "default"):
        resp = responses.get(code)
        if isinstance(resp, dict):
            content = resp.get("content") or {}
            json_resp = content.get("application/json") or {}
            schema = _resolve_ref(json_resp.get("schema") or {}, schemas)
            if schema:
                return {"type": schema.get("type", "object"), "schema": schema}
    return {"type": "object"}


def _build_input_schema(params: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        name = p.get("name")
        if not name:
            continue
        props[name] = p.get("schema") or {"type": p.get("type", "string")}
        if p.get("required"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _resolve_ref(schema: Any, schemas: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    if depth > 8 or not isinstance(schema, dict):
        return schema if isinstance(schema, dict) else {}
    ref = schema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        target = schemas.get(ref.split("/")[-1])
        if isinstance(target, dict):
            return _resolve_ref(target, schemas, depth + 1)
    return schema


def _derive_safety(meta: dict[str, Any]) -> dict[str, Any]:
    method = (meta.get("method") or "GET").upper()
    path = meta.get("path") or ""
    destructive = method in {"POST", "PUT", "PATCH", "DELETE"}
    if destructive and any(hint in path.lower() for hint in ("/search", "/query", "/list", "/find")):
        destructive = False
    idempotent = method in {"GET", "HEAD", "PUT", "DELETE"} or meta.get("x_idempotent") is True
    return {
        "destructive": destructive,
        "idempotent": idempotent,
        "requires_auth": bool(meta.get("security")),
        "rate_limit": meta.get("rate_limit"),
    }


def _extract_examples(op: dict[str, Any]) -> list[Any]:
    examples = op.get("x-examples") or op.get("examples") or []
    if isinstance(examples, dict):
        return list(examples.values())
    return examples if isinstance(examples, list) else []


def _override_for(overrides: dict[str, Any], *path: str) -> Any:
    cur: Any = overrides
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
