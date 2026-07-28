from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docmancer._version import __version__
from docmancer.core.config import ProvidersConfig
from docmancer.harness.integration_status import inspect_integrations
from docmancer.memory.delivery import inspect_hook_status
from docmancer.memory.tree.store import TreeStore
from docmancer.runtime.backend import LocalRuntime
from docmancer.web.library_catalog import LibraryCatalog


def _managed_block() -> str:
    return (
        "<!-- docmancer:start -->\n"
        f"<!-- docmancer:version {__version__} -->\n"
        "Use Docmancer.\n"
        "<!-- docmancer:end -->\n"
    )


def test_detected_codex_is_not_connected_until_integration_is_installed(tmp_path: Path) -> None:
    rows = inspect_integrations(
        detected_targets=["codex"],
        hook_rows=[],
        delivery_rows=[],
        home=tmp_path,
    )
    codex = next(row for row in rows if row["id"] == "codex")
    assert codex["detected"] is True
    assert codex["connected"] is False
    assert codex["integration_state"] == "ready-to-connect"
    assert codex["action_kind"] == "automatic"
    assert codex["can_install_from_web"] is True


def test_codex_is_connected_without_requiring_a_delivery_receipt(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md"
    memory_skill = tmp_path / ".codex" / "skills" / "docmancer-memory" / "SKILL.md"
    instructions = tmp_path / ".codex" / "AGENTS.md"
    for path in (skill, memory_skill):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docmancer\n", encoding="utf-8")
    instructions.write_text(_managed_block(), encoding="utf-8")

    rows = inspect_integrations(
        detected_targets=["codex"],
        hook_rows=[],
        delivery_rows=[],
        home=tmp_path,
    )
    codex = next(row for row in rows if row["id"] == "codex")
    assert codex["connected"] is True
    assert codex["integration_state"] == "connected"
    assert codex["last_successful_recall"] is None
    assert codex["action_kind"] == "automatic"
    assert codex["recall_setup_required"] is True


def test_connected_codex_with_recall_but_no_capture_needs_automatic_memory_setup(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md"
    memory_skill = tmp_path / ".codex" / "skills" / "docmancer-memory" / "SKILL.md"
    instructions = tmp_path / ".codex" / "AGENTS.md"
    for path in (skill, memory_skill):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docmancer\n", encoding="utf-8")
    instructions.write_text(_managed_block(), encoding="utf-8")
    codex = next(
        row for row in inspect_integrations(
            detected_targets=["codex"],
            hook_rows=[{"agent": "codex", "scope": "user", "recall": True, "capture": False}],
            delivery_rows=[],
            home=tmp_path,
        )
        if row["id"] == "codex"
    )
    assert codex["connected"] is True
    assert codex["recall_setup_required"] is True
    assert codex["capture_setup_required"] is True
    assert codex["action_kind"] == "automatic"


def test_connected_codex_with_recall_and_capture_needs_no_setup(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md"
    memory_skill = tmp_path / ".codex" / "skills" / "docmancer-memory" / "SKILL.md"
    instructions = tmp_path / ".codex" / "AGENTS.md"
    for path in (skill, memory_skill):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docmancer\n", encoding="utf-8")
    instructions.write_text(_managed_block(), encoding="utf-8")
    codex = next(
        row for row in inspect_integrations(
            detected_targets=["codex"],
            hook_rows=[{"agent": "codex", "scope": "user", "recall": True, "capture": True}],
            delivery_rows=[],
            home=tmp_path,
        )
        if row["id"] == "codex"
    )
    assert codex["connected"] is True
    assert codex["recall_setup_required"] is False
    assert codex["capture_setup_required"] is False
    assert codex["action_kind"] == "none"


def test_current_capture_hook_command_is_detected_after_setup(tmp_path: Path) -> None:
    hooks = {
        "hooks": {
            "SessionStart": [{
                "hooks": [{
                    "type": "command",
                    "command": "/opt/docmancer/bin/docmancer session-baseline --agent codex",
                }],
            }],
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": "/opt/docmancer/bin/docmancer memory hook-context --agent codex",
                }],
            }],
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": "/opt/docmancer/bin/docmancer --config /tmp/docmancer.yaml capture",
                }],
            }],
        },
    }
    path = tmp_path / ".codex" / "hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(hooks), encoding="utf-8")

    codex = next(
        row for row in inspect_hook_status(home=tmp_path)
        if row["agent"] == "codex" and row["scope"] == "user"
    )

    assert codex["recall"] is True
    assert codex["capture"] is True


