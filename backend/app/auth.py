"""Authentication: off (LAN), password (env secret) or Keycloak OIDC."""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import Settings
from .csrf import ensure_csrf_token, rotate_csrf_token
from .schemas import AuthInfo, FeatureFlags, LoginRequest, Message, PlaneInfo, UserInfo

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60


def current_user(request: Request) -> dict[str, Any] | None:
    settings = request.app.state.settings
    if settings.auth_mode == "off":
        return {
            "name": "anonymous",
            "method": "off",
            "sub": "off:anonymous",
            "groups": [],
        }
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user


def user_groups(user: dict[str, Any]) -> list[str]:
    raw = user.get("groups")
    if not isinstance(raw, list):
        return []
    return [str(item)[:200] for item in raw if isinstance(item, str)]


def is_approver(settings: Settings, user: dict[str, Any] | None) -> bool:
    """Server-side approver check; never derived from request data."""
    if not user or not settings.goals_enabled or settings.auth_mode == "off":
        return False
    if settings.auth_mode == "password" and not settings.goals_allow_password_approval:
        return False
    wanted_names = settings.goals_approver_names
    wanted_groups = settings.goals_approver_group_names
    if not wanted_names and not wanted_groups:
        return False
    name = str(user.get("name") or "")
    if name and name in wanted_names:
        return True
    return bool(set(user_groups(user)) & wanted_groups)


def require_approver(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not is_approver(request.app.state.settings, user):
        raise HTTPException(status_code=403, detail="approver role required")
    return user


def _features(settings: Settings) -> FeatureFlags:
    return FeatureFlags(
        goals=settings.goals_enabled,
        goals_execute=settings.goals_execute_enabled,
        goals_llm=settings.goals_llm_enabled,
        password_single_person=(
            settings.auth_mode == "password"
            and settings.goals_enabled
            and settings.goals_allow_password_approval
        ),
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _auth_info(
    request: Request,
    settings: Settings,
    user: dict[str, Any] | None,
    provider: str,
    login_url: str | None = None,
) -> AuthInfo:
    public_user = None
    if user:
        public_user = UserInfo(
            name=str(user.get("name") or ""),
            email=str(user.get("email") or ""),
            method=str(user.get("method") or ""),
            sub=str(user.get("sub") or ""),
            groups=user_groups(user),
        )
    return AuthInfo(
        mode=settings.auth_mode,
        user=public_user,
        provider=provider,
        login_url=login_url,
        app_name=settings.app_name,
        app_version=settings.app_version,
        plane=PlaneInfo(
            name=settings.plane_name,
            site=settings.plane_site,
            host=settings.plane_host,
            ssh_user=settings.plane_ssh_user,
        ),
        csrf_token=ensure_csrf_token(request),
        features=_features(settings),
        can_approve=is_approver(settings, user),
    )


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
    provider = (
        "Keycloak"
        if settings.auth_mode == "oidc"
        else "Password"
        if settings.auth_mode == "password"
        else "LAN"
    )
    login_url = "/api/auth/oidc/login" if settings.auth_mode == "oidc" else None
    return _auth_info(request, settings, user, provider, login_url)


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
    user = {
        "name": "operator",
        "method": "password",
        "sub": "password:operator",
        "groups": [],
    }
    request.session.clear()
    request.session["user"] = user
    rotate_csrf_token(request)
    return _auth_info(request, settings, user, "Password")


@router.post("/logout", response_model=Message)
async def logout(request: Request) -> Message:
    request.session.clear()
    ensure_csrf_token(request, rotate=True)
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
    groups_raw = userinfo.get("groups")
    groups = [str(item)[:200] for item in groups_raw] if isinstance(groups_raw, list) else []
    sub = str(userinfo.get("sub") or "")
    if not sub:
        return RedirectResponse("/login?error=oidc", status_code=303)
    user = {
        "name": str(userinfo.get("preferred_username") or userinfo.get("email") or "operator")[:200],
        "email": str(userinfo.get("email") or "")[:320],
        "method": "oidc",
        "sub": sub[:255],
        "groups": groups[:100],
    }
    request.session.clear()
    request.session["user"] = user
    rotate_csrf_token(request)
    return RedirectResponse("/", status_code=303)
