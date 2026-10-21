"""Shared fake upstream payloads, captured from the real VM105 endpoints."""

from __future__ import annotations

import json
import time

SUMMARY = {
    "total": 21,
    "running": 21,
    "stopped": 0,
    "insiden_24j": 11,
    "aksi_24j": 6,
    "pulih_24j": 4,
    "eskalasi_24j": 5,
    "menunggu_persetujuan": 2,
    "dry": False,
    "targets": {"up": 34, "total": 34, "down": 0},
}

STATE = {
    "100": {"status": "running", "node": "hq1", "sejak": "baseline", "agent_ok": False, "agent_gagal": 882},
    "105": {"status": "running", "node": "hq1", "sejak": "baseline", "agent_ok": False, "agent_gagal": 882},
    "201": {"status": "running", "node": "hq2", "sejak": "baseline", "agent_ok": True, "agent_gagal": 0},
    "202": {"status": "running", "node": "hq2", "sejak": "baseline", "agent_ok": True, "agent_gagal": 0},
    "203": {"status": "running", "node": "hq2", "sejak": "baseline", "agent_ok": True, "agent_gagal": 0},
    "301": {"status": "running", "node": "hq3", "sejak": "baseline", "agent_ok": False, "agent_gagal": 888},
}

DECISIONS = [
    {
        "ts": "2026-10-20T22:52:34+07:00",
        "aksi": "start",
        "sumber": "aturan",
        "hasil": "pulih",
        "alasan": "aksi deterministik vmid AUTO_IDS",
        "ket": "pct start 999",
        "vmid": 999,
        "nama": "healer-test",
        "node": "hq1",
        "jenis": "mati",
        "tingkat": "minor",
        "izin": "minor",
        "jenis_guest": "ct",
        "status": "stopped",
        "agent": False,
        "state": "ALERT: guest 999 stopped\nMETRIK: status=stopped",
        "dry": False,
    },
    {
        "ts": "2026-10-20T23:23:19+07:00",
        "target": "healer-test/outage",
        "aksi": "rollout_undo",
        "sumber": "aturan",
        "hasil": "pulih",
        "alasan": "replika siap 0 akibat ImagePullBackOff",
        "ket": "image busybox:1.36",
        "dry": False,
    },
    {
        "ts": "2026-10-20T23:19:00+07:00",
        "target": "healer-test/crash",
        "aksi": "escalate",
        "sumber": "gerbang",
        "hasil": "eskalasi",
        "alasan": "tidak ada revisi sebelumnya",
        "dry": False,
    },
]

KNOBS = {
    "AUTO_IDS": [201, 202, 203, 204, 205, 206, 207],
    "PROTECT": [105],
    "MAX_AKSI": 1,
    "COOLDOWN": 600,
    "INTERVAL": 60,
    "DRY_RUN": False,
    "MINOR_ACTIONS": ["start"],
    "IZIN_TTL": 900,
    "K8S_NS": [],
    "LLM_MODEL": "deepseek-chat",
    "LLM_AKTIF": True,
    "NODES": {"hq1": "10.10.0.4", "hq2": "10.10.0.5", "hq3": "10.10.0.6"},
}

_NOW = time.time()

PENDING = [
    {
        "vmid": 999,
        "nama": "healer-test",
        "node": "hq1",
        "jenis": "mati",
        "jenis_guest": "ct",
        "status": "stopped",
        "aksi": "reset",
        "sumber": "llm",
        "alasan": "LLM menilai perlu-approval",
        "diminta": _NOW - 60,
        "kedaluwarsa": _NOW + 600,
        "disetujui": 0,
        "ditolak": 0,
        "oleh": "",
    },
    {
        "vmid": 1000,
        "nama": "healer-test-2",
        "node": "hq2",
        "jenis": "hang",
        "jenis_guest": "vm",
        "status": "running",
        "aksi": "reset",
        "sumber": "llm",
        "alasan": "agent tidak menjawab",
        "diminta": _NOW - 120,
        "kedaluwarsa": _NOW + 300,
        "disetujui": _NOW - 30,
        "ditolak": 0,
        "oleh": "operator",
    },
]

CLASSIFIER_HEALTH = {"ok": True, "model": "laya-v4"}
ENGINE_HEALTH = {"ok": True}
ENGINE_DECISIONS = [
    {
        "ts": int(_NOW) - 90,
        "jenis": "pod",
        "sasaran": "aspirasi/web-1",
        "app": "web",
        "alasan": "CrashLoopBackOff",
        "kelas": "auto",
        "keterangan": "model",
        "confidence": 0.91,
        "aksi": "rollout_undo",
        "hasil_aksi": "pulih",
        "dry_run": False,
    },
    {
        "ts": int(_NOW) - 30,
        "jenis": "node",
        "sasaran": "k3s-worker-2",
        "alasan": "disk < 10%",
        "kelas": "manusia",
        "keterangan": "aturan node",
        "confidence": 0.0,
        "aksi": "eskalasi",
        "hasil_aksi": "",
        "dry_run": False,
    },
]

