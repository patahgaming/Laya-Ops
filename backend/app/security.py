"""HTTP hardening for the single-origin app.

Two layers live here:

* :class:`SecurityHeadersMiddleware` adds the static response headers.
* :class:`RequestGuardMiddleware` protects every unsafe ``/api`` request with a
  same-origin check, a session-bound CSRF token, a JSON-only rule and a hard
  body-size limit. It is deliberately ASGI-level so the body limit also applies
  to chunked requests that do not carry ``Content-Length``.
"""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .csrf import HEADER_NAME

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        headers.setdefault("Content-Security-Policy", CSP)
        return response


_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _json(status: int, detail: str) -> Response:
    return Response(
        content=json.dumps({"detail": detail}),
        status_code=status,
        media_type="application/json",
    )


def _origin_allowed(settings: Settings, headers: Headers) -> bool:
    allowed = settings.public_origins
    if not allowed:
        return True
    supplied = headers.get("origin")
    if not supplied:
        referer = headers.get("referer")
        if referer:
            parsed = urlsplit(referer)
            supplied = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not supplied or supplied == "null":
        return False
    return supplied.rstrip("/") in allowed


class RequestGuardMiddleware:
    """Reject cross-origin / un-tokened / oversized unsafe API requests."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in _UNSAFE
            or not scope.get("path", "").startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _origin_allowed(self.settings, headers):
            await _json(403, "origin not allowed")(scope, receive, send)
            return

        session = scope.get("session") or {}
        expected = session.get("csrf_token") if isinstance(session, dict) else None
        supplied = headers.get(HEADER_NAME)
        if (
            not isinstance(expected, str)
            or not expected
            or not supplied
            or not secrets.compare_digest(expected, supplied)
        ):
            await _json(403, "csrf token missing or invalid")(scope, receive, send)
            return

        length_header = headers.get("content-length")
        transfer_encoding = headers.get("transfer-encoding", "").lower()
        has_body = bool(transfer_encoding) or (length_header not in (None, "", "0"))
        if has_body:
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                await _json(415, "content-type must be application/json")(scope, receive, send)
                return
        if length_header:
            try:
                length = int(length_header)
            except ValueError:
                await _json(400, "invalid content-length")(scope, receive, send)
                return
            if length > self.settings.max_request_body:
                await _json(413, "request body too large")(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.settings.max_request_body:
                await _json(413, "request body too large")(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False
        buffered = bytes(body)

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": buffered, "more_body": False}

        await self.app(scope, replay, send)
