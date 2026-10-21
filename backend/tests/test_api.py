from __future__ import annotations


def test_healthz(client):
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "python_info" in response.text


def test_overview_maps_real_payloads(client):
    response = client.get("/api/overview")
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["total"] == 21
    assert body["summary"]["running"] == 21
    assert body["summary"]["insiden_24h"] == 11
    assert body["summary"]["aksi_24h"] == 6
    assert body["summary"]["eskalasi_24h"] == 5
    assert body["summary"]["menunggu_persetujuan"] == 2
    assert body["summary"]["targets"] == {"up": 34, "total": 34, "down": 0, "error": None}

    assert body["guests"]["total"] == 6
    assert body["guests"]["nodes"] == {"hq1": 2, "hq2": 3, "hq3": 1}
    assert body["guests"]["guests"][0]["vmid"] == 100

    assert body["alerts"]["ok"] is True
    assert body["alerts"]["instances"] == 4
    assert body["alerts"]["counts"] == {"critical": 1, "warning": 2, "info": 0, "none": 1}
    names = [group["name"] for group in body["alerts"]["groups"]]
    assert names[0] == "InfraSubdomainDead"
    assert names[-1] == "Watchdog"
    kube = next(group for group in body["alerts"]["groups"] if group["name"] == "KubePodNotReady")
    assert kube["instances"] == 2
    assert kube["namespaces"] == ["aspirasi", "default"]
    assert kube["oldest_seconds"] is not None
    assert kube["runbook"]["lines"]

    assert body["jobs"][0] == {"job": "node-exporter", "up": 8, "down": 0}
    assert body["metrics"]["healer_up"] == 1
    assert body["metrics"]["pending"] == 2
    assert body["metrics"]["action_totals"][0] == {
        "labels": {"aksi": "start", "sumber": "aturan", "hasil": "pulih"},
        "value": 4,
    }
    assert body["decisions"][0]["aksi"] == "rollout_undo"
    assert body["decisions"][0]["ts"].endswith("+07:00")
    start = next(decision for decision in body["decisions"] if decision["aksi"] == "start")
    assert start["jenis"] == "mati"
    assert start["tingkat"] == "minor"
    assert start["izin"] == "minor"
    assert start["jenis_guest"] == "ct"
    assert start["agent"] is False
    assert start["state"].startswith("ALERT:")
    assert body["alerts"]["pushed_ok"] is True
    assert {alert["alertname"] for alert in body["alerts"]["pushed"]} == {
        "PveHealerApproval",
        "PveHealerEscalation",
    }
    assert all(endpoint["ok"] for endpoint in body["endpoints"])
    assert body["links"]["grafana"].startswith("https://")
    assert body["links"]["grafana_healer_dashboard"].endswith("/d/sre-healer")


def test_status_is_lightweight(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["summary"]["total"] == 21
    assert body["alerts"]["instances"] == 4
    assert body["healer_up"] == 1


def test_guests_join_decisions(client):
    response = client.get("/api/guests")
    assert response.status_code == 200
    body = response.json()
    assert body["guests"]["total"] == 6
    assert len(body["decisions"]) == 3


def test_alerts_grouping_and_runbooks(client):
    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["counts"]["critical"] == 1
    assert len(body["groups"]) == 3
    watchdog = next(group for group in body["groups"] if group["name"] == "Watchdog")
    assert watchdog["severity"] == "none"
    assert "Watchdog" in watchdog["runbook"]["note"]
    assert body["pushed_ok"] is True
    assert len(body["pushed"]) == 2
    approval = next(alert for alert in body["pushed"] if alert["alertname"] == "PveHealerApproval")
    assert approval["status"] == "active"
    assert approval["labels"]["vmid"] == "999"
    assert "--approve 999" in approval["description"]


def test_knobs_snapshot(client):
    response = client.get("/api/knobs")
    assert response.status_code == 200
    body = response.json()
    assert body["knobs"]["AUTO_IDS"] == [201, 202, 203, 204, 205, 206, 207]
    assert body["knobs"]["PROTECT"] == [105]
    assert body["knobs"]["MINOR_ACTIONS"] == ["start"]
    assert body["knobs"]["IZIN_TTL"] == 900
    assert body["knobs"]["LLM_MODEL"] == "deepseek-chat"
    assert body["last_decision"]["aksi"] == "rollout_undo"

    assert body["pending_ok"] is True
    assert [item["vmid"] for item in body["pending"]] == [999, 1000]
    assert body["pending"][0]["approved"] is False
    assert body["pending"][0]["seconds_left"] > 0
    assert body["pending"][1]["approved"] is True
    assert body["pending"][1]["oleh"] == "operator"

    metrics = body["metrics"]
    assert metrics["pending"] == 2
    assert metrics["escalation_total"] == 2
    assert {"aksi": "reset", "sumber": "llm", "hasil": "gagal"} in [
        item["labels"] for item in metrics["action_totals"]
    ]
    assert metrics["k8s_action_totals"] == [
        {"labels": {"aksi": "rollout_undo", "hasil": "pulih"}, "value": 1}
    ]
    assert body["classifier"]["configured"] is False
    assert body["engine"]["configured"] is False


def test_pending_endpoint(client):
    response = client.get("/api/pending")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["count"] == 2
    assert {item["aksi"] for item in body["pending"]} == {"reset"}


def test_raw_is_whitelisted(client):
    response = client.get("/api/raw", params={"sources": "summary,../../etc/passwd"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"summary"}
    assert body["summary"]["ok"] is True


def test_raw_includes_pending_and_push_alerts(client):
    response = client.get("/api/raw", params={"sources": "pending,push_alerts"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"pending", "push_alerts"}
    assert body["pending"]["ok"] is True
    assert len(body["pending"]["value"]) == 2
    assert body["push_alerts"]["ok"] is True


def test_optional_runtimes_are_probed(runtime_client):
    overview = runtime_client.get("/api/overview")
    assert overview.status_code == 200
    endpoints = {endpoint["name"]: endpoint for endpoint in overview.json()["endpoints"]}
    assert endpoints["classifier_health"]["ok"] is True
    assert endpoints["classifier_health"]["detail"] == "laya-v4"
    assert endpoints["engine_healer_health"]["ok"] is True

    response = runtime_client.get("/api/knobs")
    assert response.status_code == 200
    body = response.json()
    assert body["classifier"]["configured"] is True
    assert body["classifier"]["model"] == "laya-v4"
    assert body["engine"]["configured"] is True
    assert body["engine"]["ok"] is True
    assert [decision["jenis"] for decision in body["engine"]["decisions"]] == ["node", "pod"]
    assert body["engine"]["decisions"][0]["target"] == "k3s-worker-2"
    assert body["engine"]["decisions"][1]["confidence"] == 0.91


def test_unknown_api_path_is_not_the_spa(client):
    response = client.get("/api/nope")
    assert response.status_code == 404


def test_readyz_uses_healer(client):
    response = client.get("/api/readyz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_security_headers(client):
    response = client.get("/api/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
