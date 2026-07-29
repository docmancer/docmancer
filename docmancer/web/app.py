"""ASGI application and runner for the packaged localhost interface."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from docmancer.runtime import LocalRuntime
from docmancer.web.api import LOCAL_API_VERSION, LocalApi, error_response
from docmancer.web.security import (
    LoopbackSecurity,
    MAX_REQUEST_BYTES,
    SECURITY_HEADERS,
    SESSION_COOKIE,
)


class LoopbackSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, security: LoopbackSecurity) -> None:
        super().__init__(app)
        self.security = security

    async def dispatch(self, request: Request, call_next):
        if not self.security.valid_host(request.headers):
            return PlainTextResponse("Invalid host", status_code=400)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                announced_length = int(content_length)
            except ValueError:
                return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "Content-Length is invalid"}}, status_code=400)
            if announced_length > MAX_REQUEST_BYTES:
                return JSONResponse({"error": {"code": "TOO_LARGE", "message": "Request is too large"}}, status_code=413)

        if request.url.path.startswith("/api/v1"):
            session = self.security.session(request.headers, request.cookies)
            if session is None:
                return JSONResponse({"error": {"code": "UNAUTHENTICATED", "message": "Local browser session required"}}, status_code=401)
            request.state.browser_session = session
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not self.security.valid_mutation(request.headers, session):
                return JSONResponse({"error": {"code": "FORBIDDEN", "message": "Origin or CSRF validation failed"}}, status_code=403)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and len(await request.body()) > MAX_REQUEST_BYTES:
                return JSONResponse({"error": {"code": "TOO_LARGE", "message": "Request is too large"}}, status_code=413)

        try:
            response = await call_next(request)
        except Exception as exc:
            response = error_response(exc) if request.url.path.startswith("/api/v1") else PlainTextResponse("Local application error", status_code=500)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


def create_app(
    *,
    port: int,
    config_path: str | None = None,
    project_path: str | Path | None = None,
    static_dir: str | Path | None = None,
    runtime: LocalRuntime | None = None,
    ask_history_path: str | Path | None = None,
) -> Starlette:
    security = LoopbackSecurity(port=port)
    local_runtime = runtime or LocalRuntime(config_path=config_path, project_path=project_path)
    api = LocalApi(local_runtime, ask_history_path=ask_history_path)
    asset_root = Path(static_dir) if static_dir else Path(__file__).with_name("static")
    manifest_path = asset_root / "asset-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("local_api_version") != LOCAL_API_VERSION:
            raise RuntimeError("the packaged web application requires an incompatible local API")

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async def initialize_runtime() -> None:
            try:
                await local_runtime.initialize()
                schedule_refresh = getattr(local_runtime, "schedule_memory_refresh", None)
                if callable(schedule_refresh):
                    schedule_refresh()
            except Exception:
                # Readiness exposes the failure while the static workbench
                # remains available with panel-level recovery.
                return

        task = asyncio.create_task(
            initialize_runtime(), name="docmancer-web-initialize"
        )
        _app.state.runtime_initialization = task
        await asyncio.sleep(0)
        try:
            yield
        finally:
            if not task.done():
                task.cancel()

    async def bootstrap(request: Request) -> Response:
        supplied = request.query_params.get("bootstrap")
        if supplied:
            exchanged = security.exchange_bootstrap(supplied)
            if exchanged is None:
                return PlainTextResponse("Bootstrap token is invalid or expired", status_code=401)
            session_token, _csrf = exchanged
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE,
                session_token,
                httponly=True,
                samesite="strict",
                secure=False,
                max_age=12 * 60 * 60,
                path="/",
            )
            return response
        if security.session(request.headers, request.cookies) is None:
            return PlainTextResponse("Start this page with `docmancer web`.", status_code=401)
        index = asset_root / "index.html"
        if not index.is_file():
            return PlainTextResponse("The packaged web application is missing. Reinstall Docmancer.", status_code=503)
        return Response(index.read_bytes(), media_type="text/html")

    async def compatibility_redirect(request: Request) -> Response:
        """Move retired workbench routes to their canonical replacements."""
        destinations = {
            "ask": "/",
            "agent-context": "/",
            "tree": "/library/?tab=memory",
            "inbox": "/library/?tab=memory",
            "sources": "/library/?tab=evidence",
            "docs": "/library/?tab=docs",
            "context": "/memory/",
            "common": "/memory/",
            "delivery": "/memory/",
            "timeline": "/memory/",
            "audit": "/settings/?section=safeguards",
            "maintenance": "/settings/?section=maintenance",
            "intelligence": "/memory/",
        }
        surface = request.url.path.strip("/")
        return RedirectResponse(url=destinations[surface], status_code=308)

    async def application_page(request: Request) -> Response:
        """Serve an exported application route, with a shell fallback for tests."""
        surface = request.url.path.strip("/")
        nested = asset_root / surface / "index.html"
        index = nested if nested.is_file() else asset_root / "index.html"
        if not index.is_file():
            return PlainTextResponse("The packaged web application is missing. Reinstall Docmancer.", status_code=503)
        return Response(index.read_bytes(), media_type="text/html")

    routes = [
        Route("/", bootstrap, methods=["GET"]),
        *[
            Route(path, application_page, methods=["GET", "HEAD"])
            for surface in ("memory", "library", "settings", "help")
            for path in (f"/{surface}", f"/{surface}/")
        ],
        *[
            Route(path, compatibility_redirect, methods=["GET", "HEAD"])
            for surface in (
                "ask", "agent-context", "context", "tree", "inbox", "sources",
                "docs", "common", "delivery", "timeline", "audit",
                "maintenance", "intelligence",
            )
            for path in (f"/{surface}", f"/{surface}/")
        ],
        Route("/api/v1/session", api.session, methods=["GET"]),
        Route("/api/v1/readiness", api.readiness, methods=["GET"]),
        Route("/api/v1/status", api.status, methods=["GET"]),
        Route("/api/v1/capabilities", api.capabilities, methods=["GET"]),
        Route("/api/v1/shared-memory", api.shared_memory, methods=["GET"]),
        Route("/api/v1/shared-memory/file", api.shared_memory_file, methods=["GET"]),
        Route(
            "/api/v1/agents/{agent:str}/projection",
            api.agent_projection,
            methods=["GET"],
        ),
        Route("/api/v1/tree/root", api.tree_root, methods=["GET"]),
        Route("/api/v1/tree", api.tree, methods=["GET"]),
        Route("/api/v1/library", api.library, methods=["GET"]),
        Route("/api/v1/library/{corpus:str}/{record_id:str}", api.library_detail, methods=["GET"]),
        Route("/api/v1/tree/file", api.tree_file, methods=["GET"]),
        Route("/api/v1/tree/file", api.tree_create, methods=["POST"]),
        Route("/api/v1/tree/action", api.tree_action, methods=["POST"]),
        Route("/api/v1/editors", api.editors, methods=["GET"]),
        Route("/api/v1/editor/open", api.open_editor, methods=["POST"]),
        Route("/api/v1/inbox", api.inbox, methods=["GET"]),
        Route("/api/v1/import", api.import_markdown, methods=["POST"]),
        Route("/api/v1/harvest", api.harvest, methods=["POST"]),
        Route("/api/v1/curate", api.curate, methods=["POST"]),
        Route("/api/v1/ask", api.ask, methods=["POST"]),
        Route("/api/v1/ask/conversations", api.ask_conversations, methods=["GET", "POST"]),
        Route(
            "/api/v1/ask/conversations/{conversation_id:str}",
            api.ask_conversation,
            methods=["GET", "DELETE"],
        ),
        Route("/api/v1/common", api.common, methods=["GET"]),
        Route("/api/v1/delivery", api.delivery, methods=["GET"]),
        Route("/api/v1/timeline", api.timeline, methods=["GET"]),
        Route("/api/v1/context", api.context, methods=["GET"]),
        Route("/api/v1/context/refresh", api.context_refresh, methods=["POST"]),
        Route("/api/v1/context/diff", api.context_diff, methods=["GET"]),
        Route("/api/v1/context/rollback", api.context_rollback, methods=["POST"]),
        Route("/api/v1/context/excluded", api.context_excluded, methods=["GET"]),
        Route("/api/v1/context/adopt", api.context_adopt, methods=["POST"]),
        Route("/api/v1/context/retire", api.context_retire, methods=["POST"]),
        Route("/api/v1/packs", api.context_add, methods=["POST"]),
        Route("/api/v1/packs/{identifier:str}", api.context_action, methods=["POST"]),
        Route("/api/v1/memory", api.memory, methods=["GET"]),
        Route("/api/v1/memory", api.memory_add, methods=["POST"]),
        Route("/api/v1/memory/{identifier:str}", api.memory_detail, methods=["GET"]),
        Route("/api/v1/memory/{identifier:str}", api.memory_action, methods=["POST"]),
        Route("/api/v1/sources", api.sources, methods=["GET"]),
        Route("/api/v1/sources", api.source_create, methods=["POST"]),
        Route("/api/v1/source", api.source_detail, methods=["GET"]),
        Route("/api/v1/source", api.source_update, methods=["PUT"]),
        Route("/api/v1/source", api.source_delete, methods=["DELETE"]),
        Route("/api/v1/docs", api.docs, methods=["GET"]),
        Route("/api/v1/docs/source", api.docs_source, methods=["GET"]),
        Route("/api/v1/docs/ingest", api.docs_ingest, methods=["POST"]),
        Route("/api/v1/audit", api.audit, methods=["GET"]),
        Route("/api/v1/intelligence", api.intelligence, methods=["GET"]),
        Route("/api/v1/intelligence/{identifier:str}", api.intelligence_action, methods=["POST"]),
        Route("/api/v1/settings/capture", api.capture_settings, methods=["GET", "PUT"]),
        Route("/api/v1/providers", api.providers, methods=["GET"]),
        Route("/api/v1/providers/{provider_id:str}/key", api.provider_key, methods=["PUT", "DELETE"]),
        Route("/api/v1/providers/{provider_id:str}/test", api.provider_test, methods=["POST"]),
        Route("/api/v1/providers/{provider_id:str}/models", api.provider_models, methods=["GET"]),
        Route("/api/v1/settings/ai-defaults", api.ai_defaults, methods=["GET", "PUT"]),
        Route("/api/v1/agent", api.agent_settings, methods=["GET", "PUT"]),
        Route("/api/v1/agent/setup", api.agent_setup_plan, methods=["GET"]),
        Route("/api/v1/agent/setup", api.agent_setup, methods=["POST"]),
        Route("/api/v1/context/distillation-preview", api.distillation_preview, methods=["GET"]),
        Route("/api/v1/canonical", api.canonical, methods=["GET"]),
        Route("/api/v1/canonical/refresh", api.canonical_refresh, methods=["POST"]),
        Route("/api/v1/canonical/{section:str}", api.canonical_section, methods=["GET"]),
        Route("/api/v1/canonical/{section:str}/pin", api.canonical_pin, methods=["POST"]),
        Route("/api/v1/maintenance", api.maintenance, methods=["POST"]),
        Route("/api/v1/jobs", api.jobs_list, methods=["GET"]),
        Route("/api/v1/jobs/{job_id:str}", api.job, methods=["GET"]),
        Route("/api/v1/jobs/{job_id:str}/events", api.job_events, methods=["GET"]),
        Route("/api/v1/cloud", api.cloud_status, methods=["GET"]),
        Route("/api/v1/cloud/connect", api.cloud_connect, methods=["POST"]),
        Route("/api/v1/cloud/connect/cancel", api.cloud_connect_cancel, methods=["POST"]),
        Route("/api/v1/cloud/connect/recovery-key", api.cloud_recovery_key_once, methods=["POST"]),
        Route("/api/v1/cloud/disconnect", api.cloud_disconnect, methods=["POST"]),
        Route("/api/v1/cloud/sync", api.cloud_sync, methods=["POST"]),
        Route("/api/v1/cloud/devices", api.cloud_devices, methods=["GET"]),
        Route("/api/v1/cloud/devices/{device_id:str}/approve", api.cloud_device_approve, methods=["POST"]),
        Route("/api/v1/cloud/devices/{device_id:str}/revoke", api.cloud_device_revoke, methods=["POST"]),
        Route("/api/v1/cloud/team", api.cloud_team, methods=["GET"]),
        Route("/api/v1/cloud/team/file", api.cloud_team_file, methods=["POST"]),
        Route("/api/v1/cloud/team/invitations", api.cloud_team_invite, methods=["POST"]),
        Route("/api/v1/cloud/team/{proposal_id:str}/review", api.cloud_review, methods=["POST"]),
        Route("/api/v1/cloud/recovery/verify", api.cloud_recovery_verify, methods=["POST"]),
        Route("/api/v1/cloud/policy", api.cloud_policy, methods=["GET", "PUT"]),
        Route("/api/v1/cloud/export", api.cloud_export, methods=["POST"]),
        Route("/api/v1/cloud/delete", api.cloud_delete, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=asset_root, html=True), name="static"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.security = security
    app.state.runtime = local_runtime
    app.add_middleware(LoopbackSecurityMiddleware, security=security)
    return app


def run_web(
    *,
    port: int = 0,
    open_browser: bool = True,
    config_path: str | None = None,
    project_path: str | Path | None = None,
) -> None:
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    actual_port = int(listener.getsockname()[1])
    app = create_app(port=actual_port, config_path=config_path, project_path=project_path)
    token = app.state.security.bootstrap_token
    url = f"http://127.0.0.1:{actual_port}/?bootstrap={token}"
    print(f"Docmancer web is available at http://127.0.0.1:{actual_port}")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    else:
        print(f"Open once to authenticate this browser session: {url}")
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=actual_port, log_level="warning")
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


__all__ = ["create_app", "run_web"]
