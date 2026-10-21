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
    ClassifierHealth,
    Decision,
    DecisionsResponse,
    EngineDecision,
    EngineHealer,
    Guest,
    Guests,
    GuestsResponse,
    Job,
    KnobsResponse,
    MetricCounter,
    Metrics,
    Overview,
    PendingApproval,
    PendingResponse,
    PushedAlert,
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


def epoch_iso(value: Any) -> str:
    """Epoch seconds (healer approvals / sre-healer decisions) -> ISO-8601 UTC."""
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return to_iso(str(value))


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
        menunggu_persetujuan=int(raw.get("menunggu_persetujuan") or 0),
        goal_24h=int(raw.get("goal_24j") or raw.get("goal_24h") or 0),
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
    agent = record.get("agent")
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
        jenis=str(record.get("jenis") or ""),
        tingkat=str(record.get("tingkat") or ""),
        izin=str(record.get("izin") or ""),
        jenis_guest=str(record.get("jenis_guest") or ""),
        status=str(record.get("status") or ""),
        agent=bool(agent) if isinstance(agent, bool) else None,
        oleh=str(record.get("oleh") or ""),
        state=str(record.get("state") or ""),
        dry=bool(record.get("dry") and record.get("dry") is not False),
        plan_id=str(record.get("plan_id") or ""),
        plan_hash=str(record.get("plan_hash") or ""),
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
        guest_type = str(row.get("jenis") or row.get("jenis_guest") or "")
        raw_agent = row.get("agent")
        guests.append(
            Guest(
                vmid=vmid,
                name=str(row.get("nama") or "") or name_by_vmid.get(vmid),
                node=str(row.get("node") or ""),
                status=str(row.get("status") or "unknown"),
                sejak=str(row.get("sejak") or ""),
                agent_ok=bool(row.get("agent_ok")),
                agent_gagal=int(row.get("agent_gagal") or 0),
                guest_type=guest_type,
                agent=raw_agent if isinstance(raw_agent, bool) else None,
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


def normalize_alerts(
    alerts_payload: Any,
    ages_payload: Any,
    pushed_payload: Any = None,
    pushed_ok: bool = False,
) -> AlertSummary:
    pushed = normalize_pushed_alerts(pushed_payload) if pushed_ok else []
    if not isinstance(alerts_payload, dict):
        return AlertSummary(ok=False, pushed=pushed, pushed_ok=pushed_ok)
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
    return AlertSummary(
        ok=True,
        instances=len(series),
        counts=counts,
        groups=out,
        pushed=pushed,
        pushed_ok=pushed_ok,
    )


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


# Proxmox healer serialises prometheus labels positionally as a/b/c.
_METRIC_LABELS = {
    "pve_healer_aksi_total": {"a": "aksi", "b": "sumber", "c": "hasil"},
    "pve_healer_k8s_aksi_total": {"a": "aksi", "b": "hasil"},
    "pve_healer_insiden_total": {"a": "jenis"},
    "pve_healer_k8s_insiden_total": {"a": "namespace"},
    "pve_healer_persetujuan_total": {"a": "status"},
    "pve_healer_node_gagal_total": {"a": "node"},
    "pve_healer_k8s_eskalasi_total": {"a": "alasan"},
}
_METRIC_LINE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$"
)
_METRIC_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def _parse_metrics_text(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    samples: dict[str, list[tuple[dict[str, str], float]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE.match(line)
        if not match:
            continue
        name, label_blob, raw_value = match.groups()
        labels = {
            key: value.replace('\\"', '"').replace("\\\\", "\\")
            for key, value in _METRIC_LABEL.findall(label_blob or "")
        }
        try:
            value = float(raw_value)
        except ValueError:
            continue
        samples.setdefault(name, []).append((labels, value))
    return samples


def _counters(
    samples: dict[str, list[tuple[dict[str, str], float]]], name: str
) -> list[MetricCounter]:
    mapping = _METRIC_LABELS.get(name, {})
    out = [
        MetricCounter(
            labels={mapping.get(key, key): value for key, value in labels.items()},
            value=int(value),
        )
        for labels, value in samples.get(name, [])
    ]
    out.sort(key=lambda item: (-item.value, str(sorted(item.labels.items()))))
    return out


def parse_metrics(text: Any) -> Metrics:
    if not isinstance(text, str):
        return Metrics()

    samples = _parse_metrics_text(text)

    def scalar(name: str) -> int | None:
        rows = samples.get(name)
        return int(rows[0][1]) if rows else None

    return Metrics(
        healer_up=scalar("pve_healer_up"),
        healer_dry=scalar("pve_healer_dry_run"),
        pending=scalar("pve_healer_menunggu_persetujuan"),
        action_totals=_counters(samples, "pve_healer_aksi_total"),
        incident_totals=_counters(samples, "pve_healer_insiden_total"),
        approval_totals=_counters(samples, "pve_healer_persetujuan_total"),
        escalation_total=scalar("pve_healer_eskalasi_total"),
        k8s_action_totals=_counters(samples, "pve_healer_k8s_aksi_total"),
        k8s_escalation_totals=_counters(samples, "pve_healer_k8s_eskalasi_total"),
        node_failures=_counters(samples, "pve_healer_node_gagal_total"),
    )


def normalize_pending(raw: Any, now: float | None = None) -> list[PendingApproval]:
    if not isinstance(raw, list):
        return []
    now = time.time() if now is None else now
    pending: list[PendingApproval] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        try:
            vmid = int(record.get("vmid")) if record.get("vmid") not in (None, "") else None
        except (TypeError, ValueError):
            vmid = None
        expires = record.get("kedaluwarsa")
        seconds_left: int | None = None
        try:
            seconds_left = max(0, round(float(expires) - now))
        except (TypeError, ValueError):
            pass
        approved_at = record.get("disetujui")
        pending.append(
            PendingApproval(
                vmid=vmid,
                nama=str(record.get("nama") or ""),
                node=str(record.get("node") or ""),
                jenis=str(record.get("jenis") or ""),
                jenis_guest=str(record.get("jenis_guest") or ""),
                status=str(record.get("status") or ""),
                aksi=str(record.get("aksi") or ""),
                sumber=str(record.get("sumber") or ""),
                alasan=str(record.get("alasan") or ""),
                diminta=epoch_iso(record.get("diminta")),
                kedaluwarsa=epoch_iso(expires),
                seconds_left=seconds_left,
                approved=bool(approved_at),
                approved_at=epoch_iso(approved_at),
                oleh=str(record.get("oleh") or ""),
            )
        )
    pending.sort(key=lambda item: item.vmid if item.vmid is not None else 0)
    return pending


PUSH_ALERT_PREFIXES = ("PveHealer", "Healer", "SreHealer")


def normalize_pushed_alerts(raw: Any) -> list[PushedAlert]:
    """Alerts posted directly to Alertmanager; Prometheus ALERTS cannot see these."""
    if not isinstance(raw, list):
        return []
    pushed: list[PushedAlert] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        labels = {str(key): str(value) for key, value in (record.get("labels") or {}).items()}
        name = labels.get("alertname", "")
        if not name:
            continue
        if not (name.startswith(PUSH_ALERT_PREFIXES) or "dry_run" in labels):
            continue
        annotations = record.get("annotations") or {}
        status = record.get("status") or {}
        pushed.append(
            PushedAlert(
                alertname=name,
                severity=str(labels.get("severity") or "warning"),
                status=str(status.get("state") or "active"),
                summary=str(annotations.get("summary") or ""),
                description=str(annotations.get("description") or ""),
                starts_at=to_iso(str(record.get("startsAt") or "")),
                ends_at=to_iso(str(record.get("endsAt") or "")),
                fingerprint=str(record.get("fingerprint") or ""),
                labels=labels,
            )
        )
    pushed.sort(key=lambda item: parse_ts(item.starts_at) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return pushed


def normalize_engine_decisions(raw: Any) -> list[EngineDecision]:
    if not isinstance(raw, list):
        return []
    decisions: list[EngineDecision] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        ts = epoch_iso(record.get("ts")) or str(record.get("ts") or "")
        confidence = record.get("confidence")
        decisions.append(
            EngineDecision(
                ts=ts,
                time=hhmm(ts),
                jenis=str(record.get("jenis") or ""),
                target=str(record.get("sasaran") or record.get("target") or ""),
                kelas=str(record.get("kelas") or ""),
                keterangan=str(record.get("keterangan") or ""),
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                aksi=str(record.get("aksi") or ""),
                hasil=str(record.get("hasil_aksi") or ""),
                dry_run=bool(record.get("dry_run")),
                error=str(record.get("error") or ""),
            )
        )
    decisions.reverse()  # sre-healer returns oldest -> newest
    return decisions


def _classifier_health(result: ProbeResult, configured: bool) -> ClassifierHealth:
    if not configured:
        return ClassifierHealth()
    model = ""
    if result.ok and isinstance(result.value, dict):
        model = str(result.value.get("model") or "")
    return ClassifierHealth(
        configured=True, ok=result.ok, model=model, ms=result.ms, error=result.error
    )


def _engine_healer(
    health: ProbeResult | None,
    decisions: ProbeResult | None,
    configured: bool,
) -> EngineHealer:
    if not configured or health is None:
        return EngineHealer()
    recent = normalize_engine_decisions(decisions.value) if decisions and decisions.ok else []
    return EngineHealer(
        configured=True,
        ok=health.ok,
        ms=health.ms,
        error=health.error or (decisions.error if decisions and not decisions.ok else None),
        decisions=recent,
    )


# -------------------------------------------------------------------- runbooks

RUNBOOKS: list[dict[str, Any]] = [
    {
        "test": r"^PveHealerApproval$",
        "note": "Aksi menunggu persetujuan manusia. Read-only: setujui hanya dari VM105 lewat CLI.",
        "lines": [
            "ssh root@10.10.0.107 'python3 /opt/proxmox-healer/healer.py --pending'",
            "ssh root@10.10.0.107 'python3 /opt/proxmox-healer/healer.py --approve <vmid>'",
            "curl -s http://10.10.0.107:9181/api/pending | jq .",
        ],
    },
    {
        "test": r"^(PveHealerEscalation|PveHealerAksiGagal|PveHealerK8s)$",
        "note": "Healer sudah mencoba atau menolak bertindak; insiden butuh manusia. Cek decisions terbaru.",
        "lines": [
            "ssh root@10.10.0.107 'tail -n 20 /var/lib/proxmox-healer/decisions.jsonl | jq .'",
            "ssh root@10.10.0.107 'systemctl status proxmox-healer --no-pager'",
            "curl -s http://10.10.0.107:9181/api/knobs | jq .",
        ],
    },
    {
        "test": r"^PveHealerDown$",
        "note": "Metrik healer Proxmox tidak sampai ke Prometheus.",
        "lines": [
            "ssh root@10.10.0.107 'systemctl status proxmox-healer --no-pager'",
            "ssh root@10.10.0.107 'journalctl -u proxmox-healer -n 40 --no-pager'",
            "curl -s http://10.10.0.107:9181/metrics | head",
        ],
    },
    {
        "test": r"^(HealerDown|HealerClassifierPutus|HealerAksiGagal|HealerLoopLambat|HealerBanyakEskalasi|HealerErrorLoop|NodeBermasalah)$",
        "note": "Alert dari sre-healer k8s. Cek /decisions dan /metrics runtime tersebut.",
        "lines": [
            "kubectl -n sre-healer get deploy,pods",
            "kubectl -n sre-healer logs deploy/sre-healer --tail=80",
            "kubectl -n sre-healer port-forward deploy/sre-healer 8080:8080  # lalu curl :8080/decisions",
        ],
    },
    {
        "test": r"^(NodeExporterDown|ProxmoxHostDown)$",
        "note": "Target Proxmox/node-exporter mati. Cek guest dan jalur scrape sebelum menyentuh healer.",
        "lines": [
            "ssh root@10.10.0.107 'tail -n 40 /var/log/dns-broker.log 2>/dev/null || true'",
            "curl -s http://10.10.0.107:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health==\"down\") | {labels,lastError}'",
            "ssh root@10.10.0.4 'qm status <vmid>'",
        ],
    },
    {
        "test": r"^(K3sNodeNotReady|K3sApiDown|ExternalPrometheusDown)$",
        "note": "Jalur monitoring k3s/eksternal terganggu; alert healer bisa jadi tidak lengkap.",
        "lines": [
            "kubectl get nodes -o wide",
            "kubectl -n monitoring get pods",
            "curl -s http://10.10.0.107:9090/-/ready",
        ],
    },
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


def _endpoint_detail(result: ProbeResult) -> str | None:
    if result.name == "classifier_health" and result.ok and isinstance(result.value, dict):
        return str(result.value.get("model") or "") or None
    return None


def _endpoints(results: dict[str, ProbeResult]) -> list[SourceStatus]:
    return [
        SourceStatus(
            name=result.name,
            url=result.url,
            ok=result.ok,
            ms=result.ms,
            error=result.error,
            detail=_endpoint_detail(result),
        )
        for result in results.values()
    ]


async def gather_overview(upstream: Upstream, settings: Settings) -> Overview:
    probes: dict[str, Awaitable[ProbeResult]] = {
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
        "push_alerts": upstream.alertmanager_alerts(),
    }
    if settings.classifier_base:
        probes["classifier_health"] = upstream.classifier_health()
    if settings.engine_healer_base:
        probes["engine_healer_health"] = upstream.engine_healer_health()
    results = await _gather(probes)
    decisions = normalize_decisions(results["decisions"].value if results["decisions"].ok else [])
    summary = parse_summary(results["summary"].value if results["summary"].ok else None)
    alerts = normalize_alerts(
        results["alerts"].value if results["alerts"].ok else None,
        results["alert_age"].value if results["alert_age"].ok else None,
        results["push_alerts"].value if results["push_alerts"].ok else None,
        results["push_alerts"].ok,
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
            "push_alerts": upstream.alertmanager_alerts(),
        }
    )
    alerts = normalize_alerts(
        results["alerts"].value if results["alerts"].ok else None,
        results["alert_age"].value if results["alert_age"].ok else None,
        results["push_alerts"].value if results["push_alerts"].ok else None,
        results["push_alerts"].ok,
    )
    return AlertsResponse(
        generated_at=now_iso(),
        ok=alerts.ok,
        instances=alerts.instances,
        counts=alerts.counts,
        groups=alerts.groups,
        links=settings.links,
        pushed=alerts.pushed,
        pushed_ok=alerts.pushed_ok,
    )


async def gather_knobs(upstream: Upstream, settings: Settings) -> KnobsResponse:
    classifier_configured = bool(settings.classifier_base)
    engine_configured = bool(settings.engine_healer_base)
    probes: dict[str, Awaitable[ProbeResult]] = {
        "knobs": upstream.healer("knobs", "/api/knobs"),
        "summary": upstream.healer("summary", "/api/summary"),
        "metrics": upstream.healer_text("metrics", "/metrics"),
        "decisions": upstream.healer("decisions", "/api/decisions?n=1"),
        "pending": upstream.healer("pending", "/api/pending"),
    }
    if classifier_configured:
        probes["classifier_health"] = upstream.classifier_health()
    if engine_configured:
        probes["engine_healer_health"] = upstream.engine_healer_health()
        probes["engine_healer_decisions"] = upstream.engine_healer_decisions()
    results = await _gather(probes)
    decisions = normalize_decisions(results["decisions"].value if results["decisions"].ok else [])
    pending = normalize_pending(results["pending"].value if results["pending"].ok else [])
    classifier = (
        _classifier_health(results["classifier_health"], True)
        if classifier_configured
        else ClassifierHealth()
    )
    engine = _engine_healer(
        results.get("engine_healer_health"),
        results.get("engine_healer_decisions"),
        engine_configured,
    )
    return KnobsResponse(
        generated_at=now_iso(),
        links=settings.links,
        knobs=results["knobs"].value if results["knobs"].ok and isinstance(results["knobs"].value, dict) else {},
        metrics=parse_metrics(results["metrics"].value if results["metrics"].ok else None),
        last_decision=decisions[0] if decisions else None,
        summary=parse_summary(results["summary"].value if results["summary"].ok else None),
        pending=pending,
        pending_ok=results["pending"].ok,
        classifier=classifier,
        engine=engine,
    )


async def gather_pending(upstream: Upstream) -> PendingResponse:
    result = await upstream.healer("pending", "/api/pending")
    pending = normalize_pending(result.value if result.ok else [])
    return PendingResponse(
        generated_at=now_iso(), ok=result.ok, count=len(pending), pending=pending
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
    if "pending" in sources:
        probes["pending"] = upstream.healer("pending", "/api/pending")
    if "alerts" in sources:
        probes["alerts"] = upstream.prom("alerts", PROM_ALERTS)
    if "push_alerts" in sources:
        probes["push_alerts"] = upstream.alertmanager_alerts()
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
