from __future__ import annotations

import hashlib
import time
from pathlib import Path

from starlette.testclient import TestClient

from docmancer.web.app import create_app
from docmancer.web.ask_history import AskHistoryStore
from docmancer.web.security import MAX_REQUEST_BYTES


class FakeRuntime:
    project_path = Path("/tmp/project")

    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.ask_calls: list[dict] = []
        self.capture = {"codex": True, "claude-code": False}
        self.agent = {
            "name": "Docmancer",
            "instructions": "Be direct.",
            "output_mode": "normal",
            "reasoning_effort": "medium",
            "max_output_tokens": 4096,
            "context_budget": 12000,
            "top_p": 0.95,
            "safeguards": ["Keep sources visible."],
        }

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

    async def agent_settings(self) -> dict:
        return dict(self.agent)

    async def save_agent_settings(self, value: dict) -> Path:
        self.agent.update(value)
        return Path("/tmp/docmancer.yaml")

    async def agent_setup_plan(self) -> dict:
        return {
            "items": [{
                "id": "codex",
                "family": "codex",
                "label": "Codex",
                "detected": True,
                "detected_surfaces": ["codex"],
                "integration_state": "ready-to-connect",
                "connected": False,
                "skill_installed": False,
                "instructions_installed": False,
                "instructions_stale": False,
                "recall_hook": False,
                "capture_hook": False,
                "last_successful_recall": None,
                "manual_step": None,
                "action_kind": "automatic",
                "manual_actions": [],
                "artifact_ready": False,
                "can_install_from_web": True,
            }],
            "recommended": ["codex"],
            "commands": {"setup": "docmancer setup"},
        }

    async def distillation_preview(self) -> dict:
        return {
            "available": True,
            "status": "ready",
            "atoms": 3,
            "sources": 2,
            "provider": "openai",
            "provider_label": "OpenAI",
            "model": "gpt-5-mini",
            "provider_ready": True,
            "outputs": ["Personal defaults", "Project decisions"],
            "clusters": 2,
            "estimated_provider_calls": 2,
            "estimated_input_tokens": 800,
            "estimated_output_tokens": 800,
            "estimated_cost_usd": 0.001,
            "message": "Ready to build readable Context.",
        }

    async def library(self, *, corpus: str, query: str = "", cursor=None, limit: int = 30) -> dict:
        return {
            "items": [{
                "corpus": corpus,
                "record_id": "record-1",
                "title": "Release",
                "summary": "Use Railway.",
                "kind": "decision",
            }],
            "next_cursor": None,
            "index_state": "ready",
            "last_indexed_at": "2026-07-26T18:00:00+00:00",
        }

    async def library_detail(self, corpus: str, record_id: str) -> dict | None:
        if record_id != "record-1":
            return None
        return {
            "record_id": record_id,
            "title": "Release",
            "summary": "Use Railway.",
            "kind": "decision",
            "source_count": 2,
            "diagnostics": {"corpus": corpus},
        }

    async def provider_models(self, provider_id: str) -> list[str]:
        return ["gpt-5-mini"] if provider_id == "openai" else []

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

    async def shared_memory(self) -> dict:
        return {
            "scaffold_version": 1,
            "roots": [{
                "key": "machine",
                "label": "This machine",
                "count": 1,
                "folders": [{"path": "profile", "name": "profile", "parent": ""}],
                "files": [{"address": "docmancer://memory/one", "path": "profile/about.md", "title": "About"}],
            }],
            "legacy_generated_files": 2,
        }

    async def shared_memory_read(self, address: str) -> dict:
        if address != "docmancer://memory/one":
            from docmancer.memory.tree.errors import AddressNotFoundError

            raise AddressNotFoundError(address)
        return {
            "address": address,
            "root": "machine",
            "path": "profile/about.md",
            "title": "About",
            "markdown": "# About\n",
        }

    async def agent_projection(self, agent: str, *, token_budget: int = 2_000) -> dict:
        return {
            "available": True,
            "projection": {"target_agent": agent, "token_budget": token_budget},
            "rendered": "# Shared memory\n",
        }

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

    async def ask_tree(
        self,
        task: str,
        *,
        token_budget: int = 2000,
        agent: str = "web",
        mode: str = "normal",
        on_delta=None,
        **_kwargs,
    ) -> dict:
        self.ask_calls.append({"task": task, **_kwargs})
        evidence = {"title": "Railway release", "source_path": "/memory/release.md", "authority": "advisory"}
        curated = {"title": "Release", "address": "docmancer://memory/one", "authority": "project"}
        result = {
            "answer": "Use Railway. [1]",
            "no_answer": False,
            "items": [curated, evidence],
            "mandatory_policies": [],
            "curated_memory": [curated],
            "relevant_evidence": [evidence],
            "token_estimate": 20,
            "task": task,
            "agent": agent,
        }
        if _kwargs.get("action_enabled") and task.startswith("Update "):
            result["answer"] = {"text": "I prepared one edit proposal.", "provider": "test", "model": "test"}
            result["action"] = {
                "operation": "edit",
                "scope": "project",
                "target": "docmancer://memory/one",
                "address": "docmancer://memory/one",
                "path": "decisions/release.md",
                "expected_hash": "hash-1",
                "before_markdown": "# Release\n",
                "after_markdown": "# Release\n\nRun smoke tests.\n",
                "diff": "+Run smoke tests.\n",
                "rationale": "Add smoke tests.",
                "destructive": False,
                "status": "pending",
            }
        elif _kwargs.get("mutation_disabled_reason") and task.startswith("Remember "):
            result["answer"] = {
                "text": _kwargs["mutation_disabled_reason"],
                "provider": None,
                "model": None,
            }
        elif _kwargs.get("action_enabled") and (
            task.startswith("Remove ") or _kwargs.get("pending_action_request")
        ):
            if not _kwargs.get("pending_action_request"):
                result["answer"] = {
                    "text": "Should this affect machine-wide or project memory?",
                    "provider": "test",
                    "model": "test",
                }
                result["action_kind"] = "clarification"
                result["action_request"] = task
                result["action_clarification_count"] = 1
            else:
                result["answer"] = {
                    "text": "I prepared one exclusion proposal.",
                    "provider": "test",
                    "model": "test",
                }
                result["action_kind"] = "proposal"
                result["action"] = {
                    "operation": "create",
                    "scope": "machine",
                    "target": "shared/canonical-exclusions.md",
                    "path": "shared/canonical-exclusions.md",
                    "before_markdown": "",
                    "after_markdown": (
                        "# Canonical memory exclusions\n\n"
                        "## Evidence path contains\n\n- token_tape\n"
                    ),
                    "diff": "+- token_tape\n",
                    "rationale": "Withhold TokenTape from generated Shared Memory.",
                    "destructive": False,
                    "status": "pending",
                }
        return result

    async def execute_memory_action(self, proposal: dict, *, actor_surface: str) -> dict:
        self.executed_action = {"proposal": proposal, "actor_surface": actor_surface}
        return {"address": proposal["address"], "content_hash": "hash-2"}

    async def resolve_memory_conflict(self, identifier: str, resolution: str, *, winner: str | None = None) -> dict:
        return {"relation_id": identifier, "resolution": resolution, "winner": winner}

    async def canonical_status(self) -> dict:
        return {
            "available": True,
            "root": "/home/.docmancer/tree",
            "revision_id": "laptop_abc",
            "provider": "deterministic",
            "selected": 12,
            "withheld": 3,
            "pinned_total": 1,
            "sections": [
                {"section": "about", "present": True, "pinned_lines": 1, "generated_chars": 40},
                {"section": "preferences", "present": True, "pinned_lines": 0, "generated_chars": 90},
            ],
        }

    async def canonical_section(self, section: str) -> dict:
        if section == "missing":
            raise ValueError("unknown canonical section 'missing'")
        return {
            "section": section,
            "content_hash": "hash-1",
            "pinned": "- a pinned note",
            "generated": "## Constraint\n- a generated line",
        }

    async def canonical_set_pinned(self, section: str, pinned: str, expect: str | None) -> dict:
        if expect == "stale":
            raise ValueError("canonical section 'about' changed since it was read")
        self.pinned_writes = getattr(self, "pinned_writes", [])
        self.pinned_writes.append((section, pinned, expect))
        return {"section": section, "pinned": pinned, "pinned_lines": 1, "content_hash": "hash-2"}

    async def canonical_refresh(self, *, deterministic: bool = False) -> dict:
        self.refreshes = getattr(self, "refreshes", [])
        self.refreshes.append(deterministic)
        return {"changed": True, "provider": "deterministic" if deterministic else "openrouter"}


