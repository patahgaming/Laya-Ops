"""Aggregation + normalisation of the read-only upstream data.

Everything the UI shows is built here from the healer API, Prometheus and the
service health probes. No write path exists.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .schemas import (
    AlertGroup,
    AlertsResponse,
    AlertSummary,
    Decision,
    DecisionsResponse,
    Guest,
    Guests,
    GuestsResponse,
    Job,
    KnobsResponse,
    Metrics,
    Overview,
    Runbook,
    SourceStatus,
    Status,
    StatusAlerts,
    Summary,
    Targets,
)
from .upstream import ProbeResult, Upstream

PROM_ALERTS = 'ALERTS{alertstate="firing"}'
PROM_ALERT_AGE = "ALERTS_FOR_STATE"
PROM_JOBS = "count by (job) (up)"
PROM_JOBS_DOWN = "count by (job) (up == 0)"

SEV_RANK = {"critical": 0, "warning": 1, "info": 2, "none": 3}
SEV_LABEL = {"critical": "critical", "warning": "warning", "info": "info", "none": "watchdog"}

_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")


# --------------------------------------------------------------------------- time


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    match = _OFFSET.search(text)
    if match:
        text = text[: match.start()] + match.group(1) + ":" + match.group(2)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def to_iso(value: str | None) -> str:
    parsed = parse_ts(value)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def hhmm(value: str | None) -> str:
    parsed = parse_ts(value)
    return parsed.strftime("%H:%M") if parsed else "—"


# ------------------------------------------------------------------- normalisers


def parse_summary(raw: Any) -> Summary:
    if not isinstance(raw, dict) or not raw:
        return Summary()
    targets_raw = raw.get("targets")
    targets = Targets()
    if isinstance(targets_raw, dict):
        targets = Targets(
            up=int(targets_raw.get("up") or 0),
            total=int(targets_raw.get("total") or 0),
            down=int(targets_raw.get("down") or 0),
            error=str(targets_raw.get("error")) if targets_raw.get("error") else None,
        )
    return Summary(
        total=int(raw.get("total") or 0),
        running=int(raw.get("running") or 0),
        stopped=int(raw.get("stopped") or 0),
        insiden_24h=int(raw.get("insiden_24j") or raw.get("insiden_24h") or 0),
        aksi_24h=int(raw.get("aksi_24j") or raw.get("aksi_24h") or 0),
        pulih_24h=int(raw.get("pulih_24j") or raw.get("pulih_24h") or 0),
        eskalasi_24h=int(raw.get("eskalasi_24j") or raw.get("eskalasi_24h") or 0),
        dry=bool(raw.get("dry")),
        targets=targets,
    )


def normalize_decision(record: dict[str, Any]) -> Decision:
    vmid_raw = record.get("vmid")
    try:
        vmid = int(vmid_raw) if vmid_raw not in (None, "") else None
    except (TypeError, ValueError):
        vmid = None
    nama = str(record.get("nama") or "") or None
    target = str(record.get("target") or "") or (nama or (f"#{vmid}" if vmid else "—"))
    return Decision(
        ts=to_iso(str(record.get("ts") or "")) or str(record.get("ts") or ""),
        time=hhmm(str(record.get("ts") or "")),
        target=target,
        aksi=str(record.get("aksi") or "—"),
        sumber=str(record.get("sumber") or "—"),
        hasil=str(record.get("hasil") or "—"),
        alasan=str(record.get("alasan") or ""),
        ket=str(record.get("ket") or ""),
        vmid=vmid,
        nama=nama,
        node=str(record.get("node") or "") or None,
        dry=bool(record.get("dry") and record.get("dry") is not False),
    )


def normalize_decisions(raw: Any) -> list[Decision]:
    if not isinstance(raw, list):
        return []
    decisions = [normalize_decision(item) for item in raw if isinstance(item, dict)]
    decisions.sort(key=lambda d: parse_ts(d.ts) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return decisions


def build_guests(state: Any, decisions: list[Decision]) -> Guests:
    if not isinstance(state, dict):
        return Guests()
    last_by_vmid: dict[int, Decision] = {}
    name_by_vmid: dict[int, str] = {}
    for decision in decisions:  # newest first already
        if decision.vmid is None:
            continue
        last_by_vmid.setdefault(decision.vmid, decision)
        if decision.nama:
            name_by_vmid.setdefault(decision.vmid, decision.nama)

    guests: list[Guest] = []
    for key, value in state.items():
        try:
            vmid = int(key)
        except (TypeError, ValueError):
            continue
        row = value if isinstance(value, dict) else {}
        guests.append(
            Guest(
                vmid=vmid,
                name=name_by_vmid.get(vmid),
                node=str(row.get("node") or ""),
                status=str(row.get("status") or "unknown"),
                sejak=str(row.get("sejak") or ""),
                agent_ok=bool(row.get("agent_ok")),
                agent_gagal=int(row.get("agent_gagal") or 0),
                last_action=last_by_vmid.get(vmid),
            )
        )
    guests.sort(key=lambda guest: guest.vmid)
    nodes: dict[str, int] = {}
    for guest in guests:
        nodes[guest.node] = nodes.get(guest.node, 0) + 1
    running = sum(1 for guest in guests if guest.status == "running")
    return Guests(
        total=len(guests),
        running=running,
        stopped=len(guests) - running,
        nodes=nodes,
        guests=guests,
    )


def normalize_alerts(alerts_payload: Any, ages_payload: Any) -> AlertSummary:
    if not isinstance(alerts_payload, dict):
        return AlertSummary(ok=False)
    series = (alerts_payload.get("data") or {}).get("result") or []
    ages = (ages_payload or {}).get("data", {}).get("result") or [] if isinstance(ages_payload, dict) else []
    starts: dict[tuple[str, str], float] = {}
    for item in ages:
        metric = item.get("metric") or {}
        try:
            starts[(str(metric.get("alertname") or ""), str(metric.get("namespace") or ""))] = float(
                item["value"][1]
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    now = time.time()
    counts = {"critical": 0, "warning": 0, "info": 0, "none": 0}
    groups: dict[str, dict[str, Any]] = {}
    for item in series:
        metric = item.get("metric") or {}
        name = str(metric.get("alertname") or "")
        if not name:
            continue
        severity = str(metric.get("severity") or "warning")
        if severity not in counts:
            severity = "warning"
        counts[severity] += 1

        group = groups.get(name)
        if group is None:
            group = {
                "name": name,
                "severity": severity,
                "rank": SEV_RANK.get(severity, 9),
                "instances": 0,
                "namespaces": set(),
                "jobs": set(),
                "oldest": None,
            }
            groups[name] = group
        if SEV_RANK.get(severity, 9) < group["rank"]:
            group["rank"] = SEV_RANK.get(severity, 9)
            group["severity"] = severity
        group["instances"] += 1
        namespace = metric.get("namespace")
        if namespace:
            group["namespaces"].add(str(namespace))
        job = metric.get("job")
        if job:
            group["jobs"].add(str(job))
        started = starts.get((name, str(namespace or "")))
        if started:
            age = int(max(0, now - started))
            if group["oldest"] is None or age > group["oldest"]:
                group["oldest"] = age

    ordered = sorted(groups.values(), key=lambda g: (g["rank"], -g["instances"]))
    out: list[AlertGroup] = []
    for group in ordered:
        namespaces = sorted(group["namespaces"])
        out.append(
            AlertGroup(
                name=group["name"],
                severity=group["severity"],  # type: ignore[arg-type]
                instances=group["instances"],
                namespaces=namespaces,
                jobs=sorted(group["jobs"]),
                oldest_seconds=group["oldest"],
                runbook=runbook_for(group["name"], namespaces),
            )
        )
    return AlertSummary(ok=True, instances=len(series), counts=counts, groups=out)


def normalize_jobs(up_payload: Any, down_payload: Any) -> list[Job]:
    if not isinstance(up_payload, dict):
        return []
    up = (up_payload.get("data") or {}).get("result") or []
    down = (down_payload or {}).get("data", {}).get("result") or [] if isinstance(down_payload, dict) else []
    down_by_job: dict[str, int] = {}
    for item in down:
        metric = item.get("metric") or {}
        try:
            down_by_job[str(metric.get("job") or "")] = int(float(item["value"][1]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    jobs: list[Job] = []
    for item in up:
        metric = item.get("metric") or {}
        try:
            jobs.append(
                Job(
                    job=str(metric.get("job") or ""),
                    up=int(float(item["value"][1])),
                    down=down_by_job.get(str(metric.get("job") or ""), 0),
                )
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    jobs.sort(key=lambda job: (-job.up, job.job))
    return jobs


def parse_metrics(text: Any) -> Metrics:
    if not isinstance(text, str):
        return Metrics()

    def grab(pattern: str) -> int | None:
        match = re.search(pattern, text, re.MULTILINE)
        return int(float(match.group(1))) if match else None

    return Metrics(
        healer_up=grab(r"^pve_healer_up\s+([\d.]+)"),
        healer_dry=grab(r"^pve_healer_dry_run\s+([\d.]+)"),
    )


# -------------------------------------------------------------------- runbooks

RUNBOOKS: list[dict[str, Any]] = [
    {
        "test": r"^InfraSubdomainDead$",
        "note": "Exporter hostname/lease broker: verify the lease timer and the broker record for the exporter host.",
        "lines": [
            "ssh root@10.10.0.107 'systemctl list-timers | grep -i dns'",
            "ssh root@10.10.0.107 'tail -n 30 /var/log/dns-broker.log 2>/dev/null || true'",
            "curl -s http://10.10.0.107:9090/api/v1/query?query=pve_healer_up",
        ],
    },
    {
        "test": r"^(KubePodNotReady|InfraPodFailed|KubeContainerWaiting)$",
        "note": "Pod-level failure. Read-only triage; healer only acts when a previous revision exists.",
        "lines": [
            "kubectl -n <ns> get pods -o wide",
            "kubectl -n <ns> describe pod <pod>",
            "kubectl -n <ns> logs <pod> --tail=50 --previous",
        ],
    },
    {
        "test": r"^(KubeDeploymentReplicasMismatch|InfraDeploymentReplicasMismatch|KubeDeploymentRolloutStuck)$",
        "note": "Rollout is not converging. If a prior revision exists the healer may already have run rollout_undo.",
        "lines": [
            "kubectl -n <ns> rollout status deploy/<name>",
            "kubectl -n <ns> rollout history deploy/<name>",
            "kubectl -n <ns> get rs,pods -o wide",
        ],
    },
    {
        "test": r"^KubePdbNotEnoughHealthyPods$",
        "note": "PodDisruptionBudget is protecting the workload; do not drain nodes until pods recover.",
        "lines": [
            "kubectl -n <ns> get pdb",
            "kubectl -n <ns> describe pdb <name>",
        ],
    },
    {
        "test": r"^Watchdog$",
        "note": "Watchdog is always firing on purpose — it proves the Alertmanager delivery path is alive.",
        "lines": [
            "curl -s http://10.10.0.107:9093/-/ready",
            "curl -s http://10.10.0.107:9093/api/v2/alerts | head -c 600",
        ],
    },
]


def runbook_for(alert_name: str, namespaces: list[str]) -> Runbook:
    namespace = namespaces[0] if namespaces else "default"
    for entry in RUNBOOKS:
        if re.search(entry["test"], alert_name):
            lines = [line.replace("<ns>", namespace).replace("<alert>", alert_name) for line in entry["lines"]]
            return Runbook(note=entry["note"], lines=lines)
    return Runbook(
        note="No specific runbook mapped for this alert — start from the alert labels and recent decisions.",
        lines=[
            'curl -s http://10.10.0.107:9090/api/v1/alerts | jq \'.data.alerts[] | select(.labels.alertname=="<alert>") | {labels, annotations, state, activeAt}\'',
            "kubectl get events -A --sort-by=.lastTimestamp | tail -20",
        ],
    )


# --------------------------------------------------------------------- gathering


async def _gather(probes: dict[str, Awaitable[ProbeResult]]) -> dict[str, ProbeResult]:
    keys = list(probes)
    results = await asyncio.gather(*probes.values(), return_exceptions=True)
    out: dict[str, ProbeResult] = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            out[key] = ProbeResult(name=key, url="", ok=False, ms=0, error=str(result)[:160])
        else:
            out[key] = result
    return out


def _endpoints(results: dict[str, ProbeResult]) -> list[SourceStatus]:
    return [
        SourceStatus(name=result.name, url=result.url, ok=result.ok, ms=result.ms, error=result.error)
        for result in results.values()
    ]


async def gather_overview(upstream: Upstream, settings: Settings) -> Overview:
    results = await _gather(
        {
            "summary": upstream.healer("summary", "/api/summary"),
            "state": upstream.healer("state", "/api/state"),
            "decisions": upstream.healer("decisions", "/api/decisions?n=200"),
            "knobs": upstream.healer("knobs", "/api/knobs"),
            "metrics": upstream.healer_text("metrics", "/metrics"),
            "alerts": upstream.prom("alerts", PROM_ALERTS),
            "alert_age": upstream.prom("alert_age", PROM_ALERT_AGE),
            "jobs": upstream.prom("jobs", PROM_JOBS),
            "jobs_down": upstream.prom("jobs_down", PROM_JOBS_DOWN),
            "prometheus_ready": upstream.ready("prometheus_ready", settings.prometheus_base),
            "alertmanager_ready": upstream.ready("alertmanager_ready", settings.alertmanager_base),
            "grafana_health": upstream.grafana_health(),
        }
    )
    decisions = normalize_decisions(results["decisions"].value if results["decisions"].ok else [])
    summary = parse_summary(results["summary"].value if results["summary"].ok else None)
    alerts = normalize_alerts(
        results["alerts"].value if results["alerts"].ok else None,
        results["alert_age"].value if results["alert_age"].ok else None,
    )
    jobs = normalize_jobs(
        results["jobs"].value if results["jobs"].ok else None,
        results["jobs_down"].value if results["jobs_down"].ok else None,
    )
    return Overview(
        generated_at=now_iso(),
        degraded=not results["summary"].ok or not results["alerts"].ok,
        links=settings.links,
        summary=summary,
        guests=build_guests(results["state"].value if results["state"].ok else {}, decisions),
        alerts=alerts,
        jobs=jobs,
        decisions=decisions,
        endpoints=_endpoints(results),
        metrics=parse_metrics(results["metrics"].value if results["metrics"].ok else None),
    )


async def gather_status(upstream: Upstream, settings: Settings) -> Status:
    results = await _gather(
        {
            "summary": upstream.healer("summary", "/api/summary"),
            "alerts": upstream.prom("alerts", PROM_ALERTS),
            "jobs_down": upstream.prom("jobs_down", PROM_JOBS_DOWN),
            "metrics": upstream.healer_text("metrics", "/metrics"),
        }
    )
    summary = parse_summary(results["summary"].value if results["summary"].ok else None)
    alerts = normalize_alerts(
        results["alerts"].value if results["alerts"].ok else None,
        None,
    )
    jobs_down = 0
    if results["jobs_down"].ok:
        series = (results["jobs_down"].value or {}).get("data", {}).get("result") or []
        for item in series:
            try:
                jobs_down += int(float(item["value"][1]))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
    metrics = parse_metrics(results["metrics"].value if results["metrics"].ok else None)
    return Status(
        generated_at=now_iso(),
        ok=results["summary"].ok,
        degraded=not results["summary"].ok or not results["alerts"].ok,
        summary=summary,
        alerts=StatusAlerts(instances=alerts.instances, counts=alerts.counts),
        jobs_down=jobs_down,
        healer_up=metrics.healer_up,
    )


async def gather_guests(upstream: Upstream) -> GuestsResponse:
    results = await _gather(
        {
            "state": upstream.healer("state", "/api/state"),
            "decisions": upstream.healer("decisions", "/api/decisions?n=200"),
        }
    )
    decisions = normalize_decisions(results["decisions"].value if results["decisions"].ok else [])
    guests = build_guests(results["state"].value if results["state"].ok else {}, decisions)
    return GuestsResponse(generated_at=now_iso(), guests=guests, decisions=decisions)


async def gather_alerts(upstream: Upstream, settings: Settings) -> AlertsResponse:
    results = await _gather(
        {
            "alerts": upstream.prom("alerts", PROM_ALERTS),
            "alert_age": upstream.prom("alert_age", PROM_ALERT_AGE),
        }
    )
    alerts = normalize_alerts(
        results["alerts"].value if results["alerts"].ok else None,
        results["alert_age"].value if results["alert_age"].ok else None,
    )
    return AlertsResponse(
        generated_at=now_iso(),
        ok=alerts.ok,
        instances=alerts.instances,
        counts=alerts.counts,
        groups=alerts.groups,
        links=settings.links,
    )


async def gather_knobs(upstream: Upstream) -> KnobsResponse:
    results = await _gather(
        {
            "knobs": upstream.healer("knobs", "/api/knobs"),
            "summary": upstream.healer("summary", "/api/summary"),
            "metrics": upstream.healer_text("metrics", "/metrics"),
            "decisions": upstream.healer("decisions", "/api/decisions?n=1"),
        }
    )
    decisions = normalize_decisions(results["decisions"].value if results["decisions"].ok else [])
    return KnobsResponse(
        generated_at=now_iso(),
        knobs=results["knobs"].value if results["knobs"].ok and isinstance(results["knobs"].value, dict) else {},
        metrics=parse_metrics(results["metrics"].value if results["metrics"].ok else None),
        last_decision=decisions[0] if decisions else None,
        summary=parse_summary(results["summary"].value if results["summary"].ok else None),
    )


async def gather_decisions(upstream: Upstream, limit: int) -> DecisionsResponse:
    result = await upstream.healer("decisions", f"/api/decisions?n={limit}")
    decisions = normalize_decisions(result.value if result.ok else [])
    return DecisionsResponse(generated_at=now_iso(), decisions=decisions)


async def gather_raw(upstream: Upstream, sources: set[str]) -> dict[str, Any]:
    """Raw upstream payloads for the debugging page. Read-only and whitelisted."""
    probes: dict[str, Awaitable[ProbeResult]] = {}
    if "summary" in sources:
        probes["summary"] = upstream.healer("summary", "/api/summary")
    if "state" in sources:
        probes["state"] = upstream.healer("state", "/api/state")
    if "knobs" in sources:
        probes["knobs"] = upstream.healer("knobs", "/api/knobs")
    if "decisions" in sources:
        probes["decisions"] = upstream.healer("decisions", "/api/decisions?n=100")
    if "metrics" in sources:
        probes["metrics"] = upstream.healer_text("metrics", "/metrics")
    if "alerts" in sources:
        probes["alerts"] = upstream.prom("alerts", PROM_ALERTS)
    if "jobs" in sources:
        probes["jobs"] = upstream.prom("jobs", PROM_JOBS)
    results = await _gather(probes)
    return {
        name: {
            "ok": result.ok,
            "ms": result.ms,
            "url": result.url,
            "error": result.error,
            "value": result.value,
        }
        for name, result in results.items()
    }
