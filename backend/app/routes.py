"""Read-only JSON API. Every route depends on auth unless auth_mode=off."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .aggregate import (
    gather_alerts,
    gather_decisions,
    gather_guests,
    gather_knobs,
    gather_overview,
    gather_pending,
    gather_raw,
    gather_status,
)
from .auth import require_user
from .schemas import (
    AlertsResponse,
    DecisionsResponse,
    GuestsResponse,
    KnobsResponse,
    Overview,
    PendingResponse,
    Status,
)

router = APIRouter(prefix="/api", tags=["plane"], dependencies=[Depends(require_user)])

RAW_SOURCES = {
    "summary",
    "state",
    "knobs",
    "decisions",
    "metrics",
    "pending",
    "alerts",
    "push_alerts",
    "jobs",
}


def _cache(request: Request):
    return request.app.state.cache


def _ttl(request: Request) -> float:
    return request.app.state.settings.cache_ttl


@router.get("/overview", response_model=Overview)
async def overview(request: Request) -> Overview:
    return await _cache(request).get_or_create(
        "overview",
        _ttl(request),
        lambda: gather_overview(request.app.state.upstream, request.app.state.settings),
    )


@router.get("/status", response_model=Status)
async def status(request: Request) -> Status:
    return await _cache(request).get_or_create(
        "status",
        min(_ttl(request), 3.0),
        lambda: gather_status(request.app.state.upstream, request.app.state.settings),
    )


@router.get("/guests", response_model=GuestsResponse)
async def guests(request: Request) -> GuestsResponse:
    return await _cache(request).get_or_create(
        "guests",
        _ttl(request),
        lambda: gather_guests(request.app.state.upstream),
    )


@router.get("/alerts", response_model=AlertsResponse)
async def alerts(request: Request) -> AlertsResponse:
    return await _cache(request).get_or_create(
        "alerts",
        _ttl(request),
        lambda: gather_alerts(request.app.state.upstream, request.app.state.settings),
    )


@router.get("/knobs", response_model=KnobsResponse)
async def knobs(request: Request) -> KnobsResponse:
    return await _cache(request).get_or_create(
        "knobs",
        _ttl(request),
        lambda: gather_knobs(request.app.state.upstream, request.app.state.settings),
    )


@router.get("/pending", response_model=PendingResponse)
async def pending(request: Request) -> PendingResponse:
    return await _cache(request).get_or_create(
        "pending",
        _ttl(request),
        lambda: gather_pending(request.app.state.upstream),
    )


@router.get("/decisions", response_model=DecisionsResponse)
async def decisions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> DecisionsResponse:
    return await _cache(request).get_or_create(
        f"decisions:{limit}",
        _ttl(request),
        lambda: gather_decisions(request.app.state.upstream, limit),
    )


@router.get("/raw")
async def raw(
    request: Request,
    sources: str = Query(default="summary,state,knobs,decisions"),
) -> dict:
    requested = {part.strip() for part in sources.split(",") if part.strip()}
    unknown = requested - RAW_SOURCES
    if unknown:
        requested = requested & RAW_SOURCES
    if not requested:
        requested = {"summary"}
    return await _cache(request).get_or_create(
        "raw:" + ",".join(sorted(requested)),
        _ttl(request),
        lambda: gather_raw(request.app.state.upstream, requested),
    )