def app_client(tmp_path: Path) -> tuple[TestClient, object, FakeRuntime]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>local</html>", encoding="utf-8")
    runtime = FakeRuntime()
    app = create_app(
        port=48123,
        static_dir=static,
        runtime=runtime,  # type: ignore[arg-type]
        ask_history_path=tmp_path / "ask.sqlite3",
    )
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
            "/sources/": "/library/?tab=evidence",
            "/intelligence/": "/memory/",
            "/context/": "/memory/",
        }
        for source, destination in expected.items():
            response = client.get(source, follow_redirects=False)
            assert response.status_code == 308
            assert response.headers["location"] == destination
        memory = client.get("/memory/", follow_redirects=False)
        assert memory.status_code == 200
        assert "location" not in memory.headers


def test_static_shell_and_session_do_not_wait_for_runtime_initialization(tmp_path: Path) -> None:
    import asyncio

    class SlowRuntime:
        project_path = Path("/tmp/project")
        ready = False
        initializing = True

        async def initialize(self):
            await asyncio.sleep(2)
            self.ready = True
            self.initializing = False
            return {"ready": True}

        def readiness(self):
            return {
                "ready": self.ready,
                "initializing": self.initializing,
                "error": None,
            }

    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>loading shell</html>", encoding="utf-8")
    runtime = SlowRuntime()
    app = create_app(port=48123, static_dir=static, runtime=runtime)
    started = time.monotonic()
    with TestClient(app, base_url="http://127.0.0.1:48123") as client:
        assert time.monotonic() - started < 0.5
        token = app.state.security.bootstrap_token
        assert client.get(f"/?bootstrap={token}", follow_redirects=False).status_code == 303
        assert client.get("/api/v1/session").status_code == 200
        state = client.get("/api/v1/readiness").json()
        assert state["ready"] is False
        assert state["initializing"] is True


