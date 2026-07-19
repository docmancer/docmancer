"""Textual application for browsing and curating local Docmancer data."""
from __future__ import annotations

import webbrowser
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from textual import events
from textual.app import App
from textual.binding import Binding
from textual.widgets import Button, Input, ListView, Select, Static, Tab, Tabs

from docmancer.memory import SyncInProgressError
from docmancer.tui.backend import TuiBackend
from docmancer.tui.commands import default_registry
from docmancer.tui.screens.audit import AuditScreen
from docmancer.tui.screens.cloud import CloudListScreen, ConflictResolutionScreen, DeviceApprovalScreen, PromotionReviewScreen, RecoveryKeyScreen
from docmancer.tui.screens.detail import ConfirmScreen, DetailScreen, EditScreen, SourceViewerScreen
from docmancer.tui.screens.help import HelpScreen
from docmancer.tui.screens.main import MainScreen
from docmancer.tui.screens.sources import SourcesScreen
from docmancer.tui.screens.sync import SyncScreen
from docmancer.tui.widgets import FilterPane, Inspector, ResultList, StatusBar
from docmancer.tui.widgets.inspector import render_result


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
        Binding("e", "edit_selected", "Edit"),
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
        self.mode = "memory"
        self.retrieval_mode = "hybrid"
        self.project_path = self.backend.project_path
        self.results: list[dict] = []
        self.all_results: list[dict] = []
        self.source_rows: dict[str, list[dict]] = {"memory": [], "instructions": [], "docs": []}
        self.last_query = ""
        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1
        self.has_more = False
        self._quit_deadline = 0.0
        self._main_screen: MainScreen | None = None
        self._pending_query: tuple[str, str | None, str | None] | None = None
        self.cloud_label = "off"
        self.cloud_risk_count = 0

    async def on_mount(self) -> None:
        await self.push_screen("main")
        self._main_screen = self.screen
        self._update_responsive(self.size.width)
        self.call_after_refresh(self._load_backend)

    def query_one(self, selector, expect_type=None):
        """Query the active TUI screen rather than the empty App root screen."""
        base = self._main_screen or self.screen
        if expect_type is None:
            return base.query_one(selector)
        return base.query_one(selector, expect_type)

    async def _show_modal_wait(self, screen):
        """Push a result modal and await dismissal from normal event handlers."""
        future = asyncio.get_running_loop().create_future()

        def resolve(result) -> None:
            if not future.done():
                future.set_result(result)

        await self.push_screen(screen, callback=resolve)
        return await future

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
            await self._load_source_page()
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

    async def reset_browse(self) -> None:
        """Clear transient search state and restore source-file browsing."""
        self.last_query = ""
        self.current_page = 1
        self.query_one("#filter-pane", FilterPane).reset()
        if self.mode in {"memory", "instructions"}:
            await self._load_source_page()
        else:
            self.all_results = []
            self.results = []
            self.query_one("#result-list", ResultList).set_results([])
            self.query_one("#inspector", Inspector).clear("docs")
        self.query_one("#command-input", Input).clear()

    async def _refresh_sources(self) -> None:
        memory_rows, docs_rows = await asyncio.gather(
            self.backend.memory_sources(live_preview=False),
            self.backend.docs_sources(),
        )
        self.source_rows = {"memory": memory_rows, "instructions": memory_rows, "docs": docs_rows}
        self.query_one("#filter-pane", FilterPane).set_mode(self.mode, self.source_rows[self.mode])

    def _set_counts(self, counts: dict) -> None:
        tabs = self.query_one("#mode-tabs", Tabs)
        tabs.query_one("#memory", Tab).label = f"Memory {counts['memory']:,}"
        tabs.query_one("#instructions", Tab).label = f"Instructions & Rules {counts.get('instructions', 0):,}"
        tabs.query_one("#docs", Tab).label = f"Docs {counts['docs']:,}"
        tabs.query_one("#docs", Tab).add_class("empty") if not counts["docs"] else tabs.query_one("#docs", Tab).remove_class("empty")

    def _source_kinds(self) -> tuple[str, ...]:
        return ("agent-memory", "docmancer-memory", "team-memory") if self.mode == "memory" else ("instructions", "rules")

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
        if not self.backend.ready or self.mode not in {"memory", "instructions"}:
            return
        title = "MEMORY FILES" if self.mode == "memory" else "INSTRUCTION & RULE FILES"
        self.query_one("#results-title", Static).update("SEARCHING..." if self.last_query else "LOADING...")
        args = self._source_filter_args()
        if self.last_query:
            data = await self.backend.search_memory_sources(self.last_query, mode=self.retrieval_mode, **args)
            self.results = [dict(item, view_kind="source-match") for item in data["items"]]
            self.total_pages = self.current_page + (1 if data.get("has_more") else 0)
            self.has_more = bool(data.get("has_more"))
            count = f"page {self.current_page}" + ("  more" if self.has_more else "")
            title = "MATCHING MEMORY FILES" if self.mode == "memory" else "MATCHING INSTRUCTION FILES"
        else:
            data = await self.backend.browse_memory_sources(**args)
            self.current_page = int(data["page"])
            self.total_pages = int(data["total_pages"])
            self.has_more = self.current_page < self.total_pages
            self.results = [dict(item, view_kind="source") for item in data["items"]]
            start = 0 if not data["total"] else (self.current_page - 1) * self.page_size + 1
            end = min(int(data["total"]), self.current_page * self.page_size)
            count = f"{start}-{end} of {int(data['total']):,}"
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
        if line.startswith("/"):
            await self.registry.dispatch(self, line)
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
            if self.mode in {"memory", "instructions"}:
                await self._load_source_page()
            else:
                self.all_results = await self.backend.query_docs(query, expand=expand)
                self._apply_docs_filters()
            self._update_status()
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=8)
            self.query_one("#results-title", Static).update("MEMORY FILES" if self.mode == "memory" else "MATCHING SECTIONS")

    def _apply_docs_filters(self) -> None:
        filters = self.query_one("#filter-pane", FilterPane).values()
        results = list(self.all_results)
        if filters["harness"] != "all":
            results = [item for item in results if str(item.get("source") or "").startswith(filters["harness"])]
        if filters["time"] != "any":
            days = {"day": 1, "week": 7, "month": 30}[filters["time"]]
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            results = [item for item in results if self._timestamp(item) is None or self._timestamp(item) >= cutoff]
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
            (item.get("metadata") or {}).get("timestamp")
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
        titles = {"memory": "MEMORY FILES", "instructions": "INSTRUCTION & RULE FILES", "docs": "MATCHING SECTIONS"}
        self.query_one("#results-title", Static).update(titles[mode])
        input_widget = self.query_one("#command-input", Input)
        noun = {"memory": "memory files", "instructions": "instructions and rules", "docs": "indexed documentation"}[mode]
        input_widget.placeholder = f"Search {noun} or type / for commands..."
        if mode == "docs" and not self.source_rows["docs"]:
            self.query_one("#inspector", Inspector).clear("docs",
                "# No documentation indexed\n\nIndex local documentation with `docmancer ingest ./docs`.\n\nAdd a documentation website with `docmancer add https://docs.example.com`."
            )
        elif mode in {"memory", "instructions"}:
            await self._load_source_page()
        else:
            self.query_one("#inspector", Inspector).clear(mode)
        self._update_pagination()

    async def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        if event.tab.id != self.query_one("#mode-tabs", Tabs).active:
            return
        if event.tab.id in {"memory", "instructions", "docs"}:
            await self.switch_mode(event.tab.id)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "project-selector" or event.value == "loading":
            return
        if event.value == "all":
            self.project_path = None
        elif isinstance(event.value, str):
            self.project_path = event.value
        self.backend.project_path = self.project_path or str(Path.cwd().resolve())
        if self.mode in {"memory", "instructions"}:
            self.current_page = 1
            await self._load_source_page()

    async def on_filter_pane_changed(self) -> None:
        self.current_page = 1
        if self.mode in {"memory", "instructions"}:
            await self._load_source_page()
        elif self.all_results:
            self._apply_docs_filters()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self._main_screen is None or not self._main_screen.is_attached:
            return
        item = getattr(event.item, "result", None)
        if item is not None:
            await self._inspect_result(item)

    async def _inspect_result(self, item: dict) -> None:
        inspector = self.query_one("#inspector", Inspector)
        if self.mode == "docs":
            inspector.show_docs_result(item)
            return
        source = item.get("source") if item.get("view_kind") == "source-match" else item
        document = await self.backend.get_memory_source(str(source.get("source_key") or ""))
        if document is None:
            inspector.clear(self.mode, "The indexed source snapshot is unavailable. Run `/sync` to rebuild it.")
            return
        inspector.show_source(document, item.get("matches") or [])

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = getattr(event.item, "result", None)
        if item is not None:
            await self._inspect_result(item)

    async def on_result_list_open_requested(self, event: ResultList.OpenRequested) -> None:
        if self.mode == "docs":
            await self.push_screen(DetailScreen("Document detail", render_result(event.result)))
        else:
            await self._open_source_viewer(event.result)

    async def _open_source_viewer(self, item: dict) -> None:
        source = item.get("source") if item.get("view_kind") == "source-match" else item
        document = await self.backend.get_memory_source(str(source.get("source_key") or ""))
        if document is not None:
            inspector = self.query_one("#inspector", Inspector)
            await self.push_screen(SourceViewerScreen(document, item.get("matches") or [], inspector.match_index))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "previous-page":
            await self.action_previous_page()
        elif event.button.id == "next-page":
            await self.action_next_page()

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
            if self.mode in {"memory", "instructions"}:
                await self._load_source_page()
        except SyncInProgressError as exc:
            screen.finish_with_error(str(exc))
            self.notify(str(exc), severity="warning")
        except Exception as exc:  # noqa: BLE001
            screen.finish_with_error(str(exc))
            self.notify(str(exc), severity="error")

    async def command_sources(self, _args: list[str]) -> None:
        rows = await (self.backend.memory_sources(live_preview=True) if self.mode in {"memory", "instructions"} else self.backend.docs_sources())
        await self.push_screen(SourcesScreen(rows, mode=self.mode))

    async def command_status(self, _args: list[str]) -> None:
        status = await self.backend.status()
        body = (
            f"# Local status\n\n**Project:** `{status['project']}`\n\n"
            f"**Memory index:** {status['memory'].get('atoms', 0)} passages across {status['memory'].get('sources', 0)} source files\n\n"
            f"**Docs:** {status['docs'].get('sections_count', 0)} sections\n\n"
            f"**Memory DB:** `{status['memory'].get('db_path')}`"
        )
        await self.push_screen(DetailScreen("Status", body))

    async def command_audit(self, _args: list[str]) -> None:
        await self.push_screen(AuditScreen(await self.backend.audit()))

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
        elif action == "promotions":
            try:
                rows = await self.backend.cloud_promotions()
                if not rows:
                    self.notify("No promotion proposals are awaiting review.")
                else:
                    review = await self._show_modal_wait(PromotionReviewScreen(rows))
                    if review:
                        proposal_id, decision = review
                        replacement = None
                        if decision == "edit":
                            row = next(item for item in rows if str(item.get("proposal_id")) == proposal_id)
                            replacement = await self._show_modal_wait(EditScreen(proposal_id, str(row.get("text") or "")))
                            if replacement is None:
                                return
                            decision = "approve"
                        await self.backend.cloud_review_promotion(proposal_id, decision, text=replacement)
                        self.notify(f"Promotion proposal {proposal_id} marked {decision}.")
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), severity="error", timeout=8)
        else:
            self.notify("Usage: /cloud status|sync|conflicts|devices|recovery|audit|promotions", severity="warning")

    async def command_add(self, args: list[str]) -> None:
        if not args:
            self.notify("Usage: /add <text>", severity="warning")
            return
        try:
            record, indexed = await self.backend.add(" ".join(args))
            self.notify(f"Added memory {record.record_id[:12]}" + ("" if indexed else "; run /sync to index it"))
            self._set_counts(await self.backend.counts())
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
                if self.last_query:
                    await self.run_query(self.last_query, mode="memory")
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
                if self.mode in {"memory", "instructions"}:
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
        if self.last_query and self.mode in {"memory", "instructions"}:
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
        if self.mode in {"memory", "instructions"}:
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
            return str(result.get("record_id") or "") or None
        meta = result.get("metadata") or {}
        return str(meta.get("record_id") or meta.get("atom_id") or result.get("id") or "") or None

    def _main_action_allowed(self, *, mode: str | None = None) -> bool:
        """Return whether a single-key action may operate on the main pane."""
        if self._main_screen is None or self.screen is not self._main_screen:
            return False
        if mode == "memory" and self.mode not in {"memory", "instructions"}:
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
        if self.mode in {"memory", "instructions"} and self.current_page > 1:
            self.current_page -= 1
            await self._load_source_page()

    async def action_next_page(self) -> None:
        if self.mode in {"memory", "instructions"} and self.has_more:
            self.current_page += 1
            await self._load_source_page()

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
        else:
            await self._open_source_viewer(result)

    def action_previous_match(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.query_one("#inspector", Inspector).move_match(-1)

    def action_next_match(self) -> None:
        if self._main_action_allowed(mode="memory"):
            self.query_one("#inspector", Inspector).move_match(1)

    async def action_edit_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            await self.command_edit([])

    async def action_forget_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            await self.command_forget([])

    async def action_promote_selected(self) -> None:
        if self._main_action_allowed(mode="memory"):
            await self.command_promote([])

    def action_copy_selected(self) -> None:
        if not self._main_action_allowed():
            return
        result = self.selected_result
        if result:
            if self.mode in {"memory", "instructions"}:
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
        elif self.mode in {"memory", "instructions"}:
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
