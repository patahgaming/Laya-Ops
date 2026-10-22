from __future__ import annotations

import json
import sqlite3
import threading
import uuid

import pytest

from app.goals.store import (
    Store,
    generate_approval_code,
    hash_approval_code,
    verify_approval_code,
)


def goal_record(*, goal_id: str | None = None, sub: str = "password:operator", key: str = "key-0001") -> dict:
    return {
        "id": goal_id or str(uuid.uuid4()),
        "preview_id": str(uuid.uuid4()),
        "status": "pending_approval",
        "requested_by_sub": sub,
        "requested_by_name": "operator",
        "requested_at": "2026-10-22T00:00:00+00:00",
        "expires_at": "2026-10-22T00:15:00+00:00",
        "template_id": "guest.recover.v1",
        "template_version": "1",
        "target_vmid": 301,
        "target_node": "hq3",
        "target_type": "vm",
        "target_json": json.dumps({"vmid": 301, "auto": False}),
        "goal": "pulihkan worker",
        "variables_json": json.dumps({"reason": "test"}),
        "plan_json": json.dumps({"steps": [{"action": "start"}]}),
        "plan_hash": "a" * 64,
        "evidence_hash": "b" * 64,
        "warnings_json": "[]",
        "approval_code_salt": "salt",
        "approval_code_hash": "hash",
        "idempotency_key": key,
        "created_at": "2026-10-22T00:00:00+00:00",
        "updated_at": "2026-10-22T00:00:00+00:00",
    }


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    instance.initialize()
    yield instance
    instance.close()


def test_plan_and_identity_fields_cannot_be_rewritten(store):
    record = goal_record()
    store.create_goal(record)
    with pytest.raises(ValueError):
        store.update_goal(record["id"], fields={"plan_json": "{}"})
    with pytest.raises(ValueError):
        store.update_goal(record["id"], fields={"requested_by_sub": "attacker"})
    updated = store.update_goal(record["id"], expected_status="pending_approval", fields={"status": "approved"})
    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["plan_json"] == record["plan_json"]


def test_only_one_status_transition_wins(store):
    record = goal_record()
    store.create_goal(record)
    results = []
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        barrier.wait()
        results.append(
            store.update_goal(
                record["id"],
                expected_status="pending_approval",
                fields={"status": "approved", "approved_by_name": name},
            )
        )

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for row in results if row is not None) == 1
    assert store.get_goal(record["id"])["status"] == "approved"


def test_idempotency_is_scoped_per_user(store):
    first = goal_record(key="shared-key-1")
    row, replay = store.create_goal(first)
    assert replay is False
    same, replay = store.create_goal(goal_record(key="shared-key-1"))
    assert replay is True
    assert same["id"] == row["id"]

    other, replay = store.create_goal(
        goal_record(sub="oidc:other", key="shared-key-1")
    )
    assert replay is False
    assert other["id"] != row["id"]


def test_approval_code_is_hashed_and_verifiable(store):
    code = generate_approval_code()
    assert len(code) == 12
    assert code.isalnum()
    digest = hash_approval_code(code, "abc123")
    assert code not in digest
    assert verify_approval_code(code, "abc123", digest) is True
    assert verify_approval_code(code.lower(), "abc123", digest) is False
    assert verify_approval_code(code, "other", digest) is False


def test_schema_from_the_future_fails_closed(tmp_path):
    path = tmp_path / "future"
    first = Store(path)
    first.initialize()
    first._db().execute("UPDATE schema_meta SET version = 99")
    first._db().commit()
    first.close()
    with pytest.raises(RuntimeError):
        Store(path).initialize()


def test_audit_is_append_only_and_parameterized(store):
    record = goal_record()
    store.create_goal(record)
    store.audit(
        ts="2026-10-22T00:00:01+00:00",
        goal_id=record["id"],
        actor_sub="password:operator",
        actor_name="operator",
        actor_method="password",
        event="goal.approved",
        detail={"note": "x' OR '1'='1"},
    )
    events = store.list_audit(record["id"])
    assert [event["event"] for event in events] == ["goal.approved"]
    assert events[0]["detail"]["note"] == "x' OR '1'='1"
    assert store.get_goal("' OR 1=1 --") is None


def test_listing_respects_owner_and_status(store):
    first = goal_record(key="list-1")
    store.create_goal(first)
    other = goal_record(sub="oidc:other", key="list-2")
    other["status"] = "rejected"
    store.create_goal(other)

    mine, _ = store.list_goals(
        owner_sub="password:operator", is_approver=False, status=None, limit=10, offset=0
    )
    assert [row["id"] for row in mine] == [first["id"]]

    all_rows, _ = store.list_goals(
        owner_sub="password:operator", is_approver=True, status=None, limit=10, offset=0
    )
    assert {row["id"] for row in all_rows} == {first["id"], other["id"]}

    rejected, _ = store.list_goals(
        owner_sub="password:operator", is_approver=True, status="rejected", limit=10, offset=0
    )
    assert [row["id"] for row in rejected] == [other["id"]]


