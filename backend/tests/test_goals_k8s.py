"""Phase 3A: Deployment-only rollout_undo goals."""

from __future__ import annotations

import copy

import httpx

from .fake_upstream import K8S_STATE
from .test_goals_api import login, post

TEMPLATE = "k8s.deployment.rollback.v1"


def k8s_preview_payload(
    namespace: str = "aspirasi",
    deployment: str = "web",
    *,
    reason: str = "rollout baru membuat web tidak tersedia",
    **extra,
) -> dict:
    payload = {
        "template_id": TEMPLATE,
        "target": {"namespace": namespace, "deployment": deployment},
        "goal": "pulihkan web",
        "variables": {"reason": reason, "expected_effect": "available"},
    }
    payload.update(extra)
    return payload


def make_k8s_preview(client, token: str, **kwargs) -> dict:
    response = post(client, token, "/api/goals/preview", k8s_preview_payload(**kwargs))
    assert response.status_code == 200, response.text
    return response.json()


def make_k8s_goal(client, token: str, key: str = "k8s-key-0001", **kwargs):
    preview = make_k8s_preview(client, token, **kwargs)
    response = post(
        client,
        token,
        "/api/goals",
        {
            "preview_id": preview["preview_id"],
            "plan_hash": preview["plan_hash"],
            "idempotency_key": key,
        },
    )
    return preview, response


def override_k8s(upstream, payload) -> None:
    upstream.get("http://healer.test/api/k8s").mock(
        return_value=httpx.Response(200, json=payload)
    )


def test_k8s_template_is_listed(goals_client):
    login(goals_client)
    templates = {item["id"]: item for item in goals_client.get("/api/goals/templates").json()["templates"]}
    template = templates[TEMPLATE]
    assert template["target_kind"] == "k8s_deployment"
    assert template["actions"] == ["rollout_undo", "noop", "escalate"]
    assert template["max_steps"] == 1
    assert [item["name"] for item in template["variables"]] == ["reason", "expected_effect"]


def test_targets_for_guest_and_k8s(goals_client):
    login(goals_client)
    guests = goals_client.get("/api/goals/targets?template_id=guest.recover.v1").json()
    assert guests["target_kind"] == "proxmox_guest"
    assert guests["error"] == ""
    by_vmid = {row["vmid"]: row for row in guests["targets"]}
    assert by_vmid[105]["protected"] is True
    assert by_vmid[301]["status"] == "stopped"

    k8s = goals_client.get(f"/api/goals/targets?template_id={TEMPLATE}").json()
    assert k8s["target_kind"] == "k8s_deployment"
    assert k8s["error"] == ""
    deployments = {
        (row["namespace"], row["deployment"]): row for row in k8s["targets"]
    }
    assert deployments[("aspirasi", "web")]["status"] == "degraded"
    assert deployments[("aspirasi", "web")]["previous_revision"] == 11
    assert deployments[("monitoring", "prometheus")]["protected"] is True
    assert deployments[("aspirasi", "down")]["ok"] is False


def test_targets_unknown_template(goals_client):
    login(goals_client)
    response = goals_client.get("/api/goals/targets?template_id=nope")
    assert response.status_code == 404


def test_k8s_targets_reports_disabled(goals_client, upstream):
    override_k8s(upstream, {"enabled": False, "deployments": []})
    login(goals_client)
    body = goals_client.get(f"/api/goals/targets?template_id={TEMPLATE}").json()
    assert body["targets"] == []
    assert body["error"] == "k8s_disabled"


def test_k8s_preview_requires_k8s_target_shape(goals_client):
    token = login(goals_client)
    guest_shape = k8s_preview_payload()
    guest_shape["target"] = {"vmid": 301}
    response = post(goals_client, token, "/api/goals/preview", guest_shape)
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"

    bad_name = k8s_preview_payload(deployment="Web")
    response = post(goals_client, token, "/api/goals/preview", bad_name)
    assert response.status_code == 422

    blank_reason = k8s_preview_payload(reason="   ")
    response = post(goals_client, token, "/api/goals/preview", blank_reason)
    assert response.status_code == 422

    wrong_effect = k8s_preview_payload()
    wrong_effect["variables"]["expected_effect"] = "running"
    response = post(goals_client, token, "/api/goals/preview", wrong_effect)
    assert response.status_code == 422


def test_guest_preview_rejects_k8s_target_shape(goals_client):
    token = login(goals_client)
    payload = {
        "template_id": "guest.recover.v1",
        "target": {"namespace": "aspirasi", "deployment": "web"},
        "goal": "",
        "variables": {"reason": "x", "expected_effect": "running"},
    }
    response = post(goals_client, token, "/api/goals/preview", payload)
    assert response.status_code == 422


