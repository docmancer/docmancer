"""Versioned local HTTP API over the shared Docmancer runtime."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from docmancer.cloud.client import AuthenticationError, CloudError, EntitlementError
from docmancer.runtime import LocalRuntime


CAPABILITIES = {
    "context": ["browse", "add", "edit", "remove", "distill", "review", "share"],
    "memory": ["query", "recent", "add", "edit", "forget", "promote"],
    "sources": ["browse", "search", "create", "edit", "delete"],
    "docs": ["browse", "query", "ingest"],
    "audit": ["secrets", "hooks"],
    "intelligence": ["review", "recent", "maintenance", "history", "resolve"],
    "maintenance": ["sync", "consolidate", "apply", "doctor"],
    "cloud": ["status", "sync", "devices", "recovery", "team", "billing"],
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
    def __init__(self, runtime: LocalRuntime) -> None:
        self.runtime = runtime
        self.jobs = JobRegistry()

    async def session(self, request: Request) -> JSONResponse:
        session = request.state.browser_session
        return JSONResponse({"csrf_token": session.csrf_token, "api_version": 1})

    async def status(self, request: Request) -> JSONResponse:
        status, counts = await asyncio.gather(self.runtime.status(), self.runtime.counts())
        return JSONResponse(jsonable({"status": status, "counts": counts}))

    async def capabilities(self, request: Request) -> JSONResponse:
        return JSONResponse({"api_version": 1, "capabilities": CAPABILITIES})

    async def context(self, request: Request) -> JSONResponse:
        items = await self.runtime.context()
        return JSONResponse(jsonable(paginate(items, request)))

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
        items = await self.runtime.query_docs(query, limit=100) if query else await self.runtime.docs_sources()
        return JSONResponse(jsonable({**paginate(items, request), "query": query}))

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

    async def cloud_sync(self, request: Request) -> JSONResponse:
        job = self.jobs.start("cloud.sync", lambda _progress: self.runtime.cloud_sync())
        return JSONResponse(jsonable(job), status_code=202)

    async def cloud_devices(self, request: Request) -> JSONResponse:
        return JSONResponse(jsonable({"items": await self.runtime.cloud_devices()}))

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
        proposals, conflicts, members = await asyncio.gather(
            self.runtime.cloud_promotions(), self.runtime.cloud_conflicts(), self.runtime.cloud_members(),
        )
        return JSONResponse(jsonable({"proposals": proposals, "conflicts": conflicts, "members": members}))

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
    if isinstance(exc, EntitlementError):
        return JSONResponse({"error": {"code": "UPGRADE_REQUIRED", "message": str(exc)}}, status_code=402)
    if isinstance(exc, AuthenticationError):
        return JSONResponse({"error": {"code": "UNAUTHENTICATED", "message": str(exc)}}, status_code=401)
    if isinstance(exc, CloudError):
        return JSONResponse({"error": {"code": "CLOUD_ERROR", "message": str(exc)}}, status_code=502)
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": str(exc)}}, status_code=400)
    return JSONResponse({"error": {"code": "INTERNAL", "message": "Local operation failed"}}, status_code=500)


__all__ = ["CAPABILITIES", "LocalApi", "error_response", "jsonable"]