def test_installed_codex_with_current_hooks_has_no_pending_setup(tmp_path: Path) -> None:
    for path in (
        tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md",
        tmp_path / ".codex" / "skills" / "docmancer-memory" / "SKILL.md",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docmancer\n", encoding="utf-8")
    (tmp_path / ".codex" / "AGENTS.md").write_text(_managed_block(), encoding="utf-8")
    hooks_path = tmp_path / ".codex" / "hooks.json"
    hooks_path.write_text(
        json.dumps({
            "hooks": {
                "SessionStart": [{
                    "hooks": [{
                        "command": "/opt/docmancer/bin/docmancer session-baseline --agent codex",
                    }],
                }],
                "UserPromptSubmit": [{
                    "hooks": [{
                        "command": "/opt/docmancer/bin/docmancer memory hook-context --agent codex",
                    }],
                }],
                "Stop": [{
                    "hooks": [{
                        "command": "/opt/docmancer/bin/docmancer capture",
                    }],
                }],
            },
        }),
        encoding="utf-8",
    )

    codex = next(
        row for row in inspect_integrations(
            detected_targets=["codex"],
            hook_rows=inspect_hook_status(home=tmp_path),
            delivery_rows=[],
            home=tmp_path,
        )
        if row["id"] == "codex"
    )

    assert codex["integration_state"] == "connected"
    assert codex["recall_setup_required"] is False
    assert codex["capture_setup_required"] is False
    assert codex["action_kind"] == "none"


def test_unrelated_capture_text_is_not_treated_as_a_docmancer_hook(tmp_path: Path) -> None:
    path = tmp_path / ".codex" / "hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"hooks":{"Stop":[{"hooks":[{"command":"echo capture"}]}]}}',
        encoding="utf-8",
    )

    codex = next(
        row for row in inspect_hook_status(home=tmp_path)
        if row["agent"] == "codex" and row["scope"] == "user"
    )

    assert codex["capture"] is False


def test_claude_desktop_manual_upload_is_not_an_automatic_install(tmp_path: Path) -> None:
    package = tmp_path / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"skill")

    desktop = next(
        row for row in inspect_integrations(
            detected_targets=["claude-desktop"],
            hook_rows=[],
            delivery_rows=[],
            home=tmp_path,
        )
        if row["id"] == "claude-desktop"
    )

    assert desktop["integration_state"] == "manual-step"
    assert desktop["action_kind"] == "manual"
    assert desktop["can_install_from_web"] is False
    assert desktop["artifact_ready"] is True
    assert desktop["manual_actions"][0]["label"] == "Show setup steps"