def test_shared_memory_and_projection_routes(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        memory = client.get("/api/v1/shared-memory")
        assert memory.status_code == 200
        assert memory.json()["roots"][0]["files"][0]["path"] == "profile/about.md"
        file = client.get(
            "/api/v1/shared-memory/file",
            params={"address": "docmancer://memory/one"},
        )
        assert file.json()["markdown"] == "# About\n"
        projection = client.get("/api/v1/agents/codex/projection")
        assert projection.json()["projection"]["target_agent"] == "codex"


def test_human_agent_settings_and_setup_plan_are_exposed(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        agent = client.get("/api/v1/agent")
        assert agent.status_code == 200
        assert agent.json()["name"] == "Docmancer"

        saved = client.put(
            "/api/v1/agent",
            json={**runtime.agent, "instructions": "Prefer short, sourced answers."},
            headers={
                "origin": "http://127.0.0.1:48123",
                "x-docmancer-csrf": csrf,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["instructions"] == "Prefer short, sourced answers."

        setup = client.get("/api/v1/agent/setup")
        assert setup.status_code == 200
        assert setup.json()["recommended"] == ["codex"]
        rejected = client.post(
            "/api/v1/agent/setup",
            json={"targets": ["codex"]},
            headers={
                "origin": "http://127.0.0.1:48123",
                "x-docmancer-csrf": csrf,
            },
        )
        assert rejected.status_code == 400
        assert "confirmation is required" in rejected.json()["error"]["message"]

        models = client.get("/api/v1/providers/openai/models")
        assert models.status_code == 200
        assert models.json()["items"] == [{
            "id": "gpt-5-mini",
            "label": "gpt-5-mini",
            "source": "runtime",
        }]


def test_library_and_distillation_preview_are_exposed(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)
        library = client.get("/api/v1/library?corpus=memory&limit=30")
        assert library.status_code == 200
        assert library.json()["items"][0]["title"] == "Release"
        assert library.json()["index_state"] == "ready"

        detail = client.get("/api/v1/library/memory/record-1")
        assert detail.status_code == 200
        assert detail.json()["summary"] == "Use Railway."
        assert client.get("/api/v1/library/memory/missing").status_code == 404

        preview = client.get("/api/v1/context/distillation-preview")
        assert preview.status_code == 200
        assert preview.json()["available"] is True
        assert preview.json()["status"] == "ready"
        assert preview.json()["estimated_provider_calls"] == 2


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


def test_ask_conversations_are_saved_locally_and_can_be_deleted(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        created = client.post("/api/v1/ask/conversations", json={}, headers=headers)
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        answer = client.post(
            "/api/v1/ask",
            json={
                "task": "How do we release this project?",
                "conversation_id": conversation_id,
            },
            headers=headers,
        )
        assert answer.status_code == 200
        assert answer.json()["conversation_id"] == conversation_id

        conversations = client.get("/api/v1/ask/conversations")
        assert conversations.status_code == 200
        assert conversations.json()["items"][0]["title"] == "How do we release this project?"
        assert conversations.json()["items"][0]["message_count"] == 2

        detail = client.get(f"/api/v1/ask/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert [message["role"] for message in detail.json()["messages"]] == [
            "user",
            "assistant",
        ]
        assert detail.json()["messages"][1]["content"] == "Use Railway. [1]"
        assert detail.json()["messages"][1]["evidence"][0]["title"] == "Release"

        deleted = client.delete(
            f"/api/v1/ask/conversations/{conversation_id}",
            headers=headers,
        )
        assert deleted.status_code == 200
        assert client.get(f"/api/v1/ask/conversations/{conversation_id}").status_code == 404


def test_temporary_ask_does_not_create_conversation_history(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        answer = client.post(
            "/api/v1/ask",
            json={"task": "What is temporary?", "temporary": True},
            headers=headers,
        )
        assert answer.status_code == 200
        assert answer.json()["temporary"] is True
        mutation = client.post(
            "/api/v1/ask",
            json={"task": "Remember this release decision", "temporary": True},
            headers=headers,
        )
        assert mutation.status_code == 200
        assert mutation.json().get("action") is None
        assert "Start a saved conversation" in mutation.json()["answer"]["text"]
        assert client.get("/api/v1/ask/conversations").json()["items"] == []


def test_action_clarification_continues_into_one_proposal_without_q_and_a_loop(
    tmp_path: Path,
) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        first = client.post(
            "/api/v1/ask",
            json={
                "task": "Remove TokenTape from Shared Memory",
                "conversation_id": conversation_id,
            },
            headers=headers,
        )
        second = client.post(
            "/api/v1/ask",
            json={
                "task": "Only machine-wide Shared Memory, never source files",
                "conversation_id": conversation_id,
            },
            headers=headers,
        )

        assert first.status_code == 200
        assert first.json()["action_kind"] == "clarification"
        assert second.status_code == 200
        assert second.json()["action"]["path"] == "shared/canonical-exclusions.md"
        assert runtime.ask_calls[-1]["pending_action_request"] == (
            "Remove TokenTape from Shared Memory"
        )


def test_referential_retry_recovers_original_request_after_legacy_refusal(
    tmp_path: Path,
) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        resolved_project = Path(runtime.project_path).expanduser().resolve()
        history = AskHistoryStore(
            tmp_path / "ask.sqlite3",
            project_id=hashlib.sha256(str(resolved_project).encode()).hexdigest()[:16],
            project_label=resolved_project.name,
        )
        _, answer_id = history.begin_exchange(
            conversation_id,
            "Remove TokenTape and pet projects from Shared Memory globally.",
        )
        history.complete_answer(
            conversation_id,
            answer_id,
            "The action target was refused.",
            metadata={"action_kind": "unavailable", "action_request": None},
        )

        response = client.post(
            "/api/v1/ask",
            json={"task": "remove them now", "conversation_id": conversation_id},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["action"]["path"] == "shared/canonical-exclusions.md"
        assert runtime.ask_calls[-1]["pending_action_request"] == (
            "Remove TokenTape and pet projects from Shared Memory globally."
        )


def test_chat_confirmation_never_applies_a_pending_action_or_calls_provider(
    tmp_path: Path,
) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        proposed = client.post(
            "/api/v1/ask",
            json={
                "task": "Update the release decision.",
                "conversation_id": conversation_id,
            },
            headers=headers,
        ).json()["action"]
        calls_before = len(runtime.ask_calls)
        confirmation = client.post(
            "/api/v1/ask",
            json={"task": "ok", "conversation_id": conversation_id},
            headers=headers,
        )

        assert confirmation.status_code == 200
        assert "Use Apply" in confirmation.json()["answer"]["text"]
        assert len(runtime.ask_calls) == calls_before
        assert not hasattr(runtime, "executed_action")
        assert client.get(
            f"/api/v1/ask/conversations/{conversation_id}",
        ).json()["messages"][-3]["action"]["id"] == proposed["id"]


def test_saved_ask_action_is_applied_from_server_side_proposal(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        answer = client.post(
            "/api/v1/ask",
            json={
                "task": "Update the release decision.",
                "conversation_id": conversation_id,
            },
            headers=headers,
        )
        assert answer.status_code == 200
        action = answer.json()["action"]
        assert action["status"] == "pending"

        applied = client.post(
            f"/api/v1/ask/actions/{action['id']}",
            json={"decision": "apply"},
            headers=headers,
        )
        assert applied.status_code == 200
        assert applied.json()["action"]["status"] == "applied"
        assert runtime.executed_action["proposal"]["after_markdown"] == "# Release\n\nRun smoke tests.\n"

        conversation = client.get(
            f"/api/v1/ask/conversations/{conversation_id}",
        ).json()
        assert conversation["messages"][-1]["action"]["status"] == "applied"


def test_ask_action_rejects_browser_supplied_executable_fields(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        action = client.post(
            "/api/v1/ask",
            json={"task": "Update the release decision.", "conversation_id": conversation_id},
            headers=headers,
        ).json()["action"]
        rejected = client.post(
            f"/api/v1/ask/actions/{action['id']}",
            json={
                "decision": "apply",
                "after_markdown": "# Browser content must be rejected\n",
            },
            headers=headers,
        )

        assert rejected.status_code == 400
        assert not hasattr(runtime, "executed_action")
        assert client.get(
            f"/api/v1/ask/conversations/{conversation_id}",
        ).json()["messages"][-1]["action"]["status"] == "pending"


def test_ask_action_requires_csrf_and_can_be_cancelled(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        action = client.post(
            "/api/v1/ask",
            json={"task": "Update the release decision.", "conversation_id": conversation_id},
            headers=headers,
        ).json()["action"]
        rejected = client.post(
            f"/api/v1/ask/actions/{action['id']}",
            json={"decision": "cancel"},
        )
        assert rejected.status_code == 403
        cancelled = client.post(
            f"/api/v1/ask/actions/{action['id']}",
            json={"decision": "cancel"},
            headers=headers,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["action"]["status"] == "cancelled"


def test_ask_action_stale_hash_returns_409_with_current_hash(tmp_path: Path) -> None:
    from docmancer.memory.tree.errors import StaleWriteError

    client, app, runtime = app_client(tmp_path)

    async def stale_action(_proposal, *, actor_surface):
        assert actor_surface == "web-ask"
        raise StaleWriteError(
            "docmancer://memory/release",
            "expected-hash",
            "current-hash",
        )

    runtime.execute_memory_action = stale_action
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        action = client.post(
            "/api/v1/ask",
            json={"task": "Update the release decision.", "conversation_id": conversation_id},
            headers=headers,
        ).json()["action"]
        conflict = client.post(
            f"/api/v1/ask/actions/{action['id']}",
            json={"decision": "apply"},
            headers=headers,
        )

        assert conflict.status_code == 409
        assert conflict.json()["error"]["current_hash"] == "current-hash"
        assert conflict.json()["action"]["status"] == "conflict"


def test_streamed_ask_finishes_and_saves_without_an_open_event_stream(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        headers = {
            "origin": "http://127.0.0.1:48123",
            "x-docmancer-csrf": csrf,
        }
        conversation_id = client.post(
            "/api/v1/ask/conversations",
            json={},
            headers=headers,
        ).json()["id"]
        started = client.post(
            "/api/v1/ask",
            json={
                "task": "Keep working after I leave",
                "conversation_id": conversation_id,
                "stream": True,
            },
            headers=headers,
        )
        assert started.status_code == 202

        job_id = started.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/v1/jobs/{job_id}").json()
            if job["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["state"] == "completed"

        conversation = client.get(
            f"/api/v1/ask/conversations/{conversation_id}",
        ).json()
        assert conversation["messages"][-1]["status"] == "complete"
        assert conversation["messages"][-1]["content"] == "Use Railway. [1]"


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


def test_failed_background_job_is_logged_with_a_traceback(caplog):
    """The job registry is in-memory only, so an unlogged failure leaves no
    record once the server exits. A Context build can fail 27 minutes and
    hundreds of provider calls in, which is exactly when the traceback matters.
    """
    import asyncio
    import logging

    from docmancer.web.api import JobRegistry

    async def scenario():
        registry = JobRegistry()

        async def operation(_progress):
            raise RuntimeError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac")

        job = registry.start("context.refresh", operation)
        for _ in range(200):
            if job["state"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        return job

    with caplog.at_level(logging.ERROR, logger="docmancer.web.api"):
        job = asyncio.run(scenario())

    assert job["state"] == "failed"
    assert "SSLV3_ALERT_BAD_RECORD_MAC" in job["error"]
    record = next(r for r in caplog.records if r.name == "docmancer.web.api")
    assert "context.refresh" in record.getMessage()
    assert record.exc_info is not None, "the traceback must be logged, not just the message"


def test_canonical_status_and_section_are_served(tmp_path: Path) -> None:
    client, app, _runtime = app_client(tmp_path)
    with client:
        authenticate(client, app)

        status = client.get("/api/v1/canonical")
        assert status.status_code == 200
        assert status.json()["pinned_total"] == 1

        section = client.get("/api/v1/canonical/about")
        assert section.status_code == 200
        assert section.json()["pinned"] == "- a pinned note"

        assert client.get("/api/v1/canonical/missing").status_code == 404


def test_canonical_pin_writes_and_reports_a_stale_hash_as_conflict(tmp_path: Path) -> None:
    """A reconcile can land between read and save. That must surface as a 409 the
    client can recover from, never as a silent overwrite."""
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)

        ok = client.post(
            "/api/v1/canonical/about/pin",
            json={"pinned": "- new note", "expected_hash": "hash-1"},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert ok.status_code == 200
        assert runtime.pinned_writes == [("about", "- new note", "hash-1")]

        conflict = client.post(
            "/api/v1/canonical/about/pin",
            json={"pinned": "- other", "expected_hash": "stale"},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert conflict.status_code == 409


def test_canonical_pin_accepts_clearing_every_note(tmp_path: Path) -> None:
    """Empty is a legitimate value: it is how a user removes their last note."""
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        response = client.post(
            "/api/v1/canonical/about/pin",
            json={"pinned": "", "expected_hash": "hash-1"},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert response.status_code == 200
        assert runtime.pinned_writes[-1][1] == ""


def test_canonical_refresh_passes_the_deterministic_flag(tmp_path: Path) -> None:
    client, app, runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        client.post(
            "/api/v1/canonical/refresh",
            json={"deterministic": True},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        client.post(
            "/api/v1/canonical/refresh",
            json={},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        )
        assert runtime.refreshes == [True, False]


def test_canonical_refresh_route_is_not_shadowed_by_the_section_route(tmp_path: Path) -> None:
    """/canonical/refresh must not resolve as the section named "refresh"."""
    client, app, _runtime = app_client(tmp_path)
    with client:
        csrf = authenticate(client, app)
        assert client.post(
            "/api/v1/canonical/refresh",
            json={},
            headers={"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf},
        ).status_code == 200
