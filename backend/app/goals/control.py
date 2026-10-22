"""HMAC client for the healer loopback control API.

The message format is identical to ``proxmox/goal_control.py`` in Laya Engine:

    timestamp \\n nonce \\n METHOD \\n path \\n sha256(body)

Only two endpoints exist: ``POST /execute`` and ``GET /runs/{plan_id}``. There
is deliberately no generic request method, no retry, and no redirect
following. Errors are mapped to stable codes; the raw healer response message
is never shown to the browser.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from typing import Any

import httpx

MIN_KEY_CHARS = 32
MAX_REPLY_BYTES = 256 * 1024


def signature(
    secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes
) -> str:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    message = f"{timestamp}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}"
    return hmac.new(
        str(secret).encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class ControlError(Exception):
    """Transport-level failure: we do not know whether the action ran."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ControlClient:
    def __init__(
        self,
        base: str,
        key: str,
        *,
        request_timeout: float = 15.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(str(key or "")) < MIN_KEY_CHARS:
            raise ValueError(f"GOALS_CONTROL_KEY minimal {MIN_KEY_CHARS} karakter")
        base = str(base or "").rstrip("/")
        if not base:
            raise ValueError("GOALS_CONTROL_BASE kosong")
        self.base = base
        self._key = key
        self._clock = clock
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(max(1.0, float(request_timeout))),
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={"User-Agent": "laya-ops-goals/2"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ api
    async def execute(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return await self._signed("POST", "/execute", body)

    async def status(self, plan_id: str) -> tuple[int, dict[str, Any]]:
        if (
            not isinstance(plan_id, str)
            or not plan_id
            or len(plan_id) > 128
            or not all(c.isalnum() or c in "._:-" for c in plan_id)
            or not plan_id[0].isalnum()
        ):
            raise ValueError("plan_id tidak valid")
        return await self._signed("GET", f"/runs/{plan_id}", b"")

    # -------------------------------------------------------------- internal
    async def _signed(
        self, method: str, path: str, body: bytes
    ) -> tuple[int, dict[str, Any]]:
        timestamp = str(int(self._clock()))
        nonce = secrets.token_urlsafe(24)
        headers = {
            "X-Laya-Timestamp": timestamp,
            "X-Laya-Nonce": nonce,
            "X-Laya-Key-Id": key_id(self._key),
            "X-Laya-Signature": signature(
                self._key, timestamp, nonce, method, path, body
            ),
            "Accept": "application/json",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        try:
            response = await self._client.request(
                method, self.base + path, content=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ControlError("control_timeout") from exc
        except httpx.HTTPError as exc:
            raise ControlError("control_unavailable") from exc

        if len(response.content) > MAX_REPLY_BYTES:
            raise ControlError("control_reply_too_large")
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return response.status_code, data


def key_id(key: str) -> str:
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]
