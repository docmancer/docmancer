import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from textual.app import App
from textual.widgets import Button, OptionList, Tree

from docmancer.harness.base import MemoryEntry
from docmancer.tui.app import DocmancerTuiApp
from docmancer.tui.backend import TuiBackend
from docmancer.tui.presentation import source_display_location, source_display_title
from docmancer.tui.screens import sync as sync_screen_module
from docmancer.tui.screens.audit import AuditScreen
from docmancer.tui.screens.cloud import ConflictResolutionScreen, DeviceApprovalScreen, PromotionReviewScreen
from docmancer.tui.screens.detail import CreateSourceScreen, DetailScreen, SourceViewerScreen
from docmancer.tui.screens.sources import SourcesScreen
from docmancer.tui.screens.sync import SyncScreen
from docmancer.tui.widgets import Inspector, ResultList


NOW = datetime.now(timezone.utc)


def test_codex_rollout_provenance_is_human_readable():
    path = "/Users/example/.codex/memories/rollout_summaries/2026-07-18T21-16-46-eUW9-docmancer_duplicate_memory_fix_and_readme_streamline.md"
    source_row = {
        "path": path,
        "title": "rollout_summaries/2026-07-18T21-16-46-eUW9-docmancer_duplicate_memory_fix_and_readme_streamline",
    }

    assert source_display_title(source_row) == "Docmancer duplicate memory fix and README streamline"
    assert source_display_location(path) == "Codex rollout summary · 18 Jul 2026, 21:16 UTC"


def source(index: int, *, kind: str = "agent-memory", harness: str | None = None, scope: str | None = None, content: str | None = None) -> dict:
    harness = harness or ("codex" if index % 2 == 0 else "claude-code")
    scope = scope or ("global:codex" if index % 3 else "/tmp/project")
    if not scope.startswith(("global:", "project:", "team:")):
        scope = f"project:{scope}"
    text = content or f"Memory source {index}. Production deploys run on Railway."
    return {
        "source_key": f"src-{kind}-{index}",
        "harness": harness,
        "scope": scope,
        "scope_kind": scope.split(":", 1)[0],
        "kind": kind,
        "title": f"memory-{index}",
        "path": f"/tmp/memory-{index}.md",
        "chars": len(text),
        "atom_count": 2,
        "updated_at": (NOW - timedelta(hours=index)).isoformat(),
        "indexed_at": NOW.isoformat(),
        "source_hash": f"hash-{index}",
        "record_id": "record-123" if index == 0 else None,
        "origin": "manual" if index == 0 else "harvested",
        "changed_since_sync": index == 1,
        "source_missing": False,
        "content": text,
    }


MEMORY_SOURCES = [source(index) for index in range(55)]
INSTRUCTION_SOURCE = source(
    100,
    kind="instructions",
    harness="instructions",
    scope="project:/tmp/project",
    content="# Instructions\n\nRun tests before release.\n",
)
ALL_SOURCES = [*MEMORY_SOURCES, INSTRUCTION_SOURCE]

DOC_RESULT = {
    "id": "docs:0",
    "text": "Use fixtures to provide reusable test state.",
    "source": "https://docs.pytest.org/fixtures.html",
    "chunk_index": 2,
    "score": 0.88,
    "metadata": {"title": "Fixtures", "heading": "How fixtures work", "ingested_at": NOW.isoformat()},
}

DOC_SOURCE_DETAIL = {
    "source": "https://docs.pytest.org",
    "pages": [
        {
            "source": "https://docs.pytest.org/fixtures.html",
            "title": "Fixtures",
            "format": "markdown",
            "ingested_at": NOW.isoformat(),
            "content": "# Fixtures\n\nUse fixtures to provide reusable test state.\n\n## Scope\n\nFixtures can be scoped.",
            "sections": [
                {"chunk_index": 0, "title": "Fixtures", "level": 1, "text": "Use fixtures to provide reusable test state."},
                {"chunk_index": 1, "title": "Scope", "level": 2, "text": "Fixtures can be scoped."},
            ],
        }
    ],
}


