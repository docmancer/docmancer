"""Section 22 (multipart) and Section 23 (pagination round-trip)."""
from __future__ import annotations

import httpx

from docmancer.mcp.executors.http import HttpExecutor


def test_multipart_executor():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(200, json={"uploaded": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    exec_ = HttpExecutor(client=client)

    op = {
        "executor": "http",
        "http": {
            "method": "POST",
            "path": "/v1/files",
            "base_url": "https://api.example.com",
            "encoding": "multipart",
        },
        "params": [
            {"name": "purpose", "in": "body", "type": "string"},
            {"name": "file", "in": "body", "type": "string"},
        ],
        "safety": {"destructive": False, "idempotent": False, "requires_auth": False},
    }
    result = exec_.call(
        operation=op,
        args={"purpose": "demo", "file": b"binary-bytes-here"},
        auth_headers={},
        required_headers={},
        idempotency_key=None,
        idempotency_header=None,
    )
    assert result.ok is True
    assert "multipart" in captured["content_type"]
    assert b"binary-bytes-here" in captured["body"]
    assert b"purpose" in captured["body"]


def test_pagination_response_returned_untouched():
    """Section 23: dispatcher must not page; provider cursor fields pass through."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "object": "list",
            "data": [{"id": "wgt_1"}, {"id": "wgt_2"}],
            "has_more": True,
            "url": "/v1/widgets",
        })

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    exec_ = HttpExecutor(client=client)

    op = {
        "http": {
            "method": "GET",
            "path": "/v1/widgets",
            "base_url": "https://api.acme.test",
            "encoding": "query_only",
        },
        "params": [{"name": "limit", "in": "query", "type": "integer"}],
        "safety": {"destructive": False, "idempotent": True, "requires_auth": False},
    }
    result = exec_.call(
        operation=op, args={"limit": 2},
        auth_headers={}, required_headers={},
        idempotency_key=None, idempotency_header=None,
    )
    assert result.body["has_more"] is True
    assert len(result.body["data"]) == 2


def test_idempotency_header_skipped_when_source_lacks_one():
    """Section 21: sources with idempotency_header: null get no header even on POST."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    exec_ = HttpExecutor(client=client)

    op = {
        "http": {
            "method": "POST",
            "path": "/v1/things",
            "base_url": "https://api.example.com",
            "encoding": "json",
        },
        "params": [{"name": "name", "in": "body", "type": "string"}],
        "safety": {"destructive": True, "idempotent": False, "requires_auth": False},
    }
    # idempotency_header=None because the source did not declare one
    result = exec_.call(
        operation=op, args={"name": "x"},
        auth_headers={}, required_headers={},
        idempotency_key="some-key", idempotency_header=None,
    )
    assert result.ok is True
    assert "idempotency-key" not in (k.lower() for k in captured["headers"])


def test_path_parameters_are_percent_encoded():
    """Path values containing reserved characters must be encoded as one segment,
    not interpreted as additional URL structure (e.g. branch names with `/`).
    """
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["raw_path"] = request.url.raw_path.decode()
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exec_ = HttpExecutor(client=client)
    op = {
        "http": {
            "method": "GET",
            "path": "/repos/{owner}/{repo}/contents/{path}",
            "base_url": "https://api.example.com",
            "encoding": "path_only",
        },
        "params": [
            {"name": "owner", "in": "path", "type": "string"},
            {"name": "repo", "in": "path", "type": "string"},
            {"name": "path", "in": "path", "type": "string"},
        ],
        "safety": {"destructive": False, "idempotent": True, "requires_auth": False},
    }
    # `path` contains `/` and `?`; both must be encoded so the URL still resolves
    # to /contents/<one segment>, not /contents/feat/x?ref=main/.
    result = exec_.call(
        operation=op,
        args={"owner": "acme", "repo": "core", "path": "feat/x?ref=main"},
        auth_headers={}, required_headers={},
        idempotency_key=None, idempotency_header=None,
    )
    assert result.ok is True
    assert captured["raw_path"] == "/repos/acme/core/contents/feat%2Fx%3Fref%3Dmain"


def test_apikey_in_query_is_sent_as_query_param():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exec_ = HttpExecutor(client=client)
    op = {
        "http": {
            "method": "GET",
            "path": "/v1/items",
            "base_url": "https://api.example.com",
            "encoding": "query_only",
        },
        "params": [],
        "safety": {"destructive": False, "idempotent": True, "requires_auth": True},
    }
    result = exec_.call(
        operation=op, args={},
        auth_headers={}, required_headers={},
        idempotency_key=None, idempotency_header=None,
        auth_params={"api_key": "k_query_only"},
    )
    assert result.ok is True
    assert "api_key=k_query_only" in captured["url"]
    # Must not leak into headers.
    assert not any(k.lower() == "api_key" for k in captured["headers"])


def test_apikey_in_cookie_is_sent_as_cookie():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exec_ = HttpExecutor(client=client)
    op = {
        "http": {
            "method": "GET",
            "path": "/v1/items",
            "base_url": "https://api.example.com",
            "encoding": "query_only",
        },
        "params": [],
        "safety": {"destructive": False, "idempotent": True, "requires_auth": True},
    }
    result = exec_.call(
        operation=op, args={},
        auth_headers={}, required_headers={},
        idempotency_key=None, idempotency_header=None,
        auth_cookies={"session": "abc123"},
    )
    assert result.ok is True
    assert "session=abc123" in captured["headers"].get("cookie", "")
