from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner
from textual.containers import Vertical
from textual.widgets import Button, Label, LoadingIndicator, Static, Tab, TextArea

from docmancer.cli.__main__ import cli
from docmancer.tui.app import DocmancerTuiApp
from docmancer.tui.commands import default_registry
from docmancer.tui.screens.main import StartupScreen


def _commands(output: str) -> set[str]:
    rows = output.split("◆ Commands", 1)[1].split("◆ Examples", 1)[0]
    return {line.strip().split()[0] for line in rows.splitlines() if line.startswith("  ") and line.strip()}


def test_root_and_nested_help_expose_only_the_simplified_public_surface() -> None:
    runner = CliRunner()
    root = runner.invoke(cli, ["--help"])
    memory = runner.invoke(cli, ["memory", "--help"])
    docs = runner.invoke(cli, ["docs", "--help"])
    cloud = runner.invoke(cli, ["cloud", "--help"])
    assert root.exit_code == memory.exit_code == docs.exit_code == cloud.exit_code == 0
    assert _commands(root.output) == {"agent", "cloud", "docs", "mcp", "memory", "query", "setup", "status", "sync"}
    assert _commands(memory.output) == {"add", "distill", "edit", "export", "remove", "review", "share", "show"}
    assert _commands(docs.output) == {"add", "list", "query", "remove", "sync"}
    assert _commands(cloud.output) == {"connect", "devices", "disconnect", "relay", "sync"}

    connect = runner.invoke(cli, ["cloud", "connect", "--help"])
    devices = runner.invoke(cli, ["cloud", "devices", "--help"])
    disconnect = runner.invoke(cli, ["cloud", "disconnect", "--help"])
    assert {"--create-recovery", "--recovery-key"}.issubset(set(connect.output.split()))
    assert "--approve" in set(devices.output.split())
    assert {"--revoke", "--json", "--yes"}.issubset(set(devices.output.split()))
    assert {"--export", "--delete-remote"}.issubset(set(disconnect.output.split()))


def test_hidden_alias_still_runs_and_prints_replacement() -> None:
    result = CliRunner().invoke(cli, ["memory", "status"])
    assert result.exit_code == 0
    assert "Deprecated:" in result.output
    assert "docmancer status" in result.output


def test_tui_registry_has_exactly_eight_commands() -> None:
    assert {item.name for item in default_registry().commands} == {
        "sync", "distill", "review", "add", "share", "status", "settings", "help"
    }
    assert all("pack" not in f"{item.usage} {item.description}".casefold() for item in default_registry().commands)


def test_pending_context_inspector_explains_the_approval_action() -> None:
    detail = DocmancerTuiApp._context_detail({
        "view_kind": "context-proposal",
        "proposal_id": "proposal-1",
        "pack_id": "personal-defaults",
        "operations": [{
            "action": "add",
            "text": "Deploy frontend applications on Vercel.",
            "confidence": 0.9,
            "reason": "Recurring preference.",
            "source_paths": ["/tmp/CLAUDE.md"],
        }],
    })
    assert "# Pending review" in detail
    assert "Deploy frontend applications on Vercel." in detail
    assert "Confidence:** 90%" in detail
    assert "APPROVE" in detail and "REJECT" in detail
    assert "**Context:** Personal defaults" in detail
    assert "personal-defaults" not in detail
    assert "**Pack:**" not in detail


class SimplifiedBackend:
    project_path = "/tmp/project"
    ready = False
    last_latency = 0.0
    model_label = "local"

    async def initialize(self):
        self.ready = True
        return {"context": 4, "sources": 2, "memory": 1, "instructions": 1, "atoms": 2, "docs": 1}

    async def context(self):
        return [
            {
                "view_kind": "context-pack", "pack_id": "personal-defaults", "name": "Personal defaults",
                "audience_kind": "personal", "applicability_kind": "global", "records": 1, "pending": 0,
                "text": "# Personal defaults\n\n- Use TypeScript.",
            },
            {
                "view_kind": "context-record", "pack_id": "personal-defaults", "pack_name": "Personal defaults",
                "record_id": "record-1", "memory_type": "preference", "text": "Use TypeScript.",
                "audience_kind": "personal", "applicability_kind": "global", "origin": "manual",
                "source_path": "/tmp/context.md", "updated_at": "2026-07-20T12:00:00+00:00",
            },
        ]

    async def memory_sources(self, *, live_preview=True):
        return []

    async def docs_sources(self):
        return []

    async def audit(self):
        return {"findings": [], "unique_secret_count": 0, "finding_count": 0}

    async def cloud_status(self):
        return {"configured": False, "pending": 0, "conflicts": 0}

    async def audit_if_changed(self):
        return None


class SlowResetBackend(SimplifiedBackend):
    def __init__(self) -> None:
        self.reset_started = asyncio.Event()
        self.finish_reset = asyncio.Event()

    async def reset_context(self, audience: str):
        self.reset_started.set()
        await self.finish_reset.wait()
        return {"audience": audience, "removed": 1, "rejected_proposals": 0, "proposals": []}

    async def counts(self):
        return {"context": 4, "sources": 2, "memory": 1, "instructions": 1, "atoms": 2, "docs": 1}


