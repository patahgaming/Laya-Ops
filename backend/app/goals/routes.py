"""HTTP API for AI Goals.

Included only when ``GOALS_ENABLED=true``. CSRF, same-origin and body-size
checks are enforced by ``RequestGuardMiddleware`` for every unsafe request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from ..auth import require_approver, require_user
from .schemas import (
    ActionResponse,
    ApproveRequest,
    AuditResponse,
    CancelRequest,
    CreateGoalRequest,
    ExecuteRequest,
    GoalCreated,
    GoalList,
    GoalView,
    PreviewRequest,
    PreviewResponse,
    RejectRequest,
    TemplatesResponse,
)
from .service import Actor, GoalService

ALLOWED_STATUS = {
    "pending_approval",
    "approved",
    "dispatching",
    "executing",
    "succeeded",
    "failed",
    "unknown",
    "rejected",
    "cancelled",
    "expired",
}


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/goals",
    tags=["goals"],
    dependencies=[Depends(require_user), Depends(_no_store)],
)


def _service(request: Request) -> GoalService:
    return request.app.state.goals


def _actor(request: Request) -> Actor:
    return Actor.from_user(require_user(request), request)


@router.get("/templates", response_model=TemplatesResponse)
async def templates(request: Request) -> TemplatesResponse:
    return _service(request).templates()


@router.post("/preview", response_model=PreviewResponse)
async def preview(request: Request, payload: PreviewRequest) -> PreviewResponse:
    return await _service(request).preview(_actor(request), payload)


@router.post("", response_model=GoalCreated)
async def create(request: Request, payload: CreateGoalRequest) -> GoalCreated:
    return await _service(request).create(_actor(request), payload)


@router.get("", response_model=GoalList)
async def list_goals(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=20),
) -> GoalList:
    if status is not None and status not in ALLOWED_STATUS:
        status = None
    return _service(request).list(_actor(request), status=status, limit=limit, cursor=cursor)


@router.get("/{goal_id}", response_model=GoalView)
async def get_goal(request: Request, goal_id: str) -> GoalView:
    return _service(request).get(_actor(request), goal_id)


@router.get("/{goal_id}/audit", response_model=AuditResponse)
async def get_audit(request: Request, goal_id: str) -> AuditResponse:
    events = _service(request).audit(_actor(request), goal_id)
    return AuditResponse(goal_id=goal_id, events=events)  # type: ignore[arg-type]


@router.post("/{goal_id}/approve", response_model=ActionResponse)
async def approve(
    request: Request, goal_id: str, payload: ApproveRequest
) -> ActionResponse:
    user = require_approver(request)
    goal = await _service(request).approve(Actor.from_user(user, request), goal_id, payload)
    return ActionResponse(goal=goal, message="approved")


@router.post("/{goal_id}/reject", response_model=ActionResponse)
async def reject(
    request: Request, goal_id: str, payload: RejectRequest
) -> ActionResponse:
    user = require_approver(request)
    goal = await _service(request).reject(Actor.from_user(user, request), goal_id, payload)
    return ActionResponse(goal=goal, message="rejected")


@router.post("/{goal_id}/cancel", response_model=ActionResponse)
async def cancel(
    request: Request, goal_id: str, payload: CancelRequest
) -> ActionResponse:
    goal = await _service(request).cancel(_actor(request), goal_id, payload)
    return ActionResponse(goal=goal, message="cancelled")


@router.post("/{goal_id}/execute", response_model=ActionResponse)
async def execute(
    request: Request, goal_id: str, payload: ExecuteRequest
) -> ActionResponse:
    user = require_approver(request)
    _service(request).execute(Actor.from_user(user, request), goal_id, payload.plan_hash)
    return ActionResponse(goal=_service(request).get(Actor.from_user(user, request), goal_id))


@router.post("/{goal_id}/reconcile", response_model=ActionResponse)
async def reconcile(request: Request, goal_id: str) -> ActionResponse:
    user = require_approver(request)
    actor = Actor.from_user(user, request)
    _service(request).reconcile(actor, goal_id)
    return ActionResponse(goal=_service(request).get(actor, goal_id))
