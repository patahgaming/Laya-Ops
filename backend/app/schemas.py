"""Response schemas shared by the API and the React frontend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceStatus(BaseModel):
    name: str
    url: str
    ok: bool
    ms: int
    error: str | None = None


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
    dry: bool = False


class Guest(BaseModel):
    vmid: int
    name: str | None = None
    node: str = ""
    status: str = "unknown"
    sejak: str = ""
    agent_ok: bool = False
    agent_gagal: int = 0
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


class AlertSummary(BaseModel):
    ok: bool = False
    instances: int = 0
    counts: dict[str, int] = Field(default_factory=lambda: {"critical": 0, "warning": 0, "info": 0, "none": 0})
    groups: list[AlertGroup] = Field(default_factory=list)


class Metrics(BaseModel):
    healer_up: int | None = None
    healer_dry: int | None = None


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


class KnobsResponse(BaseModel):
    generated_at: str
    knobs: dict[str, Any] = Field(default_factory=dict)
    metrics: Metrics = Field(default_factory=Metrics)
    last_decision: Decision | None = None
    summary: Summary = Field(default_factory=Summary)


class DecisionsResponse(BaseModel):
    generated_at: str
    decisions: list[Decision] = Field(default_factory=list)


class AuthInfo(BaseModel):
    mode: Literal["off", "password", "oidc"]
    user: dict[str, str] | None = None
    provider: str = "None"
    login_url: str | None = None


class LoginRequest(BaseModel):
    password: str = ""


class Message(BaseModel):
    ok: bool = True
    message: str = ""
