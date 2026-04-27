"""Tool-call dispatcher: schema validation, safety, credentials, idempotency, executor.

This is the runtime spine described in spec sections 2.5, 2.7.5, 2.8.1,
2.8.3, 2.8.5, 2.8.6, 2.8.7. Pure functions where possible so tests can
drive it directly without a real MCP transport.
"""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass
from typing import Any

import jsonschema

from docmancer.mcp import credentials, idempotency, safety
from docmancer.mcp.executors import get_executor
from docmancer.mcp.logging import log_call
from docmancer.mcp.manifest import InstalledPackage, Manifest
from docmancer.mcp.search import ToolEntry, build_corpus, search
from docmancer.mcp.slug import split_tool_name


@dataclass
class DispatchResult:
    ok: bool
    body: Any
    error_code: str | None = None
    idempotency_key: str | None = None
    status: int | str | None = None


SEARCH_TOOL = "docmancer_search_tools"
CALL_TOOL = "docmancer_call_tool"

SEARCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "package": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
    },
    "required": ["query"],
}

CALL_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["name", "args"],
}


class Dispatcher:
    def __init__(self, manifest: Manifest):
        self._manifest = manifest
        self._corpus: list[ToolEntry] = build_corpus(manifest.enabled_packages())

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": SEARCH_TOOL,
                "description": (
                    "Search across installed API packages for tools matching a task. "
                    "Returns top-K tool names with descriptions and an inlined input "
                    "schema for the top match. Always call this before docmancer_call_tool."
                ),
                "inputSchema": SEARCH_TOOL_SCHEMA,
            },
            {
                "name": CALL_TOOL,
                "description": (
                    "Invoke a tool returned by docmancer_search_tools. Use the fully "
                    "qualified name from the search result."
                ),
                "inputSchema": CALL_TOOL_SCHEMA,
            },
        ]

    def search_tools(
        self,
        query: str,
        *,
        package: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        matches = search(self._corpus, query, package=package, limit=limit)
        out: list[dict[str, Any]] = []
        for i, m in enumerate(matches):
            entry: dict[str, Any] = {
                "name": m.name,
                "package": m.package,
                "version": m.version,
                "description": m.description,
                "safety": m.safety,
            }
            if i == 0:
                entry["inputSchema"] = m.input_schema
            out.append(entry)
        return {"matches": out}

    def call_tool(self, name: str, args: dict[str, Any]) -> DispatchResult:
        start = time.time()
        resolved = self._resolve(name)
        if resolved is None:
            suggestions = self._fuzzy_suggestions(name)
            body = {
                "error": "tool_not_found",
                "message": f"Unknown tool: {name}",
                "did_you_mean": suggestions,
            }
            log_call(tool=name, args=args, status="tool_not_found",
                     latency_ms=int((time.time() - start) * 1000))
            return DispatchResult(False, body, "tool_not_found")

        pkg, operation = resolved
        contract = pkg.contract()
        auth = contract.get("auth", {}) or {}
        input_schema = operation.get("inputSchema") or _schema_from_params(operation)

        # Strip docmancer control fields before validation
        validation_args = {k: v for k, v in args.items() if not k.startswith("_docmancer")}
        try:
            jsonschema.validate(validation_args, input_schema)
        except jsonschema.ValidationError as exc:
            body = {
                "error": "invalid_args",
                "message": exc.message,
                "schema_path": list(exc.absolute_path),
                "schema": input_schema,
            }
            log_call(tool=name, args=args, status="invalid_args",
                     latency_ms=int((time.time() - start) * 1000))
            return DispatchResult(False, body, "invalid_args")

        auth_material = credentials.build_auth(pkg.package, auth, args)
        missing = auth_material.missing
        gate = safety.check(
            package=pkg.package,
            version=pkg.version,
            operation=operation,
            allow_destructive=pkg.allow_destructive,
            has_credentials=not missing or not (operation.get("safety") or {}).get("requires_auth"),
        )
        if not gate.allowed:
            body = {
                "error": gate.error_code,
                "message": gate.message,
                "missing_credential_sources": missing if gate.error_code == "missing_credentials" else None,
            }
            log_call(tool=name, args=args, status=gate.error_code or "blocked",
                     latency_ms=int((time.time() - start) * 1000))
            return DispatchResult(False, body, gate.error_code)

        # Idempotency
        op_safety = operation.get("safety") or {}
        idempotency_key: str | None = None
        idempotency_header = auth.get("idempotency_header")
        if not op_safety.get("idempotent", True) and idempotency_header:
            idempotency_key, _ = idempotency.get_or_create_key(name, args)

        executor_kind = operation.get("executor", "http")
        if executor_kind in {"python_import", "shell"} and not getattr(pkg, "allow_execute", False):
            body = {
                "error": "execution_not_allowed",
                "message": (
                    f"Operation {operation.get('id')} uses executor '{executor_kind}' which "
                    f"requires opt-in. To enable: docmancer install-pack {pkg.package}@{pkg.version} "
                    f"--allow-execute, then restart your agent."
                ),
            }
            log_call(tool=name, args=args, status="execution_not_allowed",
                     latency_ms=int((time.time() - start) * 1000))
            return DispatchResult(False, body, "execution_not_allowed")
        executor = get_executor(executor_kind)
        result = executor.call(
            operation=operation,
            args=validation_args,
            auth_headers=auth_material.headers,
            required_headers=auth.get("required_headers", {}) or {},
            idempotency_key=idempotency_key,
            idempotency_header=idempotency_header,
            auth_params=auth_material.params,
            auth_cookies=auth_material.cookies,
        )

        body: Any = result.body
        if isinstance(body, dict) and idempotency_key:
            body = {**body, "_docmancer": {"idempotency_key": idempotency_key}}

        log_call(
            tool=name,
            args=args,
            status=result.status,
            latency_ms=int((time.time() - start) * 1000),
            idempotency_key=idempotency_key,
        )
        return DispatchResult(
            ok=result.ok,
            body=body if result.ok else {"error": result.error or "executor_error", "status": result.status, "body": body},
            error_code=None if result.ok else "executor_error",
            idempotency_key=idempotency_key,
            status=result.status,
        )

    # ---- internals ----

    def _resolve(self, tool_name: str) -> tuple[InstalledPackage, dict[str, Any]] | None:
        for entry in self._corpus:
            if entry.name == tool_name:
                pkg = self._manifest.find(entry.package, entry.version)
                if pkg is None:
                    return None
                contract = pkg.contract()
                for op in contract.get("operations", []):
                    if op.get("id") == entry.operation_id:
                        return pkg, op
                return None
        # Fallback: parse the name and search the contract directly
        parts = split_tool_name(tool_name)
        if not parts:
            return None
        pkg_slug, _ver_slug, op_id = parts
        for pkg in self._manifest.enabled_packages():
            if pkg.package.replace(".", "_").replace("-", "_").replace("/", "_") != pkg_slug:
                continue
            for op in pkg.contract().get("operations", []):
                if op.get("id") == op_id:
                    return pkg, op
        return None

    def _fuzzy_suggestions(self, name: str, n: int = 3) -> list[str]:
        names = [t.name for t in self._corpus]
        return difflib.get_close_matches(name, names, n=n, cutoff=0.4)


def _schema_from_params(operation: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema from contract `params` if no inputSchema was provided."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in operation.get("params", []) or []:
        name = p.get("name")
        if not name:
            continue
        prop: dict[str, Any] = {}
        if p.get("type"):
            prop["type"] = p["type"]
        if p.get("description"):
            prop["description"] = p["description"]
        properties[name] = prop or {"type": "string"}
        if p.get("required"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema
