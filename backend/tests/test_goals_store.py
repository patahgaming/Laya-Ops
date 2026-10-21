from __future__ import annotations

import json
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
