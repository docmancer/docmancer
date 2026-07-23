from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from docmancer.web.app import create_app
from docmancer.web.security import MAX_REQUEST_BYTES


class FakeRuntime:
    project_path = Path("/tmp/project")

    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.capture = {"codex": True, "claude-code": False}

    async def initialize(self) -> dict:
        return {"ready": True}

    async def status(self) -> dict:
        return {"engine": "local"}

    async def counts(self) -> dict:
        return {"atoms": 3}

    async def add(self, text: str, *, scope_kind: str = "global") -> dict:
        self.added.append((text, scope_kind))
        return {"text": text, "scope_kind": scope_kind}

    async def find_atom(self, identifier: str) -> dict | None:
        return {"record_id": identifier, "text": "Remember the local boundary"} if identifier == "record-1" else None

    async def context(self) -> list[dict]:
        return [{"record_id": f"record-{index}", "text": f"Context {index}"} for index in range(45)]

    async def memory_recent(self, _since) -> list[dict]:
        return [{"atom_id": f"atom-{index}", "text": f"Memory {index}"} for index in range(45)]

    async def audit(self) -> dict:
        return {
            "finding_count": 1,
            "unique_secret_count": 1,
            "findings": [{"type": "API key", "severity": "high", "occurrences": [], "occurrence_count": 1}],
        }

    async def hook_status(self) -> list[dict]:
        return [{"agent": "codex", "scope": "user", "path": "/tmp/hooks.json"}]

    async def get_docs_source(self, source: str) -> dict | None:
        return {"source": source, "documents": [{"title": "Start"}]} if source == "https://docs.example" else None

    async def capture_settings(self) -> dict[str, bool]:
        return dict(self.capture)

    async def save_capture_settings(self, enabled: dict[str, bool]) -> Path:
        self.capture = dict(enabled)
        return Path("/tmp/docmancer.yaml")

    async def cloud_status(self) -> dict:
        return {"configured": False}

    async def tree_root(self) -> dict:
        return {"scope": "project", "project_id": "project-1", "display_label": "project", "health": "ready"}

    async def tree_list(self) -> list[dict]:
        return [{"address": "docmancer://memory/one", "title": "Release", "content_hash": "hash-1"}]

    async def tree_read(self, address: str) -> dict:
        if address != "docmancer://memory/one":
            from docmancer.memory.tree.errors import AddressNotFoundError

            raise AddressNotFoundError(address)
        return {"address": address, "title": "Release", "markdown": "# Release\n", "content_hash": "hash-1"}

    async def tree_create(self, body: dict) -> dict:
        return {"address": "docmancer://memory/two", "path": body["path"], "markdown": body["markdown"], "content_hash": "hash-2"}

    async def tree_mutate(self, action: str, body: dict) -> dict:
        return {"action": action, "address": body.get("address"), "restore_token": body.get("restore_token")}

    async def inbox_files(self) -> list[dict]:
        return [{"id": "capture-1", "title": "Checkpoint", "redaction_status": "applied"}]

    async def harvest_tree(self, source: str, *, apply: bool = False) -> dict:
        return {"applied": apply, "count": 1, "results": [{"source": source, "status": "inbox" if apply else "preview"}]}

    async def curate_inbox(self, inbox_id: str, relative_path: str, *, apply: bool = False) -> dict:
        return {"applied": apply, "source": inbox_id, "destination": relative_path, "diff": "+# Checkpoint"}

    async def ask_tree(self, task: str, *, token_budget: int = 2000, agent: str = "web") -> dict:
        return {"answer": None, "no_answer": False, "items": [{"title": "Release", "address": "docmancer://memory/one"}], "token_estimate": 20, "task": task, "agent": agent}

    async def resolve_memory_conflict(self, identifier: str, resolution: str, *, winner: str | None = None) -> dict:
        return {"relation_id": identifier, "resolution": resolution, "winner": winner}


def app_client(tmp_path: Path) -> tuple[TestClient, object, FakeRuntime]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>local</html>", encoding="utf-8")
    runtime = FakeRuntime()
    app = create_app(port=48123, static_dir=static, runtime=runtime)  # type: ignore[arg-type]
    return TestClient(app, base_url="http://127.0.0.1:48123"), app, runtime


def authenticate(client: TestClient, app: object) -> str:
    token = app.state.security.bootstrap_token  # type: ignore[attr-defined]
    response = client.get(f"/?bootstrap={token}", follow_redirects=False)
    assert response.status_code == 303
    session = client.get("/api/v1/session")
    assert session.status_code == 200
    return session.json()["csrf_token"]


