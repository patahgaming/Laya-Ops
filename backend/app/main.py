"""FastAPI application factory + SPA hosting.

Run locally:      uvicorn app.main:app --reload --port 8000
Production:       uvicorn app.main:app --host 0.0.0.0 --port 8000 (serving frontend/dist)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import router as auth_router
from .cache import TTLCache
from .config import Settings, get_settings
from .goals.control import ControlClient
from .goals.routes import router as goals_router
from .goals.service import GoalError, GoalService
from .goals.store import Store
from .routes import router as api_router
from .security import RequestGuardMiddleware, SecurityHeadersMiddleware
from .upstream import Upstream

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
LOG = logging.getLogger("laya.ops.goals")


def _validate_settings(settings: Settings) -> None:
    if settings.auth_mode in ("password", "oidc") and settings.session_secret == "dev-only-change-me":
        raise RuntimeError("SESSION_SECRET must be changed when auth is enabled")
    if settings.auth_mode == "password" and not settings.app_password:
        raise RuntimeError("AUTH_MODE=password requires APP_PASSWORD")
    if settings.auth_mode == "oidc":
        missing = [
            name
            for name, value in {
                "OIDC_ISSUER": settings.oidc_issuer,
                "OIDC_CLIENT_ID": settings.oidc_client_id,
                "OIDC_CLIENT_SECRET": settings.oidc_client_secret,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError("AUTH_MODE=oidc is missing: " + ", ".join(missing))

    if settings.goals_execute_enabled and not settings.goals_enabled:
        raise RuntimeError("GOALS_EXECUTE_ENABLED requires GOALS_ENABLED=true")
    if settings.goals_auto_execute_after_approval:
        raise RuntimeError("GOALS_AUTO_EXECUTE_AFTER_APPROVAL is not supported")
    if settings.goals_enabled:
        if settings.auth_mode == "off":
            raise RuntimeError("GOALS_ENABLED=true requires AUTH_MODE=password or oidc")
        if settings.session_secret == "dev-only-change-me":
            raise RuntimeError("GOALS_ENABLED=true requires a non-default SESSION_SECRET")
        if not settings.public_origins:
            raise RuntimeError("GOALS_ENABLED=true requires PUBLIC_ORIGIN")
    if settings.goals_execute_enabled:
        if not settings.goals_control_is_loopback:
            raise RuntimeError("GOALS_CONTROL_BASE must be a loopback URL when execution is enabled")
        if len(settings.goals_control_key) < 32:
            raise RuntimeError("GOALS_CONTROL_KEY must be at least 32 characters")
        if settings.goals_control_timeout < 5:
            raise RuntimeError("GOALS_CONTROL_TIMEOUT must be at least 5 seconds")
        if settings.goals_control_request_timeout < 1:
            raise RuntimeError("GOALS_CONTROL_REQUEST_TIMEOUT must be at least 1 second")
        if settings.goals_control_request_timeout >= settings.goals_control_timeout:
            raise RuntimeError(
                "GOALS_CONTROL_REQUEST_TIMEOUT must be shorter than GOALS_CONTROL_TIMEOUT"
            )
        if settings.goals_control_poll_interval < 0.5:
            raise RuntimeError("GOALS_CONTROL_POLL_INTERVAL must be at least 0.5 seconds")
    if settings.goals_llm_enabled and not settings.goals_llm_url:
        raise RuntimeError("GOALS_LLM_ENABLED=true requires GOALS_LLM_URL")


def _create_oauth(settings: Settings):
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="keycloak",
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": "openid email profile groups"},
    )
    return oauth


async def _sweeper(service: GoalService) -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(service.sweep)
        except Exception:  # a sweeper error must not kill the app
            LOG.exception("goals sweeper failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _validate_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.upstream_timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": f"laya-ops/{settings.app_version}"},
        )
        app.state.upstream = Upstream(client, settings)
        app.state.cache = TTLCache()
        store: Store | None = None
        goals: GoalService | None = None
        sweeper: asyncio.Task | None = None
        try:
            if settings.goals_enabled:
                store = Store(settings.goals_data_dir)
                store.initialize()
                control = (
                    ControlClient(
                        settings.goals_control_base,
                        settings.goals_control_key,
                        request_timeout=settings.goals_control_request_timeout,
                    )
                    if settings.goals_execute_enabled
                    else None
                )
                goals = GoalService(settings, store, app.state.upstream, control)
                app.state.goals = goals
                await asyncio.to_thread(goals.sweep)
                sweeper = asyncio.create_task(_sweeper(goals))
            yield
        finally:
            if sweeper is not None:
                sweeper.cancel()
                try:
                    await sweeper
                except asyncio.CancelledError:
                    pass
            if goals is not None:
                await goals.shutdown()
            if store is not None:
                store.close()
            await app.state.upstream.close()

    app = FastAPI(
        title="Laya Ops API",
        version=settings.app_version,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.login_attempts = {}
    app.state.goals = None
    if settings.auth_mode == "oidc":
        app.state.oauth = _create_oauth(settings)

    @app.exception_handler(GoalError)
    async def goal_error_handler(_request: Request, exc: GoalError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={"Cache-Control": "no-store"},
        )

    # Added first => innermost. Session must be outside the guard so the guard
    # can read the signed csrf_token from the session.
    app.add_middleware(RequestGuardMiddleware, settings=settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="laya_session",
        same_site="lax",
        https_only=settings.cookie_secure,
        max_age=8 * 3600,
    )
    if settings.allowed_hosts.strip():
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
        )
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(auth_router)
    app.include_router(api_router)
    if settings.goals_enabled:
        app.include_router(goals_router)

    @app.get("/api/healthz", tags=["health"])
    async def healthz() -> dict:
        return {"ok": True, "version": settings.app_version}

    @app.get("/api/readyz", tags=["health"])
    async def readyz(request: Request):
        probe = await request.app.state.upstream.healer("readyz", "/api/summary")
        return JSONResponse(
            status_code=200 if probe.ok else 503,
            content={"ok": probe.ok, "healer_ms": probe.ms, "error": probe.error},
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (FRONTEND_DIST / path).resolve()
        root = FRONTEND_DIST.resolve()
        if path and root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
