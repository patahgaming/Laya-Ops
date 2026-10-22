"""Small SQLite store for immutable plans, approvals and audit.

One process-wide connection guarded by a lock is deliberate: Laya Ops is a
single-worker deployment and the goals feature is low-volume. Every status
transition is still conditional on the expected previous status, so two
requests can never both win an approval or execution race.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Any, ClassVar

SCHEMA_VERSION = 3
APPROVAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_previews (
    id TEXT PRIMARY KEY,
    created_by_sub TEXT NOT NULL,
    created_by_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    target_kind TEXT NOT NULL DEFAULT 'proxmox_guest',
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

CREATE TABLE IF NOT EXISTS goal_requests (
    id TEXT PRIMARY KEY,
    preview_id TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by_sub TEXT NOT NULL,
    requested_by_name TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    target_vmid INTEGER NOT NULL,
    target_node TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_json TEXT NOT NULL,
    goal TEXT NOT NULL,
    variables_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    plan_id TEXT NOT NULL DEFAULT '',
    plan_hash TEXT NOT NULL,
    target_kind TEXT NOT NULL DEFAULT 'proxmox_guest',
    evidence_hash TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    approval_code_salt TEXT NOT NULL,
    approval_code_hash TEXT NOT NULL,
    approval_attempts INTEGER NOT NULL DEFAULT 0,
    approval_last_attempt TEXT NOT NULL DEFAULT '',
    approval_window_start TEXT NOT NULL DEFAULT '',
    approved_by_sub TEXT NOT NULL DEFAULT '',
    approved_by_name TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL DEFAULT '',
    rejected_by_sub TEXT NOT NULL DEFAULT '',
    rejected_by_name TEXT NOT NULL DEFAULT '',
    rejected_at TEXT NOT NULL DEFAULT '',
    reject_reason TEXT NOT NULL DEFAULT '',
    execute_before TEXT NOT NULL DEFAULT '',
    execute_requested_at TEXT NOT NULL DEFAULT '',
    execute_by_sub TEXT NOT NULL DEFAULT '',
    execute_by_name TEXT NOT NULL DEFAULT '',
    execute_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (requested_by_sub, idempotency_key)
);

CREATE TABLE IF NOT EXISTS goal_runs (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL,
    status TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    request_sent_at TEXT NOT NULL DEFAULT '',
    accepted_at TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    heartbeat_at TEXT NOT NULL DEFAULT '',
    last_polled_at TEXT NOT NULL DEFAULT '',
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS goal_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    plan_id TEXT NOT NULL DEFAULT '',
    actor_sub TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    actor_method TEXT NOT NULL,
    event TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    client_ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_goal_requests_status ON goal_requests(status);
CREATE INDEX IF NOT EXISTS idx_goal_requests_owner ON goal_requests(requested_by_sub, requested_at);
CREATE INDEX IF NOT EXISTS idx_goal_audit_goal ON goal_audit(goal_id, id);
"""

# Indexes yang memakai kolom v2 harus dibuat setelah migrasi, bukan di SCHEMA:
# database v1 belum punya kolom-kolom itu dan CREATE INDEX akan gagal.
SCHEMA_V2_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_goal_requests_plan
    ON goal_requests(plan_id) WHERE plan_id != '';
CREATE INDEX IF NOT EXISTS idx_goal_runs_lease
    ON goal_runs(status, lease_expires_at);
"""

_V2_GOAL_COLUMNS = {
    "plan_id": "TEXT NOT NULL DEFAULT ''",
    "target_kind": "TEXT NOT NULL DEFAULT 'proxmox_guest'",
    "execute_requested_at": "TEXT NOT NULL DEFAULT ''",
    "execute_by_sub": "TEXT NOT NULL DEFAULT ''",
    "execute_by_name": "TEXT NOT NULL DEFAULT ''",
    "execute_count": "INTEGER NOT NULL DEFAULT 0",
}

_V2_RUN_COLUMNS = {
    "request_sent_at": "TEXT NOT NULL DEFAULT ''",
    "accepted_at": "TEXT NOT NULL DEFAULT ''",
    "heartbeat_at": "TEXT NOT NULL DEFAULT ''",
    "last_polled_at": "TEXT NOT NULL DEFAULT ''",
    "lease_owner": "TEXT NOT NULL DEFAULT ''",
    "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
    "error_code": "TEXT NOT NULL DEFAULT ''",
    "dry_run": "INTEGER NOT NULL DEFAULT 0",
}

_V2_AUDIT_COLUMNS = {
    "plan_id": "TEXT NOT NULL DEFAULT ''",
}

_V3_PREVIEW_COLUMNS = {
    "target_kind": "TEXT NOT NULL DEFAULT 'proxmox_guest'",
}


def generate_approval_code() -> str:
    return "".join(secrets.choice(APPROVAL_ALPHABET) for _ in range(12))


def hash_approval_code(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), salt.encode("ascii"), 210_000
    ).hex()


def verify_approval_code(code: str, salt: str, expected_hash: str) -> bool:
    if not code or not salt or not expected_hash:
        return False
    actual = hash_approval_code(code, salt)
    return hmac.compare_digest(actual, expected_hash)


class Store:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "goals.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.data_dir, 0o700)
            except OSError:
                pass
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.isolation_level = None
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._conn = conn
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            else:
                version = int(row["version"])
                if version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"goals database schema v{version} is newer than this app"
                    )
                if version < SCHEMA_VERSION:
                    self._migrate(conn, version)
            conn.executescript(SCHEMA_V2_INDEXES)
            conn.commit()
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass

    def _migrate(self, conn: sqlite3.Connection, version: int) -> None:
        """Forward-only in-place migration; never drops plan or audit data."""
        if version < 2:
            self._add_columns(conn, "goal_requests", _V2_GOAL_COLUMNS)
            self._add_columns(conn, "goal_runs", _V2_RUN_COLUMNS)
            self._add_columns(conn, "goal_audit", _V2_AUDIT_COLUMNS)
            conn.execute("UPDATE goal_requests SET plan_id = id WHERE plan_id = ''")
            conn.execute("UPDATE schema_meta SET version = 2")
        if version < 3:
            self._add_columns(conn, "goal_previews", _V3_PREVIEW_COLUMNS)
            conn.execute("UPDATE schema_meta SET version = 3")

    @staticmethod
    def _add_columns(
        conn: sqlite3.Connection, table: str, columns: dict[str, str]
    ) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("goals store is not initialized")
        return self._conn

    # ------------------------------------------------------------- previews
    def create_preview(self, record: dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("target_kind", "proxmox_guest")
        with self._lock:
            self._db().execute(
                """
                INSERT INTO goal_previews (
                    id, created_by_sub, created_by_name, created_at, expires_at,
                    template_id, template_version, target_kind, target_vmid,
                    target_node, target_type, goal, variables_json, plan_json,
                    plan_hash, evidence_json, evidence_hash, warnings_json,
                    status, blocked_reason, used
                ) VALUES (
                    :id, :created_by_sub, :created_by_name, :created_at, :expires_at,
                    :template_id, :template_version, :target_kind, :target_vmid,
                    :target_node, :target_type, :goal, :variables_json, :plan_json,
                    :plan_hash, :evidence_json, :evidence_hash, :warnings_json,
                    :status, :blocked_reason, 0
                )
                """,
                record,
            )
            self._db().commit()

    def get_preview(self, preview_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM goal_previews WHERE id = ?", (preview_id,)
            ).fetchone()
        return _row(row)

    def mark_preview_used(self, preview_id: str, owner_sub: str) -> bool:
        with self._lock:
            cur = self._db().execute(
                "UPDATE goal_previews SET used = 1 WHERE id = ? AND created_by_sub = ? AND used = 0",
                (preview_id, owner_sub),
            )
            self._db().commit()
            return cur.rowcount == 1

    # --------------------------------------------------------------- goals
    def create_goal(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert a goal; replaying the same user idempotency key returns the old row."""
        record = dict(record)
        record.setdefault("plan_id", record["id"])
        record.setdefault("target_kind", "proxmox_guest")
        with self._lock:
            try:
                self._db().execute(
                    """
                    INSERT INTO goal_requests (
                        id, preview_id, status, requested_by_sub, requested_by_name,
                        requested_at, expires_at, template_id, template_version,
                        target_vmid, target_node, target_type, target_json, goal,
                        variables_json, plan_json, plan_id, plan_hash, target_kind,
                        evidence_hash, warnings_json, approval_code_salt,
                        approval_code_hash, idempotency_key, created_at, updated_at
                    ) VALUES (
                        :id, :preview_id, :status, :requested_by_sub, :requested_by_name,
                        :requested_at, :expires_at, :template_id, :template_version,
                        :target_vmid, :target_node, :target_type, :target_json, :goal,
                        :variables_json, :plan_json, :plan_id, :plan_hash, :target_kind,
                        :evidence_hash, :warnings_json, :approval_code_salt,
                        :approval_code_hash, :idempotency_key, :created_at, :updated_at
                    )
                    """,
                    record,
                )
                self._db().commit()
                return self.get_goal(str(record["id"])) or {}, False
            except sqlite3.IntegrityError:
                row = self._db().execute(
                    "SELECT * FROM goal_requests WHERE requested_by_sub = ? AND idempotency_key = ?",
                    (record["requested_by_sub"], record["idempotency_key"]),
                ).fetchone()
                self._db().rollback()
                if row is None:
                    raise
                return _row(row) or {}, True

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM goal_requests WHERE id = ?", (goal_id,)
            ).fetchone()
        return _row(row)

    def get_goal_by_idempotency(
        self, owner_sub: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM goal_requests WHERE requested_by_sub = ? AND idempotency_key = ?",
                (owner_sub, idempotency_key),
            ).fetchone()
        return _row(row)

    def list_goals(
        self,
        *,
        owner_sub: str,
        is_approver: bool,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses: list[str] = []
        params: list[Any] = []
        if not is_approver:
            clauses.append("requested_by_sub = ?")
            params.append(owner_sub)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit + 1, offset])
        with self._lock:
            rows = self._db().execute(
                f"SELECT * FROM goal_requests {where} "
                "ORDER BY requested_at DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        return [_row(row) or {} for row in selected], (
            str(offset + limit) if has_more else None
        )

    def count_goals_since(self, owner_sub: str, since: str) -> int:
        with self._lock:
            row = self._db().execute(
                "SELECT COUNT(*) AS n FROM goal_requests "
                "WHERE requested_by_sub = ? AND requested_at >= ?",
                (owner_sub, since),
            ).fetchone()
        return int(row["n"]) if row else 0

    _GOAL_UPDATABLE: ClassVar[set[str]] = {
        "status",
        "approved_by_sub",
        "approved_by_name",
        "approved_at",
        "rejected_by_sub",
        "rejected_by_name",
        "rejected_at",
        "reject_reason",
        "execute_before",
        "execute_requested_at",
        "execute_by_sub",
        "execute_by_name",
        "execute_count",
        "run_id",
        "result_json",
        "error",
        "updated_at",
        "approval_code_salt",
        "approval_code_hash",
        "approval_attempts",
        "approval_last_attempt",
        "approval_window_start",
    }

    def update_goal(
        self,
        goal_id: str,
        *,
        expected_status: str | None = None,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        unknown = set(fields) - self._GOAL_UPDATABLE
        if unknown:
            raise ValueError(f"immutable goal fields: {sorted(unknown)}")
        if not fields:
            return self.get_goal(goal_id)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = list(fields.values()) + [goal_id]
        sql = f"UPDATE goal_requests SET {assignments} WHERE id = ?"
        if expected_status is not None:
            sql += " AND status = ?"
            params.append(expected_status)
        with self._lock:
            cur = self._db().execute(sql, params)
            self._db().commit()
            if cur.rowcount != 1:
                return None
            return self.get_goal(goal_id)

    def bump_approval_attempt(
        self, goal_id: str, *, now: str, window_start: str, window_seconds: int
    ) -> int:
        """Record one code attempt; resets the counter outside the window."""
        with self._lock:
            row = self._db().execute(
                "SELECT approval_attempts, approval_window_start FROM goal_requests WHERE id = ?",
                (goal_id,),
            ).fetchone()
            if row is None:
                return 0
            start = str(row["approval_window_start"] or "")
            attempts = int(row["approval_attempts"] or 0)
            if not start or _seconds_between(start, now) > window_seconds:
                attempts = 0
                start = now
            attempts += 1
            self._db().execute(
                "UPDATE goal_requests SET approval_attempts = ?, approval_window_start = ?, "
                "approval_last_attempt = ? WHERE id = ?",
                (attempts, start, now, goal_id),
            )
            self._db().commit()
            return attempts

    # ---------------------------------------------------------------- runs
    def create_run(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._db().execute(
                """
                INSERT INTO goal_runs (
                    id, goal_id, plan_id, status, claimed_at, request_sent_at,
                    accepted_at, started_at, finished_at, heartbeat_at,
                    last_polled_at, lease_owner, lease_expires_at, result_json,
                    error, error_code, dry_run, attempts
                ) VALUES (
                    :id, :goal_id, :plan_id, :status, :claimed_at, :request_sent_at,
                    :accepted_at, :started_at, :finished_at, :heartbeat_at,
                    :last_polled_at, :lease_owner, :lease_expires_at, :result_json,
                    :error, :error_code, :dry_run, 1
                )
                """,
                record,
            )
            self._db().commit()

    def claim_execution(
        self,
        goal_id: str,
        *,
        plan_hash: str,
        now: str,
        actor_sub: str,
        actor_name: str,
        run_id: str,
        lease_owner: str,
        lease_expires_at: str,
    ) -> dict[str, Any] | None:
        """Atomically move approved -> dispatching and create exactly one run.

        ``BEGIN IMMEDIATE`` makes the check-and-claim one transaction, so two
        approvers clicking Execute can never both dispatch. Returns None when
        the goal is not approved, the hash changed, or the window expired.
        """
        with self._lock:
            conn = self._db()
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM goal_requests WHERE id = ?", (goal_id,)
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                if str(row["status"]) != "approved":
                    conn.execute("ROLLBACK")
                    return None
                if str(row["plan_hash"]) != plan_hash:
                    conn.execute("ROLLBACK")
                    return None
                execute_before = str(row["execute_before"] or "")
                if not execute_before or execute_before <= now:
                    conn.execute("ROLLBACK")
                    return None
                existing = conn.execute(
                    "SELECT id FROM goal_runs WHERE goal_id = ?", (goal_id,)
                ).fetchone()
                effective_run_id = str(existing["id"]) if existing is not None else run_id
                cur = conn.execute(
                    """
                    UPDATE goal_requests
                       SET status = 'dispatching', execute_requested_at = ?,
                           execute_by_sub = ?, execute_by_name = ?,
                           run_id = ?, execute_count = execute_count + 1,
                           updated_at = ?
                     WHERE id = ? AND status = 'approved'
                    """,
                    (now, actor_sub, actor_name, effective_run_id, now, goal_id),
                )
                if cur.rowcount != 1:
                    conn.execute("ROLLBACK")
                    return None
                if existing is not None:
                    # Retry after a retryable control rejection (busy/cooldown):
                    # the goal returned to approved, the same run row is reused.
                    conn.execute(
                        """
                        UPDATE goal_runs
                           SET status = 'dispatching', claimed_at = ?,
                               request_sent_at = ?, accepted_at = '',
                               started_at = '', finished_at = '', heartbeat_at = ?,
                               last_polled_at = '', lease_owner = ?,
                               lease_expires_at = ?, result_json = '', error = '',
                               error_code = '', dry_run = 0,
                               attempts = attempts + 1
                         WHERE goal_id = ?
                        """,
                        (now, now, now, lease_owner, lease_expires_at, goal_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO goal_runs (
                            id, goal_id, plan_id, status, claimed_at, request_sent_at,
                            accepted_at, started_at, finished_at, heartbeat_at,
                            last_polled_at, lease_owner, lease_expires_at, result_json,
                            error, error_code, dry_run, attempts
                        ) VALUES (?, ?, ?, 'dispatching', ?, ?, '', '', '', ?, '', ?, ?, '', '', '', 0, 1)
                        """,
                        (run_id, goal_id, str(row["plan_id"] or goal_id), now, now,
                         now, lease_owner, lease_expires_at),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "goal": self.get_goal(goal_id),
            "run": self.get_run(goal_id),
        }

    def get_run(self, goal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db().execute(
                "SELECT * FROM goal_runs WHERE goal_id = ?", (goal_id,)
            ).fetchone()
        return _run_row(row)

    _RUN_UPDATABLE: ClassVar[set[str]] = {
        "status",
        "started_at",
        "finished_at",
        "request_sent_at",
        "accepted_at",
        "heartbeat_at",
        "last_polled_at",
        "lease_owner",
        "lease_expires_at",
        "result_json",
        "error",
        "error_code",
        "dry_run",
        "attempts",
    }

    def update_run(
        self,
        goal_id: str,
        fields: dict[str, Any],
        *,
        expected_status: str | None = None,
    ) -> dict[str, Any] | None:
        unknown = set(fields) - self._RUN_UPDATABLE
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        if not fields:
            return self.get_run(goal_id)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        sql = f"UPDATE goal_runs SET {assignments} WHERE goal_id = ?"
        params: list[Any] = list(fields.values()) + [goal_id]
        if expected_status is not None:
            sql += " AND status = ?"
            params.append(expected_status)
        with self._lock:
            cur = self._db().execute(sql, params)
            self._db().commit()
            if cur.rowcount != 1:
                return None
            return self.get_run(goal_id)

    def renew_run_lease(
        self, goal_id: str, *, owner: str, now: str, lease_expires_at: str
    ) -> bool:
        with self._lock:
            cur = self._db().execute(
                "UPDATE goal_runs SET heartbeat_at = ?, lease_expires_at = ?, "
                "last_polled_at = ? WHERE goal_id = ? AND lease_owner = ? "
                "AND status IN ('dispatching', 'executing')",
                (now, lease_expires_at, now, goal_id, owner),
            )
            self._db().commit()
            return cur.rowcount == 1

    # --------------------------------------------------------------- audit
    def audit(
        self,
        *,
        ts: str,
        goal_id: str,
        actor_sub: str,
        actor_name: str,
        actor_method: str,
        event: str,
        detail: dict[str, Any],
        client_ip: str = "",
        user_agent: str = "",
        plan_id: str = "",
    ) -> None:
        with self._lock:
            self._db().execute(
                """
                INSERT INTO goal_audit (
                    ts, goal_id, plan_id, actor_sub, actor_name, actor_method,
                    event, detail_json, client_ip, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    goal_id,
                    plan_id,
                    actor_sub,
                    actor_name,
                    actor_method,
                    event,
                    json.dumps(detail, sort_keys=True, ensure_ascii=False),
                    client_ip,
                    user_agent[:300],
                ),
            )
            self._db().commit()

    def list_audit(self, goal_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db().execute(
                "SELECT * FROM goal_audit WHERE goal_id = ? ORDER BY id ASC", (goal_id,)
            ).fetchall()
        return [
            {
                "ts": row["ts"],
                "goal_id": row["goal_id"],
                "actor": row["actor_name"],
                "actor_sub": row["actor_sub"],
                "actor_method": row["actor_method"],
                "event": row["event"],
                "detail": _json(row["detail_json"], {}),
                "client_ip": row["client_ip"],
                "user_agent": row["user_agent"],
            }
            for row in rows
        ]

    # -------------------------------------------------------------- sweeper
    def sweep(self, *, now: str, stale_before: str) -> list[dict[str, Any]]:
        """Expire windows and stale leases. Never marks a run successful."""
        changes: list[dict[str, Any]] = []
        with self._lock:
            conn = self._db()
            conn.execute("BEGIN IMMEDIATE")
            try:
                for status, table, column, reason in (
                    ("pending_approval", "goal_requests", "expires_at", "approval_expired"),
                    ("approved", "goal_requests", "execute_before", "execution_expired"),
                ):
                    rows = conn.execute(
                        f"SELECT id FROM {table} WHERE status = ? AND {column} != '' "
                        f"AND {column} <= ?",
                        (status, now),
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            "UPDATE goal_requests SET status = 'expired', updated_at = ? "
                            "WHERE id = ? AND status = ?",
                            (now, row["id"], status),
                        )
                        changes.append(
                            {
                                "goal_id": row["id"],
                                "previous": status,
                                "status": "expired",
                                "reason": reason,
                            }
                        )

                stale = conn.execute(
                    """
                    SELECT g.id AS id, g.status AS status
                      FROM goal_requests g
                      LEFT JOIN goal_runs r ON r.goal_id = g.id
                     WHERE g.status IN ('dispatching', 'executing')
                       AND (
                         (r.lease_expires_at IS NOT NULL AND r.lease_expires_at != ''
                          AND r.lease_expires_at <= ?)
                         OR ((r.lease_expires_at IS NULL OR r.lease_expires_at = '')
                             AND g.updated_at <= ?)
                       )
                    """,
                    (now, stale_before),
                ).fetchall()
                for row in stale:
                    conn.execute(
                        "UPDATE goal_requests SET status = 'unknown', updated_at = ?, "
                        "error = 'execution lease expired; state is unknown' "
                        "WHERE id = ? AND status = ?",
                        (now, row["id"], row["status"]),
                    )
                    conn.execute(
                        "UPDATE goal_runs SET status = 'unknown', finished_at = ?, "
                        "error = 'execution lease expired', error_code = 'lease_expired' "
                        "WHERE goal_id = ? AND status IN ('dispatching', 'executing')",
                        (now, row["id"]),
                    )
                    changes.append(
                        {
                            "goal_id": row["id"],
                            "previous": row["status"],
                            "status": "unknown",
                            "reason": "lease_expired",
                        }
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return changes


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "goal_id": row["goal_id"],
        "plan_id": row["plan_id"],
        "status": row["status"],
        "claimed_at": row["claimed_at"],
        "request_sent_at": row["request_sent_at"],
        "accepted_at": row["accepted_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "heartbeat_at": row["heartbeat_at"],
        "last_polled_at": row["last_polled_at"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "result": _json(row["result_json"], None),
        "error": row["error"],
        "error_code": row["error_code"],
        "dry_run": bool(row["dry_run"]),
        "attempts": row["attempts"],
    }


def _json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _seconds_between(start: str, end: str) -> float:
    from datetime import datetime

    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return 10**9