def test_bootstrap_is_one_time_and_api_requires_session(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        assert client.get("/api/v1/status").status_code == 401
        token = app.state.security.bootstrap_token
        assert client.get(f"/?bootstrap={token}", follow_redirects=False).status_code == 303
        assert client.get(f"/?bootstrap={token}", follow_redirects=False).status_code == 401
        assert client.get("/api/v1/status").json() == {
            "status": {"engine": "local"},
            "counts": {"atoms": 3},
        }


def test_mutations_require_exact_origin_and_csrf(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        assert client.post("/api/v1/memory", json={"text": "safe"}).status_code == 403
        assert client.post(
            "/api/v1/memory",
            json={"text": "safe"},
            headers={"origin": "https://attacker.example", "x-docmancer-csrf": csrf},
        ).status_code == 403
        response = client.post(
            "/api/v1/memory",
            json={"text": "safe", "scope_kind": "project"},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert response.status_code == 201
        assert runtime.added == [("safe", "project")]


def test_rejects_untrusted_host_and_oversized_request(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        assert client.get("/", headers={"host": "attacker.example"}).status_code == 400
        csrf = authenticate(client, app)
        response = client.post(
            "/api/v1/memory",
            content=b"{}",
            headers={
                "origin": "http://127.0.0.1:48123",
                "x-docmancer-csrf": csrf,
                "content-type": "application/json",
                "content-length": str(MAX_REQUEST_BYTES + 1),
            },
        )
        assert response.status_code == 413


def test_security_headers_cover_static_content(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
        assert "connect-src 'self'" in response.headers["content-security-policy"]


def test_retired_workbench_routes_are_real_http_redirects(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        expected = {
            "/context/": "/agent-context/",
            "/memory/": "/ask/",
            "/sources/": "/inbox/",
            "/intelligence/": "/maintenance/",
        }
        for source, destination in expected.items():
            response = client.get(source, follow_redirects=False)
            assert response.status_code == 308
            assert response.headers["location"] == destination


def test_harvest_and_curation_are_interactive_local_operations(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        preview = client.post("/api/v1/harvest", json={"source": "notes", "apply": False}, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["results"] == [{"source": "notes", "status": "preview"}]
        curate = client.post(
            "/api/v1/curate",
            json={"inbox_id": "capture-1", "path": "decisions/checkpoint.md", "apply": False},
            headers=headers,
        )
        assert curate.status_code == 200
        assert curate.json()["diff"] == "+# Checkpoint"


def test_detail_and_capture_routes_are_real_operations(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        assert client.get("/api/v1/memory/record-1").json()["text"] == "Remember the local boundary"
        assert client.get("/api/v1/memory/missing").status_code == 404
        assert client.get("/api/v1/docs/source?source=https%3A%2F%2Fdocs.example").json()["source"] == "https://docs.example"
        assert client.get("/api/v1/settings/capture").json() == {"enabled": {"codex": True, "claude-code": False}}
        response = client.put(
            "/api/v1/settings/capture",
            json={"enabled": {"codex": False}},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert response.status_code == 200
        assert runtime.capture == {"codex": False}


def test_intelligence_resolution_is_allowlisted(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        response = client.post(
            "/api/v1/intelligence/relation-1",
            json={"action": "resolve", "resolution": "keep-both"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["resolution"] == "keep-both"
        rejected = client.post(
            "/api/v1/intelligence/relation-1",
            json={"action": "shell", "command": "anything"},
            headers=headers,
        )
        assert rejected.status_code == 400


def test_collection_routes_return_consistent_page_metadata(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        context = client.get("/api/v1/context?page=2&page_size=20").json()
        assert context["page"] == 2
        assert context["total"] == 45
        assert context["total_pages"] == 3
        assert len(context["items"]) == 20

        memory = client.get("/api/v1/memory?page=3&page_size=20").json()
        assert memory["page"] == 3
        assert memory["total"] == 45
        assert len(memory["items"]) == 5

        audit = client.get("/api/v1/audit").json()
        assert audit["total"] == 2
        assert audit["items"][0]["view_kind"] == "secret-finding"
        assert audit["items"][1]["view_kind"] == "hook-status"


def test_optional_cloud_pages_return_a_graceful_disconnected_state(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        devices = client.get("/api/v1/cloud/devices")
        assert devices.status_code == 200
        assert devices.json()["state"] == "not_connected"
        assert devices.json()["available"] is False

        team = client.get("/api/v1/cloud/team")
        assert team.status_code == 200
        assert team.json()["state"] == "not_connected"
        assert "not connected" in team.json()["message"].lower()


def test_tree_inbox_and_ask_routes_use_typed_resources(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        assert client.get("/api/v1/tree/root").json()["project_id"] == "project-1"
        assert client.get("/api/v1/tree").json()["items"][0]["address"] == "docmancer://memory/one"
        encoded = "docmancer%3A%2F%2Fmemory%2Fone"
        assert client.get(f"/api/v1/tree/file?address={encoded}").json()["title"] == "Release"
        missing = client.get("/api/v1/tree/file?address=missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["retry_safe"] is True
        created = client.post(
            "/api/v1/tree/file",
            json={"path": "deployment/release.md", "markdown": "# Release\n"},
            headers=headers,
        )
        assert created.status_code == 201
        assert created.json()["path"] == "deployment/release.md"
        trashed = client.post(
            "/api/v1/tree/action",
            json={"action": "trash", "address": "docmancer://memory/one", "expected_hash": "hash-1"},
            headers=headers,
        )
        assert trashed.status_code == 200
        assert trashed.json()["action"] == "trash"
        assert client.get("/api/v1/inbox").json()["items"][0]["redaction_status"] == "applied"
        ask = client.post("/api/v1/ask", json={"task": "How do we release?", "token_budget": 1000}, headers=headers)
        assert ask.status_code == 200
        assert ask.json()["items"][0]["address"] == "docmancer://memory/one"
