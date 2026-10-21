"""Strict request/response models for the goals API.

Every request model forbids unknown fields. Target, identity, plan and risk are
server-resolved; none of them may be supplied by the browser.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GoalStatus = Literal[
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
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetRef(_Strict):
    vmid: int = Field(ge=1, le=999_999)


class RecoverVariables(_Strict):
    reason: str = Field(min_length=1, max_length=200)
    expected_effect: Literal["running", "reachable"] = "running"
    allow_reset: bool = False

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class PreviewRequest(_Strict):
    template_id: str = Field(min_length=1, max_length=64)
    target: TargetRef
    goal: str = Field(default="", max_length=1000)
    variables: RecoverVariables


class CreateGoalRequest(_Strict):
    preview_id: str = Field(min_length=1, max_length=64)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=128)


class ApproveRequest(_Strict):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_code: str = Field(min_length=8, max_length=64)
    confirm: bool = False
    high_risk_passphrase: str = Field(default="", max_length=256)
    confirmation: str = Field(default="", max_length=128)


class RejectRequest(_Strict):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class CancelRequest(_Strict):
    reason: str = Field(min_length=1, max_length=300)


class ExecuteRequest(_Strict):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False


class PlanTarget(_Strict):
    vmid: int
    name: str = ""
    node: str
    guest_type: Literal["vm", "ct"]
    status: str


class PlanStep(BaseModel):
    step_id: str
    action: Literal["start", "resume", "reset", "noop", "escalate"]
    target: PlanTarget
    params: dict[str, Any] = Field(default_factory=dict)
    expected_effect: str = "running"
    risk: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = True


class Plan(BaseModel):
    template_id: str
    template_version: str
    goal: str = ""
    target: PlanTarget
    variables: dict[str, Any]
    steps: list[PlanStep]
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
    generated_by: Literal["rules", "llm"] = "rules"
    evidence_hash: str = ""


class TemplateVariable(BaseModel):
    name: str
    type: str
    required: bool = False
    max_length: int | None = None
    enum: list[str] = Field(default_factory=list)
    default: Any = None
    description: str = ""


class ManualSecret(BaseModel):
    name: str
    description: str


class TemplateInfo(BaseModel):
    id: str
    version: str
    name: str
    description: str
    target_kind: str
    actions: list[str]
    max_steps: int
    variables: list[TemplateVariable]
    manual_secrets: list[ManualSecret]
    execution_enabled: bool = False


class TemplatesResponse(BaseModel):
    templates: list[TemplateInfo]


class PreviewResponse(BaseModel):
    preview_id: str
    status: Literal["ready", "needs_input", "blocked"]
    plan: dict[str, Any]
    plan_hash: str
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    blocked_reason: str = ""
    expires_at: str


class ApprovalRequirements(BaseModel):
    approval_code: bool = True
    confirm: bool = True
    high_risk: bool = False
    passphrase_required: bool = False
    typed_confirmation: str = ""


class GoalView(BaseModel):
    id: str
    status: GoalStatus
    template_id: str
    template_version: str = ""
    target: dict[str, Any] = Field(default_factory=dict)
    goal: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str = ""
    evidence_hash: str = ""
    warnings: list[str] = Field(default_factory=list)
    requested_by: str = ""
    requested_by_sub: str = ""
    requested_at: str = ""
    expires_at: str = ""
    approved_by: str = ""
    approved_at: str = ""
    rejected_by: str = ""
    rejected_at: str = ""
    reject_reason: str = ""
    execute_before: str = ""
    run: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    can_approve: bool = False
    can_execute: bool = False
    approval_mode: str = ""
    execution_enabled: bool = False
    high_risk: bool = False
    requirements: ApprovalRequirements = Field(default_factory=ApprovalRequirements)


class GoalCreated(GoalView):
    approval_code: str | None = None
    idempotent_replay: bool = False


class GoalList(BaseModel):
    goals: list[GoalView]
    next_cursor: str | None = None


class AuditEntry(BaseModel):
    ts: str
    goal_id: str
    actor: str
    actor_sub: str
    actor_method: str
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)
    client_ip: str = ""
    user_agent: str = ""


class AuditResponse(BaseModel):
    goal_id: str
    events: list[AuditEntry]


class ActionResponse(BaseModel):
    ok: bool = True
    goal: GoalView
    message: str = ""
