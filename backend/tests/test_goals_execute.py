"""Phase 2: execute/reconcile against the loopback healer control API."""

from __future__ import annotations

import json
import time

import httpx
from fastapi.testclient import TestClient

from app.goals.control import signature
from app.main import create_app

from .conftest import (
    GOALS_CONTROL_BASE,
    GOALS_CONTROL_KEY,
    GOALS_ORIGIN,
    GOALS_PASSWORD,
    goals_settings,
)
from .test_goals_api import make_goal, post


def login(client) -> str:
    token = client.get("/api/auth/config").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"password": GOALS_PASSWORD},
        headers={"X-CSRF-Token": token, "Origin": GOALS_ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def approve(client, token: str, preview: dict, goal: dict) -> dict:
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/approve",
        {
            "plan_hash": preview["plan_hash"],
            "approval_code": goal["approval_code"],
            "confirm": True,
            "confirmation": "SETUJU start 301",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["goal"]


def ready_goal(client, token: str, key: str = "execute-key-0001"):
    preview, created = make_goal(client, token, key=key)
    assert created.status_code == 200, created.text
    goal = approve(client, token, preview, created.json())
    assert goal["status"] == "approved"
    assert goal["can_execute"] is True
    return preview, goal


def wait_goal(client, goal_id: str, statuses: set[str], timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    goal: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/goals/{goal_id}")
        assert response.status_code == 200, response.text
        goal = response.json()
        if goal["status"] in statuses:
            return goal
        time.sleep(0.05)
    raise AssertionError(f"goal tidak mencapai {statuses}: {goal}")


def journal_run(
    status: str = "done", *, result=None, error="", error_code="", dry_run=False
):
    return {
        "run": {
            "plan_id": "",
            "plan_hash": "a" * 64,
            "status": status,
            "dry_run": dry_run,
            "action": "start",
            "vmid": 301,
            "node": "hq3",
            "approved_by": "operator",
            "claimed_at": "2026-10-22T00:00:00Z",
            "finished_at": "2026-10-22T00:00:05Z",
            "result": result
            if result is not None
            else {"ok": True, "detail": "qm start 301"},
            "error": error,
            "error_code": error_code,
        }
    }


def test_execute_dispatches_signed_request_and_follows_journal(
    goals_execute_client, upstream
):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token)
    captured: dict = {}
    polled = {"n": 0}

    def execute_route(request):
        captured["body"] = request.content
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            202,
            json={
                "accepted": True,
                "plan_id": goal["id"],
                "run": journal_run("claimed")["run"],
            },
        )

    def status_route(request):
        polled["n"] += 1
        return httpx.Response(200, json=journal_run("done"))

    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(side_effect=execute_route)
    upstream.get(f"{GOALS_CONTROL_BASE}/runs/{goal['id']}").mock(
        side_effect=status_route
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True
    finished = wait_goal(client, goal["id"], {"succeeded", "failed", "unknown"})

    assert finished["status"] == "succeeded"
    assert finished["run"]["status"] == "done"
    assert finished["run"]["result"]["ok"] is True
    assert finished["result"]["ok"] is True
    assert polled["n"] >= 1

    body = json.loads(captured["body"])
    assert set(body) == {
        "plan_id",
        "plan_hash",
        "plan",
        "approved_by",
        "approved_at",
        "expires_at",
    }
    assert body["plan_id"] == goal["id"]
    assert body["plan_hash"] == preview["plan_hash"]
    assert body["approved_by"] == "operator"
    headers = httpx.Headers(captured["headers"])
    expected = signature(
        GOALS_CONTROL_KEY,
        headers["x-laya-timestamp"],
        headers["x-laya-nonce"],
        "POST",
        "/execute",
        captured["body"],
    )
    assert headers["x-laya-signature"] == expected
    assert '"approval_code": "' not in json.dumps(finished)

    audit = client.get(f"/api/goals/{goal['id']}/audit").json()["events"]
    events = [event["event"] for event in audit]
    assert "execute.requested" in events
    assert "execute.accepted" in events
    assert "execute.finished" in events


def test_execute_requires_confirmation_flag(goals_execute_client):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0002")
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": False},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "confirmation_required"


def test_execute_rejects_plan_hash_mismatch(goals_execute_client):
    client = goals_execute_client
    token = login(client)
    _, goal = ready_goal(client, token, key="execute-key-0003")
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": "0" * 64, "confirm": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "plan_hash_mismatch"


def test_replay_done_marks_succeeded(goals_execute_client, upstream):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0004")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        return_value=httpx.Response(200, json={**journal_run("done"), "replayed": True})
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202
    finished = wait_goal(client, goal["id"], {"succeeded", "failed", "unknown"})
    assert finished["status"] == "succeeded"


def test_retryable_rejection_returns_to_approved(goals_execute_client, upstream):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0005")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        return_value=httpx.Response(409, json={"error": "busy"})
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202
    back = wait_goal(client, goal["id"], {"approved", "failed", "unknown"})
    assert back["status"] == "approved"
    assert back["can_execute"] is True
    assert back["run"]["status"] == "rejected"
    assert back["run"]["error_code"] == "busy"


def test_protected_target_marks_failed(goals_execute_client, upstream):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0006")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        return_value=httpx.Response(403, json={"error": "protected_target"})
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202
    finished = wait_goal(client, goal["id"], {"succeeded", "failed", "unknown"})
    assert finished["status"] == "failed"
    assert finished["run"]["error_code"] == "protected_target"


def test_transport_error_marks_unknown_then_reconcile_recovers(
    goals_execute_client, upstream
):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0007")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        side_effect=httpx.ConnectError("healer mati")
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202
    unknown = wait_goal(client, goal["id"], {"unknown", "failed", "succeeded"})
    assert unknown["status"] == "unknown"
    assert unknown["run"]["error_code"] == "control_unavailable"
    assert unknown["can_reconcile"] is True

    upstream.get(f"{GOALS_CONTROL_BASE}/runs/{goal['id']}").mock(
        return_value=httpx.Response(200, json=journal_run("done"))
    )
    reconciled = post(client, token, f"/api/goals/{goal['id']}/reconcile")
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["goal"]["status"] == "succeeded"


def test_reconcile_without_journal_record_marks_failed(goals_execute_client, upstream):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0008")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        side_effect=httpx.ConnectError("healer mati")
    )
    response = post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert response.status_code == 202
    unknown = wait_goal(client, goal["id"], {"unknown", "failed", "succeeded"})
    assert unknown["status"] == "unknown"

    upstream.get(f"{GOALS_CONTROL_BASE}/runs/{goal['id']}").mock(
        return_value=httpx.Response(404, json={"error": "not_found"})
    )
    reconciled = post(client, token, f"/api/goals/{goal['id']}/reconcile")
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["goal"]["status"] == "failed"
    assert reconciled.json()["goal"]["run"]["error_code"] == "not_dispatched"


def test_poll_timeout_marks_unknown(upstream, tmp_path):
    app = create_app(
        goals_settings(
            tmp_path,
            goals_execute_enabled=True,
            goals_control_base=GOALS_CONTROL_BASE,
            goals_control_key=GOALS_CONTROL_KEY,
            goals_control_timeout=5,
            goals_control_request_timeout=1,
            goals_control_poll_interval=0.5,
        )
    )
    with TestClient(app) as client:
        token = login(client)
        preview, goal = ready_goal(client, token, key="execute-key-0009")
        upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
            return_value=httpx.Response(202, json=journal_run("claimed"))
        )
        upstream.get(f"{GOALS_CONTROL_BASE}/runs/{goal['id']}").mock(
            return_value=httpx.Response(500, json={"error": "internal_error"})
        )
        response = post(
            client,
            token,
            f"/api/goals/{goal['id']}/execute",
            {"plan_hash": preview["plan_hash"], "confirm": True},
        )
        assert response.status_code == 202
        finished = wait_goal(client, goal["id"], {"unknown", "failed", "succeeded"})
    assert finished["status"] == "unknown"
    assert finished["run"]["error_code"] == "control_timeout"


def test_dry_run_is_surfaced_from_journal(goals_execute_client, upstream):
    client = goals_execute_client
    token = login(client)
    preview, goal = ready_goal(client, token, key="execute-key-0010")
    upstream.post(f"{GOALS_CONTROL_BASE}/execute").mock(
        return_value=httpx.Response(200, json=journal_run("done", dry_run=True))
    )
    post(
        client,
        token,
        f"/api/goals/{goal['id']}/execute",
        {"plan_hash": preview["plan_hash"], "confirm": True},
    )
    finished = wait_goal(client, goal["id"], {"succeeded", "failed", "unknown"})
    assert finished["status"] == "succeeded"
    assert finished["run"]["dry_run"] is True
