"""Versioned local HTTP API over the shared Docmancer runtime."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from docmancer.cloud.client import AuthenticationError, CloudError, EntitlementError
from docmancer.runtime import LocalRuntime
from docmancer.web.ask_history import AskHistoryStore


LOCAL_API_VERSION = 8

CAPABILITIES = {
    "tree": ["list", "read", "create", "edit", "move", "duplicate", "trash", "restore", "reindex"],
    "inbox": ["list", "import", "curate"],
    "editors": ["list", "open-markdown"],
    "ask": ["context", "conversation-history", "temporary-chat"],
    "common": ["recurring-memory"],
    "delivery": ["agent-matrix", "bundle-receipts"],
    "timeline": ["file-mutations", "diffs"],
    "context": ["status", "refresh", "diff", "rollback", "excluded", "adopt", "retire"],
    "providers": ["list", "key", "test", "models", "defaults"],
    "agent": ["settings", "setup-plan", "setup"],
    "memory": ["query", "recent", "add", "edit", "forget", "promote"],
    "sources": ["browse", "search", "create", "edit", "delete"],
    "docs": ["browse", "query", "ingest"],
    "library": ["browse", "search", "detail", "background-index"],
    "audit": ["secrets", "hooks"],
    "intelligence": ["review", "recent", "maintenance", "history", "resolve"],
    "maintenance": ["sync", "consolidate", "apply", "doctor"],
    "cloud": ["status", "connect", "disconnect", "sync", "devices", "recovery", "team", "billing"],
}

COMMERCIAL_LINKS = {
    "pricing": "https://docmancer.dev/pricing",
    "personal_sync": "https://docmancer.dev/cloud",
    "team": "https://docmancer.dev/teams",
    "account": "https://docmancer.dev/account",
}


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return "[binary]"
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return jsonable(model_dump())
    return value


def answer_text(result: dict[str, Any]) -> str:
    answer = result.get("answer")
    if isinstance(answer, dict):
        text = str(answer.get("text") or "").strip()
        if text:
            return text
    elif isinstance(answer, str) and answer.strip():
        return answer.strip()
    unavailable = str(result.get("answer_unavailable") or "").strip()
    if unavailable:
        return unavailable
    items = result.get("items") or []
    if items:
        count = len(items)
        return f"Docmancer found {count} relevant source{'s' if count != 1 else ''}, but no generated answer was available."
    return "Docmancer could not find relevant memory for this question."


def answer_metadata(result: dict[str, Any]) -> dict[str, Any]:
    answer = result.get("answer")
    answer_details = answer if isinstance(answer, dict) else {}
    evidence = [
        *list(result.get("mandatory_policies") or []),
        *list(result.get("curated_memory") or []),
        *list(result.get("relevant_evidence") or []),
    ]
    return {
        "provider": answer_details.get("provider"),
        "model": answer_details.get("model"),
        "cost_usd": answer_details.get("cost_usd"),
        "token_estimate": result.get("token_estimate"),
        "index_revision": result.get("index_revision"),
        "evidence": evidence,
        "verification": answer_details.get("verification"),
        "refused": answer_details.get("refused"),
    }


async def request_json(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


class JobRegistry:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def start(
        self,
        kind: str,
        operation: Callable[[Callable[[str, dict[str, Any]], None]], Awaitable[Any]],
    ) -> dict[str, Any]:
        job_id = secrets.token_urlsafe(12)
        job = {
            "id": job_id,
            "kind": kind,
            "state": "queued",
            "progress": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.jobs[job_id] = job

        def progress(stage: str, data: dict[str, Any]) -> None:
            job["progress"].append({
                "stage": stage,
                "data": jsonable(data),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            job["progress"] = job["progress"][-100:]

        async def run() -> None:
            job["state"] = "running"
            try:
                job["result"] = jsonable(await operation(progress))
                job["state"] = "completed"
            except Exception as exc:  # Converted to a bounded local error for polling.
                job["state"] = "failed"
                job["error"] = str(exc)
            finally:
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

        asyncio.create_task(run())
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        return list(reversed(list(self.jobs.values())[-50:]))


class LocalApi:
    def __init__(
        self,
        runtime: LocalRuntime,
        *,
        ask_history_path: str | Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.jobs = JobRegistry()
        project_path = Path(runtime.project_path).expanduser().resolve()
        project_id = hashlib.sha256(str(project_path).encode()).hexdigest()[:16]
        self.ask_history = AskHistoryStore(
            ask_history_path or project_path / ".docmancer" / "state" / "ask.sqlite3",
            project_id=project_id,
            project_label=project_path.name,
        )

    async def session(self, request: Request) -> JSONResponse:
        session = request.state.browser_session
        return JSONResponse({"csrf_token": session.csrf_token, "api_version": LOCAL_API_VERSION})

    async def status(self, request: Request) -> JSONResponse:
        status, counts = await asyncio.gather(self.runtime.status(), self.runtime.counts())
        return JSONResponse(jsonable({"status": status, "counts": counts}))

    async def capabilities(self, request: Request) -> JSONResponse:
        return JSONResponse({
            "api_version": LOCAL_API_VERSION,
            "capabilities": CAPABILITIES,
            "commercial_links": COMMERCIAL_LINKS,
        })

    async def tree_root(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.tree_root()))

    async def tree(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(paginate(await self.runtime.tree_list(), request)))

    async def library(self, request: Request) -> JSONResponse:
        result = await self.runtime.library(
            corpus=(request.query_params.get("corpus") or "memory").strip(),
            query=(request.query_params.get("q") or "").strip(),
            cursor=(request.query_params.get("cursor") or "").strip() or None,
            limit=bounded_int(request.query_params.get("limit"), 30, maximum=100),
        )
        return JSONResponse(jsonable(result))

    async def library_detail(self, request: Request) -> JSONResponse:
        result = await self.runtime.library_detail(
            str(request.path_params["corpus"]),
            str(request.path_params["record_id"]),
        )
        if result is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "Library item not found"}},
                status_code=404,
            )
        return JSONResponse(jsonable(result))

    async def tree_file(self, request: Request) -> JSONResponse:
        address = str(request.query_params.get("address") or "")
        if not address:
            return error_response(ValueError("address is required"))
        try:
            return JSONResponse(jsonable(await self.runtime.tree_read(address)))
        except Exception as exc:  # noqa: BLE001 - converted to shared envelope
            return error_response(exc)

    async def tree_create(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            required_text(body, "path")
            required_text(body, "markdown")
            return JSONResponse(jsonable(await self.runtime.tree_create(body)), status_code=201)
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def tree_action(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            action = required_text(body, "action")
            return JSONResponse(jsonable(await self.runtime.tree_mutate(action, body)))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def inbox(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(paginate(await self.runtime.inbox_files(), request)))

    async def harvest(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            return JSONResponse(jsonable(await self.runtime.harvest_tree(
                str(body.get("source") or ""), apply=bool(body.get("apply", False))
            )))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def import_markdown(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            source = required_text(body, "source")
            return JSONResponse(jsonable(await self.runtime.import_markdown(
                source, apply=bool(body.get("apply", True))
            )))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def editors(self, request: Request) -> JSONResponse:
        try:
            path = str(request.query_params.get("path") or "")
            if not path:
                raise ValueError("path is required")
            return JSONResponse({"items": jsonable(await self.runtime.available_editors(path))})
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def open_editor(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            path = required_text(body, "path")
            editor_id = required_text(body, "editor")
            return JSONResponse(jsonable(await self.runtime.open_markdown_file(
                path,
                editor_id=editor_id,
                line=int(body["line"]) if body.get("line") else None,
                column=int(body["column"]) if body.get("column") else None,
            )))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def curate(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            return JSONResponse(jsonable(await self.runtime.curate_inbox(
                required_text(body, "inbox_id"),
                required_text(body, "path"),
                apply=bool(body.get("apply", False)),
            )))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def ask(self, request: Request) -> JSONResponse:
        try:
            body = await request_json(request)
            task = required_text(body, "task")
            budget = int(body.get("token_budget") or 4000)
            if budget < 1 or budget > 100_000:
                raise ValueError("token_budget must be between 1 and 100000")
            answer = body.get("answer")
            if answer is not None and not isinstance(answer, bool):
                raise ValueError("answer must be a boolean")
            mode = str(body.get("mode") or "normal")
            if mode not in {"concise", "normal", "thorough"}:
                raise ValueError("mode must be concise, normal, or thorough")
            ask_kwargs = {
                "token_budget": budget,
                "agent": str(body.get("agent") or "web"),
            }
            if answer is not None:
                ask_kwargs["answer"] = answer
            if "mode" in body:
                ask_kwargs["mode"] = mode
            conversation_id = str(body.get("conversation_id") or "").strip()
            temporary = bool(body.get("temporary"))
            if conversation_id and temporary:
                raise ValueError("temporary chats cannot have a saved conversation id")
            exchange: tuple[str, str] | None = None
            if conversation_id:
                exchange = await asyncio.to_thread(
                    self.ask_history.begin_exchange,
                    conversation_id,
                    task,
                )

            async def run_ask(on_delta=None):
                try:
                    result = await self.runtime.ask_tree(
                        task,
                        **ask_kwargs,
                        on_delta=on_delta,
                    )
                    if exchange is not None:
                        await asyncio.to_thread(
                            self.ask_history.complete_answer,
                            conversation_id,
                            exchange[1],
                            answer_text(result),
                            metadata=answer_metadata(result),
                        )
                    return {
                        **result,
                        "conversation_id": conversation_id or None,
                        "user_message_id": exchange[0] if exchange else None,
                        "assistant_message_id": exchange[1] if exchange else None,
                        "temporary": temporary or not bool(conversation_id),
                    }
                except Exception as exc:
                    if exchange is not None:
                        await asyncio.to_thread(
                            self.ask_history.complete_answer,
                            conversation_id,
                            exchange[1],
                            "This answer did not complete.",
                            metadata={"error": type(exc).__name__},
                            status="failed",
                        )
                    raise

            if bool(body.get("stream")) and answer is not False:
                async def operation(progress):
                    def on_delta(delta: str) -> None:
                        progress("answer_delta", {"delta": delta})

                    return await run_ask(on_delta)

                job = self.jobs.start("memory.ask", operation)
                return JSONResponse(
                    jsonable({
                        **job,
                        "conversation_id": conversation_id or None,
                        "user_message_id": exchange[0] if exchange else None,
                        "assistant_message_id": exchange[1] if exchange else None,
                        "temporary": temporary or not bool(conversation_id),
                    }),
                    status_code=202,
                )
            return JSONResponse(jsonable(await run_ask()))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def ask_conversations(self, request: Request) -> JSONResponse:
        try:
            if request.method == "POST":
                body = await request_json(request)
                if body.get("temporary"):
                    return JSONResponse({"temporary": True, "conversation": None}, status_code=201)
                conversation = await asyncio.to_thread(self.ask_history.create_conversation)
                return JSONResponse(jsonable(conversation), status_code=201)
            limit = bounded_int(request.query_params.get("limit"), 60, maximum=200)
            items = await asyncio.to_thread(
                self.ask_history.list_conversations,
                limit=limit,
            )
            return JSONResponse({"items": jsonable(items)})
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def ask_conversation(self, request: Request) -> JSONResponse:
        try:
            conversation_id = str(request.path_params["conversation_id"])
            if request.method == "DELETE":
                deleted = await asyncio.to_thread(
                    self.ask_history.delete_conversation,
                    conversation_id,
                )
                if not deleted:
                    return JSONResponse(
                        {"error": {"code": "NOT_FOUND", "message": "Conversation not found"}},
                        status_code=404,
                    )
                return JSONResponse({"deleted": True, "id": conversation_id})
            conversation = await asyncio.to_thread(
                self.ask_history.get_conversation,
                conversation_id,
            )
            if conversation is None:
                return JSONResponse(
                    {"error": {"code": "NOT_FOUND", "message": "Conversation not found"}},
                    status_code=404,
                )
            return JSONResponse(jsonable(conversation))
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)

    async def common(self, request: Request) -> JSONResponse:
        rows = await self.runtime.common_memory()
        query = (request.query_params.get("q") or "").strip().casefold()
        if query:
            rows = [
                row for row in rows
                if query in json.dumps(row, ensure_ascii=False, default=str).casefold()
            ]
        return JSONResponse(jsonable({**paginate(rows, request), "query": query}))

    async def delivery(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(paginate(await self.runtime.context_delivery(), request)))

    async def timeline(self, request: Request) -> JSONResponse:
        rows = await self.runtime.decision_journal(
            file_id=(request.query_params.get("file_id") or "").strip() or None,
            operation=(request.query_params.get("operation") or "").strip() or None,
            limit=bounded_int(request.query_params.get("limit"), 200, maximum=1000),
        )
        query = (request.query_params.get("q") or "").strip().casefold()
        if query:
            rows = [
                row for row in rows
                if query in json.dumps(row, ensure_ascii=False, default=str).casefold()
            ]
        return JSONResponse(jsonable({**paginate(rows, request), "query": query}))

    async def context(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.context_artifact()))

    async def context_add(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        text = required_text(body, "text")
        result = await self.runtime.add_context(text, str(body.get("pack_id") or "personal-defaults"))
        return JSONResponse(jsonable(result), status_code=201)

    async def context_action(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        action = required_text(body, "action")
        identifier = request.path_params["identifier"]
        if action == "edit":
            result = await self.runtime.edit_context(identifier, required_text(body, "text"))
        elif action == "remove":
            require_confirmation(body, identifier)
            result = await self.runtime.remove_context(identifier)
        elif action in {"approve", "reject"}:
            result = await self.runtime.review_context(identifier, action, text=body.get("text"))
        elif action == "share":
            result = await self.runtime.share_context(identifier)
        elif action == "distill":
            result = await self.runtime.distill_context(identifier)
        else:
            raise ValueError("unsupported context action")
        return JSONResponse(jsonable(result))

    async def context_refresh(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        provider = str(body.get("provider") or "none")
        mode = str(body.get("mode") or "normal")
        if mode not in {"concise", "normal", "thorough"}:
            raise ValueError("mode must be concise, normal, or thorough")
        dry_run = bool(body.get("dry_run"))
        if dry_run:
            return JSONResponse(jsonable(await self.runtime.refresh_context(
                provider=provider,
                model=str(body["model"]) if body.get("model") else None,
                mode=mode,
                full=bool(body.get("full")),
                dry_run=True,
            )))
        job = self.jobs.start(
            "context.refresh",
            lambda progress: self.runtime.refresh_context(
                provider=provider,
                model=str(body["model"]) if body.get("model") else None,
                mode=mode,
                full=bool(body.get("full")),
                progress_callback=progress,
            ),
        )
        return JSONResponse(jsonable(job), status_code=202)

    async def context_diff(self, request: Request) -> JSONResponse:
        left = str(request.query_params.get("a") or "")
        if not left:
            raise ValueError("a revision is required")
        right = str(request.query_params.get("b") or "") or None
        return JSONResponse(jsonable(await self.runtime.context_diff(left, right)))

    async def context_rollback(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        return JSONResponse(jsonable(
            await self.runtime.rollback_context(required_text(body, "revision_id"))
        ))

    async def context_excluded(self, request: Request) -> JSONResponse:
        artifact = await self.runtime.context_artifact()
        return JSONResponse({
            "items": jsonable(((artifact.get("current") or {}).get("excluded") or []))
        })

    async def context_adopt(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        return JSONResponse(jsonable(await self.runtime.adopt_context(
            required_text(body, "cluster_id"),
            destination=str(body["destination"]) if body.get("destination") else None,
        )))

    async def context_retire(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        return JSONResponse(jsonable(
            await self.runtime.retire_context(required_text(body, "cluster_id"))
        ))

    async def memory(self, request: Request) -> JSONResponse:
        query = (request.query_params.get("q") or "").strip()
        page_size = bounded_int(request.query_params.get("page_size"), 20, maximum=100)
        if query:
            items = await self.runtime.query_memory(
                query,
                mode=request.query_params.get("mode") or "hybrid",
                scope=request.query_params.get("scope"),
                project_path=self.runtime.project_path,
                limit=100,
            )
        else:
            items = await self.runtime.memory_recent(datetime.now(timezone.utc) - timedelta(days=7))
        return JSONResponse(jsonable({**paginate(items, request, page_size=page_size), "query": query}))

    async def memory_add(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        result = await self.runtime.add(
            required_text(body, "text"),
            scope_kind=str(body.get("scope_kind") or "global"),
        )
        return JSONResponse(jsonable(result), status_code=201)

    async def memory_detail(self, request: Request) -> JSONResponse:
        result = await self.runtime.find_atom(request.path_params["identifier"])
        if result is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "Memory atom not found"}},
                status_code=404,
            )
        return JSONResponse(jsonable(result))

    async def memory_action(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        action = required_text(body, "action")
        identifier = request.path_params["identifier"]
        if action == "edit":
            result = await self.runtime.edit(identifier, required_text(body, "text"))
        elif action == "forget":
            require_confirmation(body, identifier)
            result = await self.runtime.forget(identifier)
        elif action == "promote":
            result = await self.runtime.promote(identifier)
        else:
            raise ValueError("unsupported memory action")
        return JSONResponse(jsonable(result))

    async def sources(self, request: Request) -> JSONResponse:
        query = (request.query_params.get("q") or "").strip()
        kinds = tuple(filter(None, (request.query_params.get("kinds") or "agent-memory,docmancer-memory,team-memory,instructions,rules").split(",")))
        page = bounded_int(request.query_params.get("page"), 1)
        page_size = bounded_int(request.query_params.get("page_size"), 50, maximum=100)
        if query:
            result = await self.runtime.search_memory_sources(
                query,
                kinds=kinds,
                project_path=self.runtime.project_path,
                page=page,
                page_size=page_size,
            )
        else:
            result = await self.runtime.browse_memory_sources(
                kinds=kinds,
                project_path=self.runtime.project_path,
                page=page,
                page_size=page_size,
            )
        return JSONResponse(jsonable(result))

    async def source_detail(self, request: Request) -> JSONResponse:
        key = request.query_params.get("key") or ""
        if not key:
            raise ValueError("source key is required")
        return JSONResponse(jsonable(await self.runtime.get_live_source(key)))

    async def source_create(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        path, created = await self.runtime.create_source(required_text(body, "path"), required_text(body, "content", allow_empty=True))
        return JSONResponse({"path": str(path), "created": created}, status_code=201)

    async def source_update(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        result = await self.runtime.edit_source(
            required_text(body, "source_key"),
            required_text(body, "content", allow_empty=True),
            expected_hash=required_text(body, "expected_hash"),
        )
        return JSONResponse(jsonable(result))

    async def source_delete(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        source_key = required_text(body, "source_key")
        require_confirmation(body, source_key)
        deleted = await self.runtime.delete_source(source_key, expected_hash=required_text(body, "expected_hash"))
        return JSONResponse({"deleted": deleted})

    async def docs(self, request: Request) -> JSONResponse:
        query = (request.query_params.get("q") or "").strip()
        source = (request.query_params.get("source") or "").strip() or None
        items = (
            await self.runtime.query_docs(query, limit=100, source=source)
            if query else await self.runtime.docs_sources()
        )
        return JSONResponse(jsonable({
            **paginate(items, request),
            "query": query,
            "source": source,
        }))

    async def docs_ingest(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        target = required_text(body, "target")
        job = self.jobs.start("docs.ingest", lambda progress: self.runtime.ingest_docs(target, progress))
        return JSONResponse(jsonable(job), status_code=202)

    async def docs_source(self, request: Request) -> JSONResponse:
        source = (request.query_params.get("source") or "").strip()
        if not source:
            raise ValueError("documentation source is required")
        result = await self.runtime.get_docs_source(source)
        if result is None:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "Documentation source not found"}},
                status_code=404,
            )
        return JSONResponse(jsonable(result))

    async def audit(self, request: Request) -> JSONResponse:
        report, hooks = await asyncio.gather(self.runtime.audit(), self.runtime.hook_status())
        findings = [dict(item, view_kind="secret-finding") for item in report.get("findings", [])]
        hook_rows = [dict(item, view_kind="hook-status") for item in hooks]
        return JSONResponse(jsonable({
            **paginate([*findings, *hook_rows], request),
            "report": report,
            "hook_count": len(hooks),
        }))

    async def intelligence(self, request: Request) -> JSONResponse:
        result = await self.runtime.memory_intelligence(
            view=request.query_params.get("view") or "review",
            project_path=self.runtime.project_path,
            query=request.query_params.get("q"),
            page=bounded_int(request.query_params.get("page"), 1),
            page_size=bounded_int(request.query_params.get("page_size"), 20, maximum=100),
        )
        return JSONResponse(jsonable(result))

    async def intelligence_action(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        action = required_text(body, "action")
        if action != "resolve":
            raise ValueError("unsupported intelligence action")
        resolution = required_text(body, "resolution")
        winner = body.get("winner")
        relation_ids = body.get("relation_ids")
        if relation_ids is not None:
            if not isinstance(relation_ids, list) or not all(
                isinstance(value, str) and value for value in relation_ids
            ):
                raise ValueError("relation_ids must be a list of identifiers")
            result = await self.runtime.resolve_memory_conflict_group(
                relation_ids,
                resolution,
                winner=winner if isinstance(winner, str) else None,
            )
        else:
            result = await self.runtime.resolve_memory_conflict(
                request.path_params["identifier"],
                resolution,
                winner=winner if isinstance(winner, str) else None,
            )
        return JSONResponse(jsonable(result))

    async def capture_settings(self, request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse({"enabled": await self.runtime.capture_settings()})
        body = await request_json(request)
        enabled = body.get("enabled")
        if not isinstance(enabled, dict) or not all(
            isinstance(key, str) and isinstance(value, bool)
            for key, value in enabled.items()
        ):
            raise ValueError("enabled must map agent names to booleans")
        path = await self.runtime.save_capture_settings(enabled)
        return JSONResponse({"enabled": enabled, "saved_to": str(path)})

    async def providers(self, request: Request) -> JSONResponse:
        return JSONResponse({"items": jsonable(await self.runtime.provider_catalog())})

    async def provider_key(self, request: Request) -> JSONResponse:
        provider_id = request.path_params["provider_id"]
        if request.method == "DELETE":
            return JSONResponse(jsonable(await self.runtime.remove_provider_key(provider_id)))
        body = await request_json(request)
        return JSONResponse(jsonable(await self.runtime.provider_key(
            provider_id,
            required_text(body, "key"),
            validate=bool(body.get("validate")),
        )))

    async def provider_test(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(
            await self.runtime.test_provider(request.path_params["provider_id"])
        ))

    async def provider_models(self, request: Request) -> JSONResponse:
        provider_id = request.path_params["provider_id"]
        if request.query_params.get("refresh") == "1":
            result = await self.runtime.provider_models(provider_id, refresh=True)
        else:
            result = await self.runtime.provider_models(provider_id)
        if isinstance(result, list):  # Compatibility for presentation-runtime adapters.
            result = {
                "provider": provider_id,
                "items": [
                    {"id": str(item), "label": str(item), "source": "runtime"}
                    for item in result
                ],
                "state": "ready",
            }
        return JSONResponse(jsonable(result))

    async def ai_defaults(self, request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse(jsonable(await self.runtime.ai_defaults()))
        body = await request_json(request)
        path = await self.runtime.save_ai_defaults(body)
        return JSONResponse({
            **jsonable(await self.runtime.ai_defaults()),
            "saved_to": str(path),
        })

    async def agent_settings(self, request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse(jsonable(await self.runtime.agent_settings()))
        body = await request_json(request)
        path = await self.runtime.save_agent_settings(body)
        return JSONResponse({
            **jsonable(await self.runtime.agent_settings()),
            "saved_to": str(path),
        })

    async def agent_setup_plan(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.agent_setup_plan()))

    async def agent_setup(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        if body.get("confirmed") is not True:
            raise ValueError("setup confirmation is required")
        targets = body.get("targets")
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ValueError("targets must be a list of agent identifiers")
        job = self.jobs.start(
            "agent.setup",
            lambda progress: self.runtime.run_agent_setup(
                targets,
                capture_hooks=True,
                confirmed=True,
                progress_callback=progress,
            ),
        )
        return JSONResponse(jsonable(job), status_code=202)

    async def distillation_preview(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.distillation_preview()))

    async def maintenance(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        action = required_text(body, "action")
        if action == "sync":
            job = self.jobs.start("memory.sync", lambda progress: self.runtime.sync(progress))
        elif action == "consolidate":
            job = self.jobs.start("memory.consolidate", lambda _progress: self.runtime.consolidate(body.get("query")))
        elif action == "apply":
            job = self.jobs.start("memory.apply", lambda _progress: self.runtime.apply_memory(required_text(body, "agent"), body.get("draft")))
        elif action == "doctor":
            return JSONResponse(jsonable(await self.runtime.doctor()))
        else:
            raise ValueError("unsupported maintenance action")
        return JSONResponse(jsonable(job), status_code=202)

    async def jobs_list(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable({"items": self.jobs.list()}))

    async def job(self, request: Request) -> JSONResponse:
        job = self.jobs.get(request.path_params["job_id"])
        if job is None:
            return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Job not found"}}, status_code=404)
        return JSONResponse(jsonable(job))

    async def job_events(self, request: Request) -> StreamingResponse:
        job_id = request.path_params["job_id"]

        async def events():
            seen = 0
            while True:
                job = self.jobs.get(job_id)
                if job is None:
                    yield 'event: error\ndata: {"message":"Job not found"}\n\n'
                    return
                progress = list(job.get("progress") or [])
                for event in progress[seen:]:
                    yield f"event: progress\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
                seen = len(progress)
                if job.get("state") in {"completed", "failed"}:
                    yield f"event: done\ndata: {json.dumps(jsonable(job), separators=(',', ':'))}\n\n"
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(events(), media_type="text/event-stream")

    async def cloud_status(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.cloud_status()))

    async def cloud_connect(self, request: Request) -> JSONResponse:
        from docmancer.cloud.config import default_cloud_base_url

        body = await request_json(request)
        status = await self.runtime.cloud_status()
        if status.get("configured"):
            return JSONResponse(
                {"error": {"code": "ALREADY_CONNECTED", "message": "this device is already connected"}},
                status_code=409,
            )
        base_url = optional_text(body, "base_url") or default_cloud_base_url()
        create_recovery = bool(body.get("create_recovery"))

        async def operation(progress: Callable[[str, dict[str, Any]], None]) -> dict:
            outcome = await self.runtime.cloud_connect(
                base_url=base_url, create_recovery=create_recovery, progress=progress,
            )
            # The recovery key is shown exactly once and never enters the pollable job record.
            recovery_key = outcome.pop("recovery_key", None)
            self._recovery_key_once = recovery_key
            outcome["recovery_key_available"] = recovery_key is not None
            return outcome

        job = self.jobs.start("cloud.connect", operation)
        return JSONResponse(jsonable(job), status_code=202)

    async def cloud_recovery_key_once(self, request: Request) -> JSONResponse:
        recovery_key = getattr(self, "_recovery_key_once", None)
        self._recovery_key_once = None
        if not recovery_key:
            return JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "no unread recovery key is available"}},
                status_code=404,
            )
        return JSONResponse({"recovery_key": recovery_key})

    async def cloud_connect_cancel(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(self.runtime.cloud_cancel_connect()))

    async def cloud_disconnect(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.cloud_disconnect()))

    async def cloud_sync(self, request: Request) -> JSONResponse:
        job = self.jobs.start("cloud.sync", lambda _progress: self.runtime.cloud_sync())
        return JSONResponse(jsonable(job), status_code=202)

    async def cloud_devices(self, request: Request) -> JSONResponse:
        status = await self.runtime.cloud_status()
        if not status.get("configured"):
            return JSONResponse(cloud_unavailable("not_connected"))
        try:
            items = await self.runtime.cloud_devices()
        except Exception as exc:  # A read-only Cloud page must not break the local app.
            return JSONResponse(cloud_unavailable_from(exc))
        return JSONResponse(jsonable({"available": True, "configured": True, "items": items}))

    async def cloud_device_approve(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        result = await self.runtime.cloud_approve_device(request.path_params["device_id"], required_text(body, "fingerprint"))
        return JSONResponse(jsonable(result))

    async def cloud_device_revoke(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        device_id = request.path_params["device_id"]
        require_confirmation(body, device_id)
        return JSONResponse(jsonable(await self.runtime.cloud_revoke_device(device_id)))

    async def cloud_team(self, request: Request) -> JSONResponse:
        status = await self.runtime.cloud_status()
        preview = await self.runtime.team_file()
        if not status.get("configured"):
            return JSONResponse(jsonable({
                **cloud_unavailable("not_connected"),
                "local_preview_available": True,
                "team_file": preview,
                "proposals": [],
                "conflicts": await self.runtime.cloud_conflicts(),
                "members": [],
            }))
        try:
            proposals, conflicts, members = await asyncio.gather(
                self.runtime.cloud_promotions(), self.runtime.cloud_conflicts(), self.runtime.cloud_members(),
            )
        except Exception as exc:  # Keep optional Cloud state separate from local availability.
            return JSONResponse(jsonable({
                **cloud_unavailable_from(exc),
                "local_preview_available": True,
                "team_file": preview,
                "proposals": [],
                "conflicts": await self.runtime.cloud_conflicts(),
                "members": [],
            }))
        return JSONResponse(jsonable({
            "available": True,
            "configured": True,
            "team_file": preview,
            "proposals": proposals,
            "conflicts": conflicts,
            "members": members,
        }))

    async def cloud_team_file(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        domain = str(body.get("domain") or "standards").strip()
        if not domain or not all(character.isalnum() or character in {"-", "_"} for character in domain):
            raise ValueError("domain must contain only letters, numbers, hyphens, or underscores")
        outcome = str(body.get("outcome") or "").strip()
        if outcome:
            result = await self.runtime.team_file_transition(
                domain=domain,
                outcome=outcome,
                approver_id=str(body.get("approver_id") or "").strip() or None,
            )
            return JSONResponse(jsonable(result))
        apply = bool(body.get("apply"))
        approved = bool(body.get("approved"))
        if apply and not approved:
            raise ValueError("complete-file approval is required before publication")
        result = await self.runtime.team_file(
            domain=domain,
            apply=apply,
            approved=approved,
            approver_id=str(body.get("approver_id") or "").strip() or None,
        )
        return JSONResponse(jsonable(result))

    async def cloud_team_invite(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        role = required_text(body, "role")
        if role not in {"admin", "reviewer", "member"}:
            raise ValueError("role must be admin, reviewer, or member")
        return JSONResponse(jsonable(await self.runtime.cloud_invite_member(required_text(body, "email"), role)), status_code=201)

    async def cloud_review(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        result = await self.runtime.cloud_review_promotion(
            request.path_params["proposal_id"],
            required_text(body, "decision"),
            text=body.get("text"),
        )
        return JSONResponse(jsonable(result))

    async def cloud_recovery_verify(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        await self.runtime.cloud_verify_recovery(required_text(body, "recovery_key"))
        return JSONResponse({"verified": True})

    async def cloud_policy(self, request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse(jsonable(await self.runtime.cloud_policy()))
        body = await request_json(request)
        policy = body.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("policy must be an object")
        version = bounded_int(str(body.get("policy_version") or "1"), 1)
        return JSONResponse(jsonable(await self.runtime.cloud_update_policy(version, policy)))

    async def cloud_export(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable(await self.runtime.cloud_request_export()), status_code=202)

    async def cloud_delete(self, request: Request) -> JSONResponse:
        body = await request_json(request)
        if body.get("confirmation") != "DELETE":
            raise ValueError("type DELETE to confirm remote deletion")
        return JSONResponse(jsonable(await self.runtime.cloud_delete_remote("DELETE")), status_code=202)


def required_text(body: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = body.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{key} is required")
    return value if allow_empty else value.strip()


def optional_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    return value.strip() if isinstance(value, str) else ""


def require_confirmation(body: dict[str, Any], expected: str) -> None:
    if body.get("confirmation") != expected:
        raise ValueError("confirmation does not match the target")


def paginate(
    items: list[Any],
    request: Request,
    *,
    page_size: int | None = None,
) -> dict[str, Any]:
    """Return stable page metadata for every local collection surface."""
    size = page_size or bounded_int(request.query_params.get("page_size"), 20, maximum=100)
    requested_page = bounded_int(request.query_params.get("page"), 1)
    total = len(items)
    total_pages = max(1, (total + size - 1) // size)
    page = min(requested_page, total_pages)
    start = (page - 1) * size
    return {
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "page_size": size,
        "total_pages": total_pages,
        "has_more": page < total_pages,
    }


def bounded_int(value: str | None, default: int, *, maximum: int = 10_000) -> int:
    if value is None:
        return default
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"value must be between 1 and {maximum}")
    return parsed


def error_response(exc: Exception) -> JSONResponse:
    from docmancer.memory.tree.errors import TreeError

    if isinstance(exc, TreeError):
        payload = {
            "code": exc.__class__.__name__.replace("Error", "").upper(),
            "message": str(exc),
            "retry_safe": bool(getattr(exc, "retry_safe", False)),
            "likely_cause": str(getattr(exc, "likely_cause", "")),
            "next_action": str(getattr(exc, "next_action", "")),
        }
        candidates = getattr(exc, "candidates", None)
        if candidates:
            payload["candidates"] = list(candidates)
        status = 409 if exc.__class__.__name__ in {"StaleWriteError", "AlreadyExistsError", "AmbiguousAddressError"} else 404 if exc.__class__.__name__ == "AddressNotFoundError" else 400
        return JSONResponse({"error": payload}, status_code=status)
    if isinstance(exc, EntitlementError):
        return JSONResponse({"error": {"code": "UPGRADE_REQUIRED", "message": str(exc)}}, status_code=402)
    if isinstance(exc, AuthenticationError):
        return JSONResponse({"error": {"code": "UNAUTHENTICATED", "message": str(exc)}}, status_code=401)
    if isinstance(exc, CloudError):
        return JSONResponse({"error": {"code": "CLOUD_ERROR", "message": str(exc)}}, status_code=502)
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": str(exc)}}, status_code=400)
    return JSONResponse({"error": {"code": "INTERNAL", "message": "Local operation failed"}}, status_code=500)


def cloud_unavailable(reason: str) -> dict[str, Any]:
    messages = {
        "not_connected": "This machine is not connected to Docmancer Cloud. Connect it when you want encrypted device or team sync.",
        "authentication": "The Cloud session needs to be renewed. Reconnect this machine before managing shared state.",
        "entitlement": "This account does not currently include the requested Cloud feature. Local Docmancer remains available.",
        "unreachable": "Docmancer Cloud could not be reached. Your local memory and context are unaffected.",
    }
    return {"available": False, "configured": reason != "not_connected", "state": reason, "message": messages[reason]}


def cloud_unavailable_from(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, EntitlementError):
        return cloud_unavailable("entitlement")
    if isinstance(exc, AuthenticationError):
        return cloud_unavailable("authentication")
    return cloud_unavailable("unreachable")


__all__ = ["CAPABILITIES", "LocalApi", "error_response", "jsonable"]
