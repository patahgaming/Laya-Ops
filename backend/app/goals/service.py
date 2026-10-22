"""Goal preview / approval service.

The service is the only place that builds a plan. It resolves the target from
live healer state, treats upstream evidence as untrusted input, stores an
immutable plan plus hash, and enforces the approval rules server-side.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from ..auth import is_approver
from ..config import Settings
from ..upstream import Upstream
from . import planner
from .control import ControlClient, ControlError
from .schemas import (
    ApprovalRequirements,
    ApproveRequest,
    CancelRequest,
    CreateGoalRequest,
    GoalCreated,
    GoalList,
    GoalView,
    K8sRollbackVariables,
    K8sTargetRef,
    PreviewRequest,
    PreviewResponse,
    RecoverVariables,
    RejectRequest,
    TargetRef,
    TargetsResponse,
    TemplateInfo,
    TemplatesResponse,
)
from .store import (
    Store,
    generate_approval_code,
    hash_approval_code,
    verify_approval_code,
)
from .templates import TEMPLATES, get_template

ADMIN_STATUSES = {"pending_approval", "approved"}
TERMINAL_STATUSES = {"succeeded", "failed", "unknown", "rejected", "cancelled", "expired"}
ACTION_RANK = {"start": 1, "resume": 1, "reset": 3, "noop": 0, "escalate": 0}
TARGET_KIND_GUEST = "proxmox_guest"
TARGET_KIND_K8S = "k8s_deployment"
ACTIVE_EXECUTION = {"dispatching", "executing"}
CONTROL_TERMINAL = {"done": "succeeded", "failed": "failed", "unknown": "unknown"}
# Rejections that mean "try again before execute_before"; the goal returns to
# approved and the same run row is reused. Nothing was executed.
CONTROL_RETRYABLE = {
    "busy",
    "cooldown",
    "incident_pending",
    "rate_limited",
    "run_in_progress",
    "state_unavailable",
    "approvals_unavailable",
}
CONTROL_EXPIRED = {"execution_expired"}


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


def _classify_rejection(status: int, body: dict[str, Any]) -> tuple[str, str]:
    """Map a healer rejection to retryable | failed | unknown.

    Only rejections that happen before the journal claim are retryable. A 5xx
    may have been raised after the claim, so it is always ``unknown``.
    """
    code = str(body.get("error") or "")[:80]
    if status == 429:
        return "retryable", code or "rate_limited"
    if status == 503:
        return "retryable", code or "control_unavailable"
    if 500 <= status < 600:
        return "unknown", code or "control_error"
    if status == 404:
        return "failed", "control_endpoint_missing"
    if 200 <= status < 300:
        return "unknown", "unexpected_success"
    if code in CONTROL_RETRYABLE:
        return "retryable", code
    return "failed", code or "control_rejected"


class GoalService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        upstream: Upstream,
        control: ControlClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.upstream = upstream
        self.control = control
        self._worker_id = uuid.uuid4().hex[:12]
        self._dispatch_sem = asyncio.Semaphore(1)
        self._tasks: set[asyncio.Task[Any]] = set()

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

    async def _k8s_snapshot(self, namespace: str, deployment: str) -> dict[str, Any]:
        """Read one Deployment from the healer's allow-listed k8s view.

        Only deployments the healer exposes are ever returned; a name that is
        not in the list is indistinguishable from one that does not exist.
        """
        result = await self.upstream.healer("k8s", "/api/k8s")
        if isinstance(result, Exception) or not result.ok:
            raise GoalError(503, "k8s_unavailable")
        value = result.value if isinstance(result.value, dict) else {}
        if not value.get("enabled"):
            raise GoalError(404, "target_not_allowed")
        rows = value.get("deployments")
        row = None
        if isinstance(rows, list):
            for item in rows:
                if (
                    isinstance(item, dict)
                    and str(item.get("namespace") or "") == namespace
                    and str(item.get("deployment") or "") == deployment
                ):
                    row = item
                    break
        if row is None:
            raise GoalError(404, "target_not_allowed")
        if not row.get("ok"):
            raise GoalError(503, "k8s_unavailable")
        if not row.get("protected") and not row.get("allowed"):
            raise GoalError(404, "target_not_allowed")
        return row

    @staticmethod
    def _k8s_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
        def _int(key: str) -> int:
            try:
                return int(snapshot.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        def _images(key: str) -> list[str]:
            value = snapshot.get(key)
            if not isinstance(value, list):
                return []
            return [_short(item, 300) for item in value[:20] if isinstance(item, str)]

        return {
            "observed": {
                "namespace": _short(snapshot.get("namespace"), 63),
                "deployment": _short(snapshot.get("deployment"), 253),
                "revision": _int("revision"),
                "previous_revision": _int("previous_revision"),
                "status": _short(snapshot.get("status"), 40),
                "replicas": _int("replicas"),
                "available": _int("available"),
                "ready": _int("ready"),
                "updated": _int("updated"),
                "images": _images("images"),
                "previous_images": _images("previous_images"),
            },
            "knobs": {
                "allowed": bool(snapshot.get("allowed")),
                "protected": bool(snapshot.get("protected")),
            },
        }

    # ----------------------------------------------------------------- targets
    async def targets(self, template_id: str) -> TargetsResponse:
        template = get_template(template_id)
        if template is None:
            raise GoalError(404, "template_not_found")
        if str(template.get("target_kind") or "guest") == TARGET_KIND_K8S:
            return await self._k8s_targets(template_id)
        return await self._guest_targets(template_id)

    async def _guest_targets(self, template_id: str) -> TargetsResponse:
        results = await asyncio.gather(
            self.upstream.healer("state", "/api/state"),
            self.upstream.healer("knobs", "/api/knobs"),
            return_exceptions=True,
        )
        state_result, knobs_result = results
        if isinstance(state_result, Exception) or not state_result.ok:
            return TargetsResponse(
                template_id=template_id,
                target_kind=TARGET_KIND_GUEST,
                error="healer_state_unavailable",
            )
        if isinstance(knobs_result, Exception) or not knobs_result.ok:
            return TargetsResponse(
                template_id=template_id,
                target_kind=TARGET_KIND_GUEST,
                error="healer_knobs_unavailable",
            )
        state = state_result.value if isinstance(state_result.value, dict) else {}
        knobs = knobs_result.value if isinstance(knobs_result.value, dict) else {}
        auto_ids = _int_set(knobs.get("AUTO_IDS"))
        protect = _int_set(knobs.get("PROTECT"))
        if auto_ids is None or protect is None:
            return TargetsResponse(
                template_id=template_id,
                target_kind=TARGET_KIND_GUEST,
                error="healer_knobs_unavailable",
            )
        rows: list[dict[str, Any]] = []
        for key, row in state.items():
            if not isinstance(row, dict):
                continue
            try:
                vmid = int(key)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "vmid": vmid,
                    "name": _short(row.get("nama"), 120),
                    "node": _short(row.get("node"), 80),
                    "guest_type": _guest_type(row.get("jenis") or row.get("jenis_guest")),
                    "status": _short(row.get("status"), 40) or "unknown",
                    "auto": vmid in auto_ids,
                    "protected": vmid in protect,
                }
            )
        rows.sort(key=lambda item: int(item["vmid"]))
        return TargetsResponse(
            template_id=template_id, target_kind=TARGET_KIND_GUEST, targets=rows
        )

    async def _k8s_targets(self, template_id: str) -> TargetsResponse:
        result = await self.upstream.healer("k8s", "/api/k8s")
        if isinstance(result, Exception) or not result.ok:
            return TargetsResponse(
                template_id=template_id,
                target_kind=TARGET_KIND_K8S,
                error="k8s_unavailable",
            )
        value = result.value if isinstance(result.value, dict) else {}
        if not value.get("enabled"):
            return TargetsResponse(
                template_id=template_id,
                target_kind=TARGET_KIND_K8S,
                error="k8s_disabled",
            )
        rows: list[dict[str, Any]] = []
        deployments = value.get("deployments")
        for item in deployments if isinstance(deployments, list) else []:
            if not isinstance(item, dict):
                continue
            images = item.get("images")
            previous_images = item.get("previous_images")
            rows.append(
                {
                    "namespace": _short(item.get("namespace"), 63),
                    "deployment": _short(item.get("deployment"), 253),
                    "revision": int(item.get("revision") or 0),
                    "previous_revision": int(item.get("previous_revision") or 0),
                    "status": _short(item.get("status"), 40) or "unknown",
                    "replicas": int(item.get("replicas") or 0),
                    "available": int(item.get("available") or 0),
                    "images": [
                        _short(image, 300)
                        for image in (images if isinstance(images, list) else [])[:20]
                        if isinstance(image, str)
                    ],
                    "previous_images": [
                        _short(image, 300)
                        for image in (
                            previous_images if isinstance(previous_images, list) else []
                        )[:20]
                        if isinstance(image, str)
                    ],
                    "ok": bool(item.get("ok")),
                    "allowed": bool(item.get("allowed")),
                    "protected": bool(item.get("protected")),
                }
            )
        return TargetsResponse(
            template_id=template_id, target_kind=TARGET_KIND_K8S, targets=rows
        )

    # ----------------------------------------------------------------- preview
    async def preview(self, actor: Actor, request: PreviewRequest) -> PreviewResponse:
        template = get_template(request.template_id)
        if template is None:
            raise GoalError(404, "template_not_found")
        goal = _short(request.goal, self.settings.goals_max_goal_chars)
        if len(request.goal or "") > self.settings.goals_max_goal_chars:
            raise GoalError(422, "goal_too_long")
        if str(template.get("target_kind") or "guest") == TARGET_KIND_K8S:
            return await self._preview_k8s(actor, request, template, goal)
        return await self._preview_guest(actor, request, template, goal)

    @staticmethod
    def _validated(
        target_kind: str, request: PreviewRequest
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate the per-template target/variables shape, fail closed."""
        try:
            if target_kind == TARGET_KIND_K8S:
                target = K8sTargetRef(**request.target).model_dump()
                variables = K8sRollbackVariables(**request.variables).model_dump()
            else:
                target = TargetRef(**request.target).model_dump()
                variables = RecoverVariables(**request.variables).model_dump()
        except ValidationError:
            raise GoalError(422, "invalid_request") from None
        return target, variables

    async def _preview_guest(
        self,
        actor: Actor,
        request: PreviewRequest,
        template: dict[str, Any],
        goal: str,
    ) -> PreviewResponse:
        target_ref, variables = self._validated(TARGET_KIND_GUEST, request)
        vmid = int(target_ref["vmid"])
        snapshot = await self._snapshot(vmid)
        target = snapshot.target or {}
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

        return self._record_preview(
            actor,
            request,
            template,
            goal,
            plan,
            snapshot.evidence,
            warnings,
            missing,
            blocked_reason,
            target_kind=TARGET_KIND_GUEST,
            target_vmid=vmid,
            target_node=str(target.get("node") or ""),
            target_type=str(target.get("guest_type") or ""),
            audit_detail={"vmid": vmid},
        )

    async def _preview_k8s(
        self,
        actor: Actor,
        request: PreviewRequest,
        template: dict[str, Any],
        goal: str,
    ) -> PreviewResponse:
        target_ref, variables = self._validated(TARGET_KIND_K8S, request)
        namespace = str(target_ref["namespace"])
        deployment = str(target_ref["deployment"])
        snapshot = await self._k8s_snapshot(namespace, deployment)
        evidence = self._k8s_evidence(snapshot)
        blocked_reason = ""
        warnings: list[str] = []
        missing: list[str] = []

        if snapshot.get("protected"):
            plan = planner.build_k8s_plan(
                snapshot,
                variables,
                goal,
                evidence,
                action="escalate",
                risk="high",
                rationale="Target ada di daftar K8S_PROTECT; tidak ada aksi otomatis.",
                warnings=[],
            )
            blocked_reason = "protected_target"
        else:
            plan = planner.decide_k8s(snapshot, variables, goal, evidence)
            warnings = list(plan.get("warnings") or [])
            if plan["steps"][0]["action"] not in planner.K8S_EXECUTABLE:
                blocked_reason = "no_safe_action"

        return self._record_preview(
            actor,
            request,
            template,
            goal,
            plan,
            evidence,
            warnings,
            missing,
            blocked_reason,
            target_kind=TARGET_KIND_K8S,
            target_vmid=0,
            target_node=namespace,
            target_type="deployment",
            audit_detail={"namespace": namespace, "deployment": deployment},
        )

    def _record_preview(
        self,
        actor: Actor,
        request: PreviewRequest,
        template: dict[str, Any],
        goal: str,
        plan: dict[str, Any],
        evidence: dict[str, Any],
        warnings: list[str],
        missing: list[str],
        blocked_reason: str,
        *,
        target_kind: str,
        target_vmid: int,
        target_node: str,
        target_type: str,
        audit_detail: dict[str, Any],
    ) -> PreviewResponse:
        plan_hash = planner.sha256_json(plan)
        now = _now()
        expires = now + timedelta(seconds=max(30, self.settings.goals_preview_ttl))
        preview_id = str(uuid.uuid4())
        status = "blocked" if blocked_reason else "ready"
        self.store.create_preview(
            {
                "id": preview_id,
                "created_by_sub": actor.sub,
                "created_by_name": actor.name,
                "created_at": _iso(now),
                "expires_at": _iso(expires),
                "template_id": request.template_id,
                "template_version": str(template["version"]),
                "target_kind": target_kind,
                "target_vmid": target_vmid,
                "target_node": target_node,
                "target_type": target_type,
                "goal": goal,
                "variables_json": json.dumps(plan.get("variables") or {}, sort_keys=True),
                "plan_json": json.dumps(plan, sort_keys=True),
                "plan_hash": plan_hash,
                "evidence_json": json.dumps(evidence, sort_keys=True),
                "evidence_hash": plan.get("evidence_hash", ""),
                "warnings_json": json.dumps(warnings, sort_keys=True),
                "status": status,
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
                **audit_detail,
                "action": plan["steps"][0]["action"],
                "plan_hash": plan_hash,
                "status": status,
                "blocked_reason": blocked_reason,
            },
            client_ip=actor.client_ip,
            user_agent=actor.user_agent,
        )
        return PreviewResponse(
            preview_id=preview_id,
            status=status,  # type: ignore[arg-type]
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

        target_kind = str(preview.get("target_kind") or TARGET_KIND_GUEST)
        if target_kind == TARGET_KIND_K8S:
            target_info = await self._create_target_k8s(plan)
        else:
            target_kind = TARGET_KIND_GUEST
            target_info = await self._create_target_guest(preview, plan)

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
            "target_vmid": int(target_info["target_vmid"]),
            "target_node": str(target_info["target_node"]),
            "target_type": str(target_info["target_type"]),
            "target_json": str(target_info["target_json"]),
            "goal": str(preview["goal"]),
            "variables_json": str(preview["variables_json"]),
            "plan_json": json.dumps(plan, sort_keys=True),
            "plan_id": goal_id,
            "plan_hash": request.plan_hash,
            "target_kind": target_kind,
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
                **target_info["audit"],
                "action": plan["steps"][0]["action"],
                "plan_hash": request.plan_hash,
                "replay": replay,
            },
            client_ip=actor.client_ip,
            user_agent=actor.user_agent,
        )
        return self._created_view(row, None if replay else code, replay=replay)

    async def _create_target_guest(
        self, preview: dict[str, Any], plan: dict[str, Any]
    ) -> dict[str, Any]:
        vmid = int(preview["target_vmid"])
        snapshot = await self._snapshot(vmid)
        self._recheck_target(preview, plan, snapshot)
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
        return {
            "target_vmid": vmid,
            "target_node": str(preview["target_node"]),
            "target_type": str(preview["target_type"]),
            "target_json": target_json,
            "audit": {"vmid": vmid},
        }

    async def _create_target_k8s(self, plan: dict[str, Any]) -> dict[str, Any]:
        target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
        namespace = _short(target.get("namespace"), 63)
        deployment = _short(target.get("deployment"), 253)
        if not namespace or not deployment:
            raise GoalError(409, "preview_invalid")
        snapshot = await self._k8s_snapshot(namespace, deployment)
        self._recheck_k8s_target(plan, snapshot)
        target_json = json.dumps(
            {
                "namespace": namespace,
                "deployment": deployment,
                "revision": int(target.get("revision") or 0),
                "previous_revision": int(target.get("previous_revision") or 0),
                "status": str(snapshot.get("status") or ""),
                "replicas": int(snapshot.get("replicas") or 0),
                "available": int(snapshot.get("available") or 0),
                "images": list(target.get("images") or []),
                "previous_images": list(target.get("previous_images") or []),
            },
            sort_keys=True,
        )
        return {
            "target_vmid": 0,
            "target_node": namespace,
            "target_type": "deployment",
            "target_json": target_json,
            "audit": {"namespace": namespace, "deployment": deployment},
        }

    def _recheck_k8s_target(
        self, plan: dict[str, Any], snapshot: dict[str, Any]
    ) -> None:
        if snapshot.get("protected"):
            raise GoalError(409, "protected_target")
        if not snapshot.get("allowed"):
            raise GoalError(409, "target_not_allowed")
        target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
        for field in ("namespace", "deployment", "revision", "previous_revision", "status"):
            expected = target.get(field)
            current = snapshot.get(field)
            if field in ("revision", "previous_revision"):
                try:
                    expected = int(expected)
                    current = int(current)
                except (TypeError, ValueError):
                    raise GoalError(409, "state_changed") from None
            if str(expected or "") != str(current or ""):
                raise GoalError(409, "state_changed")
        if int(snapshot.get("replicas") or 0) <= 0:
            raise GoalError(409, "state_changed")

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
                confirmation = self._confirmation(goal, action)
                if (
                    not confirmation
                    or request.confirmation.strip().upper() != confirmation.upper()
                ):
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
                **self._target_audit(goal),
                "action": action,
                "plan_hash": goal["plan_hash"],
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
    async def execute(
        self, actor: Actor, goal_id: str, plan_hash: str, confirm: bool
    ) -> GoalView:
        if not self.settings.goals_execute_enabled:
            raise GoalError(409, "execution_disabled")
        if not is_approver(self.settings, self._approver_user(actor)):
            raise GoalError(403, "approver role required")
        if not confirm:
            raise GoalError(400, "confirmation_required")
        goal = self._load(goal_id)
        if goal["status"] != "approved":
            raise GoalError(409, "goal_not_approved")
        if goal.get("plan_hash") != plan_hash:
            raise GoalError(409, "plan_hash_mismatch")
        if _expired(str(goal.get("execute_before") or "")):
            raise GoalError(410, "execution_expired")
        if self.control is None:
            raise GoalError(503, "control_not_configured")
        plan = _json(str(goal.get("plan_json") or ""), {})
        if not isinstance(plan, dict) or not plan.get("steps"):
            raise GoalError(409, "plan_invalid")

        now = _now()
        generated_run_id = str(uuid.uuid4())
        lease_owner = f"{self._worker_id}:{generated_run_id}"
        claimed = self.store.claim_execution(
            goal_id,
            plan_hash=plan_hash,
            now=_iso(now),
            actor_sub=actor.sub,
            actor_name=actor.name,
            run_id=generated_run_id,
            lease_owner=lease_owner,
            lease_expires_at=self._lease_iso(),
        )
        if claimed is None:
            fresh = self.store.get_goal(goal_id)
            if fresh and str(fresh.get("status")) == "approved" and _expired(
                str(fresh.get("execute_before") or "")
            ):
                raise GoalError(410, "execution_expired")
            raise GoalError(409, "execution_state_changed")

        run = claimed.get("run") or {}
        goal_row = claimed.get("goal") or {}
        run_id = str(run.get("id") or generated_run_id)
        plan_id = str(goal_row.get("plan_id") or goal_id)
        self._audit(
            goal_id,
            actor,
            "execute.requested",
            {
                "plan_id": plan_id,
                "run_id": run_id,
                **self._target_audit(goal),
                "attempt": int(run.get("attempts") or 1),
            },
            now,
        )
        task = asyncio.create_task(
            self._dispatch(
                goal_id, run_id, lease_owner, actor, plan, plan_hash, plan_id
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self._view(goal_row or goal, actor, True)

    async def _dispatch(
        self,
        goal_id: str,
        run_id: str,
        lease_owner: str,
        actor: Actor,
        plan: dict[str, Any],
        plan_hash: str,
        plan_id: str,
    ) -> None:
        async with self._dispatch_sem:
            current = self.store.get_goal(goal_id)
            if (
                current is None
                or str(current.get("status")) != "dispatching"
                or str(current.get("run_id") or "") != run_id
            ):
                return
            assert self.control is not None
            self.store.update_run(goal_id, {"request_sent_at": _iso(_now())})
            payload = {
                "plan_id": plan_id,
                "plan_hash": plan_hash,
                "plan": plan,
                "approved_by": str(current.get("approved_by_name") or ""),
                "approved_at": str(current.get("approved_at") or ""),
                "expires_at": str(current.get("execute_before") or ""),
            }
            try:
                status, body = await self.control.execute(payload)
            except ControlError as exc:
                self._finalize(
                    goal_id,
                    run_id,
                    "unknown",
                    "execute.unknown",
                    actor,
                    error="hasil eksekusi tidak diketahui",
                    error_code=exc.code,
                )
                return

            if status == 202:
                now = _now()
                updated = self.store.update_goal(
                    goal_id,
                    expected_status="dispatching",
                    fields={"status": "executing", "updated_at": _iso(now)},
                )
                if updated is None:
                    return
                self.store.update_run(
                    goal_id,
                    {
                        "status": "executing",
                        "accepted_at": _iso(now),
                        "started_at": _iso(now),
                        "heartbeat_at": _iso(now),
                        "last_polled_at": _iso(now),
                        "lease_expires_at": self._lease_iso(),
                    },
                )
                self._audit(
                    goal_id,
                    actor,
                    "execute.accepted",
                    {"plan_id": plan_id, "run_id": run_id},
                    now,
                )
                await self._poll(goal_id, run_id, lease_owner, actor, plan_id)
                return

            if status == 200:
                run = body.get("run")
                if isinstance(run, dict):
                    self._finish_from_run(
                        goal_id, run_id, actor, run, event="execute.replayed"
                    )
                else:
                    self._finalize(
                        goal_id,
                        run_id,
                        "unknown",
                        "execute.unknown",
                        actor,
                        error="balasan control tidak dikenal",
                        error_code="invalid_reply",
                    )
                return

            outcome, code = _classify_rejection(status, body)
            if outcome == "retryable":
                self._retryable(goal_id, run_id, actor, code)
            elif outcome == "failed":
                final = "expired" if code in CONTROL_EXPIRED else "failed"
                self._finalize(
                    goal_id,
                    run_id,
                    final,
                    "execute.failed",
                    actor,
                    error="execution rejected",
                    error_code=code,
                )
            else:
                self._finalize(
                    goal_id,
                    run_id,
                    "unknown",
                    "execute.unknown",
                    actor,
                    error="hasil eksekusi tidak diketahui",
                    error_code=code,
                )

    async def _poll(
        self, goal_id: str, run_id: str, lease_owner: str, actor: Actor, plan_id: str
    ) -> None:
        if self.control is None:
            return
        interval = max(0.5, float(self.settings.goals_control_poll_interval))
        deadline = time.monotonic() + max(5.0, float(self.settings.goals_control_timeout))
        while True:
            if time.monotonic() >= deadline:
                self._finalize(
                    goal_id,
                    run_id,
                    "unknown",
                    "execute.unknown",
                    actor,
                    error="waktu tunggu habis; status tidak diketahui",
                    error_code="control_timeout",
                )
                return
            await asyncio.sleep(interval)
            now = _now()
            if not self.store.renew_run_lease(
                goal_id,
                owner=lease_owner,
                now=_iso(now),
                lease_expires_at=self._lease_iso(),
            ):
                return
            try:
                status, body = await self.control.status(plan_id)
            except ControlError:
                continue
            if status == 200:
                run = body.get("run")
                if not isinstance(run, dict):
                    continue
                if str(run.get("status") or "") in CONTROL_TERMINAL:
                    self._finish_from_run(
                        goal_id, run_id, actor, run, event="execute.finished"
                    )
                    return
                continue
            if status in (401, 403):
                self._finalize(
                    goal_id,
                    run_id,
                    "unknown",
                    "execute.unknown",
                    actor,
                    error="status journal tidak bisa dibaca",
                    error_code="control_auth_failed",
                )
                return
            # 404/5xx: the journal may not hold this plan yet; keep polling.

    async def reconcile(self, actor: Actor, goal_id: str) -> GoalView:
        if not self.settings.goals_execute_enabled:
            raise GoalError(409, "execution_disabled")
        if not is_approver(self.settings, self._approver_user(actor)):
            raise GoalError(403, "approver role required")
        if self.control is None:
            raise GoalError(503, "control_not_configured")
        goal = self._load(goal_id)
        status = str(goal.get("status") or "")
        if status not in ACTIVE_EXECUTION | {"unknown", "succeeded", "failed"}:
            raise GoalError(409, "reconcile_not_needed")
        plan_id = str(goal.get("plan_id") or "")
        if not plan_id:
            raise GoalError(409, "reconcile_unavailable")
        run_id = str(goal.get("run_id") or "")
        now = _now()
        try:
            http_status, body = await self.control.status(plan_id)
        except ControlError as exc:
            self._audit(
                goal_id, actor, "reconcile.failed", {"error_code": exc.code}, now
            )
            raise GoalError(503, exc.code) from None
        if http_status == 404:
            if status == "unknown":
                self._finalize(
                    goal_id,
                    run_id,
                    "failed",
                    "reconcile.finished",
                    actor,
                    error="healer tidak memiliki catatan plan ini",
                    error_code="not_dispatched",
                    allowed=ACTIVE_EXECUTION | {"unknown"},
                )
                return self._view_after(goal_id, actor)
            self._audit(goal_id, actor, "reconcile.pending", {"plan_id": plan_id}, now)
            raise GoalError(409, "run_not_found")
        if http_status != 200:
            self._audit(
                goal_id,
                actor,
                "reconcile.failed",
                {"http_status": http_status},
                now,
            )
            raise GoalError(502, "control_rejected")
        run = body.get("run")
        if not isinstance(run, dict):
            raise GoalError(502, "invalid_control_reply")
        healer_status = str(run.get("status") or "")
        if healer_status in CONTROL_TERMINAL:
            self._finish_from_run(
                goal_id,
                run_id,
                actor,
                run,
                event="reconcile.finished",
                allowed=ACTIVE_EXECUTION | {"unknown"},
            )
        else:
            self.store.update_run(
                goal_id,
                {"last_polled_at": _iso(now), "heartbeat_at": _iso(now)},
            )
            self._audit(
                goal_id,
                actor,
                "reconcile.pending",
                {"plan_id": plan_id, "healer_status": healer_status},
                now,
            )
        return self._view_after(goal_id, actor)

    # ------------------------------------------------------- dispatch helpers
    def _lease_iso(self) -> str:
        seconds = max(180.0, float(self.settings.goals_control_timeout) + 120.0)
        return _iso(_now() + timedelta(seconds=seconds))

    def _view_after(self, goal_id: str, actor: Actor) -> GoalView:
        refreshed = self.store.get_goal(goal_id)
        if refreshed is None:
            raise GoalError(404, "goal_not_found")
        return self._view(refreshed, actor, True)

    def _retryable(self, goal_id: str, run_id: str, actor: Actor, code: str) -> None:
        now = _now()
        goal = self.store.get_goal(goal_id)
        if goal is None or str(goal.get("status")) not in ACTIVE_EXECUTION:
            return
        updated = self.store.update_goal(
            goal_id,
            expected_status=str(goal.get("status")),
            fields={"status": "approved", "error": code, "updated_at": _iso(now)},
        )
        if updated is None:
            return
        self.store.update_run(
            goal_id,
            {
                "status": "rejected",
                "finished_at": _iso(now),
                "error": "ditolak healer; aman dicoba lagi sebelum execute_before",
                "error_code": code,
                "lease_owner": "",
                "lease_expires_at": "",
            },
        )
        self._audit(
            goal_id,
            actor,
            "execute.retryable",
            {"error_code": code, "run_id": run_id},
            now,
        )

    def _finish_from_run(
        self,
        goal_id: str,
        run_id: str,
        actor: Actor,
        run: dict[str, Any],
        *,
        event: str,
        allowed: set[str] | None = None,
    ) -> None:
        healer_status = str(run.get("status") or "")
        final = CONTROL_TERMINAL.get(healer_status)
        if final is None:
            self._finalize(
                goal_id,
                run_id,
                "unknown",
                event,
                actor,
                error="status journal tidak dikenal",
                error_code="invalid_run_status",
                allowed=allowed,
            )
            return
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        self._finalize(
            goal_id,
            run_id,
            final,
            event,
            actor,
            result=result,
            error=str(run.get("error") or "")[:300],
            error_code=str(run.get("error_code") or "")[:80],
            dry_run=bool(run.get("dry_run")),
            run_status=healer_status,
            allowed=allowed,
        )

    def _finalize(
        self,
        goal_id: str,
        run_id: str,
        status: str,
        event: str,
        actor: Actor,
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
        error_code: str = "",
        dry_run: bool = False,
        run_status: str | None = None,
        allowed: set[str] | None = None,
    ) -> None:
        now = _now()
        goal = self.store.get_goal(goal_id)
        permitted = ACTIVE_EXECUTION if allowed is None else allowed
        if goal is None or str(goal.get("status")) not in permitted:
            return
        result_json = (
            json.dumps(result, sort_keys=True) if isinstance(result, dict) and result else ""
        )
        updated = self.store.update_goal(
            goal_id,
            expected_status=str(goal.get("status")),
            fields={
                "status": status,
                "result_json": result_json,
                "error": error[:300],
                "updated_at": _iso(now),
            },
        )
        if updated is None:
            return
        self.store.update_run(
            goal_id,
            {
                "status": run_status or status,
                "finished_at": _iso(now),
                "result_json": result_json,
                "error": error[:300],
                "error_code": error_code[:80],
                "dry_run": 1 if dry_run else 0,
                "lease_owner": "",
                "lease_expires_at": "",
            },
        )
        self._audit(
            goal_id,
            actor,
            event,
            {
                "status": status,
                "error_code": error_code,
                "run_id": run_id,
                "dry_run": dry_run,
            },
            now,
        )

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            # The task already recorded its outcome; a cancelled dispatch must
            # not make app shutdown fail.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self.control is not None:
            await self.control.close()

    def sweep(self) -> list[dict[str, Any]]:
        """Expire windows / stale leases, then audit each change."""
        now = _now()
        stale = now - timedelta(seconds=max(60, self.settings.goals_control_timeout + 30))
        changes = self.store.sweep(now=_iso(now), stale_before=_iso(stale))
        for change in changes:
            goal_id = str(change.get("goal_id") or "")
            goal = self.store.get_goal(goal_id) or {}
            self.store.audit(
                ts=_iso(now),
                goal_id=goal_id,
                plan_id=str(goal.get("plan_id") or ""),
                actor_sub="system:sweeper",
                actor_name="sweeper",
                actor_method="system",
                event=f"goal.{change.get('status')}",
                detail={
                    "previous": change.get("previous"),
                    "reason": change.get("reason"),
                },
            )
        return changes

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
        if str(goal.get("target_kind") or TARGET_KIND_GUEST) == TARGET_KIND_K8S:
            return action, action in planner.K8S_EXECUTABLE
        target = _json(str(goal.get("target_json") or ""), {})
        high = action == "reset" or not bool(target.get("auto"))
        return action, high

    def _confirmation(self, goal: dict[str, Any], action: str) -> str:
        """Typed confirmation the approver must reproduce for a high-risk goal."""
        if str(goal.get("target_kind") or TARGET_KIND_GUEST) == TARGET_KIND_K8S:
            target = _json(str(goal.get("target_json") or ""), {})
            namespace = _short(target.get("namespace"), 63)
            deployment = _short(target.get("deployment"), 253)
            if not namespace or not deployment:
                return ""
            return f"SETUJU {action} {namespace}/{deployment}"
        return f"SETUJU {action} {goal.get('target_vmid')}"

    def _target_audit(self, goal: dict[str, Any]) -> dict[str, Any]:
        if str(goal.get("target_kind") or TARGET_KIND_GUEST) == TARGET_KIND_K8S:
            target = _json(str(goal.get("target_json") or ""), {})
            return {
                "namespace": _short(target.get("namespace"), 63),
                "deployment": _short(target.get("deployment"), 253),
            }
        return {"vmid": goal.get("target_vmid")}

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
        target_kind = str(goal.get("target_kind") or TARGET_KIND_GUEST)
        if target_kind == TARGET_KIND_K8S:
            high_risk = action in planner.K8S_EXECUTABLE
        else:
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
            and self.control is not None
            and not _expired(str(goal.get("execute_before") or ""))
        )
        can_reconcile = bool(
            status in ACTIVE_EXECUTION | {"unknown"}
            and self.settings.goals_execute_enabled
            and is_approver_actor
            and self.control is not None
            and bool(goal.get("plan_id"))
        )
        if self.settings.auth_mode == "password":
            approval_mode = "password_single_person"
        elif self.settings.goals_allow_self_approval:
            approval_mode = "self_allowed"
        else:
            approval_mode = "two_person"
        confirmation_hint = self._confirmation(goal, action) if high_risk else ""
        if target_kind == TARGET_KIND_K8S:
            target_view: dict[str, Any] = (
                dict(plan_target) if isinstance(plan_target, dict) else dict(target)
            )
        else:
            target_view = (
                {**plan_target, "auto": bool(target.get("auto"))}
                if isinstance(plan_target, dict)
                else target
            )
        return GoalView(
            id=str(goal["id"]),
            status=status,  # type: ignore[arg-type]
            template_id=str(goal.get("template_id") or ""),
            template_version=str(goal.get("template_version") or ""),
            target=target_view,
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
            execute_by=str(goal.get("execute_by_name") or ""),
            execute_requested_at=str(goal.get("execute_requested_at") or ""),
            execute_count=int(goal.get("execute_count") or 0),
            target_kind=str(goal.get("target_kind") or "proxmox_guest"),
            run=self.store.get_run(str(goal["id"])),
            result=_json(str(goal.get("result_json") or ""), None),
            error=str(goal.get("error") or ""),
            created_at=str(goal.get("created_at") or ""),
            updated_at=str(goal.get("updated_at") or ""),
            can_approve=can_approve,
            can_execute=can_execute,
            can_reconcile=can_reconcile,
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
