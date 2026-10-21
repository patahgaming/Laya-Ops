"""Shared fake upstream payloads, captured from the real VM105 endpoints."""

from __future__ import annotations

import json

SUMMARY = {
    "total": 21,
    "running": 21,
    "stopped": 0,
    "insiden_24j": 11,
    "aksi_24j": 6,
    "pulih_24j": 4,
    "eskalasi_24j": 5,
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
        "status": "stopped",
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
    "K8S_NS": [],
    "LLM_MODEL": "deepseek-chat",
    "LLM_AKTIF": True,
    "NODES": {"hq1": "10.10.0.4", "hq2": "10.10.0.5", "hq3": "10.10.0.6"},
}

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

METRICS = "pve_healer_up 1\npve_healer_dry_run 0\n"


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
