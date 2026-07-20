"""Textual application for browsing and curating local Docmancer data."""
from __future__ import annotations

import webbrowser
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from textual import events
from textual.app import App
from textual.binding import Binding
from textual.widgets import Button, Input, ListView, OptionList, Select, Static, Tab, Tabs
from textual.widgets.option_list import Option

from docmancer.memory import SyncInProgressError
from docmancer.tui.backend import TuiBackend
from docmancer.tui.commands import default_registry
from docmancer.tui.screens.audit import AuditScreen
from docmancer.tui.screens.cloud import CloudListScreen, ConflictResolutionScreen, DeviceApprovalScreen, PromotionReviewScreen, RecoveryKeyScreen
from docmancer.tui.screens.consolidate import ConsolidateScreen
from docmancer.tui.screens.detail import ConfirmScreen, CreateSourceScreen, DetailScreen, EditScreen, SourceViewerScreen
from docmancer.tui.screens.help import HelpScreen
from docmancer.tui.screens.main import MainScreen, StartupScreen
from docmancer.tui.screens.sources import SourcesScreen
from docmancer.tui.screens.sync import SyncScreen
from docmancer.tui.screens.settings import SettingsScreen
from docmancer.tui.widgets import FilterPane, Inspector, ResultList, StatusBar
from docmancer.tui.widgets.inspector import render_result
from docmancer.tui.presentation import context_display_name, context_scope_label