class SlowStartupBackend(SimplifiedBackend):
    def __init__(self) -> None:
        self.initialize_started = asyncio.Event()
        self.finish_initialize = asyncio.Event()

    async def initialize(self):
        self.initialize_started.set()
        await self.finish_initialize.wait()
        return await super().initialize()


@pytest.mark.asyncio
async def test_tui_shows_startup_screen_until_initial_data_is_ready() -> None:
    backend = SlowStartupBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(130, 40)) as pilot:
        await asyncio.wait_for(backend.initialize_started.wait(), timeout=1)
        assert isinstance(app.screen, StartupScreen)
        assert app.screen.query_one("#startup-spinner", LoadingIndicator).display is True
        assert "Loading local memory" in str(app.screen.query_one("#startup-detail", Static).render())

        backend.finish_initialize.set()
        await pilot.pause()
        assert app.screen is app._main_screen


@pytest.mark.asyncio
async def test_tui_exposes_context_sources_audit_and_docs() -> None:
    app = DocmancerTuiApp(backend=SimplifiedBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        assert [tab.id for tab in app._main_screen.query(Tab)] == ["context", "sources", "audit", "docs"]
        assert app.mode == "context"
        assert app.results[0]["pack_id"] == "personal-defaults"
        assert "Use TypeScript" in app.results[0]["text"]
        assert app.query_one("#inspector-markdown").display is True
        assert app.query_one("#harness-filter").value == "personal"
        assert str(app.query_one("#harness-filter-label", Label).render()) == "View"
        assert app.query_one("#source-new", Button).display is True
        assert app.query_one("#source-edit", Button).display is False
        assert app.query_one("#source-delete", Button).display is False
        assert app.query_one("#source-promote", Button).display is True
        assert "1 approved" in str(app.query_one("#context-reset-personal", Button).label)
        assert app.query_one("#context-reset-personal", Button).disabled is False
        assert app.query_one("#context-reset-team", Button).disabled is True

        app.query_one("#result-list").index = 1
        await pilot.pause()
        assert app.selected_result["view_kind"] == "context-record"
        assert app.query_one("#source-new", Button).display is False
        assert app.query_one("#source-edit", Button).display is True
        assert str(app.query_one("#source-edit", Button).label) == "E  EDIT"
        assert str(app.query_one("#source-delete", Button).label) == "D  REMOVE"


@pytest.mark.asyncio
async def test_long_pending_review_keeps_context_actions_visible() -> None:
    app = DocmancerTuiApp(backend=SimplifiedBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        inspector = app.query_one("#inspector")
        proposal = {
            "view_kind": "context-proposal",
            "proposal_id": "proposal-1",
            "pack_id": "personal-defaults",
        }
        inspector.show_context(proposal, "# Pending review\n\n" + ("Long proposed context.\n\n" * 100))
        await pilot.pause()

        assert "SELECTED CONTEXT" in str(app.query_one("#inspector-title", Static).render())
        assert app.query_one("#source-meta", Static).display is False
        assert app.query_one("#source-text", TextArea).display is False
        action_bar = app.query_one("#source-action-bar", Vertical)
        approve = app.query_one("#source-edit", Button)
        markdown = app.query_one("#inspector-markdown")
        assert action_bar.display is True
        assert approve.display is True
        assert app.query_one("#source-new", Button).display is False
        assert action_bar.region.bottom <= inspector.region.bottom
        assert markdown.max_scroll_y > 0

        markdown.focus()
        await pilot.press("end")
        await pilot.pause()
        assert markdown.scroll_y > 0

        inspector.set_context_busy("Approving proposal...")
        await pilot.pause()
        assert app.query_one("#context-loading", LoadingIndicator).display is True
        assert approve.disabled is True
        inspector.set_context_busy(None)
        assert approve.disabled is False


@pytest.mark.asyncio
async def test_reset_button_stays_loading_until_reset_finishes() -> None:
    backend = SlowResetBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        reset = app.query_one("#context-reset-personal", Button)

        await pilot.click("#context-reset-personal")
        assert reset.loading is True

        confirm_click = asyncio.create_task(pilot.click("#confirm"))
        await asyncio.wait_for(backend.reset_started.wait(), timeout=1)
        assert reset.loading is True

        backend.finish_reset.set()
        await asyncio.wait_for(confirm_click, timeout=1)
        await pilot.pause()
        await pilot.pause()
        assert reset.loading is False


def test_agent_projections_use_the_same_compiled_context_for_every_target(tmp_path, monkeypatch) -> None:
    from docmancer.memory import projections

    monkeypatch.setattr(projections, "default_home", lambda: tmp_path)

    class Service:
        def compiled_markdown(self, **_kwargs):
            return "# Active context\n\n- Use TypeScript.\n"

    rows = projections.refresh_projections(Service(), agents=list(projections.PROJECTION_TARGETS), installed_only=False)
    assert {row["agent"] for row in rows} == set(projections.PROJECTION_TARGETS)
    contents = {Path(row["path"]).read_text() for row in rows}
    assert len(contents) == 1
    assert "Use TypeScript" in contents.pop()
