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

    async def get_docs_source(self, source: str) -> dict | None:
        return {"source": source, "documents": [{"title": "Start"}]} if source == "https://docs.example" else None

    async def capture_settings(self) -> dict[str, bool]:
        return dict(self.capture)

    async def save_capture_settings(self, enabled: dict[str, bool]) -> Path:
        self.capture = dict(enabled)
        return Path("/tmp/docmancer.yaml")

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
