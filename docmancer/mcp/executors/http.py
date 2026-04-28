"""HTTP executor with explicit per-operation encoding (D19)."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from docmancer.mcp.executors.base import Executor, ExecutorResult

DEFAULT_TIMEOUT = 30.0


class HttpExecutor(Executor):
    def __init__(self, client: httpx.Client | None = None, timeout: float = DEFAULT_TIMEOUT):
        self._client = client
        self._timeout = timeout

    def call(
        self,
        *,
        operation: dict[str, Any],
        args: dict[str, Any],
        auth_headers: dict[str, str],
        required_headers: dict[str, str],
        idempotency_key: str | None,
        idempotency_header: str | None,
        auth_params: dict[str, str] | None = None,
        auth_cookies: dict[str, str] | None = None,
    ) -> ExecutorResult:
        http_meta = operation.get("http", {})
        method = http_meta.get("method", "GET").upper()
        base_url = http_meta.get("base_url", "")
        path_template = http_meta.get("path", "")
        encoding = http_meta.get("encoding", "json")

        params = operation.get("params", []) or []
        path_args, query_args, header_args, body_args = _partition_args(params, args)

        url = base_url.rstrip("/") + _render_path(path_template, path_args)

        headers: dict[str, str] = {}
        headers.update(required_headers or {})
        headers.update(auth_headers or {})
        headers.update(header_args)
        if idempotency_key and idempotency_header and method != "GET":
            headers[idempotency_header] = idempotency_key

        merged_query: dict[str, Any] = {**(query_args or {}), **(auth_params or {})}
        request_kwargs: dict[str, Any] = {"params": merged_query or None, "headers": headers}
        if auth_cookies:
            request_kwargs["cookies"] = dict(auth_cookies)

        if encoding == "json" and body_args:
            request_kwargs["json"] = body_args
        elif encoding == "form" and body_args:
            # Flatten to (key, value) pairs; collapse to dict for httpx (post-flattening keys are unique paths).
            pairs = _flatten_form(body_args)
            request_kwargs["data"] = dict(pairs)
        elif encoding == "multipart" and body_args:
            files, data = _split_multipart(body_args)
            if files:
                request_kwargs["files"] = files
            if data:
                request_kwargs["data"] = data
        elif encoding == "query_only":
            request_kwargs["params"] = {**merged_query, **body_args} or None
        # path_only: nothing extra

        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = client.request(method, url, **request_kwargs)
        except httpx.HTTPError as exc:
            return ExecutorResult(False, "network_error", None, error=str(exc))
        finally:
            if owns_client:
                client.close()

        body: Any
        try:
            body = response.json()
        except (ValueError, httpx.DecodingError):
            body = response.text

        ok = 200 <= response.status_code < 300
        return ExecutorResult(
            ok=ok,
            status=response.status_code,
            body=body,
            error=None if ok else _extract_error(body),
            extras={"headers": dict(response.headers)},
        )


def _partition_args(
    params: list[dict[str, Any]],
    args: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]]:
    path_args: dict[str, Any] = {}
    query_args: dict[str, Any] = {}
    header_args: dict[str, str] = {}
    body_args: dict[str, Any] = {}
    by_name = {p.get("name"): p for p in params}
    for name, value in args.items():
        if name.startswith("_docmancer"):
            continue
        meta = by_name.get(name)
        location = (meta.get("in") if meta else "body") or "body"
        if location == "path":
            path_args[name] = value
        elif location == "query":
            query_args[name] = value
        elif location == "header":
            header_args[name] = str(value)
        else:
            body_args[name] = value
    return path_args, query_args, header_args, body_args


def _render_path(template: str, path_args: dict[str, Any]) -> str:
    """Substitute `{name}` placeholders, percent-encoding each value as a single
    path segment so values containing `/`, `?`, `#`, or other reserved characters
    do not alter the URL structure (e.g. branch names like `feat/x`, S3 keys with
    slashes, IDs with `?`).
    """
    out = template
    for k, v in path_args.items():
        out = out.replace("{" + k + "}", quote(str(v), safe=""))
    return out


def _flatten_form(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Bracket flattening for form-encoded request bodies (e.g. `metadata[key]=value`)."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}[{k}]" if prefix else str(k)
            out.extend(_flatten_form(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            out.extend(_flatten_form(v, key))
    elif obj is None:
        pass
    elif isinstance(obj, bool):
        out.append((prefix, "true" if obj else "false"))
    else:
        out.append((prefix, str(obj)))
    return out


def _split_multipart(body_args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    files: dict[str, Any] = {}
    data: dict[str, Any] = {}
    for k, v in body_args.items():
        if isinstance(v, (bytes, bytearray)) or (isinstance(v, dict) and "content" in v):
            files[k] = v
        else:
            data[k] = v
    return files, data


def _extract_error(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message") or err.get("code") or str(err)
        if isinstance(err, str):
            return err
        if "message" in body:
            return str(body["message"])
    return "non_2xx"
