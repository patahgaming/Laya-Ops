"""Authentication: off (LAN), password (env secret) or Keycloak OIDC."""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .schemas import AuthInfo, LoginRequest, Message

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60


def current_user(request: Request) -> dict[str, str] | None:
    settings = request.app.state.settings
    if settings.auth_mode == "off":
        return {"name": "anonymous", "method": "off"}
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def require_user(request: Request) -> dict[str, str]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> bool:
    attempts: dict[str, list[float]] = request.app.state.login_attempts
    ip = _client_ip(request)
    now = time.monotonic()
    recent = [stamp for stamp in attempts.get(ip, []) if now - stamp < WINDOW_SECONDS]
    if len(recent) >= MAX_ATTEMPTS:
        attempts[ip] = recent
        return True
    recent.append(now)
    attempts[ip] = recent
    return False


@router.get("/config", response_model=AuthInfo)
async def auth_config(request: Request) -> AuthInfo:
    settings = request.app.state.settings
    user = current_user(request)
    provider = "Keycloak" if settings.auth_mode == "oidc" else "Password" if settings.auth_mode == "password" else "LAN"
    login_url = "/api/auth/oidc/login" if settings.auth_mode == "oidc" else None
    return AuthInfo(mode=settings.auth_mode, user=user, provider=provider, login_url=login_url)


@router.post("/login", response_model=AuthInfo)
async def login(request: Request, payload: LoginRequest) -> AuthInfo:
    settings = request.app.state.settings
    if settings.auth_mode != "password":
        raise HTTPException(status_code=400, detail="password login is not enabled")
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="too many attempts, try again later")
    expected = settings.app_password
    if not expected:
        raise HTTPException(status_code=503, detail="APP_PASSWORD is not configured")
    if not secrets.compare_digest(payload.password.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid password")
    user = {"name": "operator", "method": "password"}
    request.session.clear()
    request.session["user"] = user
    return AuthInfo(mode=settings.auth_mode, user=user, provider="Password")


@router.post("/logout", response_model=Message)
async def logout(request: Request) -> Message:
    request.session.clear()
    return Message(message="logged out")


@router.get("/oidc/login")
async def oidc_login(request: Request):
    settings = request.app.state.settings
    oauth = getattr(request.app.state, "oauth", None)
    if settings.auth_mode != "oidc" or oauth is None:
        raise HTTPException(status_code=400, detail="OIDC login is not enabled")
    redirect_uri = settings.oidc_redirect_uri or str(request.url_for("oidc_callback"))
    return await oauth.keycloak.authorize_redirect(request, redirect_uri)


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request):
    settings = request.app.state.settings
    oauth = getattr(request.app.state, "oauth", None)
    if settings.auth_mode != "oidc" or oauth is None:
        raise HTTPException(status_code=400, detail="OIDC login is not enabled")
    try:
        token = await oauth.keycloak.authorize_access_token(request)
    except Exception:  # noqa: BLE001 - redirect back to login on any IdP error
        return RedirectResponse("/login?error=oidc", status_code=303)
    userinfo = token.get("userinfo") or {}
    user = {
        "name": str(userinfo.get("preferred_username") or userinfo.get("email") or "operator"),
        "email": str(userinfo.get("email") or ""),
        "method": "oidc",
    }
    request.session.clear()
    request.session["user"] = user
    return RedirectResponse("/", status_code=303)
