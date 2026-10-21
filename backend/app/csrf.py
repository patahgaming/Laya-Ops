"""Session-bound CSRF tokens for every unsafe request.

The token lives in the signed session cookie and is returned by GET
``/api/auth/config``. Browsers send it back in ``X-CSRF-Token``; it is never
accepted from a cookie header alone. Login rotates the token together with the
session so a pre-authentication token cannot be replayed after login.
"""

from __future__ import annotations

import secrets

from starlette.requests import Request

SESSION_KEY = "csrf_token"
HEADER_NAME = "x-csrf-token"


def ensure_csrf_token(request: Request, *, rotate: bool = False) -> str:
    token = request.session.get(SESSION_KEY)
    if rotate or not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = token
    return token


def rotate_csrf_token(request: Request) -> str:
    request.session.pop(SESSION_KEY, None)
    return ensure_csrf_token(request, rotate=True)


def csrf_matches(request: Request, supplied: str | None) -> bool:
    expected = request.session.get(SESSION_KEY)
    if not isinstance(expected, str) or not expected or not supplied:
        return False
    return secrets.compare_digest(expected, supplied)