AM_ALERTS = [
    {
        "labels": {
            "alertname": "PveHealerApproval",
            "severity": "warning",
            "node": "hq1",
            "vmid": "999",
            "instance": "healer-test",
            "dry_run": "false",
        },
        "annotations": {
            "summary": "butuh persetujuan: healer-test (999) reset",
            "description": "setujui: healer.py --approve 999",
        },
        "startsAt": "2026-10-20T22:55:00+07:00",
        "endsAt": "0001-01-01T00:00:00Z",
        "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
        "fingerprint": "abc123",
    },
    {
        "labels": {
            "alertname": "PveHealerEscalation",
            "severity": "warning",
            "node": "hq2",
            "vmid": "1000",
            "instance": "healer-test-2",
            "dry_run": "false",
        },
        "annotations": {"summary": "healer Proxmox eskalasi", "description": "tidak ada revisi"},
        "startsAt": "2026-10-20T22:40:00+07:00",
        "endsAt": "0001-01-01T00:00:00Z",
        "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
        "fingerprint": "def456",
    },
    {
        "labels": {"alertname": "KubePodNotReady", "severity": "warning", "namespace": "aspirasi"},
        "annotations": {"summary": "prometheus rule, not a direct push"},
        "startsAt": "2026-10-20T22:41:00+07:00",
        "endsAt": "0001-01-01T00:00:00Z",
        "status": {"state": "active"},
        "fingerprint": "ghi789",
    },
]

ALERTS = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {"metric": {"alertname": "InfraSubdomainDead", "severity": "critical", "job": "dns-broker-exporter"}, "value": [1792563494.0, "1"]},
            {"metric": {"alertname": "KubePodNotReady", "severity": "warning", "namespace": "aspirasi", "job": "kube-state-metrics"}, "value": [1792563494.0, "1"]},
            {"metric": {"alertname": "KubePodNotReady", "severity": "warning", "namespace": "default", "job": "kube-state-metrics"}, "value": [1792563494.0, "1"]},
            {"metric": {"alertname": "Watchdog", "severity": "none"}, "value": [1792563494.0, "1"]},
        ],
    },
}

ALERTS_AGE = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {"metric": {"alertname": "InfraSubdomainDead"}, "value": [1792563494.0, 1792563300.0]},
            {"metric": {"alertname": "KubePodNotReady", "namespace": "aspirasi"}, "value": [1792563494.0, 1792500000.0]},
            {"metric": {"alertname": "KubePodNotReady", "namespace": "default"}, "value": [1792563494.0, 1792500000.0]},
            {"metric": {"alertname": "Watchdog"}, "value": [1792563494.0, 1792563300.0]},
        ],
    },
}

JOBS = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {"metric": {"job": "node-exporter"}, "value": [1792563494.0, "8"]},
            {"metric": {"job": "pve-healer"}, "value": [1792563494.0, "1"]},
        ],
    },
}

JOBS_DOWN = {"status": "success", "data": {"resultType": "vector", "result": []}}

METRICS = (
    "pve_healer_up 1\n"
    "pve_healer_dry_run 0\n"
    "pve_healer_menunggu_persetujuan 2\n"
    'pve_healer_aksi_total{a="start",b="aturan",c="pulih"} 4\n'
    'pve_healer_aksi_total{a="reset",b="llm",c="gagal"} 1\n'
    'pve_healer_insiden_total{a="mati"} 5\n'
    'pve_healer_persetujuan_total{a="diminta"} 3\n'
    'pve_healer_persetujuan_total{a="disetujui"} 2\n'
    "pve_healer_eskalasi_total 2\n"
    'pve_healer_k8s_aksi_total{a="rollout_undo",b="pulih"} 1\n'
    'pve_healer_node_gagal_total{a="hq1"} 0\n'
)


def prom_response(query: str) -> dict:
    if "ALERTS_FOR_STATE" in query:
        return ALERTS_AGE
    if query.startswith("ALERTS"):
        return ALERTS
    if "up == 0" in query:
        return JOBS_DOWN
    if "count by (job)" in query:
        return JOBS
    return {"status": "success", "data": {"resultType": "vector", "result": []}}


def json_bytes(payload) -> bytes:
    return json.dumps(payload).encode()
