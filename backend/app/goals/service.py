"""Goal preview / approval service.

The service is the only place that builds a plan. It resolves the target from
live healer state, treats upstream evidence as untrusted input, stores an
immutable plan plus hash, and enforces the approval rules server-side.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..auth import is_approver
from ..config import Settings
from ..upstream import ProbeResult, Upstream
from . import planner
from .schemas import (
    ApprovalRequirements,
    ApproveRequest,
    CancelRequest,
    CreateGoalRequest,
    GoalCreated,
    GoalList,
    GoalView,
    PreviewRequest,
    PreviewResponse,
    RejectRequest,
    TemplateInfo,
    TemplatesResponse,
)
from .store import (
    Store,
    generate_approval_code,
    hash_approval_code,
    verify_approval_code,
)
from .templates import GUEST_RECOVER, TEMPLATES, get_template

ADMIN_STATUSES = {"pending_approval", "approved"}
TERMINAL_STATUSES = {"succeeded", "failed", "unknown", "rejected", "cancelled", "expired"}
ACTION_RANK = {"start": 1, "resume": 1, "reset": 3, "noop": 0, "escalate": 0}


class GoalError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class Actor:
    sub: str
    name: str
    method: str
    groups: list[str] | None = None
    client_ip: str = ""
    user_agent: str = ""

    @classmethod
    def from_user(cls, user: dict[str, Any], request: Any = None) -> Actor:
        ip = ""
        ua = ""
        if request is not None:
            forwarded = request.headers.get("x-forwarded-for")
            ip = (
                forwarded.split(",")[0].strip()
                if forwarded
                else (request.client.host if request.client else "")
            )
            ua = request.headers.get("user-agent", "")
        raw_groups = user.get("groups")
        groups = [str(item) for item in raw_groups] if isinstance(raw_groups, list) else []
        return cls(
            sub=str(user.get("sub") or user.get("name") or ""),
            name=str(user.get("name") or ""),
            method=str(user.get("method") or ""),
            groups=groups,
            client_ip=ip[:80],
            user_agent=ua[:300],
        )


@dataclass(slots=True)
class Snapshot:
    target: dict[str, Any] | None
    evidence: dict[str, Any]
    auto_ids: set[int]
    protect: set[int]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _expired(value: str) -> bool:
    parsed = _parse(value)
    return parsed is None or parsed <= _now()


def _json(value: str, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _int_set(value: Any) -> set[int] | None:
    """Parse a vmid list fail-closed.

    PROTECT is absolute. If the knob is missing or any entry is malformed we
    must not silently treat the list as empty, because that would turn a
    protected target into an actionable one.
    """
    if not isinstance(value, list):
        return None
    out: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            number = item
        elif isinstance(item, str) and item.strip().isdigit():
            number = int(item.strip())
        else:
            return None
        if number <= 0:
            return None
        out.add(number)
    return out


def _short(value: Any, limit: int) -> str:
    return planner.clean_text(value, limit)


def _guest_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("ct", "lxc", "container"):
        return "ct"
    if raw in ("vm", "qemu"):
        return "vm"
    return ""


class GoalService:
    def __init__(self, settings: Settings, store: Store, upstream: Upstream) -> None:
        self.settings = settings
        self.store = store
        self.upstream = upstream

    # --------------------------------------------------------------- templates
    def templates(self) -> TemplatesResponse:
        items: list[TemplateInfo] = []
        for template in TEMPLATES.values():
            data = dict(template)
            items.append(
                TemplateInfo(
                    **{key: value for key, value in data.items() if key != "manual_secrets"},
                    manual_secrets=data.get("manual_secrets", []),
                    execution_enabled=self.settings.goals_execute_enabled,
                )
            )
        return TemplatesResponse(templates=items)

    # ---------------------------------------------------------------- snapshot
    async def _snapshot(self, vmid: int) -> Snapshot:
        results = await asyncio.gather(
            self.upstream.healer("state", "/api/state"),
            self.upstream.healer("knobs", "/api/knobs"),
            self.upstream.healer("decisions", "/api/decisions?n=50"),
            self.upstream.healer("pending", "/api/pending"),
            return_exceptions=True,
        )
        state_result, knobs_result, decisions_result, pending_result = results
        if isinstance(state_result, Exception) or not state_result.ok:
            raise GoalError(503, "healer_state_unavailable")
        if isinstance(knobs_result, Exception) or not knobs_result.ok:
            raise GoalError(503, "healer_knobs_unavailable")
        state = state_result.value if isinstance(state_result.value, dict) else {}
        knobs = knobs_result.value if isinstance(knobs_result.value, dict) else {}
        row = state.get(str(vmid))
        if not isinstance(row, dict):
            raise GoalError(404, "target_not_found")

        guest_type = _guest_type(row.get("jenis") or row.get("jenis_guest"))
        node = _short(row.get("node"), 80)
        name = _short(row.get("nama"), 120)
        status = _short(row.get("status"), 40) or "unknown"
        raw_agent = row.get("agent")
        agent = raw_agent if isinstance(raw_agent, bool) else None
        auto_ids = _int_set(knobs.get("AUTO_IDS"))
        protect = _int_set(knobs.get("PROTECT"))
        if auto_ids is None or protect is None:
            raise GoalError(503, "healer_knobs_unavailable")

        peers = [
            item
            for item in state.values()
            if isinstance(item, dict) and str(item.get("node") or "") == node
        ]
        peers_running = sum(1 for item in peers if item.get("status") == "running")

        decisions: list[dict[str, Any]] = []
        decisions_ok = not isinstance(decisions_result, Exception) and decisions_result.ok
        if decisions_ok:
            raw_decisions = decisions_result.value
            if isinstance(raw_decisions, list):
                for item in raw_decisions:
                    if not isinstance(item, dict):
                        continue
                    try:
                        item_vmid = int(item.get("vmid"))
                    except (TypeError, ValueError):
                        continue
                    if item_vmid != vmid:
                        continue
                    decisions.append(
                        {
                            "ts": _short(item.get("ts"), 40),
                            "aksi": _short(item.get("aksi"), 40),
                            "sumber": _short(item.get("sumber"), 40),
                            "hasil": _short(item.get("hasil"), 40),
                            "alasan": _short(item.get("alasan"), 300),
                            "ket": _short(item.get("ket"), 300),
                            "oleh": _short(item.get("oleh"), 120),
                            "status": _short(item.get("status"), 40),
                            "jenis_guest": _short(item.get("jenis_guest"), 20),
                            "agent": item.get("agent") if isinstance(item.get("agent"), bool) else None,
                        }
                    )
                    if len(decisions) >= 5:
                        break

        pending: list[dict[str, Any]] = []
        pending_ok = not isinstance(pending_result, Exception) and pending_result.ok
        if pending_ok and isinstance(pending_result.value, list):
            for item in pending_result.value:
                if not isinstance(item, dict):
                    continue
                try:
                    item_vmid = int(item.get("vmid"))
                except (TypeError, ValueError):
                    continue
                if item_vmid != vmid:
                    continue
                pending.append(
                    {
                        "aksi": _short(item.get("aksi"), 40),
                        "sumber": _short(item.get("sumber"), 40),
                        "status": _short(item.get("status"), 40),
                        "alasan": _short(item.get("alasan"), 300),
                        "diminta": _short(item.get("diminta"), 40),
                        "kedaluwarsa": _short(item.get("kedaluwarsa"), 40),
                    }
                )
                if len(pending) >= 5:
                    break

        target = {
            "vmid": vmid,
            "name": name,
            "node": node,
            "guest_type": guest_type,
            "status": status,
            "agent": agent,
            "agent_gagal": int(row.get("agent_gagal") or 0),
            "auto": vmid in auto_ids,
            "protected": vmid in protect,
        }
        evidence = {
            "observed": {
                "status": status,
                "node": node,
                "guest_type": guest_type,
                "agent": agent,
                "agent_gagal": target["agent_gagal"],
                "sejak": _short(row.get("sejak"), 60),
            },
            "node_peers": {"running": peers_running, "total": len(peers)},
            "recent_decisions": decisions,
            "pending": pending,
            "evidence_ok": {"decisions": bool(decisions_ok), "pending": bool(pending_ok)},
            "knobs": {
                "auto": vmid in auto_ids,
                "protected": vmid in protect,
                "dry_run": bool(knobs.get("DRY_RUN")),
            },
        }
        return Snapshot(target=target, evidence=evidence, auto_ids=auto_ids, protect=protect)

    # ----------------------------------------------------------------- preview
    async def preview(self, actor: Actor, request: PreviewRequest) -> PreviewResponse:
        template = get_template(request.template_id)
        if template is None:
            raise GoalError(404, "template_not_found")
        goal = _short(request.goal, self.settings.goals_max_goal_chars)
        if len(request.goal or "") > self.settings.goals_max_goal_chars:
            raise GoalError(422, "goal_too_long")

        snapshot = await self._snapshot(request.target.vmid)
        target = snapshot.target or {}
        variables = request.variables.model_dump()
        blocked_reason = ""
        warnings: list[str] = []
        missing: list[str] = []

        if target.get("protected"):
            plan = planner.build_plan(
                target | {"guest_type": target.get("guest_type") or "vm"},
                variables,
                goal,
                snapshot.evidence,
                action="escalate",
                risk="high",
                rationale="Target ada di daftar PROTECT; tidak ada aksi otomatis.",
                warnings=[],
                generated_by="rules",
            )
            blocked_reason = "protected_target"
        elif not target.get("guest_type") or not target.get("node"):
            plan = planner.build_plan(
                target | {"guest_type": target.get("guest_type") or "vm"},
                variables,
                goal,
                snapshot.evidence,
                action="escalate",
                risk="high",
                rationale="Metadata guest belum lengkap di state healer.",
                warnings=[],
                generated_by="rules",
            )
            blocked_reason = "target_metadata_missing"
        else:
            plan = await planner.decide(
                self.upstream,
                self.settings,
                target,
                variables,
                goal,
                snapshot.evidence,
            )
            action = plan["steps"][0]["action"]
            warnings = list(plan.get("warnings") or [])
            if action not in planner.EXECUTABLE:
                blocked_reason = "no_safe_action"

        plan_hash = planner.sha256_json(plan)
        now = _now()
        expires = now + timedelta(seconds=max(30, self.settings.goals_preview_ttl))
        preview_id = str(uuid.uuid4())
        self.store.create_preview(
            {
                "id": preview_id,
                "created_by_sub": actor.sub,
                "created_by_name": actor.name,
                "created_at": _iso(now),
                "expires_at": _iso(expires),
                "template_id": request.template_id,
                "template_version": str(template["version"]),
                "target_vmid": request.target.vmid,
                "target_node": str(target.get("node") or ""),
                "target_type": str(target.get("guest_type") or ""),
                "goal": goal,
                "variables_json": json.dumps(variables, sort_keys=True),
                "plan_json": json.dumps(plan, sort_keys=True),
                "plan_hash": plan_hash,
                "evidence_json": json.dumps(snapshot.evidence, sort_keys=True),
                "evidence_hash": plan.get("evidence_hash", ""),
                "warnings_json": json.dumps(warnings, sort_keys=True),
                "status": "blocked" if blocked_reason else "ready",
                "blocked_reason": blocked_reason,
            }
        )
        self.store.audit(
            ts=_iso(now),
            goal_id=preview_id,
            actor_sub=actor.sub,
            actor_name=actor.name,
            actor_method=actor.method,
            event="preview.created",
            detail={
                "template_id": request.template_id,
                "vmid": request.target.vmid,
                "action": plan["steps"][0]["action"],
                "plan_hash": plan_hash,
                "status": "blocked" if blocked_reason else "ready",
                "blocked_reason": blocked_reason,
            },
            client_ip=actor.client_ip,
            user_agent=actor.user_agent,
        )
        return PreviewResponse(
            preview_id=preview_id,
            status="blocked" if blocked_reason else "ready",
            plan=plan,
            plan_hash=plan_hash,
            warnings=warnings,
            missing=missing,
            blocked_reason=blocked_reason,
            expires_at=_iso(expires),
        )

    # ------------------------------------------------------------------ create
    async def create(self, actor: Actor, request: CreateGoalRequest) -> GoalCreated:
        existing = self.store.get_goal_by_idempotency(actor.sub, request.idempotency_key)
        if existing is not None:
            return self._created_view(existing, None, replay=True)

        preview = self.store.get_preview(request.preview_id)
        if preview is None or preview.get("created_by_sub") != actor.sub:
            raise GoalError(404, "preview_not_found")
        if preview.get("used"):
            raise GoalError(409, "preview_used")
        if _expired(str(preview.get("expires_at") or "")):
            raise GoalError(410, "preview_expired")
        if preview.get("plan_hash") != request.plan_hash:
            raise GoalError(409, "plan_hash_mismatch")
        if preview.get("status") != "ready":
            raise GoalError(409, "preview_blocked")
        plan = _json(str(preview.get("plan_json") or ""), {})
        if not isinstance(plan, dict) or not plan.get("steps"):
            raise GoalError(409, "preview_invalid")
        if planner.sha256_json(plan) != request.plan_hash:
            raise GoalError(409, "plan_hash_mismatch")

        vmid = int(preview["target_vmid"])
        snapshot = await self._snapshot(vmid)
        self._recheck_target(preview, plan, snapshot)

        if self.store.count_goals_since(
            actor.sub, _iso(_now() - timedelta(hours=1))
        ) >= self.settings.goals_rate_limit_per_hour:
            raise GoalError(429, "rate_limited")

        if not self.store.mark_preview_used(request.preview_id, actor.sub):
            concurrent = self.store.get_goal_by_idempotency(actor.sub, request.idempotency_key)
            if concurrent is not None:
                return self._created_view(concurrent, None, replay=True)
            raise GoalError(409, "preview_used")

        now = _now()
        code = generate_approval_code()
        salt = secrets.token_hex(16)
        digest = await asyncio.to_thread(hash_approval_code, code, salt)
        goal_id = str(uuid.uuid4())
        target = plan.get("target") or {}
        active = snapshot.target or {}
        target_json = json.dumps(
            {
                "vmid": vmid,
                "name": target.get("name") or active.get("name") or "",
                "node": target.get("node") or active.get("node") or "",
                "guest_type": target.get("guest_type") or active.get("guest_type") or "",
                "status": target.get("status") or active.get("status") or "",
                "agent": active.get("agent"),
                "auto": bool(active.get("auto")),
            },
            sort_keys=True,
        )
        record = {
            "id": goal_id,
            "preview_id": request.preview_id,
            "status": "pending_approval",
            "requested_by_sub": actor.sub,
            "requested_by_name": actor.name,
            "requested_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=max(60, self.settings.goals_approval_ttl))),
            "template_id": str(preview["template_id"]),
            "template_version": str(preview["template_version"]),
            "target_vmid": vmid,
            "target_node": str(preview["target_node"]),
            "target_type": str(preview["target_type"]),
            "target_json": target_json,
            "goal": str(preview["goal"]),
            "variables_json": str(preview["variables_json"]),
            "plan_json": json.dumps(plan, sort_keys=True),
            "plan_hash": request.plan_hash,
            "evidence_hash": str(preview["evidence_hash"]),
            "warnings_json": str(preview["warnings_json"]),
            "approval_code_salt": salt,
            "approval_code_hash": digest,
            "idempotency_key": request.idempotency_key,
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        row, replay = self.store.create_goal(record)
        self.store.audit(
            ts=_iso(now),
            goal_id=goal_id,
            actor_sub=actor.sub,
            actor_name=actor.name,
            actor_method=actor.method,
            event="goal.created",
            detail={
                "vmid": vmid,
                "action": plan["steps"][0]["action"],
                "plan_hash": request.plan_hash,
                "replay": replay,
            },
            client_ip=actor.client_ip,
            user_agent=actor.user_agent,
        )
        return self._created_view(row, None if replay else code, replay=replay)

    def _recheck_target(
        self, preview: dict[str, Any], plan: dict[str, Any], snapshot: Snapshot
    ) -> None:
        active = snapshot.target
        if active is None:
            raise GoalError(409, "state_changed")
        if active.get("protected"):
            raise GoalError(409, "protected_target")
        target = plan.get("target") or {}
        for field in ("vmid", "node", "guest_type", "status"):
            expected = target.get(field)
            current = active.get(field)
            if field == "vmid":
                try:
                    expected = int(expected)
                    current = int(current)
                except (TypeError, ValueError):
                    raise GoalError(409, "state_changed") from None
            if str(expected or "") != str(current or ""):
                raise GoalError(409, "state_changed")
        old_evidence = _json(str(preview.get("evidence_json") or ""), {})
        old_agent = (old_evidence.get("observed") or {}).get("agent")
        if old_agent != active.get("agent"):
            raise GoalError(409, "state_changed")

    # ----------------------------------------------------------------- approval
    async def approve(
        self, actor: Actor, goal_id: str, request: ApproveRequest
    ) -> GoalView:
        if not is_approver(self.settings, self._approver_user(actor)):
            raise GoalError(403, "approver role required")
        goal = self._load(goal_id)
        if goal["status"] == "expired":
            raise GoalError(410, "goal_expired")
        view = self._view(goal, actor, True)
        if not view.can_approve:
            if goal["status"] == "pending_approval" and goal.get("requested_by_sub") == actor.sub:
                raise GoalError(403, "self_approval_forbidden")
            raise GoalError(409, "goal_not_pending")
        if goal.get("plan_hash") != request.plan_hash:
            raise GoalError(409, "plan_hash_mismatch")
        if not request.confirm:
            raise GoalError(400, "confirmation_required")

        now = _now()
        attempts = self.store.bump_approval_attempt(
            goal_id,
            now=_iso(now),
            window_start=str(goal.get("approval_window_start") or ""),
            window_seconds=15 * 60,
        )
        if attempts > 5:
            self._audit(
                goal_id,
                actor,
                "approval.blocked",
                {"reason": "too_many_attempts", "attempts": attempts},
                now,
            )
            raise GoalError(429, "too_many_approval_attempts")
        valid = await asyncio.to_thread(
            verify_approval_code,
            request.approval_code,
            str(goal.get("approval_code_salt") or ""),
            str(goal.get("approval_code_hash") or ""),
        )
        if not valid:
            self._audit(
                goal_id,
                actor,
                "approval.failed",
                {"reason": "invalid_code", "attempts": attempts},
                now,
            )
            raise GoalError(403, "invalid_approval_code")

        action, high_risk = self._risk(goal)
        if high_risk:
            passphrase = self.settings.goals_high_risk_passphrase
            if passphrase:
                supplied = request.high_risk_passphrase.encode("utf-8")
                if not supplied or not hmac.compare_digest(supplied, passphrase.encode("utf-8")):
                    raise GoalError(403, "high_risk_passphrase_invalid")
            else:
                confirmation = f"SETUJU {action} {goal['target_vmid']}"
                if request.confirmation.strip().upper() != confirmation.upper():
                    raise GoalError(400, "typed_confirmation_required")

        updated = self.store.update_goal(
            goal_id,
            expected_status="pending_approval",
            fields={
                "status": "approved",
                "approved_by_sub": actor.sub,
                "approved_by_name": actor.name,
                "approved_at": _iso(now),
                "execute_before": _iso(
                    now + timedelta(seconds=max(60, self.settings.goals_execution_ttl))
                ),
                "approval_code_salt": "",
                "approval_code_hash": "",
                "approval_attempts": 0,
                "approval_window_start": "",
                "updated_at": _iso(now),
            },
        )
        if updated is None:
            raise GoalError(409, "state_changed")
        self._audit(
            goal_id,
            actor,
            "goal.approved",
            {
                "action": action,
                "plan_hash": goal["plan_hash"],
                "vmid": goal["target_vmid"],
                "high_risk": high_risk,
            },
            now,
        )
        return self._view(updated, actor, True)

    async def reject(
        self, actor: Actor, goal_id: str, request: RejectRequest
    ) -> GoalView:
        goal = self._load(goal_id)
        view = self._view(goal, actor, True)
        if not is_approver(self.settings, self._approver_user(actor)):
            raise GoalError(403, "approver role required")
        if goal["status"] != "pending_approval" or _expired(str(goal.get("expires_at") or "")):
            raise GoalError(409, "goal_not_pending")
        if goal.get("plan_hash") != request.plan_hash:
            raise GoalError(409, "plan_hash_mismatch")
        now = _now()
        updated = self.store.update_goal(
            goal_id,
            expected_status="pending_approval",
            fields={
                "status": "rejected",
                "rejected_by_sub": actor.sub,
                "rejected_by_name": actor.name,
                "rejected_at": _iso(now),
                "reject_reason": planner.clean_text(request.reason, 300),
                "approval_code_salt": "",
                "approval_code_hash": "",
                "updated_at": _iso(now),
            },
        )
        if updated is None:
            raise GoalError(409, "state_changed")
        self._audit(
            goal_id,
            actor,
            "goal.rejected",
            {"reason": planner.clean_text(request.reason, 300), "plan_hash": goal["plan_hash"]},
            now,
        )
        return view if updated is None else self._view(updated, actor, True)

    async def cancel(
        self, actor: Actor, goal_id: str, request: CancelRequest
    ) -> GoalView:
        goal = self._load(goal_id)
        approver = is_approver(self.settings, self._approver_user(actor))
        if goal.get("requested_by_sub") != actor.sub and not approver:
            raise GoalError(404, "goal_not_found")
        if goal["status"] not in ADMIN_STATUSES:
            raise GoalError(409, "goal_not_cancellable")
        now = _now()
        updated = self.store.update_goal(
            goal_id,
            expected_status=goal["status"],
            fields={
                "status": "cancelled",
                "reject_reason": planner.clean_text(request.reason, 300),
                "approval_code_salt": "",
                "approval_code_hash": "",
                "updated_at": _iso(now),
            },
        )
        if updated is None:
            raise GoalError(409, "state_changed")
        self._audit(
            goal_id,
            actor,
            "goal.cancelled",
            {"reason": planner.clean_text(request.reason, 300)},
            now,
        )
        return self._view(updated, actor, approver)

    # ------------------------------------------------------------------ execute
    def execute(self, actor: Actor, goal_id: str, plan_hash: str) -> None:
        # Phase 1 intentionally has no dispatch path.
        raise GoalError(409, "execution_disabled")

    def reconcile(self, actor: Actor, goal_id: str) -> None:
        raise GoalError(409, "execution_disabled")

    # --------------------------------------------------------------- read views
    def get(self, actor: Actor, goal_id: str) -> GoalView:
        goal = self._load(goal_id)
        approver = is_approver(self.settings, self._approver_user(actor))
        if goal.get("requested_by_sub") != actor.sub and not approver:
            raise GoalError(404, "goal_not_found")
        return self._view(goal, actor, approver)

    def list(
        self, actor: Actor, *, status: str | None, limit: int, cursor: str | None
    ) -> GoalList:
        approver = is_approver(self.settings, self._approver_user(actor))
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError:
            offset = 0
        rows, next_cursor = self.store.list_goals(
            owner_sub=actor.sub,
            is_approver=approver,
            status=status,
            limit=limit,
            offset=offset,
        )
        return GoalList(
            goals=[self._view(row, actor, approver) for row in rows],
            next_cursor=next_cursor,
        )

    def audit(self, actor: Actor, goal_id: str) -> list[dict[str, Any]]:
        goal = self._load(goal_id)
        approver = is_approver(self.settings, self._approver_user(actor))
        if goal.get("requested_by_sub") != actor.sub and not approver:
            raise GoalError(404, "goal_not_found")
        return self.store.list_audit(goal_id)

    # -------------------------------------------------------------------- helpers
    def _load(self, goal_id: str) -> dict[str, Any]:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise GoalError(404, "goal_not_found")
        self._expire_if_needed(goal)
        refreshed = self.store.get_goal(goal_id)
        return refreshed or goal

    def _expire_if_needed(self, goal: dict[str, Any]) -> None:
        now = _now()
        status = goal.get("status")
        if status == "pending_approval" and _expired(str(goal.get("expires_at") or "")):
            self.store.update_goal(
                str(goal["id"]),
                expected_status="pending_approval",
                fields={"status": "expired", "updated_at": _iso(now)},
            )
        elif status == "approved" and _expired(str(goal.get("execute_before") or "")):
            self.store.update_goal(
                str(goal["id"]),
                expected_status="approved",
                fields={"status": "expired", "updated_at": _iso(now)},
            )

    def _approver_user(self, actor: Actor) -> dict[str, Any]:
        return {
            "name": actor.name,
            "sub": actor.sub,
            "method": actor.method,
            "groups": list(actor.groups or []),
        }

    def _risk(self, goal: dict[str, Any]) -> tuple[str, bool]:
        plan = _json(str(goal.get("plan_json") or ""), {})
        steps = plan.get("steps") if isinstance(plan, dict) else None
        action = str(steps[0].get("action") or "") if isinstance(steps, list) and steps else ""
        target = _json(str(goal.get("target_json") or ""), {})
        high = action == "reset" or not bool(target.get("auto"))
        return action, high

    def _view(
        self, goal: dict[str, Any], actor: Actor, is_approver_actor: bool
    ) -> GoalView:
        status = str(goal.get("status") or "pending_approval")
        plan = _json(str(goal.get("plan_json") or ""), {})
        target = _json(str(goal.get("target_json") or ""), {})
        plan_target = plan.get("target") if isinstance(plan, dict) else {}
        steps = plan.get("steps") if isinstance(plan, dict) else None
        action = (
            str(steps[0].get("action") or "")
            if isinstance(steps, list) and steps and isinstance(steps[0], dict)
            else ""
        )
        high_risk = action == "reset" or not bool(target.get("auto"))
        owner = goal.get("requested_by_sub") == actor.sub
        pending_live = status == "pending_approval" and not _expired(
            str(goal.get("expires_at") or "")
        )
        can_approve = bool(
            pending_live
            and is_approver_actor
            and (not owner or self.settings.goals_allow_self_approval)
        )
        can_execute = bool(
            status == "approved"
            and self.settings.goals_execute_enabled
            and is_approver_actor
            and not _expired(str(goal.get("execute_before") or ""))
        )
        if self.settings.auth_mode == "password":
            approval_mode = "password_single_person"
        elif self.settings.goals_allow_self_approval:
            approval_mode = "self_allowed"
        else:
            approval_mode = "two_person"
        confirmation_hint = (
            f"SETUJU {action} {goal.get('target_vmid')}" if high_risk else ""
        )
        return GoalView(
            id=str(goal["id"]),
            status=status,  # type: ignore[arg-type]
            template_id=str(goal.get("template_id") or ""),
            template_version=str(goal.get("template_version") or ""),
            target=(
                {**plan_target, "auto": bool(target.get("auto"))}
                if isinstance(plan_target, dict)
                else target
            ),
            goal=str(goal.get("goal") or ""),
            variables=_json(str(goal.get("variables_json") or ""), {}),
            plan=plan if isinstance(plan, dict) else {},
            plan_hash=str(goal.get("plan_hash") or ""),
            evidence_hash=str(goal.get("evidence_hash") or ""),
            warnings=_json(str(goal.get("warnings_json") or ""), []),
            requested_by=str(goal.get("requested_by_name") or ""),
            requested_by_sub=str(goal.get("requested_by_sub") or ""),
            requested_at=str(goal.get("requested_at") or ""),
            expires_at=str(goal.get("expires_at") or ""),
            approved_by=str(goal.get("approved_by_name") or ""),
            approved_at=str(goal.get("approved_at") or ""),
            rejected_by=str(goal.get("rejected_by_name") or ""),
            rejected_at=str(goal.get("rejected_at") or ""),
            reject_reason=str(goal.get("reject_reason") or ""),
            execute_before=str(goal.get("execute_before") or ""),
            run=self.store.get_run(str(goal["id"])),
            result=_json(str(goal.get("result_json") or ""), None),
            error=str(goal.get("error") or ""),
            created_at=str(goal.get("created_at") or ""),
            updated_at=str(goal.get("updated_at") or ""),
            can_approve=can_approve,
            can_execute=can_execute,
            approval_mode=approval_mode,
            execution_enabled=self.settings.goals_execute_enabled,
            high_risk=high_risk,
            requirements=ApprovalRequirements(
                approval_code=True,
                confirm=True,
                high_risk=high_risk,
                passphrase_required=bool(high_risk and self.settings.goals_high_risk_passphrase),
                typed_confirmation=confirmation_hint if high_risk else "",
            ),
        )

    def _created_view(
        self, goal: dict[str, Any], code: str | None, *, replay: bool
    ) -> GoalCreated:
        actor = Actor(
            sub=str(goal.get("requested_by_sub") or ""),
            name=str(goal.get("requested_by_name") or ""),
            method="",
        )
        base = self._view(goal, actor, is_approver(self.settings, self._approver_user(actor)))
        return GoalCreated(
            **base.model_dump(),
            approval_code=code,
            idempotent_replay=replay,
        )

    def _audit(
        self,
        goal_id: str,
        actor: Actor,
        event: str,
        detail: dict[str, Any],
        now: datetime,
    ) -> None:
        self.store.audit(
            ts=_iso(now),
            goal_id=goal_id,
            actor_sub=actor.sub,
            actor_name=actor.name,
            actor_method=actor.method,
            event=event,
            detail=detail,
            client_ip=actor.client_ip,
            user_agent=actor.user_agent,
        )
