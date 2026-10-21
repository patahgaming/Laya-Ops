"""Thin async HTTP client for the read-only upstreams.

The backend never exposes an upstream URL parameter to the browser: every call is
constructed from server-side settings, so this app cannot become an open proxy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .config import Settings


@dataclass(slots=True)
class ProbeResult:
    name: str
    url: str
    ok: bool
    ms: int
    error: str | None = None
    value: object | None = None


class Upstream:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self.settings = settings

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self, name: str, url: str, *, kind: str = "json", params: dict[str, str] | None = None
    ) -> ProbeResult:
        started = time.perf_counter()
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            value = response.text if kind == "text" else response.json()
            return ProbeResult(
                name=name,
                url=url,
                ok=True,
                ms=round((time.perf_counter() - started) * 1000),
                value=value,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as endpoint status
            return ProbeResult(
                name=name,
                url=url,
                ok=False,
                ms=round((time.perf_counter() - started) * 1000),
                error=_short_error(exc),
            )

    async def healer(self, name: str, path: str) -> ProbeResult:
        return await self._request(name, self.settings.healer_base.rstrip("/") + path)

    async def healer_text(self, name: str, path: str) -> ProbeResult:
        return await self._request(name, self.settings.healer_base.rstrip("/") + path, kind="text")

    async def prom(self, name: str, query: str) -> ProbeResult:
        started = time.perf_counter()
        url = self.settings.prometheus_base.rstrip("/") + "/api/v1/query"
        try:
            response = await self._client.get(url, params={"query": query})
            response.raise_for_status()
            return ProbeResult(
                name=name,
                url=url,
                ok=True,
                ms=round((time.perf_counter() - started) * 1000),
                value=response.json(),
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                name=name,
                url=url,
                ok=False,
                ms=round((time.perf_counter() - started) * 1000),
                error=_short_error(exc),
            )

    async def ready(self, name: str, base: str, path: str = "/-/ready") -> ProbeResult:
        return await self._request(name, base.rstrip("/") + path, kind="text")

    async def grafana_health(self) -> ProbeResult:
        return await self._request(
            "grafana_health",
            self.settings.grafana_base.rstrip("/") + "/api/health",
            kind="json",
        )

    async def alertmanager_alerts(self) -> ProbeResult:
        """Active alerts held by Alertmanager, including direct healer pushes.

        Prometheus `ALERTS` only sees rule evaluations; alerts the healer posts to
        the Alertmanager API (`PveHealerApproval`, `PveHealerEscalation`, ...) live
        here and nowhere else.
        """
        return await self._request(
            "am_alerts",
            self.settings.alertmanager_base.rstrip("/") + "/api/v2/alerts",
            params={"active": "true", "silenced": "false", "inhibited": "false"},
        )

    async def classifier_health(self) -> ProbeResult:
        return await self._request(
            "classifier_health",
            self.settings.classifier_base.rstrip("/") + "/healthz",
            kind="json",
        )

    async def engine_healer_health(self) -> ProbeResult:
        return await self._request(
            "engine_healer_health",
            self.settings.engine_healer_base.rstrip("/") + "/healthz",
            kind="json",
        )

    async def engine_healer_decisions(self) -> ProbeResult:
        return await self._request(
            "engine_healer_decisions",
            self.settings.engine_healer_base.rstrip("/") + "/decisions",
            kind="json",
        )


def _short_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.ConnectError):
        return "connection failed"
    return str(exc)[:160]
