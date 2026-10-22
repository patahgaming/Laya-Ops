"""Response schemas shared by the API and the React frontend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceStatus(BaseModel):
    name: str
    url: str
    ok: bool
    ms: int
    error: str | None = None
    detail: str | None = None


class Targets(BaseModel):
    up: int = 0
    total: int = 0
    down: int = 0
    error: str | None = None


class Summary(BaseModel):
    total: int = 0
    running: int = 0
    stopped: int = 0
    insiden_24h: int = 0
    aksi_24h: int = 0
    pulih_24h: int = 0
    eskalasi_24h: int = 0
    menunggu_persetujuan: int = 0
    goal_24h: int = 0
    dry: bool = False
    targets: Targets = Field(default_factory=Targets)


class Decision(BaseModel):
    ts: str = ""
    time: str = ""
    target: str = "—"
    aksi: str = "—"
    sumber: str = "—"
    hasil: str = "—"
    alasan: str = ""
    ket: str = ""
    vmid: int | None = None
    nama: str | None = None
    node: str | None = None
    jenis: str = ""
    tingkat: str = ""
    izin: str = ""
    jenis_guest: str = ""
    status: str = ""
    agent: bool | None = None
    oleh: str = ""
    state: str = ""
    dry: bool = False
    plan_id: str = ""
    plan_hash: str = ""


class Guest(BaseModel):
    vmid: int
    name: str | None = None
    node: str = ""
    status: str = "unknown"
    sejak: str = ""
    agent_ok: bool = False
    agent_gagal: int = 0
    guest_type: str = ""
    agent: bool | None = None
    last_action: Decision | None = None


class Guests(BaseModel):
    total: int = 0
    running: int = 0
    stopped: int = 0
    nodes: dict[str, int] = Field(default_factory=dict)
    guests: list[Guest] = Field(default_factory=list)


class Job(BaseModel):
    job: str = ""
    up: int = 0
    down: int = 0


class Runbook(BaseModel):
    note: str = ""
    lines: list[str] = Field(default_factory=list)


class AlertGroup(BaseModel):
    name: str
    severity: Literal["critical", "warning", "info", "none"] = "warning"
    instances: int = 0
    namespaces: list[str] = Field(default_factory=list)
    jobs: list[str] = Field(default_factory=list)
    oldest_seconds: int | None = None
    runbook: Runbook = Field(default_factory=Runbook)


class PushedAlert(BaseModel):
    alertname: str = ""
    severity: str = "warning"
    status: str = "active"
    summary: str = ""
    description: str = ""
    starts_at: str = ""
    ends_at: str = ""
    fingerprint: str = ""
    labels: dict[str, str] = Field(default_factory=dict)


class AlertSummary(BaseModel):
    ok: bool = False
    instances: int = 0
    counts: dict[str, int] = Field(default_factory=lambda: {"critical": 0, "warning": 0, "info": 0, "none": 0})
    groups: list[AlertGroup] = Field(default_factory=list)
    pushed: list[PushedAlert] = Field(default_factory=list)
    pushed_ok: bool = False


class MetricCounter(BaseModel):
    labels: dict[str, str] = Field(default_factory=dict)
    value: int = 0


class Metrics(BaseModel):
    healer_up: int | None = None
    healer_dry: int | None = None
    pending: int | None = None
    action_totals: list[MetricCounter] = Field(default_factory=list)
    incident_totals: list[MetricCounter] = Field(default_factory=list)
    approval_totals: list[MetricCounter] = Field(default_factory=list)
    escalation_total: int | None = None
    k8s_action_totals: list[MetricCounter] = Field(default_factory=list)
    k8s_escalation_totals: list[MetricCounter] = Field(default_factory=list)
    node_failures: list[MetricCounter] = Field(default_factory=list)


class PendingApproval(BaseModel):
    vmid: int | None = None
    nama: str = ""
    node: str = ""
    jenis: str = ""
    jenis_guest: str = ""
    status: str = ""
    aksi: str = ""
    sumber: str = ""
    alasan: str = ""
    diminta: str = ""
    kedaluwarsa: str = ""
    seconds_left: int | None = None
    approved: bool = False
    approved_at: str = ""
    oleh: str = ""


class PendingResponse(BaseModel):
    generated_at: str
    ok: bool = True
    count: int = 0
    pending: list[PendingApproval] = Field(default_factory=list)


class ClassifierHealth(BaseModel):
    configured: bool = False
    ok: bool = False
    model: str = ""
    ms: int = 0
    error: str | None = None


class EngineDecision(BaseModel):
    ts: str = ""
    time: str = ""
    jenis: str = ""
    target: str = ""
    kelas: str = ""
    keterangan: str = ""
    confidence: float | None = None
    aksi: str = ""
    hasil: str = ""
    dry_run: bool = False
    error: str = ""


class EngineHealer(BaseModel):
    configured: bool = False
    ok: bool = False
    ms: int = 0
    error: str | None = None
    decisions: list[EngineDecision] = Field(default_factory=list)


class Overview(BaseModel):
    generated_at: str
    degraded: bool = False
    links: dict[str, str] = Field(default_factory=dict)
    summary: Summary = Field(default_factory=Summary)
    guests: Guests = Field(default_factory=Guests)
    alerts: AlertSummary = Field(default_factory=AlertSummary)
    jobs: list[Job] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    endpoints: list[SourceStatus] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)


class StatusAlerts(BaseModel):
    instances: int = 0
    counts: dict[str, int] = Field(default_factory=lambda: {"critical": 0, "warning": 0, "info": 0, "none": 0})


class Status(BaseModel):
    generated_at: str
    ok: bool = True
    degraded: bool = False
    summary: Summary = Field(default_factory=Summary)
    alerts: StatusAlerts = Field(default_factory=StatusAlerts)
    jobs_down: int = 0
    healer_up: int | None = None


class GuestsResponse(BaseModel):
    generated_at: str
    guests: Guests
    decisions: list[Decision] = Field(default_factory=list)


class AlertsResponse(BaseModel):
    generated_at: str
    ok: bool = False
    instances: int = 0
    counts: dict[str, int] = Field(default_factory=lambda: {"critical": 0, "warning": 0, "info": 0, "none": 0})
    groups: list[AlertGroup] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    pushed: list[PushedAlert] = Field(default_factory=list)
    pushed_ok: bool = False


class KnobsResponse(BaseModel):
    generated_at: str
    links: dict[str, str] = Field(default_factory=dict)
    knobs: dict[str, Any] = Field(default_factory=dict)
    metrics: Metrics = Field(default_factory=Metrics)
    last_decision: Decision | None = None
    summary: Summary = Field(default_factory=Summary)
    pending: list[PendingApproval] = Field(default_factory=list)
    pending_ok: bool = False
    classifier: ClassifierHealth = Field(default_factory=ClassifierHealth)
    engine: EngineHealer = Field(default_factory=EngineHealer)


class DecisionsResponse(BaseModel):
    generated_at: str
    decisions: list[Decision] = Field(default_factory=list)


class PlaneInfo(BaseModel):
    name: str = ""
    site: str = ""
    host: str = ""
    ssh_user: str = "root"


class UserInfo(BaseModel):
    name: str = ""
    email: str = ""
    method: str = ""
    sub: str = ""
    groups: list[str] = Field(default_factory=list)


class FeatureFlags(BaseModel):
    goals: bool = False
    goals_execute: bool = False
    goals_llm: bool = False
    password_single_person: bool = False


class AuthInfo(BaseModel):
    mode: Literal["off", "password", "oidc"]
    user: UserInfo | None = None
    provider: str = "None"
    login_url: str | None = None
    app_name: str = ""
    app_version: str = ""
    plane: PlaneInfo = Field(default_factory=PlaneInfo)
    csrf_token: str = ""
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    can_approve: bool = False


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(default="", max_length=1024)


class Message(BaseModel):
    ok: bool = True
    message: str = ""