# ------------------------------------------------------------------ schema v2
def test_v1_schema_migrates_in_place(tmp_path):
    import sqlite3

    data = tmp_path / "migrate"
    data.mkdir()
    conn = sqlite3.connect(data / "goals.db")
    conn.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER NOT NULL);
        CREATE TABLE goal_requests (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT '',
            requested_by_sub TEXT NOT NULL DEFAULT '',
            requested_at TEXT NOT NULL DEFAULT '',
            plan_hash TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE goal_runs (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL UNIQUE,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE goal_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            goal_id TEXT NOT NULL,
            actor_sub TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            actor_method TEXT NOT NULL,
            event TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            client_ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO schema_meta(version) VALUES (1);
        INSERT INTO goal_requests(id) VALUES ('goal-v1');
        """
    )
    conn.commit()
    conn.close()

    store = Store(data)
    store.initialize()
    try:
        row = store.get_goal("goal-v1")
        assert row is not None
        assert row["plan_id"] == "goal-v1"
        assert row["target_kind"] == "proxmox_guest"
        assert row["execute_count"] == 0
        assert store._db().execute("SELECT version FROM schema_meta").fetchone()[0] == 3
        columns = {
            item["name"]
            for item in store._db().execute("PRAGMA table_info(goal_runs)").fetchall()
        }
        assert {"lease_owner", "lease_expires_at", "dry_run", "error_code"} <= columns
        preview_columns = {
            item["name"]
            for item in store._db().execute("PRAGMA table_info(goal_previews)").fetchall()
        }
        assert "target_kind" in preview_columns
    finally:
        store.close()


def test_v2_schema_adds_preview_target_kind(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "goals.db")
    conn.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER NOT NULL);
        CREATE TABLE goal_previews (
            id TEXT PRIMARY KEY,
            created_by_sub TEXT NOT NULL,
            created_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            template_id TEXT NOT NULL,
            template_version TEXT NOT NULL,
            target_vmid INTEGER NOT NULL,
            target_node TEXT NOT NULL,
            target_type TEXT NOT NULL,
            goal TEXT NOT NULL,
            variables_json TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            status TEXT NOT NULL,
            blocked_reason TEXT NOT NULL DEFAULT '',
            used INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO schema_meta(version) VALUES (2);
        INSERT INTO goal_previews (
            id, created_by_sub, created_by_name, created_at, expires_at,
            template_id, template_version, target_vmid, target_node, target_type,
            goal, variables_json, plan_json, plan_hash, evidence_json,
            evidence_hash, warnings_json, status
        ) VALUES (
            'p1', 'u', 'operator', 't', 't', 'guest.recover.v1', '1', 301,
            'hq3', 'vm', '', '{}', '{}', 'h', '{}', 'e', '[]', 'ready'
        );
        """
    )
    conn.commit()
    conn.close()

    store = Store(data)
    store.initialize()
    try:
        row = store.get_preview("p1")
        assert row is not None
        assert row["target_kind"] == "proxmox_guest"
        assert store._db().execute("SELECT version FROM schema_meta").fetchone()[0] == 3
    finally:
        store.close()


def test_claim_execution_is_atomic(store):
    record = goal_record(key="claim-1")
    store.create_goal(record)
    assert store.update_goal(
        record["id"],
        expected_status="pending_approval",
        fields={
            "status": "approved",
            "approved_by_sub": "password:operator",
            "approved_by_name": "operator",
            "approved_at": "2026-10-22T00:01:00+00:00",
            "execute_before": "2026-10-22T00:20:00+00:00",
            "updated_at": "2026-10-22T00:01:00+00:00",
        },
    ) is not None
    results = []
    barrier = threading.Barrier(2)

    def worker(run_id: str) -> None:
        barrier.wait()
        results.append(
            store.claim_execution(
                record["id"],
                plan_hash=record["plan_hash"],
                now="2026-10-22T00:05:00+00:00",
                actor_sub="password:operator",
                actor_name="operator",
                run_id=run_id,
                lease_owner=f"owner-{run_id}",
                lease_expires_at="2026-10-22T00:10:00+00:00",
            )
        )

    threads = [
        threading.Thread(target=worker, args=(name,)) for name in ("run-a", "run-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [row for row in results if row is not None]
    assert len(winners) == 1
    goal = store.get_goal(record["id"])
    assert goal["status"] == "dispatching"
    assert goal["execute_count"] == 1
    assert goal["run_id"] == winners[0]["run"]["id"]
    assert store.get_run(record["id"])["status"] == "dispatching"


def test_retry_reuses_the_same_run_row(store):
    record = goal_record(key="claim-retry")
    store.create_goal(record)
    assert store.update_goal(
        record["id"],
        expected_status="pending_approval",
        fields={
            "status": "approved",
            "execute_before": "2026-10-22T00:20:00+00:00",
            "updated_at": "2026-10-22T00:01:00+00:00",
        },
    ) is not None
    first = store.claim_execution(
        record["id"],
        plan_hash=record["plan_hash"],
        now="2026-10-22T00:05:00+00:00",
        actor_sub="password:operator",
        actor_name="operator",
        run_id="run-1",
        lease_owner="owner-1",
        lease_expires_at="2026-10-22T00:10:00+00:00",
    )
    assert first is not None
    assert store.update_goal(
        record["id"],
        expected_status="dispatching",
        fields={"status": "approved", "updated_at": "2026-10-22T00:06:00+00:00"},
    )
    store.update_run(
        record["id"],
        {"status": "rejected", "error_code": "busy", "lease_owner": ""},
    )
    second = store.claim_execution(
        record["id"],
        plan_hash=record["plan_hash"],
        now="2026-10-22T00:07:00+00:00",
        actor_sub="password:operator",
        actor_name="operator",
        run_id="run-2",
        lease_owner="owner-2",
        lease_expires_at="2026-10-22T00:12:00+00:00",
    )
    assert second is not None
    assert second["run"]["id"] == "run-1"
    assert second["run"]["attempts"] == 2
    run = store.get_run(record["id"])
    assert run["status"] == "dispatching"
    assert run["error_code"] == ""
    assert store.get_goal(record["id"])["run_id"] == "run-1"


def test_sweep_expires_windows_and_stale_leases(store):
    pending = goal_record(key="sweep-pending")
    pending["expires_at"] = "2026-10-22T00:00:00+00:00"
    store.create_goal(pending)

    approved = goal_record(key="sweep-approved")
    store.create_goal(approved)
    store.update_goal(
        approved["id"],
        expected_status="pending_approval",
        fields={
            "status": "approved",
            "execute_before": "2026-10-22T00:00:00+00:00",
            "updated_at": "2026-10-22T00:00:00+00:00",
        },
    )

    stale = goal_record(key="sweep-stale")
    store.create_goal(stale)
    store.update_goal(
        stale["id"],
        expected_status="pending_approval",
        fields={
            "status": "approved",
            "execute_before": "2026-10-22T02:00:00+00:00",
            "updated_at": "2026-10-22T00:00:00+00:00",
        },
    )
    assert (
        store.claim_execution(
            stale["id"],
            plan_hash=stale["plan_hash"],
            now="2026-10-22T00:00:00+00:00",
            actor_sub="password:operator",
            actor_name="operator",
            run_id="run-stale",
            lease_owner="owner",
            lease_expires_at="2026-10-22T00:00:30+00:00",
        )
        is not None
    )

    fresh = goal_record(key="sweep-fresh")
    store.create_goal(fresh)
    store.update_goal(
        fresh["id"],
        expected_status="pending_approval",
        fields={
            "status": "approved",
            "execute_before": "2026-10-22T02:00:00+00:00",
            "updated_at": "2026-10-22T00:00:00+00:00",
        },
    )
    assert (
        store.claim_execution(
            fresh["id"],
            plan_hash=fresh["plan_hash"],
            now="2026-10-22T00:00:00+00:00",
            actor_sub="password:operator",
            actor_name="operator",
            run_id="run-fresh",
            lease_owner="owner",
            lease_expires_at="2026-10-22T01:00:00+00:00",
        )
        is not None
    )

    changes = store.sweep(
        now="2026-10-22T00:05:00+00:00",
        stale_before="2026-10-22T00:04:00+00:00",
    )
    by_goal = {change["goal_id"]: change for change in changes}
    assert by_goal[pending["id"]]["status"] == "expired"
    assert by_goal[approved["id"]]["status"] == "expired"
    assert by_goal[stale["id"]]["status"] == "unknown"
    assert by_goal[stale["id"]]["reason"] == "lease_expired"
    assert fresh["id"] not in by_goal

    assert store.get_goal(pending["id"])["status"] == "expired"
    assert store.get_goal(approved["id"])["status"] == "expired"
    assert store.get_goal(stale["id"])["status"] == "unknown"
    assert store.get_goal(fresh["id"])["status"] == "dispatching"
    stale_run = store.get_run(stale["id"])
    assert stale_run["status"] == "unknown"
    assert stale_run["error_code"] == "lease_expired"
    assert store.get_run(fresh["id"])["status"] == "dispatching"
