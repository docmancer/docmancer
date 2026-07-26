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

    async def context_artifact(self) -> dict:
        return {
            "available": True,
            "current": {
                "revision_id": "revision-current",
                "topics": [{"cluster_id": "ctx_one", "topic_label": "Deployment"}],
                "excluded": [],
            },
            "revisions": [{"revision_id": "revision-current"}],
            "delivery": await self.context_delivery(),
        }

    async def memory_recent(self, _since) -> list[dict]:
        return [{"atom_id": f"atom-{index}", "text": f"Memory {index}"} for index in range(45)]

    async def common_memory(self) -> list[dict]:
        return [{
            "cluster_id": "common:one",
            "text": "Deploy on Railway.",
            "harnesses": ["claude-code", "codex"],
            "harness_count": 2,
            "source_count": 2,
        }]

    async def context_delivery(self) -> list[dict]:
        return [{
            "agent": "codex",
            "integration_mode": "hook",
            "hook_status": "installed",
            "bundle_hash": "abc123",
            "status": "delivered",
        }]

    async def decision_journal(self, *, file_id=None, operation=None, limit=200) -> list[dict]:
        return [{
            "event_id": "evt_1",
            "file_id": file_id or "memory-1",
            "operation": operation or "edit",
            "revision_id": "rev-2",
            "diff": "-old\n+new\n",
        }][:limit]

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

    async def cloud_conflicts(self) -> list[dict]:
        return []

    async def team_file(
        self, *, domain: str = "standards", apply: bool = False,
        approved: bool = False, approver_id: str | None = None,
    ) -> dict:
        return {
            "domain": domain,
            "selected_count": 2,
            "excluded": [{"title": "Personal note", "reason": "non-project scope"}],
            "privacy_checks": {"secrets": "passed"},
            "approval": {"granularity": "complete-file", "approved": approved},
            "diff": "+# Team Standards",
            "applied": apply,
            "published": False,
            "approver_id": approver_id,
        }

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

    async def import_markdown(self, source: str, *, apply: bool = True) -> dict:
        return {"imported": apply, "count": 1, "results": [{"source": source, "status": "inbox" if apply else "preview"}]}

    async def available_editors(self, path: str) -> list[dict]:
        return [{"id": "vscode", "label": "VS Code"}, {"id": "default", "label": "Default app"}]

    async def open_markdown_file(self, path: str, *, editor_id: str, line=None, column=None) -> dict:
        return {"opened": True, "path": path, "editor": editor_id, "line": line, "column": column}

    async def curate_inbox(self, inbox_id: str, relative_path: str, *, apply: bool = False) -> dict:
        return {"applied": apply, "source": inbox_id, "destination": relative_path, "diff": "+# Checkpoint"}

    async def ask_tree(self, task: str, *, token_budget: int = 2000, agent: str = "web") -> dict:
        evidence = {"title": "Railway release", "source_path": "/memory/release.md", "authority": "advisory"}
        curated = {"title": "Release", "address": "docmancer://memory/one", "authority": "project"}
        return {
            "answer": None,
            "no_answer": False,
            "items": [curated, evidence],
            "mandatory_policies": [],
            "curated_memory": [curated],
            "relevant_evidence": [evidence],
            "token_estimate": 20,
            "task": task,
            "agent": agent,
        }

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
            "/memory/": "/ask/",
            "/sources/": "/inbox/",
            "/intelligence/": "/maintenance/",
        }
        for source, destination in expected.items():
            response = client.get(source, follow_redirects=False)
            assert response.status_code == 308
            assert response.headers["location"] == destination
        context = client.get("/context/", follow_redirects=False)
        assert context.status_code == 200
        assert "location" not in context.headers


def test_harvest_and_curation_are_interactive_local_operations(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        preview = client.post("/api/v1/harvest", json={"source": "notes", "apply": False}, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["results"] == [{"source": "notes", "status": "preview"}]
        imported = client.post("/api/v1/import", json={"source": "notes"}, headers=headers)
        assert imported.status_code == 200
        assert imported.json()["imported"] is True
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
        context = client.get("/api/v1/context").json()
        assert context["available"] is True
        assert context["current"]["revision_id"] == "revision-current"
        assert len(context["revisions"]) == 1

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
        assert team.json()["local_preview_available"] is True
        assert team.json()["team_file"]["approval"]["granularity"] == "complete-file"


def test_team_file_preview_and_whole_file_approval(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        preview = client.post(
            "/api/v1/cloud/team/file",
            headers=headers,
            json={"domain": "engineering", "apply": False},
        )
        assert preview.status_code == 200
        assert preview.json()["domain"] == "engineering"
        assert preview.json()["applied"] is False

        rejected = client.post(
            "/api/v1/cloud/team/file",
            headers=headers,
            json={"domain": "engineering", "apply": True, "approved": False},
        )
        assert rejected.status_code == 400

        approved = client.post(
            "/api/v1/cloud/team/file",
            headers=headers,
            json={"domain": "engineering", "apply": True, "approved": True},
        )
        assert approved.status_code == 200
        assert approved.json()["applied"] is True
        assert approved.json()["approval"]["granularity"] == "complete-file"


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
        assert ask.json()["curated_memory"][0]["address"] == "docmancer://memory/one"
        assert ask.json()["relevant_evidence"][0]["title"] == "Railway release"


def test_editor_routes_list_and_open_allowlisted_markdown_apps(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}
        path = "/tmp/project/README.md"

        editors = client.get("/api/v1/editors", params={"path": path})
        assert editors.status_code == 200
        assert editors.json()["items"][0] == {"id": "vscode", "label": "VS Code"}

        opened = client.post(
            "/api/v1/editor/open",
            json={"path": path, "editor": "vscode"},
            headers=headers,
        )
        assert opened.status_code == 200
        assert opened.json()["opened"] is True
        assert opened.json()["editor"] == "vscode"


def test_core_outcome_routes_expose_common_delivery_and_timeline(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)

        common = client.get("/api/v1/common")
        delivery = client.get("/api/v1/delivery")
        timeline = client.get("/api/v1/timeline?file_id=memory-1&operation=edit")

        assert common.status_code == delivery.status_code == timeline.status_code == 200
        assert common.json()["items"][0]["harness_count"] == 2
        assert delivery.json()["items"][0]["bundle_hash"] == "abc123"
        assert timeline.json()["items"][0]["file_id"] == "memory-1"
        assert timeline.json()["items"][0]["operation"] == "edit"