def test_k8s_preview_plans_rollback(goals_client):
    token = login(goals_client)
    preview = make_k8s_preview(goals_client, token)
    assert preview["status"] == "ready"
    plan = preview["plan"]
    assert plan["target_kind"] == "k8s_deployment"
    assert plan["generated_by"] == "rules"
    step = plan["steps"][0]
    assert step["action"] == "rollout_undo"
    assert step["risk"] == "high"
    assert step["target"]["namespace"] == "aspirasi"
    assert step["target"]["deployment"] == "web"
    assert step["target"]["revision"] == 12
    assert step["target"]["previous_revision"] == 11
    assert plan["evidence_hash"]
    assert len(preview["plan_hash"]) == 64

    again = make_k8s_preview(goals_client, token)
    assert again["plan_hash"] == preview["plan_hash"]


def test_k8s_preview_blocks_without_previous_revision(goals_client):
    token = login(goals_client)
    preview = make_k8s_preview(goals_client, token, deployment="cron")
    assert preview["status"] == "blocked"
    assert preview["blocked_reason"] == "no_safe_action"
    assert preview["plan"]["steps"][0]["action"] == "escalate"

    response = post(
        goals_client,
        token,
        "/api/goals",
        {
            "preview_id": preview["preview_id"],
            "plan_hash": preview["plan_hash"],
            "idempotency_key": "blocked-key-1",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "preview_blocked"


def test_k8s_preview_blocks_protected(goals_client):
    token = login(goals_client)
    preview = make_k8s_preview(
        goals_client, token, namespace="monitoring", deployment="prometheus"
    )
    assert preview["status"] == "blocked"
    assert preview["blocked_reason"] == "protected_target"
    assert preview["plan"]["steps"][0]["action"] == "escalate"


def test_k8s_preview_rejects_unlisted_target(goals_client):
    token = login(goals_client)
    response = post(
        goals_client,
        token,
        "/api/goals/preview",
        k8s_preview_payload(deployment="not-listed"),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "target_not_allowed"


def test_k8s_preview_reports_unavailable(goals_client, upstream):
    override_k8s(
        upstream, {"enabled": True, "deployments": [K8S_STATE["deployments"][3]]}
    )
    token = login(goals_client)
    response = post(
        goals_client,
        token,
        "/api/goals/preview",
        k8s_preview_payload(deployment="down"),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "k8s_unavailable"


def test_k8s_create_and_typed_confirmation(goals_client):
    token = login(goals_client)
    preview, created = make_k8s_goal(goals_client, token)
    assert created.status_code == 200, created.text
    goal = created.json()
    assert goal["status"] == "pending_approval"
    assert goal["target_kind"] == "k8s_deployment"
    assert goal["target"]["namespace"] == "aspirasi"
    assert goal["target"]["deployment"] == "web"
    assert goal["target"]["revision"] == 12
    assert goal["high_risk"] is True
    assert goal["requirements"]["typed_confirmation"] == "SETUJU rollout_undo aspirasi/web"
    assert len(goal["approval_code"]) == 12

    wrong = post(
        goals_client,
        token,
        f"/api/goals/{goal['id']}/approve",
        {
            "plan_hash": preview["plan_hash"],
            "approval_code": goal["approval_code"],
            "confirm": True,
            "confirmation": "SETUJU rollout_undo 301",
        },
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "typed_confirmation_required"

    approved = post(
        goals_client,
        token,
        f"/api/goals/{goal['id']}/approve",
        {
            "plan_hash": preview["plan_hash"],
            "approval_code": goal["approval_code"],
            "confirm": True,
            "confirmation": "SETUJU rollout_undo aspirasi/web",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["goal"]["status"] == "approved"


def test_k8s_create_rechecks_live_state(goals_client, upstream):
    token = login(goals_client)
    preview = make_k8s_preview(goals_client, token)

    changed = copy.deepcopy(K8S_STATE)
    for row in changed["deployments"]:
        if row["namespace"] == "aspirasi" and row["deployment"] == "web":
            row["revision"] = 13
            row["previous_revision"] = 12
    override_k8s(upstream, changed)

    response = post(
        goals_client,
        token,
        "/api/goals",
        {
            "preview_id": preview["preview_id"],
            "plan_hash": preview["plan_hash"],
            "idempotency_key": "k8s-changed-1",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "state_changed"


def test_k8s_create_rejects_target_become_available(goals_client, upstream):
    token = login(goals_client)
    preview = make_k8s_preview(goals_client, token)

    changed = copy.deepcopy(K8S_STATE)
    for row in changed["deployments"]:
        if row["namespace"] == "aspirasi" and row["deployment"] == "web":
            row["status"] = "available"
            row["available"] = 3
    override_k8s(upstream, changed)

    response = post(
        goals_client,
        token,
        "/api/goals",
        {
            "preview_id": preview["preview_id"],
            "plan_hash": preview["plan_hash"],
            "idempotency_key": "k8s-recovered-1",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "state_changed"


def test_k8s_targets_route_is_not_shadowed_by_goal_id(goals_client):
    login(goals_client)
    response = goals_client.get(f"/api/goals/targets?template_id={TEMPLATE}")
    assert response.status_code == 200
    assert "targets" in response.json()
