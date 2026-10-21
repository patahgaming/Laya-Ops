"""FastAPI application factory + SPA hosting.

Run locally:      uvicorn app.main:app --reload --port 8000
Production:       uvicorn app.main:app --host 0.0.0.0 --port 8000 (serving frontend/dist)
"""

from __future__ import annotations

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
from .routes import router as api_router
from .security import SecurityHeadersMiddleware
from .upstream import Upstream

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


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


def _create_oauth(settings: Settings):
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="keycloak",
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


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
        try:
            yield
        finally:
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
    if settings.auth_mode == "oidc":
        app.state.oauth = _create_oauth(settings)

    app.add_middleware(SecurityHeadersMiddleware)
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

    app.include_router(auth_router)
    app.include_router(api_router)

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