class DocmancerTuiApp(App):
    """Local memory and documentation explorer."""

    CSS_PATH = "styles.tcss"
    TITLE = "docmancer"
    SUB_TITLE = "local memory explorer"
    SCREENS = {"main": MainScreen}
    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("ctrl+k", "command_palette", "Commands"),
        Binding("ctrl+s", "sources", "Sources"),
        Binding("ctrl+r", "repeat_query", "Repeat query"),
        Binding("alt+left", "previous_page", "Previous page"),
        Binding("alt+right", "next_page", "Next page"),
        Binding("ctrl+c", "request_quit", "Quit", priority=True),
        Binding("v", "view_selected", "View file"),
        Binding("[", "previous_match", "Previous match"),
        Binding("]", "next_match", "Next match"),
        Binding("n", "new_source", "New file"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete file"),
        Binding("f", "forget_selected", "Forget"),
        Binding("p", "promote_selected", "Promote"),
        Binding("c", "copy_selected", "Copy"),
        Binding("o", "open_source", "Open source"),
        Binding("x", "expand_page", "Expand page"),
    ]

    def __init__(
        self,
        *,
        config_path: str | None = None,
        backend: TuiBackend | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend or TuiBackend(config_path=config_path)
        self.registry = default_registry()
        self.mode = "context"
        self.retrieval_mode = "hybrid"
        self.project_path = self.backend.project_path
        self.results: list[dict] = []
        self.all_results: list[dict] = []
        self.source_rows: dict[str, list[dict]] = {
            "context": [], "sources": [], "audit": [], "docs": []
        }
        self.security_report: dict | None = None
        self.hook_rows: list[dict] = []
        self.last_query = ""
        self.current_page = 1
        self.page_size = 10
        self.total_pages = 1
        self.has_more = False
        self._quit_deadline = 0.0
        self._main_screen: MainScreen | None = None
        self._pending_query: tuple[str, str | None, str | None] | None = None
        self.cloud_label = "off"
        self.cloud_risk_count = 0
        self._inspection_generation = 0
        self.pending_consolidation_draft: str | None = None
        self._button_loading_tasks: set[asyncio.Task] = set()

    async def on_mount(self) -> None:
        await self.push_screen("main")
        self._main_screen = self.screen
        self._update_responsive(self.size.width)
        await self.push_screen(StartupScreen())
        self.run_worker(self._load_backend(), group="startup", exit_on_error=False)

    def query_one(self, selector, expect_type=None):
        """Query the active TUI screen rather than the empty App root screen."""
        base = self._main_screen or self.screen
        if expect_type is None:
            return base.query_one(selector)
        return base.query_one(selector, expect_type)

    async def _show_modal_wait(self, screen):
        """Push a result modal in a worker so its controls remain responsive."""
        worker = self.run_worker(
            self.push_screen_wait(screen),
            group="modal",
            exit_on_error=False,
        )
        return await worker.wait()

    async def _load_backend(self) -> None:
        self._update_status()
        try:
            counts = await self.backend.initialize()
            await self._refresh_sources()
            self._set_counts(counts)
            project_selector = self.query_one("#project-selector", Select)
            project_selector.set_options(
                [(f"Project: {Path(self.project_path).name}", self.project_path), ("All projects", "all")]
            )
            self.project_path = None
            project_selector.value = "all"
            self.query_one("#command-input", Input).focus()
            await self._load_context_page()
            await self._refresh_security_report()
            if self._pending_query is not None:
                query, mode, expand = self._pending_query
                self._pending_query = None
                await self.run_query(query, mode=mode, expand=expand)
            self._update_status()
            await self._refresh_cloud_status()
            self.set_interval(10, self._refresh_cloud_status)
            self.set_interval(60, self._continuous_cloud_audit)
        except Exception as exc:  # noqa: BLE001 - keep the shell usable and show the local error
            self.notify(f"Backend failed to load: {exc}", severity="error", timeout=8)
            self._update_status()
        finally:
            if isinstance(self.screen, StartupScreen):
                await self.pop_screen()

    async def reset_browse(self) -> None:
        """Clear transient search state and restore source-file browsing."""
        self.last_query = ""
        self.current_page = 1
        self.query_one("#filter-pane", FilterPane).reset()
        if self.mode == "sources":
            await self._load_source_page()
        elif self.mode == "context":
            await self._load_context_page()
        elif self.mode == "audit":
            await self._load_security_page()
        else:
            await self._load_docs_page()
        self.query_one("#command-input", Input).clear()
        self._hide_command_menu()

    async def _refresh_sources(self) -> None:
        memory_rows, docs_rows = await asyncio.gather(
            self.backend.memory_sources(live_preview=False),
            self.backend.docs_sources(),
        )
        context_rows = await self.backend.context() if hasattr(self.backend, "context") else []
        self.source_rows = {"context": context_rows, "sources": memory_rows, "audit": [], "docs": docs_rows}
        self.query_one("#filter-pane", FilterPane).set_mode(self.mode, self.source_rows[self.mode])

    def _set_counts(self, counts: dict) -> None:
        tabs = self.query_one("#mode-tabs", Tabs)
        tabs.query_one("#context", Tab).label = f"Context {counts.get('context', 0):,}"
        tabs.query_one("#sources", Tab).label = f"Sources {counts.get('sources', counts.get('memory', 0) + counts.get('instructions', 0)):,}"
        tabs.query_one("#audit", Tab).label = f"Audit {counts.get('audit', 0):,}"
        tabs.query_one("#docs", Tab).label = f"Docs {counts['docs']:,}"
        tabs.query_one("#docs", Tab).add_class("empty") if not counts["docs"] else tabs.query_one("#docs", Tab).remove_class("empty")

    def _source_kinds(self) -> tuple[str, ...]:
        return ("agent-memory", "docmancer-memory", "team-memory", "instructions", "rules")

    def _source_filter_args(self) -> dict:
        values = self.query_one("#filter-pane", FilterPane).values()
        updated_after = None
        if values["time"] != "any":
            updated_after = datetime.now(timezone.utc) - timedelta(days={"day": 1, "week": 7, "month": 30}[values["time"]])
        return {
            "kinds": self._source_kinds(),
            "harness": None if values["harness"] == "all" else values["harness"],
            "scope_kind": None if values["scope"] == "all" else values["scope"],
            "project_path": self.project_path,
            "updated_after": updated_after,
            "page": self.current_page,
            "page_size": self.page_size,
        }

    async def _load_source_page(self) -> None:
        if not self.backend.ready or self.mode != "sources":
            return
        title = "SOURCES"
        self.query_one("#results-title", Static).update("SEARCHING..." if self.last_query else "LOADING...")
        args = self._source_filter_args()
        if self.last_query:
            data = await self.backend.search_memory_sources(self.last_query, mode=self.retrieval_mode, **args)
            self.results = [dict(item, view_kind="source-match") for item in data["items"]]
            self.total_pages = self.current_page + (1 if data.get("has_more") else 0)
            self.has_more = bool(data.get("has_more"))
            count = f"page {self.current_page}" + ("  more" if self.has_more else "")
            title = "MATCHING SOURCES"
        else:
            data = await self.backend.browse_memory_sources(**args)
            self.current_page = int(data["page"])
            self.total_pages = int(data["total_pages"])
            self.has_more = self.current_page < self.total_pages
            self.results = [dict(item, view_kind="source") for item in data["items"]]
            start = 0 if not data["total"] else (self.current_page - 1) * self.page_size + 1
            end = min(int(data["total"]), self.current_page * self.page_size)
            count = f"{start}-{end} of {int(data['total']):,}"
        security_by_path = {
            str(row.get("path") or ""): row
            for row in self.source_rows.get("sources", [])
            if row.get("security_findings")
        }
        for result in self.results:
            source = result.get("source") if result.get("view_kind") == "source-match" else result
            warning = security_by_path.get(str(source.get("path") or ""))
            if warning:
                source["security_findings"] = warning["security_findings"]
                source["security_severity"] = warning.get("security_severity")
        display_start = (self.current_page - 1) * self.page_size
        self.results = [dict(row, display_number=display_start + offset + 1) for offset, row in enumerate(self.results)]
        self.all_results = list(self.results)
        self.query_one("#result-list", ResultList).set_results(self.results)
        self.query_one("#results-title", Static).update(f"{title}  {count}")
        self._update_pagination()
        inspector = self.query_one("#inspector", Inspector)
        if self.results:
            await self._inspect_result(self.results[0])
        else:
            message = "No matching files. Reset the filters or run `/reset`." if self.last_query else "No indexed files match these filters."
            inspector.clear(self.mode, message)

    async def _load_context_page(self) -> None:
        if not self.backend.ready:
            return
        rows = await self.backend.context() if hasattr(self.backend, "context") else []
        self.source_rows["context"] = rows
        self.query_one("#filter-pane", FilterPane).set_context_counts(rows)
        selected = self.query_one("#filter-pane", FilterPane).values()["harness"]
        if selected == "pending":
            rows = [row for row in rows if row.get("view_kind") == "context-proposal"]
        elif selected == "personal":
            rows = [
                row for row in rows
                if row.get("audience_kind") == "personal"
                or str(row.get("pack_id") or "").startswith("personal-")
            ]
        elif selected != "all":
            rows = [row for row in rows if str(row.get("pack_id") or "").startswith(selected)]
        if self.last_query:
            needle = self.last_query.casefold()
            rows = [row for row in rows if needle in str(row.get("text") or "").casefold()]
        order = {"context-proposal": 0, "context-pack": 1, "context-record": 2}
        rows.sort(key=lambda row: (order.get(str(row.get("view_kind") or ""), 9), str(row.get("pack_id") or "")))
        total = len(rows)
        self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, self.total_pages)
        start_index = (self.current_page - 1) * self.page_size
        page_rows = rows[start_index : start_index + self.page_size]
        self.has_more = self.current_page < self.total_pages
        self.results = [
            dict(row, display_number=start_index + index)
            for index, row in enumerate(page_rows, start=1)
        ]
        self.all_results = list(self.results)
        self.query_one("#result-list", ResultList).set_results(self.results)
        start = 0 if not total else start_index + 1
        end = min(total, start_index + len(page_rows))
        self.query_one("#results-title", Static).update(f"CONTEXT  {start}-{end} of {total:,}")
        self._update_pagination()
        inspector = self.query_one("#inspector", Inspector)
        if self.results:
            await self._inspect_result(self.results[0])
        else:
            inspector.clear("context", "# No matching context\n\nRun `/distill` to propose approved context from current evidence.")

    async def _load_docs_page(self) -> None:
        """Browse documentation roots when there is no section query."""
        filters = self.query_one("#filter-pane", FilterPane).values()
        rows = list(self.source_rows["docs"])
        if filters["harness"] != "all":
            rows = [row for row in rows if str(row.get("source") or "") == filters["harness"]]
        if filters["time"] != "any":
            cutoff = datetime.now(timezone.utc) - timedelta(days={"day": 1, "week": 7, "month": 30}[filters["time"]])
            rows = [row for row in rows if self._timestamp(row) is not None and self._timestamp(row) >= cutoff]
        total = len(rows)
        self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, self.total_pages)
        start_index = (self.current_page - 1) * self.page_size
        page_rows = rows[start_index : start_index + self.page_size]
        self.has_more = self.current_page < self.total_pages
        self.results = [dict(row, view_kind="docs-source") for row in page_rows]
        self.all_results = list(self.results)
        self.query_one("#result-list", ResultList).set_results(self.results)
        start = 0 if not total else start_index + 1
        end = min(total, start_index + self.page_size)
        self.query_one("#results-title", Static).update(f"DOCUMENTATION SOURCES  {start}-{end} of {total:,}")
        self._update_pagination()
        inspector = self.query_one("#inspector", Inspector)
        if self.results:
            await self._inspect_result(self.results[0])
        else:
            inspector.clear(
                "docs",
                "# No documentation indexed\n\nIndex local documentation with `docmancer docs add ./docs`.\n\nAdd a documentation website with `docmancer docs add https://docs.example.com`.",
            )

    async def _refresh_security_report(self) -> None:
        """Run the local masked audit and update the Sources status badge."""
        try:
            self.security_report = await self.backend.audit()
        except Exception as exc:  # noqa: BLE001 - audit failure must not break browsing
            self.security_report = {"error": str(exc), "findings": [], "unique_secret_count": 0, "finding_count": 0}
        tabs = self.query_one("#mode-tabs", Tabs)
        source_tab = tabs.query_one("#sources", Tab)
        audit_tab = tabs.query_one("#audit", Tab)
        error = self.security_report.get("error")
        count = int(self.security_report.get("unique_secret_count") or 0)
        findings_by_path: dict[str, list[dict]] = {}
        for finding in self.security_report.get("findings") or []:
            for occurrence in finding.get("occurrences") or []:
                findings_by_path.setdefault(str(occurrence.get("source_path") or ""), []).append(finding)
        for source in self.source_rows.get("sources", []):
            findings = findings_by_path.get(str(source.get("path") or ""), [])
            source["security_findings"] = len(findings)
            source["security_severity"] = (findings[0].get("severity") if findings else None)
        base_count = len(self.source_rows.get("sources", []))
        source_tab.label = f"Sources {base_count:,} !" if error or count else f"Sources {base_count:,} ✓"
        source_tab.set_class(bool(count or error), "risk")
        audit_tab.label = f"Audit {count:,} !" if error or count else "Audit 0 ✓"
        audit_tab.set_class(bool(count or error), "risk")

    async def _load_security_page(self) -> None:
        report = self.security_report or {"findings": [], "unique_secret_count": 0, "finding_count": 0}
        findings = list(report.get("findings") or [])
        raw_hooks = await self.backend.hook_status() if hasattr(self.backend, "hook_status") else []
        hooks = self._effective_hook_rows(raw_hooks)
        self.hook_rows = hooks
        self.query_one("#filter-pane", FilterPane).set_audit_hooks(hooks)
        selected_view = self.query_one("#filter-pane", FilterPane).values()["harness"]
        if selected_view != "all":
            severity = selected_view
            findings = [item for item in findings if item.get("severity") == severity]
        if self.last_query:
            query = self.last_query.casefold()
            findings = [
                item
                for item in findings
                if query
                in " ".join(
                    [
                        str(item.get("type") or ""),
                        str(item.get("severity") or ""),
                        *[
                            " ".join(
                                str(occurrence.get(key) or "")
                                for key in ("source_path", "agent", "scope", "title", "masked_excerpt")
                            )
                            for occurrence in (item.get("occurrences") or [])
                        ],
                    ]
                ).casefold()
            ]
        combined = [dict(item, view_kind="security-finding") for item in findings]
        total = len(combined)
        self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, self.total_pages)
        start_index = (self.current_page - 1) * self.page_size
        page_rows = combined[start_index : start_index + self.page_size]
        self.has_more = self.current_page < self.total_pages
        self.results = page_rows
        self.all_results = list(self.results)
        self.query_one("#result-list", ResultList).set_results(self.results)
        start = 0 if not total else start_index + 1
        end = min(total, start_index + self.page_size)
        self.query_one("#results-title", Static).update(f"SECURITY FINDINGS  {start}-{end} of {total:,}")
        self._update_pagination()
        inspector = self.query_one("#inspector", Inspector)
        if self.results:
            await self._inspect_result(self.results[0])
        else:
            inspector.show_security_summary(report)

    @staticmethod
    def _effective_hook_rows(rows: list[dict]) -> list[dict]:
        """Collapse hook scopes into one understandable coverage row per agent."""
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("agent") or "agent"), []).append(row)

        summaries = []
        for agent in sorted(grouped, key=lambda value: (value != "claude-code", value != "codex", value)):
            agent_rows = grouped[agent]
            user = next((row for row in agent_rows if row.get("scope") == "user"), None)
            project = next((row for row in agent_rows if row.get("scope") == "project"), None)
            user_context = bool(user and user.get("recall"))
            project_context = bool(project and project.get("recall"))
            user_capture = bool(user and user.get("capture"))
            project_capture = bool(project and project.get("capture"))
            context_coverage = "all projects" if user_context else "this project" if project_context else "off"
            capture_coverage = "all projects" if user_capture else "this project" if project_capture else "off"
            context_row = user if user_context else project if project_context else user or project or {}
            configured_rows = [
                row for row in agent_rows
                if row.get("recall") or row.get("capture") or row.get("exists") or row.get("error")
            ]
            summaries.append(
                {
                    "agent": agent,
                    "scope": context_coverage,
                    "context_coverage": context_coverage,
                    "capture_coverage": capture_coverage,
                    "recall": user_context or project_context,
                    "capture": user_capture or project_capture,
                    "events": sorted(
                        {
                            str(event)
                            for row in configured_rows
                            for event in (row.get("events") or [])
                        }
                    ),
                    "path": str(context_row.get("path") or ""),
                    "paths": [str(row.get("path")) for row in configured_rows if row.get("path")],
                    "project_override": project_context and user_context,
                    "error": "; ".join(str(row.get("error")) for row in agent_rows if row.get("error")),
                }
            )
        return summaries

    async def _load_intelligence_page(self) -> None:
        view = self.query_one("#filter-pane", FilterPane).values()["harness"]
        if view not in {"review", "recent", "maintenance", "history"}:
            view = "review"
        try:
            data = await self.backend.memory_intelligence(
                view=view,
                project_path=self.project_path,
                query=self.last_query or None,
                page=self.current_page,
                page_size=self.page_size,
            )
        except sqlite3.OperationalError as exc:
            detail = str(exc).casefold()
            if "locked" in detail or "busy" in detail:
                message = (
                    "Memory intelligence is temporarily unavailable while another Docmancer "
                    "process updates the index. Wait for sync to finish, then reopen this tab."
                )
            else:
                message = f"Memory intelligence is temporarily unavailable: {exc}"
            self.results = []
            self.all_results = []
            self.current_page = 1
            self.total_pages = 1
            self.has_more = False
            self.query_one("#result-list", ResultList).set_results([])
            self.query_one("#results-title", Static).update("MEMORY INTELLIGENCE  temporarily unavailable")
            self._update_pagination()
            self.query_one("#inspector", Inspector).clear("intelligence", message)
            self.notify(message, severity="warning", timeout=8)
            return
        rows = list(data["items"])
        total = int(data["total"])
        self.current_page = int(data["page"])
        self.total_pages = int(data["total_pages"])
        start_index = (self.current_page - 1) * self.page_size
        self.results = [dict(row, display_number=start_index + offset + 1) for offset, row in enumerate(rows)]
        self.all_results = list(self.results)
        self.has_more = bool(data["has_more"])
        self.query_one("#result-list", ResultList).set_results(self.results)
        start = 0 if not total else start_index + 1
        end = min(total, start_index + len(self.results))
        titles = {
            "review": "NEEDS REVIEW",
            "recent": "RECENT CHANGES",
            "maintenance": "MEMORY MAINTENANCE",
            "history": "REVIEW HISTORY",
        }
        self.query_one("#results-title", Static).update(f"{titles[view]}  {start}-{end} of {total:,}")
        self._update_pagination()
        inspector = self.query_one("#inspector", Inspector)
        if self.results:
            inspector.show_intelligence(self.results[0])
        else:
            empty = {
                "review": "Nothing needs review. Docmancer found no precise conflicting claims.",
                "recent": "No memory changes were recorded in the past seven days.",
                "maintenance": "No durable unconnected memories need maintenance.",
                "history": "No reviewed conflicts or deterministic revisions are recorded.",
            }
            inspector.clear("intelligence", empty[view])

    def _update_pagination(self) -> None:
        self.query_one("#previous-page", Button).disabled = self.current_page <= 1
        self.query_one("#next-page", Button).disabled = not self.has_more
        suffix = "+" if self.last_query and self.has_more else ""
        self.query_one("#page-label", Static).update(f"Page {self.current_page} of {self.total_pages}{suffix}")

    def _update_status(self) -> None:
        self.query_one("#status-bar", StatusBar).set_status(
            mode=self.retrieval_mode,
            model=getattr(self.backend, "model_label", "local"),
            latency=self.backend.last_latency,
            ready=self.backend.ready,
            cloud=self.cloud_label,
        )

    async def _refresh_cloud_status(self) -> None:
        if not self.backend.ready:
            return
        try:
            value = await self.backend.cloud_status()
            if not value.get("configured"):
                self.cloud_label = "off"
            elif value.get("entitlement") not in {"active", "trial", "grace", "unknown"}:
                self.cloud_label = "paused"
            elif value.get("conflicts"):
                self.cloud_label = f"{value['conflicts']} conflict(s)"
            elif value.get("pending"):
                self.cloud_label = f"{value['pending']} queued"
            else:
                self.cloud_label = "synced"
        except Exception:  # noqa: BLE001 - footer state must never disrupt the explorer
            self.cloud_label = "offline"
        self._update_status()

    async def _continuous_cloud_audit(self) -> None:
        """Paid cross-machine monitoring reuses the local masked audit shape."""
        try:
            status = await self.backend.cloud_status()
            if not status.get("configured") or not status.get("continuous_audit") or status.get("entitlement") not in {"active", "trial", "grace"}:
                return
            metadata = await self.backend.cloud_report_audit()
            if metadata is None:
                return
            self.cloud_risk_count = int(metadata.get("total") or 0)
        except Exception:  # noqa: BLE001 - monitoring cannot disturb local TUI work
            return

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        if not line:
            await self.reset_browse()
            self.notify("Search and filters reset.")
            return
        event.input.clear()
        self._hide_command_menu()
        if line.startswith("/"):
            self.run_worker(
                self.registry.dispatch(self, line),
                group="slash-command",
                exit_on_error=False,
            )
        else:
            await self.run_query(line)

    async def run_query(self, query: str, *, mode: str | None = None, expand: str | None = None) -> None:
        if not self.backend.ready:
            self._pending_query = (query, mode, expand)
            self.notify("The local indexes are still loading. Your query is queued.", severity="warning")
            return
        if mode is not None:
            await self.switch_mode(mode)
        self.last_query = query
        self.current_page = 1
        self.query_one("#results-title", Static).update("SEARCHING...")
        try:
            if self.mode == "sources":
                await self._load_source_page()
            elif self.mode == "audit":
                await self._load_security_page()
            elif self.mode == "docs":
                self.all_results = await self.backend.query_docs(query, expand=expand)
                self._apply_docs_filters()
            else:
                await self._load_context_page()
            self._update_status()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
            self.query_one("#results-title", Static).update("SOURCES" if self.mode == "sources" else "MATCHING SECTIONS")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command-input":
            return
        value = event.value
        if not value.startswith("/") or any(character.isspace() for character in value):
            self._hide_command_menu()
            return
        prefix = value[1:].casefold()
        specs = [spec for spec in self.registry.commands if spec.name.startswith(prefix)]
        menu = self.query_one("#command-menu", OptionList)
        menu.set_options(
            [Option(f"{spec.usage}  [dim]{spec.description}[/dim]", id=spec.name) for spec in specs]
        )
        menu.set_class(bool(specs), "visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "command-menu" or not event.option.id:
            return
        spec = next((item for item in self.registry.commands if item.name == event.option.id), None)
        if spec is None:
            return
        input_widget = self.query_one("#command-input", Input)
        input_widget.value = f"/{spec.name}" + (" " if spec.usage != f"/{spec.name}" else "")
        input_widget.focus()
        input_widget.cursor_position = len(input_widget.value)
        self._hide_command_menu()

    def _hide_command_menu(self) -> None:
        self.query_one("#command-menu", OptionList).remove_class("visible")

    def _apply_docs_filters(self) -> None:
        filters = self.query_one("#filter-pane", FilterPane).values()
        results = list(self.all_results)
        if filters["harness"] != "all":
            results = [item for item in results if str(item.get("source") or "").startswith(filters["harness"])]
        if filters["time"] != "any":
            days = {"day": 1, "week": 7, "month": 30}[filters["time"]]
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            results = [item for item in results if self._timestamp(item) is not None and self._timestamp(item) >= cutoff]
        self.results = results
        self.query_one("#result-list", ResultList).set_results(results)
        title = "MATCHING SECTIONS"
        count = f"{len(results)}" if len(results) == len(self.all_results) else f"{len(results)} / {len(self.all_results)}"
        self.query_one("#results-title", Static).update(f"{title}  {count}")
        inspector = self.query_one("#inspector", Inspector)
        inspector.show_docs_result(results[0] if results else None)
        if not results:
            inspector.clear("docs", "# No documentation matches\n\nReset the filters or run `/reset`.")

    @staticmethod
    def _timestamp(item: dict) -> datetime | None:
        raw = (
            item.get("updated_at")
            or item.get("timestamp")
            or item.get("ingested_at")
            or (item.get("metadata") or {}).get("timestamp")
            or (item.get("metadata") or {}).get("updated_at")
            or (item.get("metadata") or {}).get("ingested_at")
        )
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    async def switch_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        tabs = self.query_one("#mode-tabs", Tabs)
        tabs.active = mode
        self.all_results = []
        self.results = []
        self.last_query = ""
        self.current_page = 1
        self.total_pages = 1
        self.has_more = False
        self.query_one("#filter-pane", FilterPane).set_mode(mode, self.source_rows[mode])
        self.query_one("#result-list", ResultList).set_results([])
        titles = {"context": "CONTEXT", "sources": "SOURCES", "audit": "AUDIT", "docs": "DOCUMENTATION SOURCES"}
        self.query_one("#results-title", Static).update(titles[mode])
        input_widget = self.query_one("#command-input", Input)
        noun = {
            "context": "context and pending review",
            "sources": "agent memory, instructions, rules, and provenance",
            "audit": "security findings and automatic context coverage",
            "docs": "indexed documentation",
        }[mode]
        input_widget.placeholder = f"Search {noun} or type / for commands..."
        if mode == "sources":
            await self._load_source_page()
        elif mode == "audit":
            await self._load_security_page()
        elif mode == "docs":
            await self._load_docs_page()
        else:
            await self._load_context_page()

    async def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        if event.tab.id != self.query_one("#mode-tabs", Tabs).active:
            return
        if event.tab.id in {"context", "sources", "audit", "docs"}:
            await self.switch_mode(event.tab.id)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        if event.select.id != "project-selector" or event.value == "loading":
            return
        if event.value == "all":
            self.project_path = None
        elif isinstance(event.value, str):
            self.project_path = event.value
        self.backend.project_path = self.project_path or str(Path.cwd().resolve())
        if self.mode == "sources":
            self.current_page = 1
            await self._load_source_page()
        elif self.mode == "context":
            await self._load_context_page()
        elif self.mode == "audit":
            await self._load_security_page()

    async def on_filter_pane_changed(self) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        self.current_page = 1
        if self.mode == "sources":
            await self._load_source_page()
        elif self.mode == "context":
            await self._load_context_page()
        elif self.mode == "audit":
            await self._load_security_page()
        elif self.last_query:
            self._apply_docs_filters()
        else:
            await self._load_docs_page()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        item = getattr(event.item, "result", None)
        if item is None:
            return
        # Rebuilding the list queues highlight events for the rows it just replaced.
        # Those arrive after the caller already inspected the new first result, so
        # honouring them would put a file from the previous page in the inspector.
        if not any(item is result for result in self.results):
            return
        await self._inspect_result(item)

    async def _inspect_result(self, item: dict) -> None:
        self._inspection_generation += 1
        generation = self._inspection_generation
        inspector = self.query_one("#inspector", Inspector)
        if self.mode == "docs":
            if item.get("view_kind") in {"source", "source-match"}:
                return
            if item.get("view_kind") == "docs-source":
                document = await self.backend.get_docs_source(str(item.get("source") or ""))
                if generation != self._inspection_generation:
                    return
                inspector.show_docs_source(item, document)
            else:
                inspector.show_docs_result(item)
            return
        if self.mode == "context":
            inspector.show_context(item, self._context_detail(item))
            return
        if item.get("view_kind") == "security-finding":
            inspector.show_security_finding(item)
            return
        if item.get("view_kind") == "hook-status":
            inspector.show_hook_status(item)
            return
        if item.get("view_kind") == "docs-source":
            return
        source = item.get("source") if item.get("view_kind") == "source-match" else item
        document = await self.backend.get_memory_source(str(source.get("source_key") or ""))
        if generation != self._inspection_generation:
            return
        if document is None:
            inspector.clear(self.mode, "The indexed source snapshot is unavailable. Run `/sync` to rebuild it.")
            return
        matches = item.get("matches") if item.get("view_kind") == "source-match" else None
        inspector.show_source(document, matches)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = getattr(event.item, "result", None)
        if item is not None:
            await self._inspect_result(item)

    async def on_result_list_open_requested(self, event: ResultList.OpenRequested) -> None:
        if self.mode == "docs":
            await self.push_screen(DetailScreen("Document detail", render_result(event.result)))
        elif self.mode == "context":
            inspector = self.query_one("#inspector", Inspector)
            inspector.show_context(event.result, self._context_detail(event.result))
            inspector.query_one("#inspector-markdown").focus()
        elif self.mode == "audit":
            await self._inspect_result(event.result)
        else:
            await self._open_source_viewer(event.result)

    @staticmethod
    def _context_detail(item: dict) -> str:
        if item.get("view_kind") == "context-record":
            return "\n".join(
                [
                    f"# {str(item.get('memory_type') or 'Context').title()}",
                    "",
                    str(item.get("text") or ""),
                    "",
                    f"- **Context:** {context_display_name(item.get('pack_id'), item.get('pack_name'))}",
                    f"- **Record:** `{item.get('record_id')}`",
                    f"- **Updated:** {item.get('updated_at') or 'unknown'}",
                    f"- **Origin:** {item.get('origin') or 'unknown'}",
                    f"- **Source:** `{item.get('source_path') or 'unknown'}`",
                ]
            )
        if item.get("view_kind") != "context-proposal":
            count = int(item.get("records") or 0)
            pending = int(item.get("pending") or 0)
            return "\n".join(
                [
                    f"# {context_display_name(item.get('pack_id'), item.get('name'))}",
                    "",
                    f"**{count:,} approved statement{'s' if count != 1 else ''}**"
                    + (f" and **{pending} pending proposal{'s' if pending != 1 else ''}**" if pending else ""),
                    "",
                    f"**{context_scope_label(item.get('audience_kind'), item.get('applicability_kind'))}**",
                    "",
                    (
                        "Approved statements are listed in the middle pane. Select one to read, edit, or remove it."
                        if count
                        else "There is no approved context here yet. Use Add or Distill to create it."
                    ),
                ]
            )
        if item.get("proposal_kind") == "cloud-conflict":
            return "\n".join(
                [
                    "# Cloud conflict",
                    "",
                    str(item.get("text") or "Encrypted sync revisions need review."),
                    "",
                    "Choose **APPROVE** to keep the remote revision or **REJECT** to keep the local revision.",
                ]
            )

        lines = [
            "# Pending review",
            "",
            f"- **Context:** {context_display_name(item.get('pack_id'), item.get('context_name'))}",
            f"- **Proposal:** `{item.get('proposal_id') or item.get('id') or 'unknown'}`",
        ]
        operations = list(item.get("operations") or [])
        for index, operation in enumerate(operations, start=1):
            action = str(operation.get("action") or "change").upper()
            lines.extend(["", f"## {index}. {action}", "", str(operation.get("text") or "No statement text.")])
            reason = str(operation.get("reason") or "").strip()
            if reason:
                lines.extend(["", f"**Why:** {reason}"])
            confidence = operation.get("confidence")
            if confidence is not None:
                lines.append(f"**Confidence:** {float(confidence):.0%}")
            source_paths = [str(path) for path in operation.get("source_paths") or [] if path]
            if source_paths:
                lines.extend(["", "**Sources:**", *[f"- `{path}`" for path in source_paths]])
        if not operations:
            lines.extend(["", str(item.get("text") or "No structured operations are available.")])
        lines.extend(["", "Choose **APPROVE** to activate these changes or **REJECT** to discard them."])
        return "\n".join(lines)

    async def _open_source_viewer(self, item: dict) -> None:
        source = item.get("source") if item.get("view_kind") == "source-match" else item
        document = await self.backend.get_memory_source(str(source.get("source_key") or ""))
        if document is not None:
            inspector = self.query_one("#inspector", Inspector)
            matches = item.get("matches") if item.get("view_kind") == "source-match" else document.get("atoms")
            await self.push_screen(SourceViewerScreen(document, matches or [], inspector.match_index))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Show immediate feedback and prevent duplicate button actions."""
        button = event.button
        if not button.is_attached or button.screen is not self._main_screen:
            return
        if button.loading:
            return
        button.loading = True
        worker = self.run_worker(
            self._handle_button_pressed(event),
            group="button-action",
            exit_on_error=False,
        )
        self._track_button_worker(button, worker)

    async def _handle_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "context-how-it-works":
            await self.push_screen(DetailScreen("How context works", self._canonical_context_help()))
            return
        if event.button.id in {"context-reset-personal", "context-reset-team"}:
            audience = "personal" if event.button.id.endswith("personal") else "team"
            message = (
                "Remove all approved personal defaults and current-project context? "
                "Docmancer will write tombstones, reject pending personal proposals, and keep the raw source corpus."
                if audience == "personal"
                else "Create review proposals to remove all approved team standards and team-project context? "
                "Team context is not deleted until those proposals are approved."
            )
            confirmed = await self._show_modal_wait(
                ConfirmScreen(
                    f"Reset {audience} context",
                    message,
                    confirm_label="Reset personal" if audience == "personal" else "Create proposals",
                )
            )
            if confirmed:
                await self._reset_context(audience)
            return
        if event.button.id == "audit-how-it-works":
            await self.push_screen(DetailScreen("How automatic context works", self._automatic_context_help()))
            return
        if event.button.id in {"audit-hook-claude-code", "audit-hook-codex"}:
            agent = str(event.button.id).removeprefix("audit-hook-")
            hook = next((row for row in self.hook_rows if row.get("agent") == agent), None)
            if hook is not None:
                self.query_one("#inspector", Inspector).show_hook_status(hook)
            return
        if self.mode == "context" and event.button.id in {"source-new", "source-edit", "source-delete", "source-forget", "source-promote"}:
            if event.button.id == "source-new":
                selected = self.selected_result or {}
                pack_id = str(selected.get("pack_id") or "personal-defaults")
                audience = str(selected.get("audience_kind") or "personal")
                title = (
                    "Propose team context"
                    if audience == "team"
                    else "Add project context"
                    if pack_id.startswith("personal-project")
                    else "Add personal context"
                )
                text = await self._show_modal_wait(EditScreen("new-context", "", title=title))
                if text and text.strip():
                    await self.command_add([text.strip()], pack_id=pack_id)
                return
            selected = self.selected_result or {}
            proposal_id = str(selected.get("proposal_id") or "")
            if selected.get("view_kind") == "context-record" and event.button.id in {"source-edit", "source-delete"}:
                if event.button.id == "source-edit":
                    await self._edit_context_record(selected)
                else:
                    await self._remove_context_record(selected)
                return
            if event.button.id in {"source-edit", "source-delete"}:
                if not proposal_id:
                    self.notify("Select a pending proposal first.", severity="warning")
                    return
                decision = "approve" if event.button.id == "source-edit" else "reject"
                await self.command_review([proposal_id, decision])
                return
            if event.button.id == "source-forget":
                await self.command_review([])
                return
            await self.command_share([str(selected.get("pack_id") or "personal-defaults")])
            return
        if event.button.id == "previous-page":
            await self.action_previous_page()
        elif event.button.id == "next-page":
            await self.action_next_page()
        elif event.button.id == "source-new":
            await self.command_new([])
        elif event.button.id == "source-edit":
            await self.command_edit([])
        elif event.button.id == "source-delete":
            await self.command_delete([])
        elif event.button.id == "source-forget":
            await self.command_forget([])
        elif event.button.id == "source-promote":
            await self.command_promote([])

    def _track_button_worker(self, button: Button, worker) -> None:
        """Keep a button busy until a background command worker finishes."""

        async def wait_and_clear() -> None:
            try:
                await worker.wait()
            except Exception:  # The command worker reports its own errors.
                pass
            finally:
                if button.is_attached:
                    button.loading = False

        task = asyncio.create_task(wait_and_clear())
        self._button_loading_tasks.add(task)
        task.add_done_callback(self._button_loading_tasks.discard)

    @staticmethod
    def _automatic_context_help() -> str:
        return """## The short version

Docmancer keeps a smaller set of approved context above the raw source corpus. Automatic context lets Claude Code or Codex receive the relevant parts when a session starts or when you submit a prompt.

## What the status means

- **All projects** means a user-level integration is installed and covers every project for that agent.
- **This project** means only the currently selected project has an integration.
- **Not connected** means automatic delivery is off. Manual `docmancer query` commands still work.

## What gets delivered

Docmancer sends task-relevant approved context, not the complete raw memory corpus. Project context overrides global defaults, and team context overrides personal context at the same level.

## New-memory capture

Capture is optional and separate from delivery. When enabled, completed sessions can propose new memories for review. Turning capture off does not stop approved context from reaching the agent.

## Privacy

Automatic context runs through local agent hooks. Managed projections and hook output are delivery mechanisms, not sources of truth."""

    @staticmethod
    def _canonical_context_help() -> str:
        return """## Sources versus context

Sources are the full evidence corpus harvested from agents, instructions, and rules. Approved context is the smaller set of statements that Docmancer delivers automatically.

## Your four context areas

- **Personal defaults** contains durable preferences that apply across projects.
- **Current project** contains project decisions and explicit exceptions.
- **Team standards** contains approved defaults shared by the team.
- **Team project** contains shared project context and exceptions.

## Distill

Distill proposes durable defaults and recurring evidence that are not already represented. It should not paginate through raw task history or re-propose an approved source atom. Nothing becomes active until you approve the proposal.

## Manage records

Select an individual statement in the middle pane to edit or remove it. Personal changes apply immediately. Team changes create review proposals.

## Reset

Reset Personal removes approved personal records, rejects pending personal proposals, and writes tombstones. Reset Team creates removal proposals because every team change requires approval. Raw sources remain untouched, so you can distill again later."""

    async def _reset_context(self, audience: str) -> None:
        await self._start_context_work(f"Resetting {audience} context...")
        try:
            result = await self.backend.reset_context(audience)
            proposals = list(result.get("proposals") or [])
            if proposals:
                self.notify(f"Created {len(proposals)} team reset proposal(s). Review them to finish the reset.")
            else:
                self.notify(
                    f"Removed {int(result.get('removed') or 0)} personal context record(s)"
                    f" and rejected {int(result.get('rejected_proposals') or 0)} pending proposal(s)."
                )
            await self._load_context_page()
            self._set_counts(await self.backend.counts())
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    async def _edit_context_record(self, record: dict) -> None:
        replacement = await self._show_modal_wait(
            EditScreen(
                str(record.get("record_id") or "context"),
                str(record.get("text") or ""),
                title="Edit canonical context",
            )
        )
        if replacement is None or not replacement.strip():
            return
        await self._start_context_work("Updating context...")
        try:
            result = await self.backend.edit_context(str(record.get("record_id") or ""), replacement.strip())
            if result.get("proposal"):
                self.notify("Created a team edit proposal for review.")
            else:
                self.notify("Updated personal context.")
            await self._load_context_page()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    async def _remove_context_record(self, record: dict) -> None:
        confirmed = await self._show_modal_wait(
            ConfirmScreen(
                "Remove canonical context",
                "Remove this approved statement? Personal context is tombstoned immediately. Team context creates a review proposal.",
                confirm_label="Remove",
            )
        )
        if not confirmed:
            return
        await self._start_context_work("Removing context...")
        try:
            result = await self.backend.remove_context(str(record.get("record_id") or ""))
            if result.get("proposal"):
                self.notify("Created a team removal proposal for review.")
            else:
                self.notify("Removed context and wrote a tombstone.")
            await self._load_context_page()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    def on_resize(self, event: events.Resize) -> None:
        self._update_responsive(event.size.width)

    def _update_responsive(self, width: int) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        self._main_screen.set_class(width < 120, "compact")
        self._main_screen.set_class(width < 90, "narrow")

    @property
    def selected_result(self) -> dict | None:
        return self.query_one("#result-list", ResultList).selected_result

    async def command_memory(self, args: list[str]) -> None:
        if not args:
            await self.switch_mode("memory")
            return
        await self.run_query(" ".join(args), mode="memory")

    async def command_instructions(self, args: list[str]) -> None:
        if not args:
            await self.switch_mode("instructions")
            return
        await self.run_query(" ".join(args), mode="instructions")

    async def command_docs(self, args: list[str]) -> None:
        if not args:
            await self.switch_mode("docs")
            return
        await self.run_query(" ".join(args), mode="docs")

    async def command_security(self, args: list[str]) -> None:
        await self.switch_mode("audit")
        if args:
            await self.run_query(" ".join(args), mode="audit")

    async def command_intelligence(self, args: list[str]) -> None:
        await self.switch_mode("intelligence")
        if args:
            self.last_query = " ".join(args)
            await self._load_intelligence_page()

    async def command_recent(self, args: list[str]) -> None:
        from docmancer.cli.memory_commands import _parse_recap_time

        try:
            since = _parse_recap_time(args[0] if args else "7d")
            rows = await self.backend.memory_recent(since)
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error")
            return
        lines = ["# Recent memory activity", ""]
        for row in rows:
            reference = f"docmancer://record/{row['record_id']}" if row.get("record_id") else row.get("atom_id")
            lines.append(f"- **{str(row['activity_at'])[:16]}** `{row['harness']}` `{reference}`")
            lines.append(f"  {row['text']}")
        if not rows:
            lines.append("No memory activity matched this time window.")
        await self.push_screen(DetailScreen("Recent memory", "\n".join(lines)))

    async def command_consolidate(self, args: list[str]) -> None:
        confirmed = await self._show_modal_wait(
            ConfirmScreen(
                "Consolidate memory",
                "This sends privacy-redacted memory text to the configured OpenRouter model. The result is review-only until you apply it.",
                confirm_label="Send and consolidate",
            )
        )
        if not confirmed:
            return
        screen = ConsolidateScreen()
        await self.push_screen(screen)

        def progress(name: str, data: dict) -> None:
            try:
                self.call_from_thread(screen.update_event, name, data)
            except RuntimeError:
                screen.update_event(name, data)

        try:
            self.pending_consolidation_draft = await self.backend.consolidate(" ".join(args) or None, progress)
            screen.finish("Draft complete. Close this window, review it, then run /apply <agent>.")
            await self.push_screen(DetailScreen("Consolidated draft", self.pending_consolidation_draft))
        except Exception as exc:  # noqa: BLE001
            screen.finish(f"Consolidation failed: {exc}")
            self.notify(str(exc), severity="error", timeout=8)

    async def command_apply(self, args: list[str]) -> None:
        agent = args[0].lower() if args else "codex"
        confirmed = await self._show_modal_wait(
            ConfirmScreen(
                "Apply reviewed memory",
                f"Write Docmancer's managed memory block to the {agent} always-loaded file? Existing content outside the block is preserved.",
                confirm_label="Apply",
            )
        )
        if not confirmed:
            return
        try:
            target = await self.backend.apply_memory(agent, self.pending_consolidation_draft)
            self.notify(f"Applied reviewed memory to {target}.")
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)

    async def command_settings(self, _args: list[str]) -> None:
        enabled = await self.backend.capture_settings()
        value = await self._show_modal_wait(SettingsScreen(enabled))
        if value is None:
            return
        try:
            path = await self.backend.save_capture_settings(value)
            self.notify(f"Saved capture settings to {path}.")
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error")

    async def command_ingest(self, args: list[str]) -> None:
        if not args:
            self.notify("Usage: /ingest <path-or-url>", severity="warning")
            return
        screen = ConsolidateScreen("Documentation ingest")
        await self.push_screen(screen)

        def progress(name: str, data: dict) -> None:
            screen.update_event(name, data)

        try:
            total = await self.backend.ingest_docs(args[0], progress)
            await self._refresh_sources()
            self._set_counts(await self.backend.counts())
            screen.finish(f"Indexed {total} document section(s).")
            await self.switch_mode("docs")
        except Exception as exc:  # noqa: BLE001
            screen.finish(f"Ingest failed: {exc}")
            self.notify(str(exc), severity="error", timeout=8)

    async def command_resolve(self, args: list[str]) -> None:
        selected = self.selected_result
        selected_group = selected if selected and selected.get("intelligence_kind") == "conflict-group" else None
        group_syntax = bool(selected_group and args and args[0] in {"choose", "keep-both", "dismiss"})
        if group_syntax:
            relation_ids = list(selected_group.get("relation_ids") or [])
            relation_id = str(selected_group.get("group_id") or "selected claim")
            resolution = args[0]
            winner = args[1] if len(args) > 1 else None
        else:
            if len(args) < 2 or args[1] not in {"choose", "keep-both", "dismiss"}:
                usage = (
                    "Select a claim, then use /resolve choose <memory-id>, /resolve keep-both, or /resolve dismiss."
                    if selected_group
                    else "Usage: /resolve <relation-id> choose|keep-both|dismiss [winner-id]"
                )
                self.notify(usage, severity="warning")
                return
            relation_id, resolution = args[0], args[1]
            relation_ids = []
            winner = args[2] if len(args) > 2 else None
        if resolution == "choose" and not winner:
            self.notify("A winner memory ID is required with choose.", severity="warning")
            return
        confirmed = await self._show_modal_wait(
            ConfirmScreen(
                "Resolve memory conflict",
                f"Apply {resolution} to {relation_id}? This review decision persists across syncs.",
                confirm_label="Resolve",
            )
        )
        if not confirmed:
            return
        try:
            if group_syntax:
                await self.backend.resolve_memory_conflict_group(relation_ids, resolution, winner=winner)
            else:
                await self.backend.resolve_memory_conflict(relation_id, resolution, winner=winner)
            self._set_counts(await self.backend.counts())
            await self.switch_mode("intelligence")
            await self._load_intelligence_page()
            self.notify(f"Resolved {relation_id}.")
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        if args:
            await self.run_query(" ".join(args), mode="audit")

    async def command_sync(self, _args: list[str]) -> None:
        screen = SyncScreen()
        await self.push_screen(screen)
        await screen.wait_for_refresh()

        def progress(stage: str, detail: str = "") -> None:
            try:
                self.call_from_thread(screen.update_stage, stage, detail)
            except RuntimeError:
                screen.update_stage(stage, detail)

        try:
            await self.backend.sync(progress)
            counts = await self.backend.counts()
            self._set_counts(counts)
            await self._refresh_sources()
            await self._refresh_security_report()
            if self.mode == "sources":
                await self._load_source_page()
            elif self.mode == "context":
                await self._load_context_page()
        except SyncInProgressError as exc:
            screen.finish_with_error(str(exc))
            self.notify(str(exc), severity="warning")
        except Exception as exc:  # noqa: BLE001
            screen.finish_with_error(str(exc))
            self.notify(str(exc), severity="error")

    async def command_sources(self, _args: list[str]) -> None:
        rows = await (self.backend.docs_sources() if self.mode == "docs" else self.backend.memory_sources(live_preview=True))
        await self.push_screen(SourcesScreen(rows, mode="docs" if self.mode == "docs" else "memory"))

    async def command_status(self, _args: list[str]) -> None:
        status = await self.backend.status()
        body = (
            f"# Local status\n\n**Project:** `{status['project']}`\n\n"
            f"**Memory index:** {status['memory'].get('atoms', 0)} atoms across {status['memory'].get('sources', 0)} source files\n\n"
            f"**Docs:** {status['docs'].get('sections_count', 0)} sections\n\n"
            f"**Context:** {status.get('context', {}).get('packs', 0)} areas with {status.get('context', {}).get('pending_reviews', 0)} pending review\n\n"
            f"**Memory DB:** `{status['memory'].get('db_path')}`"
        )
        await self.push_screen(DetailScreen("Status", body))

    async def command_audit(self, _args: list[str]) -> None:
        await self._refresh_security_report()
        await self.push_screen(AuditScreen(self.security_report or {}))

    async def command_cloud(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        if action == "status":
            value = await self.backend.cloud_status()
            body = "# Encrypted cloud sync\n\n" + "\n\n".join(
                f"**{key.replace('_', ' ').title()}:** `{item if item is not None else '-'}`"
                for key, item in value.items()
            )
            await self.push_screen(DetailScreen("Cloud status", body))
        elif action == "sync":
            try:
                value = await self.backend.cloud_sync()
                self.notify(f"Cloud sync complete: {value.get('pushed', 0)} pushed, {value.get('applied', 0)} applied")
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
            await self._refresh_cloud_status()
        elif action == "conflicts":
            try:
                rows = await self.backend.cloud_conflicts()
                if not rows:
                    self.notify("No unresolved conflicts.")
                else:
                    resolution = await self._show_modal_wait(ConflictResolutionScreen(rows))
                    if resolution:
                        await self.backend.cloud_resolve(*resolution)
                        self.notify(f"Conflict {resolution[0]} resolved with a merge revision.")
                        await self._refresh_cloud_status()
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
        elif action == "devices":
            try:
                rows = await self.backend.cloud_devices()
                pending = next((row for row in rows if not row.get("approved")), None)
                if pending:
                    approval = await self._show_modal_wait(DeviceApprovalScreen(pending))
                    if approval:
                        await self.backend.cloud_approve_device(*approval)
                        self.notify(f"Approved device {approval[0]} after fingerprint confirmation.")
                    else:
                        self.notify("Device was not approved. The fingerprint must match exactly.", severity="warning")
                else:
                    await self.push_screen(CloudListScreen("Cloud devices", rows, ("device_id", "state", "fingerprint")))
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
        elif action == "recovery":
            key = await self._show_modal_wait(RecoveryKeyScreen())
            if key:
                try:
                    await self.backend.cloud_verify_recovery(key)
                    self.notify("Recovery key verified.")
                except Exception as exc:  # noqa: BLE001
                    self.notify(str(exc), severity="error", timeout=8)
        elif action == "audit":
            await self.push_screen(AuditScreen(await self.backend.audit()))
        else:
            self.notify("Usage: /cloud status|sync|conflicts|devices|recovery|audit", severity="warning")

    async def _start_context_work(self, label: str) -> None:
        if self.mode == "context":
            self.query_one("#inspector", Inspector).set_context_busy(label)
            self.notify(label.capitalize())
            await asyncio.sleep(0)

    def _finish_context_work(self) -> None:
        if self.mode == "context" and self._main_screen is not None and self._main_screen.is_attached:
            self.query_one("#inspector", Inspector).set_context_busy(None)

    async def command_add(self, args: list[str], *, pack_id: str | None = None) -> None:
        if not args:
            self.notify("Usage: /add <text>", severity="warning")
            return
        await self._start_context_work("Adding context...")
        try:
            if hasattr(self.backend, "add_context"):
                result = await self.backend.add_context(" ".join(args), pack_id or "personal-defaults")
                if result.get("proposal"):
                    self.notify(f"Created team proposal {result['proposal'].proposal_id}")
                else:
                    self.notify(f"Added context {result['record'].record_id[:12]}")
                await self.switch_mode("context")
                await self._load_context_page()
            else:
                record, indexed = await self.backend.add(" ".join(args))
                self.notify(f"Added memory {record.record_id[:12]}" + ("" if indexed else "; run /sync to index it"))
            self._set_counts(await self.backend.counts())
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    async def command_distill(self, args: list[str]) -> None:
        pack_id = args[0] if args else self._selected_context_id()
        await self._start_context_work("Distilling context...")
        try:
            proposal = await self.backend.distill_context(pack_id)
            if proposal is None:
                self.notify("No update proposed. Approved context already matches the evidence.")
            else:
                self.notify(f"Created proposal {proposal.proposal_id} with {len(proposal.operations)} operation(s).")
            await self.switch_mode("context")
            await self._load_context_page()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    async def command_review(self, args: list[str]) -> None:
        if not args:
            await self.switch_mode("context")
            selector = self.query_one("#filter-pane", FilterPane).query_one("#harness-filter", Select)
            selector.value = "pending"
            await self._load_context_page()
            return
        decision = args[1] if len(args) > 1 else ""
        if decision not in {"approve", "reject", "keep-left", "keep-right", "keep-both"}:
            self.notify("Usage: /review <proposal> approve|reject|keep-left|keep-right|keep-both", severity="warning")
            return
        progress = (
            "Approving proposal..."
            if decision == "approve"
            else "Rejecting proposal..."
            if decision == "reject"
            else "Resolving proposal..."
        )
        await self._start_context_work(progress)
        try:
            await self.backend.review_context(args[0], decision)
            state = (
                "approved"
                if decision == "approve"
                else "rejected"
                if decision == "reject"
                else "resolved"
            )
            self.notify(f"Proposal {args[0]} is {state}.")
            await self.switch_mode("context")
            await self._load_context_page()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    async def command_share(self, args: list[str]) -> None:
        pack_id = args[0] if args else self._selected_context_id(personal_only=True)
        await self._start_context_work("Preparing team proposal...")
        try:
            proposal = await self.backend.share_context(pack_id)
            self.notify(
                f"Created team proposal {proposal.proposal_id}."
                if proposal is not None
                else "No new context needs team review."
            )
            await self.switch_mode("context")
            await self._load_context_page()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
        finally:
            self._finish_context_work()

    def _selected_context_id(self, *, personal_only: bool = False) -> str:
        """Use the visible context selection without exposing its internal ID."""
        selected = self.selected_result or {}
        identifier = str(selected.get("pack_id") or "") if self.mode == "context" else ""
        if identifier == "cloud-transport":
            identifier = ""
        if personal_only and not identifier.startswith("personal-"):
            identifier = ""
        return identifier or "personal-defaults"

    def _selected_source(self) -> dict | None:
        result = self.selected_result
        if not result or self.mode != "sources":
            return None
        return result.get("source") if result.get("view_kind") == "source-match" else result

    async def _refresh_after_source_mutation(self) -> None:
        counts = await self.backend.counts()
        self._set_counts(counts)
        await self._refresh_sources()
        await self._refresh_security_report()
        if self.mode == "sources":
            await self._load_source_page()

    async def command_new(self, args: list[str]) -> None:
        if self.mode != "sources":
            self.notify("New source files are available in Sources.", severity="warning")
            return
        source = self._selected_source()
        owned_record = bool(
            source
            and source.get("record_id")
            and source.get("origin") != "harvested"
        )
        if source is None or owned_record:
            text = await self._show_modal_wait(
                EditScreen(
                    "new-memory",
                    "",
                    title="Create Docmancer memory",
                    note="Creates a durable global record with revision history and immediate indexing.",
                )
            )
            if text is None or not text.strip():
                return
            try:
                record, indexed = await self.backend.add(text)
                await self._refresh_after_source_mutation()
                self.notify(
                    f"Added memory {record.record_id[:12]}"
                    + ("" if indexed else "; run /sync to index it")
                )
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
            return
        kind = str((source or {}).get("kind") or "agent-memory")
        path = Path(str((source or {}).get("path") or Path.cwd())).expanduser()
        directory = path.parent if path.suffix else path
        stem = {"agent-memory": "new-memory", "rules": "new-rule"}.get(kind, "new-instructions")
        suggested = str(directory / f"{stem}.md")
        if args:
            suggested = " ".join(args)
        result = await self._show_modal_wait(
            CreateSourceScreen(suggested, kind_label=kind.replace("-", " "))
        )
        if result is None:
            return
        destination, content = result
        try:
            created, indexed = await self.backend.create_source(destination, content)
            await self._refresh_after_source_mutation()
            if indexed:
                self.notify(f"Created and indexed {created}")
            else:
                self.notify(
                    f"Created {created}, but no installed harness discovers that location.",
                    severity="warning",
                    timeout=8,
                )
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)

    async def command_show(self, args: list[str]) -> None:
        if not args:
            self.notify("Usage: /show <id>", severity="warning")
            return
        atom = await self.backend.find_atom(args[0])
        if atom is None:
            self.notify("Memory id is missing or ambiguous.", severity="error")
            return
        body = f"# {atom.type.title()}\n\n{atom.text}\n\n**ID:** `{atom.record_id or atom.atom_id}`\n\n**Source:** `{atom.source_path}`"
        await self.push_screen(DetailScreen("Memory detail", body))

    async def command_edit(self, args: list[str]) -> None:
        source = self._selected_source() if not args else None
        if source and source.get("source_key") and not (
            source.get("record_id") and source.get("origin") != "harvested"
        ):
            try:
                live = await self.backend.get_live_source(str(source["source_key"]))
                edited = await self._show_modal_wait(
                    EditScreen(
                        str(source["source_key"]),
                        str(live["content"]),
                        title=f"Edit {Path(str(live['path'])).name}",
                        note=f"Direct file edit: {live['path']}",
                    )
                )
                if edited is not None and edited != live["content"]:
                    await self.backend.edit_source(
                        str(source["source_key"]),
                        edited,
                        expected_hash=str(live["content_hash"]),
                    )
                    await self._refresh_after_source_mutation()
                    self.notify(f"Saved and re-indexed {live['path']}")
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
            return
        identifier = args[0] if args else self._selected_identifier()
        if not identifier:
            self.notify("Usage: /edit <id>", severity="warning")
            return
        atom = await self.backend.find_atom(identifier)
        if atom is None:
            self.notify("Memory id is missing or ambiguous.", severity="error")
            return
        if not atom.record_id or atom.origin == "harvested":
            self.notify("Only user-owned Docmancer records can be edited.", severity="warning")
            return
        edited = await self._show_modal_wait(EditScreen(atom.record_id, atom.text))
        if edited is not None and edited.strip() and edited.strip() != atom.text.strip():
            try:
                await self.backend.edit(atom.record_id, edited)
                self.notify(f"Updated memory {atom.record_id[:12]}")
                await self._refresh_after_source_mutation()
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)

    async def command_delete(self, _args: list[str]) -> None:
        source = self._selected_source()
        if not source or not source.get("source_key"):
            self.notify("Select a memory, instruction, or rule file to delete.", severity="warning")
            return
        if source.get("record_id") and source.get("origin") != "harvested":
            identifier = str(source["record_id"])
            confirmed = await self._show_modal_wait(
                ConfirmScreen(
                    "Delete Docmancer record",
                    f"Delete record {identifier[:12]} and remove its Markdown file? "
                    "A content-free tombstone is retained for sync and suppression.",
                    confirm_label="Delete record",
                )
            )
            if not confirmed:
                return
            try:
                await self.backend.forget(identifier)
                await self._refresh_after_source_mutation()
                self.notify(f"Deleted record {identifier[:12]}")
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
            return
        try:
            live = await self.backend.get_live_source(str(source["source_key"]))
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
            return
        confirmed = await self._show_modal_wait(
            ConfirmScreen(
                "Delete source file",
                f"Permanently delete this {source.get('kind') or 'source'} file from disk?\n\n"
                f"{live['path']}\n\nThis changes the owning agent's files and cannot be undone by Docmancer.",
                confirm_label="Delete file",
            )
        )
        if not confirmed:
            return
        try:
            deleted = await self.backend.delete_source(
                str(source["source_key"]),
                expected_hash=str(live["content_hash"]),
            )
            await self._refresh_after_source_mutation()
            self.notify(f"Deleted and removed from the index: {deleted}")
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)

    async def command_forget(self, args: list[str]) -> None:
        identifier = args[0] if args else self._selected_identifier()
        if not identifier:
            self.notify("Usage: /forget <id>", severity="warning")
            return
        confirmed = await self._show_modal_wait(ConfirmScreen("Forget memory", f"Forget memory {identifier[:12]}? This updates the local source and index.", confirm_label="Forget"))
        if confirmed:
            try:
                await self.backend.forget(identifier)
                self.notify(f"Excluded passage {identifier[:12]} from recall")
                if self.mode == "sources":
                    await self._load_source_page()
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)

    async def command_promote(self, args: list[str]) -> None:
        identifier = args[0] if args else self._selected_identifier()
        if not identifier:
            self.notify("Usage: /promote <id>", severity="warning")
            return
        try:
            record, indexed = await self.backend.promote(identifier)
            self.notify(f"Promoted passage as memory {record.record_id[:12]}" + ("" if indexed else "; run /sync to index it"))
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)

    async def command_reset(self, _args: list[str]) -> None:
        await self.reset_browse()
        self.notify("Search and filters reset.")

    async def command_mode(self, args: list[str]) -> None:
        if not args or args[0] not in {"hybrid", "lexical", "dense"}:
            self.notify("Usage: /mode hybrid|lexical|dense", severity="warning")
            return
        self.retrieval_mode = args[0]
        self._update_status()
        if self.last_query and self.mode == "sources":
            await self.run_query(self.last_query)

    async def command_scope(self, args: list[str]) -> None:
        if not args:
            self.notify("Usage: /scope <project path>", severity="warning")
            return
        self.project_path = str(Path(" ".join(args)).expanduser().resolve())
        self.backend.project_path = self.project_path
        selector = self.query_one("#project-selector", Select)
        selector.set_options([(f"Project: {Path(self.project_path).name}", self.project_path), ("All projects", "all")])
        selector.value = self.project_path
        if self.mode == "sources":
            await self._load_source_page()

    async def command_doctor(self, _args: list[str]) -> None:
        report = await self.backend.doctor()
        body = "# Environment checks\n\n" + "\n\n".join(f"**{key.replace('_', ' ').title()}:** `{value}`" for key, value in report.items())
        await self.push_screen(DetailScreen("Doctor", body))

    async def command_clear(self, _args: list[str]) -> None:
        confirmed = await self._show_modal_wait(ConfirmScreen("Clear memory index", "Delete the local memory search index? Durable records and source files remain on disk.", confirm_label="Clear index"))
        if confirmed:
            removed = await self.backend.clear_memory()
            self.all_results = []
            self.results = []
            self.query_one("#result-list", ResultList).set_results([])
            counts = await self.backend.counts()
            self._set_counts({"memory": 0, "instructions": 0, "docs": counts["docs"]})
            self.query_one("#inspector", Inspector).clear(self.mode, "The local memory index is empty.")
            self.notify(f"Removed {len(removed)} local index file(s).")

    async def command_help(self, _args: list[str]) -> None:
        await self.push_screen(HelpScreen(self.registry.commands))

    def _selected_identifier(self) -> str | None:
        result = self.selected_result
        if not result:
            return None
        if result.get("view_kind") == "source-match":
            matches = result.get("matches") or []
            if not matches:
                return None
            index = self.query_one("#inspector", Inspector).match_index
            return str(matches[min(index, len(matches) - 1)].get("identifier") or "") or None
        if result.get("view_kind") == "source":
            return self.query_one("#inspector", Inspector).selected_memory_identifier or str(result.get("record_id") or "") or None
        meta = result.get("metadata") or {}
        return str(meta.get("record_id") or meta.get("atom_id") or result.get("id") or "") or None

    def _main_action_allowed(self, *, mode: str | None = None) -> bool:
        """Return whether a single-key action may operate on the main pane."""
        if self._main_screen is None or self.screen is not self._main_screen:
            return False
        if mode == "memory" and self.mode != "sources":
            return False
        if mode is not None and mode != "memory" and self.mode != mode:
            return False
        command_input = self._main_screen.query_one("#command-input", Input)
        return self._main_screen.focused is not command_input

    async def action_help(self) -> None:
        await self.command_help([])

    async def action_sources(self) -> None:
        await self.command_sources([])

    async def action_repeat_query(self) -> None:
        if self.last_query:
            await self.run_query(self.last_query)

    async def action_previous_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            if self.mode == "sources":
                await self._load_source_page()
            elif self.mode == "context":
                await self._load_context_page()
            elif self.mode == "audit":
                await self._load_security_page()
            elif not self.last_query:
                await self._load_docs_page()

    async def action_next_page(self) -> None:
        if self.has_more:
            self.current_page += 1
            if self.mode == "sources":
                await self._load_source_page()
            elif self.mode == "context":
                await self._load_context_page()
            elif self.mode == "audit":
                await self._load_security_page()
            elif not self.last_query:
                await self._load_docs_page()

    async def action_view_selected(self) -> None:
        if not self._main_action_allowed():
            return
        if not isinstance(self._main_screen.focused, ResultList):
            return
        result = self.selected_result
        if not result:
            return
        if self.mode == "docs":
            await self.push_screen(DetailScreen("Document detail", render_result(result)))
        elif self.mode == "context":
            inspector = self.query_one("#inspector", Inspector)
            inspector.show_context(result, self._context_detail(result))
            inspector.query_one("#inspector-markdown").focus()
        else:
            await self._open_source_viewer(result)

    def action_previous_match(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.query_one("#inspector", Inspector).move_match(-1)

    def action_next_match(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.query_one("#inspector", Inspector).move_match(1)

    def action_edit_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.run_worker(self.command_edit([]), group="modal-command", exit_on_error=False)

    def action_new_source(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.run_worker(self.command_new([]), group="modal-command", exit_on_error=False)

    def action_delete_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.run_worker(self.command_delete([]), group="modal-command", exit_on_error=False)

    def action_forget_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.run_worker(self.command_forget([]), group="modal-command", exit_on_error=False)

    async def action_promote_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            await self.command_promote([])

    def action_copy_selected(self) -> None:
        if not self._main_action_allowed():
            return
        result = self.selected_result
        if result:
            if self.mode == "sources":
                text = str((self.query_one("#inspector", Inspector).document or {}).get("content") or "")
            else:
                text = str(result.get("text") or "")
            self.copy_to_clipboard(text)
            self.notify("Copied selected context.")

    def action_open_source(self) -> None:
        if not self._main_action_allowed():
            return
        result = self.selected_result
        if not result:
            return
        if self.mode == "docs" and result.get("source"):
            webbrowser.open(str(result["source"]))
            self.notify("Opened the source in your browser.")
        elif self.mode == "sources":
            document = self.query_one("#inspector", Inspector).document or {}
            path = Path(str(document.get("path") or "")).expanduser()
            if path.exists():
                webbrowser.open(path.resolve().as_uri())
                self.notify("Opened the original source file.")
            else:
                self.notify("The original source file is unavailable.", severity="warning")

    async def action_expand_page(self) -> None:
        if self._main_action_allowed(mode="docs") and self.last_query:
            await self.run_query(self.last_query, expand="page")

    def action_request_quit(self) -> None:
        now = monotonic()
        if now <= self._quit_deadline:
            self.exit()
            return
        self._quit_deadline = now + 1.5
        self.notify("Press Ctrl+C again to quit.", timeout=1.5)


__all__ = ["DocmancerTuiApp"]