class FakeBackend:
    def __init__(self):
        self.project_path = "/tmp/project"
        self.ready = False
        self.last_latency = 0.0
        self.model_label = "model2vec"
        self.forgotten = []
        self.promoted = []
        self.edited = []
        self.edited_sources = []
        self.deleted_sources = []
        self.created_sources = []
        self.cleared = False
        self.cloud_audit_reports = 0

    async def initialize(self):
        self.ready = True
        return {"memory": 55, "instructions": 1, "atoms": 112, "docs": 1}

    async def counts(self):
        return {"memory": 55, "instructions": 1, "atoms": 112, "docs": 1}

    async def memory_sources(self, live_preview=True):
        return [
            {"agent": item["harness"], "scope": item["scope"], "type": item["kind"], "atoms": item["atom_count"], "path": item["path"]}
            for item in ALL_SOURCES
        ]

    async def browse_memory_sources(self, *, kinds, harness=None, scope_kind=None, project_path=None, updated_after=None, page=1, page_size=50):
        rows = [item for item in ALL_SOURCES if item["kind"] in kinds]
        if harness:
            rows = [item for item in rows if item["harness"] == harness]
        if scope_kind:
            rows = [item for item in rows if item["scope_kind"] == scope_kind]
        if project_path:
            rows = [item for item in rows if item["scope_kind"] == "global" or item["scope"].split(":", 1)[1] == project_path]
        if updated_after:
            rows = [item for item in rows if datetime.fromisoformat(item["updated_at"]) >= updated_after]
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        summaries = [{key: value for key, value in item.items() if key != "content"} for item in rows[start : start + page_size]]
        return {"items": summaries, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}

    async def search_memory_sources(self, text, *, kinds, page=1, page_size=50, **kwargs):
        rows = [item for item in ALL_SOURCES if item["kind"] in kinds and text.lower() in item["content"].lower()]
        groups = []
        for item in rows:
            summary = {key: value for key, value in item.items() if key != "content"}
            identifier = "record-123" if item["source_key"] == "src-agent-memory-0" else f"atom-{item['source_key']}"
            groups.append(
                {
                    "source": summary,
                    "matches": [
                        {
                            "identifier": identifier,
                            "text": "Production deploys run on Railway.",
                            "score": 0.91,
                            "line_start": 1,
                            "line_end": 1,
                            "memory_type": "decision",
                            "record_id": "record-123" if identifier == "record-123" else None,
                            "atom_id": None if identifier == "record-123" else identifier,
                            "origin": item["origin"],
                        }
                    ],
                }
            )
        start = (page - 1) * page_size
        return {"items": groups[start : start + page_size], "page": page, "page_size": page_size, "has_more": start + page_size < len(groups)}

    async def get_memory_source(self, source_key):
        return next((dict(item) for item in ALL_SOURCES if item["source_key"] == source_key), None)

    async def get_live_source(self, source_key):
        source_row = next(item for item in ALL_SOURCES if item["source_key"] == source_key)
        content = source_row["content"]
        return {
            **source_row,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    async def edit_source(self, source_key, content, *, expected_hash):
        self.edited_sources.append((source_key, content, expected_hash))
        source_row = next(item for item in ALL_SOURCES if item["source_key"] == source_key)
        return source_row

    async def delete_source(self, source_key, *, expected_hash):
        self.deleted_sources.append((source_key, expected_hash))
        source_row = next(item for item in ALL_SOURCES if item["source_key"] == source_key)
        return source_row["path"]

    async def create_source(self, path, content):
        self.created_sources.append((path, content))
        return path, True

    async def docs_sources(self):
        return [{"source": "https://docs.pytest.org", "pages": 10, "sections": 40, "ingested_at": NOW.isoformat(), "formats": ["markdown"]}]

    async def query_docs(self, text, **kwargs):
        self.last_latency = 0.02
        return [DOC_RESULT] if "fixture" in text else []

    async def get_docs_source(self, source_root):
        return DOC_SOURCE_DETAIL if source_root == "https://docs.pytest.org" else None

    async def status(self):
        return {"project": self.project_path, "memory": {"atoms": 112, "sources": 56, "db_path": "/tmp/memory.db"}, "docs": {"sections_count": 1}, "last_sync": {}}

    async def sync(self, progress):
        for stage in ("lock", "harvest", "redact", "merge", "graph", "index", "finalize", "done"):
            progress(stage, f"{stage} detail")
        return 112

    async def memory_intelligence(self, *, view="review", page=1, page_size=10, **kwargs):
        rows = []
        return {
            "items": rows,
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 1,
            "has_more": False,
            "view": view,
        }

    async def audit(self):
        return {"unique_secret_count": 0, "finding_count": 0, "findings": [], "by_severity": {}}

    async def hook_status(self):
        return [
            {
                "agent": "claude-code",
                "scope": "user",
                "path": "/tmp/.claude/settings.json",
                "exists": True,
                "recall": True,
                "capture": False,
                "events": ["SessionStart", "UserPromptSubmit"],
                "error": None,
            },
            {
                "agent": "codex",
                "scope": "user",
                "path": "/tmp/.codex/hooks.json",
                "exists": False,
                "recall": False,
                "capture": False,
                "events": [],
                "error": None,
            },
        ]

    async def add(self, text, **kwargs):
        return type("Record", (), {"record_id": "new-record"})(), True

    async def find_atom(self, identifier):
        if identifier not in {"record-123", "atom-src-agent-memory-1"}:
            return None
        return type("Atom", (), {"record_id": "record-123" if identifier == "record-123" else None, "atom_id": identifier, "text": MEMORY_SOURCES[0]["content"], "type": "decision", "source_path": "/tmp/memory-0.md", "origin": "manual" if identifier == "record-123" else "harvested"})()

    async def edit(self, identifier, text):
        self.edited.append((identifier, text))

    async def forget(self, identifier):
        self.forgotten.append(identifier)

    async def promote(self, identifier):
        self.promoted.append(identifier)
        return type("Record", (), {"record_id": "team-record"})(), True

    async def clear_memory(self):
        self.cleared = True
        return []

    async def doctor(self):
        return {"python": "3.13", "config_exists": True}

    async def cloud_status(self):
        return {"configured": False}

    async def cloud_report_audit(self):
        self.cloud_audit_reports += 1
        return None


class SecurityBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.audit_calls = 0

    async def audit(self):
        self.audit_calls += 1
        occurrence = {
            "type": "github-token",
            "severity": "high",
            "line": 12,
            "source_path": "/tmp/memory-0.md",
            "agent": "codex",
            "scope": "global:codex",
            "title": "memory",
            "masked_excerpt": "ghp_…abcd",
            "fingerprint": "masked-fingerprint",
        }
        finding = {
            "fingerprint": "masked-fingerprint",
            "type": "github-token",
            "severity": "high",
            "occurrences": [occurrence],
            "occurrence_count": 1,
        }
        return {
            "unique_secret_count": 1,
            "finding_count": 1,
            "findings": [finding],
            "by_severity": {"critical": [], "high": [finding], "medium": [], "low": []},
        }


@pytest.mark.asyncio
async def test_tui_browses_paginated_files_and_click_does_not_open_modal():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        tabs = app.query_one("#mode-tabs")
        sources_tab = app.query_one("#sources")
        docs_tab = app.query_one("#docs")
        assert tabs.active == "sources"
        assert sources_tab.has_class("-active")
        assert sources_tab.styles.background != docs_tab.styles.background
        assert len(app.results) == 10
        assert app.total_pages == 6
        assert len(app.query_one("#source-text").text) == len(MEMORY_SOURCES[0]["content"])
        assert str(app.query_one("#source-action-label").render()) == "RECORD CONTROLS"
        assert str(app.query_one("#source-new").label) == "N  NEW"
        assert app.query_one("#source-delete").variant == "error"

        await pilot.click("#result-list > ResultItem")
        await pilot.pause()
        assert app.screen is app._main_screen

        app.query_one("#result-list", ResultList).action_select_cursor()
        await pilot.pause()
        assert isinstance(app.screen, SourceViewerScreen)


@pytest.mark.asyncio
async def test_tui_pagination_tabs_and_filters_cover_the_full_file_corpus():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        await app.action_next_page()
        assert app.current_page == 2
        assert len(app.results) == 10

        app.query_one("#harness-filter").value = "instructions"
        await pilot.pause(0.2)
        assert len(app.results) == 1
        assert app.results[0]["kind"] == "instructions"
        assert str(app.query_one("#source-action-label").render()) == "FILE CONTROLS"

        app.query_one("#harness-filter").value = "codex"
        await pilot.pause(0.2)
        assert app.results
        assert all(item["harness"] == "codex" for item in app.results)


@pytest.mark.asyncio
async def test_removed_intelligence_backend_does_not_affect_context_tab():
    class BusyBackend(FakeBackend):
        async def memory_intelligence(self, **kwargs):
            raise sqlite3.OperationalError("database is locked")

    app = DocmancerTuiApp(backend=BusyBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        assert app.mode == "context"
        assert app.results == []
        assert "CONTEXT" in str(app.query_one("#results-title").render())
        assert app.query_one("#context")
        assert app.query_one("#sources")
        assert app.query_one("#audit")
        assert app.query_one("#docs")


@pytest.mark.asyncio
async def test_intelligence_review_groups_claims_and_paginates_them():
    class FakeMemory:
        def conflicts(self, *, unresolved_only=True):
            assert unresolved_only is True
            return [
                {
                    "relation_id": "rel-1",
                    "source_node_id": "node-a",
                    "target_node_id": "node-b",
                    "source_atom_id": "atom-a",
                    "target_atom_id": "atom-b",
                    "source_text": "The project uses npm.",
                    "target_text": "The project uses pnpm.",
                    "source_scope": "project:test",
                    "target_scope": "project:test",
                    "confidence": 0.95,
                    "evidence": {
                        "claim_key": "the project|uses",
                        "subject": "the project",
                        "source_value": "npm",
                        "target_value": "pnpm",
                    },
                }
            ]

        def recent(self, *, since, limit):
            assert since.tzinfo is not None
            assert limit == 50_000
            return [
                {
                    "atom_id": "atom-recent",
                    "text": "The project uses pnpm.",
                    "activity_at": NOW.isoformat(),
                    "scope": "project:test",
                    "project_path": "/tmp/project",
                }
            ]

    backend = TuiBackend(memory_factory=FakeMemory)
    backend.memory = FakeMemory()
    backend.ready = True

    data = await backend.memory_intelligence(view="review", page=1, page_size=10)

    assert data["total"] == 1
    assert data["total_pages"] == 1
    assert data["items"][0]["intelligence_kind"] == "conflict-group"
    assert data["items"][0]["relation_ids"] == ["rel-1"]
    assert [member["atom_id"] for member in data["items"][0]["members"]] == ["atom-a", "atom-b"]

    recent = await backend.memory_intelligence(view="recent", page=1, page_size=10)
    assert recent["total"] == 1
    assert recent["items"][0]["intelligence_kind"] == "recent-source"
    assert recent["items"][0]["atom_count"] == 1


@pytest.mark.asyncio
async def test_source_inspector_navigates_atoms_instead_of_an_unlabelled_passage_count():
    class AtomBackend(FakeBackend):
        async def get_memory_source(self, source_key):
            document = await super().get_memory_source(source_key)
            assert document is not None
            document["atoms"] = [
                {
                    "navigation_kind": "atom",
                    "identifier": "atom-one",
                    "atom_id": "atom-one",
                    "memory_type": "decision",
                    "status": "current",
                    "line_start": 1,
                    "line_end": 1,
                    "text": "Production deploys run on Railway.",
                },
                {
                    "navigation_kind": "atom",
                    "identifier": "atom-two",
                    "atom_id": "atom-two",
                    "memory_type": "fact",
                    "status": "current",
                    "line_start": 1,
                    "line_end": 1,
                    "text": "The support email is help@example.test.",
                },
            ]
            document["atom_count"] = 2
            return document

    app = DocmancerTuiApp(backend=AtomBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        inspector = app.query_one("#inspector", Inspector)

        assert inspector.navigation_kind == "atom"
        assert inspector.selected_memory_identifier == "atom-one"
        assert "atom 1/2" in str(app.query_one("#source-meta").render())
        assert str(app.query_one("#source-action-label").render()) == "ATOM CONTROLS"

        inspector.move_match(1)
        assert inspector.selected_memory_identifier == "atom-two"
        assert "atom 2/2" in str(app.query_one("#source-meta").render())


@pytest.mark.asyncio
async def test_slash_opens_all_commands_and_wide_layout_uses_20_30_50_columns():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(200, 45)) as pilot:
        await pilot.pause()
        command_input = app.query_one("#command-input")
        command_input.value = "/"
        await pilot.pause()

        menu = app.query_one("#command-menu", OptionList)
        assert menu.has_class("visible")
        assert menu.option_count == len(app.registry.commands)

        filter_width = app.query_one("#filter-pane").size.width
        results_width = app.query_one("#results-pane").size.width
        inspector_width = app.query_one("#inspector").size.width
        total = filter_width + results_width + inspector_width
        assert filter_width / total == pytest.approx(0.20, abs=0.02)
        assert results_width / total == pytest.approx(0.30, abs=0.02)
        assert inspector_width / total == pytest.approx(0.50, abs=0.02)


@pytest.mark.asyncio
async def test_updated_filter_and_docs_tab_browse_without_a_query():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        app.query_one("#time-filter").value = "day"
        await pilot.pause(0.2)
        assert app.results
        assert all(datetime.fromisoformat(item["updated_at"]) >= datetime.now(timezone.utc) - timedelta(days=1) for item in app.results)

        await app.switch_mode("docs")
        await pilot.pause()
        assert len(app.results) == 1
        assert app.results[0]["view_kind"] == "docs-source"
        assert str(app.query_one("#inspector-title").render()) == "DOCUMENTATION SOURCE"
        tree = app.query_one("#docs-outline", Tree)
        assert tree.display
        assert len(tree.root.children) == 1
        assert len(tree.root.children[0].children) == 2
        assert app.query_one("#source-text").text.startswith("# Fixtures")

        section = tree.root.children[0].children[1]
        tree.post_message(Tree.NodeSelected(section))
        await pilot.pause()
        assert app.query_one("#source-text").text == "Fixtures can be scoped."

        await app.run_query("fixture")
        assert app.results[0]["source"].startswith("https://docs.pytest.org")


@pytest.mark.asyncio
async def test_security_audit_annotates_sources_and_status_badge():
    backend = SecurityBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause()
        assert backend.audit_calls == 1
        assert "Sources 56 !" in str(app.query_one("#sources").label)
        assert "Audit 1 !" in str(app.query_one("#audit").label)

        await app.switch_mode("audit")
        await pilot.pause()
        assert [row["view_kind"] for row in app.results] == ["security-finding"]
        assert app.results[0]["type"] == "github-token"
        assert str(app.query_one("#inspector-title").render()) == "AUDIT"
        assert app.query_one("#inspector-markdown").display is True
        assert "CLAUDE CODE" in str(app.query_one("#audit-hook-claude-code", Button).label)
        assert "all projects" in str(app.query_one("#audit-hook-claude-code", Button).label)

        await pilot.click("#audit-hook-claude-code")
        await pilot.pause()
        assert str(app.query_one("#inspector-title").render()) == "AUDIT"

        await pilot.click("#audit-how-it-works")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("escape")
        await pilot.pause()

        await app.switch_mode("sources")
        await pilot.pause()
        warned = next(row for row in app.results if row["path"] == "/tmp/memory-0.md")
        assert warned["security_findings"] == 1
        assert warned["security_severity"] == "high"


@pytest.mark.asyncio
async def test_tui_groups_search_matches_and_uses_passage_actions(monkeypatch):
    backend = FakeBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        await app.run_query("Railway")
        await pilot.pause()
        selected = app.query_one("#result-list", ResultList).selected_result
        assert selected["view_kind"] == "source-match"
        assert selected["matches"][0]["line_start"] == 1
        assert app.query_one("#source-text").selection.start == (0, 0)
        assert str(app.query_one("#source-action-label").render()) == "MATCH CONTROLS"
        assert app.query_one("#source-new").display is False
        assert app.query_one("#source-forget").variant == "warning"
        assert app.query_one("#source-promote").variant == "success"

        monkeypatch.setattr(app, "_show_modal_wait", lambda screen: _confirmed())
        await app.command_promote([])
        await app.command_forget([])
        assert backend.promoted == ["record-123"]
        assert backend.forgotten == ["record-123"]


@pytest.mark.asyncio
async def test_tui_queries_docs_and_opens_operational_overlays():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.run_query("fixture", mode="docs")
        assert app.mode == "docs"
        assert app.results[0]["source"].startswith("https://docs.pytest.org")

        await app.command_status([])
        assert isinstance(app.screen, DetailScreen)
        app.pop_screen()
        await app.command_sources([])
        assert isinstance(app.screen, SourcesScreen)
        app.pop_screen()
        await app.command_audit([])
        assert isinstance(app.screen, AuditScreen)
        app.pop_screen()
        await app.command_sync([])
        assert isinstance(app.screen, SyncScreen)
        assert app.screen.finished is True


@pytest.mark.asyncio
async def test_sync_screen_animates_and_reports_stage_durations(monkeypatch):
    class Clock:
        now = 100.0

        def __call__(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(sync_screen_module, "monotonic", clock)
    app = App()
    screen = SyncScreen()
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        initial = str(screen.query_one("#sync-lock").render())
        clock.now = 102.5
        screen._tick()
        moving = str(screen.query_one("#sync-lock").render())
        assert initial != moving
        assert "2.5s" in moving
        assert "Step 1 of 7" in str(screen.query_one("#sync-detail").render())

        screen.update_stage("harvest", "Found 203 source files")
        assert str(screen.query_one("#sync-lock").render()) == "[✓] lock  2.5s"
        clock.now = 105.75
        screen.update_stage("graph", "Reconciling 5,521 memory atoms")
        assert "3.2s" in str(screen.query_one("#sync-harvest").render())
        assert "Step 5 of 7" in str(screen.query_one("#sync-detail").render())
        assert "Reconciling 5,521 memory atoms" in str(screen.query_one("#sync-detail").render())

        clock.now = 165.75
        screen.update_stage("done", "Indexed 5,521 memory atoms")
        assert "1m 05.8s total" in str(screen.query_one("#sync-done").render())
        assert "Sync complete in 1m 05.8s" in str(screen.query_one("#sync-detail").render())


@pytest.mark.asyncio
async def test_tui_edit_uses_real_modal_result():
    backend = FakeBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        task = asyncio.create_task(app.command_edit(["record-123"]))
        await pilot.pause()
        app.screen.query_one("#record-editor").text = "Production deploys run on Fly.io."
        await pilot.click("#save")
        await task
        assert backend.edited == [("record-123", "Production deploys run on Fly.io.")]


@pytest.mark.asyncio
async def test_tui_external_sources_can_be_created_edited_and_deleted(monkeypatch):
    backend = FakeBackend()
    app = DocmancerTuiApp(backend=backend)
    async with app.run_test(size=(150, 42)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        app.query_one("#result-list", ResultList).index = 1
        await pilot.pause()
        selected = app.selected_result
        assert selected["origin"] == "harvested"
        assert app.query_one("#source-edit").display
        assert app.query_one("#source-delete").display

        edit_task = asyncio.create_task(app.command_edit([]))
        await pilot.pause()
        app.screen.query_one("#record-editor").text = "Updated external agent memory."
        await pilot.click("#save")
        await edit_task
        assert backend.edited_sources[0][0] == selected["source_key"]
        assert backend.edited_sources[0][1] == "Updated external agent memory."

        monkeypatch.setattr(app, "_show_modal_wait", lambda screen: _confirmed())
        app.query_one("#result-list", ResultList).index = 1
        await pilot.pause()
        await app.command_delete([])
        assert backend.deleted_sources[0][0] == selected["source_key"]

        async def created(_screen):
            return "/tmp/new-rule.md", "# Rule\n\nUse Ruff.\n"

        monkeypatch.setattr(app, "_show_modal_wait", created)
        app.query_one("#harness-filter").value = "instructions"
        await pilot.pause(0.2)
        await app.command_new([])
        assert backend.created_sources == [("/tmp/new-rule.md", "# Rule\n\nUse Ruff.\n")]


@pytest.mark.asyncio
async def test_new_button_cancel_dismisses_modal_without_blocking_the_ui():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(150, 42)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        app.query_one("#harness-filter").value = "instructions"
        await pilot.pause(0.2)

        new_button = app.query_one("#source-new", Button)
        await pilot.click("#source-new")
        await pilot.pause()
        assert isinstance(app.screen, CreateSourceScreen)
        assert new_button.loading is True

        await pilot.click("#cancel")
        await pilot.pause()
        assert app.screen is app._main_screen
        assert new_button.loading is False


@pytest.mark.asyncio
async def test_tui_large_source_is_not_truncated():
    large = "first line\n" + ("memory detail\n" * 40_000) + "last line"
    original = MEMORY_SOURCES[0]["content"]
    MEMORY_SOURCES[0]["content"] = large
    MEMORY_SOURCES[0]["chars"] = len(large)
    try:
        app = DocmancerTuiApp(backend=FakeBackend())
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            await app.switch_mode("sources")
            assert app.query_one("#source-text").text.endswith("last line")
            assert len(app.query_one("#source-text").text) > 500_000
    finally:
        MEMORY_SOURCES[0]["content"] = original
        MEMORY_SOURCES[0]["chars"] = len(original)


@pytest.mark.asyncio
async def test_tui_narrow_layout_and_cloud_overlays_mount():
    app = DocmancerTuiApp(backend=FakeBackend())
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert app._main_screen.has_class("compact")
        assert app._main_screen.has_class("narrow")

    shell = App()
    async with shell.run_test(size=(100, 35)) as pilot:
        await shell.push_screen(ConflictResolutionScreen([{"conflict_id": 1, "reason": "diverged_heads", "local_revision_id": "left", "remote_revision_id": "right"}]))
        await pilot.pause()
        assert shell.screen.query_one("#conflict-table")
        shell.pop_screen()
        await shell.push_screen(DeviceApprovalScreen({"device_id": "dev", "fingerprint": "AAAA:BBBB"}))
        await pilot.pause()
        assert shell.screen.query_one("#device-fingerprint")
        shell.pop_screen()
        await shell.push_screen(PromotionReviewScreen([{"proposal_id": "p1", "author": "member", "text": "Reviewed memory"}]))
        await pilot.pause()
        assert shell.screen.query_one("#promotion-table")


@pytest.mark.asyncio
async def test_continuous_audit_skips_unchanged_source_contents(tmp_path):
    source_path = tmp_path / "memory.md"
    source_path.write_text("No secrets here.", encoding="utf-8")

    class FakeMemory:
        home = tmp_path
        config = None

        def __init__(self):
            self.preview_calls = 0

        def preview(self):
            self.preview_calls += 1
            return [MemoryEntry("fake", "global:fake", "Memory", source_path.read_text(encoding="utf-8"), str(source_path))]

        def sources(self, *, live_preview=False):
            assert live_preview is False
            return [{"path": str(source_path)}]

    memory = FakeMemory()
    backend = TuiBackend(memory_factory=lambda: memory)
    backend.memory = memory
    backend.ready = True
    first = await backend.audit_if_changed()
    second = await backend.audit_if_changed()
    source_path.write_text("Still no secrets, but changed.", encoding="utf-8")
    third = await backend.audit_if_changed()

    assert first is not None
    assert second is None
    assert third is not None
    assert memory.preview_calls == 2


@pytest.mark.asyncio
async def test_hook_status_reports_user_and_project_recall_and_capture(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (project / ".codex").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        '{"hooks":{"SessionStart":[{"hooks":[{"command":"docmancer memory hook-context --agent claude-code"}]}]}}',
        encoding="utf-8",
    )
    (project / ".codex" / "hooks.json").write_text(
        '{"hooks":{"Stop":[{"hooks":[{"command":"docmancer memory capture-hook --agent codex"}]}]}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    backend = TuiBackend(project_path=project)
    rows = await backend.hook_status()
    by_key = {(row["agent"], row["scope"]): row for row in rows}

    assert by_key[("claude-code", "user")]["recall"] is True
    assert by_key[("claude-code", "user")]["events"] == ["SessionStart"]
    assert by_key[("codex", "project")]["capture"] is True
    assert by_key[("codex", "project")]["events"] == ["Stop"]


def test_hook_status_ui_collapses_scopes_into_effective_agent_coverage():
    rows = DocmancerTuiApp._effective_hook_rows(
        [
            {
                "agent": "claude-code",
                "scope": "user",
                "path": "/tmp/.claude/settings.json",
                "exists": True,
                "recall": True,
                "capture": False,
                "events": ["SessionStart"],
                "error": None,
            },
            {
                "agent": "claude-code",
                "scope": "project",
                "path": "/tmp/project/.claude/settings.json",
                "exists": False,
                "recall": False,
                "capture": False,
                "events": [],
                "error": None,
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["agent"] == "claude-code"
    assert rows[0]["context_coverage"] == "all projects"
    assert rows[0]["capture_coverage"] == "off"
    assert rows[0]["paths"] == ["/tmp/.claude/settings.json"]


class NarrowSearchBackend(FakeBackend):
    """Search hits only a couple of files, so the first match is not row 0 of the browse page."""

    async def search_memory_sources(self, text, *, kinds, page=1, page_size=50, **kwargs):
        data = await super().search_memory_sources(text, kinds=kinds, page=page, page_size=page_size, **kwargs)
        data["items"] = data["items"][3:5]
        data["has_more"] = False
        return data


@pytest.mark.asyncio
async def test_tui_search_inspects_first_match_after_a_previous_selection():
    """Rebuilding the result list must not leave a previously listed file in the inspector."""
    app = DocmancerTuiApp(backend=NarrowSearchBackend())
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        await app.switch_mode("sources")
        result_list = app.query_one("#result-list", ResultList)
        inspector = app.query_one("#inspector", Inspector)

        result_list.index = 7
        await pilot.pause()
        assert (inspector.document or {}).get("source_key") == "src-agent-memory-7"

        app.query_one("#command-input").focus()
        await pilot.pause()
        for character in "Railway":
            await pilot.press(character)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert app.results, "the search should return matches"
        expected = app.results[0]["source"]["source_key"]
        assert (inspector.document or {}).get("source_key") == expected
        assert result_list.index == 0
        assert result_list.selected_result is app.results[0]


async def _confirmed():
    return True