def test_installed_codex_with_old_managed_instructions_needs_update(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md"
    memory_skill = tmp_path / ".codex" / "skills" / "docmancer-memory" / "SKILL.md"
    instructions = tmp_path / ".codex" / "AGENTS.md"
    for path in (skill, memory_skill):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Docmancer\n", encoding="utf-8")
    instructions.write_text(
        "<!-- docmancer:start -->\n"
        "<!-- docmancer:version 0.0.1 -->\n"
        "Use Docmancer.\n"
        "<!-- docmancer:end -->\n",
        encoding="utf-8",
    )

    codex = next(
        row for row in inspect_integrations(
            detected_targets=["codex"],
            hook_rows=[],
            delivery_rows=[],
            home=tmp_path,
        )
        if row["id"] == "codex"
    )
    assert codex["skill_installed"] is True
    assert codex["instructions_installed"] is True
    assert codex["connected"] is True
    assert codex["integration_state"] == "stale"


def test_human_preview_removes_local_paths_and_memory_addresses() -> None:
    preview = LocalRuntime._readable_markdown_preview(
        "Decision from /Users/example/secret/project/AGENTS.md and "
        "memory://atom/abc123 should stay diagnostic only."
    )
    assert "/Users/" not in preview
    assert "memory://atom/" not in preview
    assert "a local file" in preview


@pytest.mark.asyncio
async def test_synthesized_context_body_is_presented_as_readable_context(tmp_path: Path) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    runtime.memory = type(
        "Memory",
        (),
        {"indexed_atoms": lambda self: []},
    )()

    topics = await runtime._humanize_context_topics([
        {
            "cluster_id": "ctx_release",
            "body": "# Release process\n\nDeploy through Railway after the full test suite passes.",
            "synthesized": True,
            "source_addresses": [],
        }
    ])

    assert topics[0]["title"] == "Release process"
    assert topics[0]["summary"] == "Deploy through Railway after the full test suite passes."
    assert topics[0]["has_readable_summary"] is True


def test_library_catalog_searches_and_cursor_paginates(tmp_path: Path) -> None:
    catalog = LibraryCatalog(tmp_path / "library.sqlite")
    catalog.replace([
        {
            "corpus": "memory",
            "record_id": f"record-{index:02d}",
            "title": f"Release decision {index:02d}",
            "summary": "Deploy with Railway" if index == 12 else "A durable decision",
            "kind": "decision",
            "detail_key": f"docmancer://memory/{index}",
            "updated_at": f"2026-07-{index + 1:02d}T10:00:00+00:00",
        }
        for index in range(20)
    ])
    first = catalog.list(corpus="memory", limit=7)
    second = catalog.list(corpus="memory", limit=7, cursor=first["next_cursor"])
    search = catalog.list(corpus="memory", query="Railway")

    assert len(first["items"]) == len(second["items"]) == 7
    assert {item["record_id"] for item in first["items"]}.isdisjoint(
        {item["record_id"] for item in second["items"]}
    )
    assert [item["record_id"] for item in search["items"]] == ["record-12"]

    catalog.replace([])
    assert catalog.list(corpus="memory")["items"] == []


@pytest.mark.asyncio
async def test_library_hides_a_stale_empty_context_scaffold(tmp_path: Path) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    catalog = LibraryCatalog(tmp_path / "library.sqlite")
    catalog.replace([
        {
            "corpus": "memory",
            "record_id": "context-scaffold",
            "title": "Project context",
            "summary": "Curated project memory lives in this tree.",
            "kind": "context",
            "detail_key": "docmancer://memory/context",
        },
        {
            "corpus": "memory",
            "record_id": "release",
            "title": "Release decision",
            "summary": "Use Railway.",
            "kind": "decision",
            "detail_key": "docmancer://memory/release",
        },
    ])
    runtime._library_catalog_instance = catalog
    runtime._library_bootstrap_checked = True

    result = await runtime.library(corpus="memory")

    assert [item["record_id"] for item in result["items"]] == ["release"]


class _Memory:
    def sources(self, *, live_preview: bool = False):
        assert live_preview is False
        return []


class _Docs:
    async def list_grouped_sources_with_dates(self):
        return []


@pytest.mark.asyncio
async def test_library_excludes_generated_context_and_tree_list_scans_once(tmp_path: Path) -> None:
    project = tmp_path / "project"
    store = TreeStore(project / ".docmancer" / "tree")
    store.write(
        relative_path="decisions/release.md",
        text="# Release\n\nUse Railway.",
        memory_type="decision",
        scope="project",
        authority="advisory",
        project_id="project",
    )
    store.write(
        relative_path="context.md",
        text="# Project context\n\nCurated project memory lives in this tree.",
        memory_type="context",
        scope="project",
        authority="advisory",
        project_id="project",
    )
    store.write(
        relative_path="context/generated.md",
        text="# Generated\n\nRaw generated Context.",
        memory_type="fact",
        scope="project",
        authority="advisory",
        project_id="project",
    )
    runtime = LocalRuntime(
        project_path=project,
        memory_factory=lambda: _Memory(),
        docs_factory=lambda: _Docs(),
    )
    runtime.memory = _Memory()
    runtime.docs = _Docs()
    runtime.ready = True
    runtime._tree_store_instance = store

    calls = 0
    original = store.index.entries

    def counted():
        nonlocal calls
        calls += 1
        return original()

    store.index.entries = counted  # type: ignore[method-assign]
    payloads = await runtime.tree_list()
    assert calls == 1
    assert {item["title"] for item in payloads} == {"Release", "Generated", "Project context"}

    records = await runtime._library_records()
    assert [item["title"] for item in records if item["corpus"] == "memory"] == ["Release"]


class _ProviderMemory:
    def __init__(self, providers: ProvidersConfig) -> None:
        self.config = SimpleNamespace(providers=providers)


@pytest.mark.asyncio
async def test_provider_model_catalog_filters_non_generation_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    runtime.memory = _ProviderMemory(
        ProvidersConfig(
            default_llm="openai",
            models={"openai": "gpt-5-mini"},
        )
    )
    monkeypatch.setattr(
        runtime,
        "_discover_provider_models",
        lambda _provider_id: [
            "gpt-5",
            "gpt-4.1",
            "text-embedding-3-large",
            "omni-moderation-latest",
            "gpt-image-1",
        ],
    )

    result = await runtime.provider_models("openai", refresh=True)
    model_ids = [item["id"] for item in result["items"]]

    assert result["state"] == "ready"
    assert model_ids[:2] == ["gpt-5-mini", "gpt-5"]
    assert "gpt-4.1" in model_ids
    assert "text-embedding-3-large" not in model_ids
    assert "omni-moderation-latest" not in model_ids
    assert "gpt-image-1" not in model_ids


class _PreviewMemory(_ProviderMemory):
    def status(self) -> dict:
        return {"atoms": 240}

    def sources(self, *, live_preview: bool = False) -> list[dict]:
        assert live_preview is False
        return [{"path": "AGENTS.md"}, {"path": "CLAUDE.md"}]


class _PlanningContextEngine:
    def __init__(self) -> None:
        self.calls = 0

    def build(self, **kwargs) -> dict:
        self.calls += 1
        assert kwargs == {"dry_run": True}
        return {
            "clusters": 6,
            "estimated_provider_calls": 6,
            "estimated_input_tokens": 12000,
            "estimated_output_tokens": 3000,
            "estimated_cost_usd": 0.12,
            "writes": ["context/personal.md", "context/project.md"],
        }


@pytest.mark.asyncio
async def test_ai_distillation_preview_only_builds_a_deterministic_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    runtime.memory = _PreviewMemory(
        ProvidersConfig(
            default_llm="ollama",
            models={"ollama": "qwen3"},
        )
    )
    engine = _PlanningContextEngine()
    monkeypatch.setattr(runtime, "_context_engine", lambda: engine)

    preview = await runtime.distillation_preview()

    assert engine.calls == 1
    assert preview["available"] is True
    assert preview["provider"] == "ollama"
    assert preview["model"] == "qwen3"
    assert preview["atoms"] == 240
    assert preview["sources"] == 2
    assert preview["clusters"] == 6
    assert preview["estimated_provider_calls"] == 6
