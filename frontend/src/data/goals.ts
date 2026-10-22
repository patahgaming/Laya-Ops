import { fmtAge, parseTs } from "./format";
import type {
  GoalGuestTargetOption,
  GoalK8sTargetOption,
  GoalPlanTarget,
  GoalRisk,
  GoalRun,
  GoalStatus,
  GoalTargetOption,
  K8sPlanTarget
} from "./types";

export type GoalTone = "mint" | "amber" | "coral" | "blue" | "violet" | "neutral";

const STATUS_TONE: Record<GoalStatus, GoalTone> = {
  pending_approval: "amber",
  approved: "blue",
  dispatching: "blue",
  executing: "blue",
  succeeded: "mint",
  failed: "coral",
  unknown: "violet",
  rejected: "neutral",
  cancelled: "neutral",
  expired: "neutral"
};

const STATUS_LABEL: Record<GoalStatus, string> = {
  pending_approval: "pending approval",
  approved: "approved",
  dispatching: "dispatching",
  executing: "executing",
  succeeded: "succeeded",
  failed: "failed",
  unknown: "unknown",
  rejected: "rejected",
  cancelled: "cancelled",
  expired: "expired"
};

const BLOCKED_LABEL: Record<string, string> = {
  protected_target: "Target ada di daftar PROTECT — tidak ada aksi otomatis.",
  target_metadata_missing: "Metadata guest (node/jenis) belum lengkap di state healer.",
  target_not_found: "Target tidak ada di state healer.",
  target_not_allowed: "Target tidak ada di allow-list healer.",
  no_safe_action: "Planner tidak menemukan aksi aman; eskalasi ke manusia.",
  healer_state_unavailable: "State healer tidak tersedia; preview tidak bisa dibuat.",
  healer_knobs_unavailable: "Knob healer tidak tersedia; PROTECT tidak bisa diverifikasi.",
  k8s_unavailable: "Snapshot Kubernetes tidak tersedia dari healer.",
  k8s_disabled: "Healer K8s tidak aktif atau K8S_ALLOW kosong.",
  state_changed: "State target berubah sejak preview; preview ulang.",
  invalid_request: "Target/variabel tidak sesuai template."
};

export function goalStatusTone(status: GoalStatus): GoalTone {
  return STATUS_TONE[status] ?? "neutral";
}

export function goalStatusLabel(status: GoalStatus): string {
  return STATUS_LABEL[status] ?? status;
}

const ACTIVE_EXECUTION: ReadonlySet<GoalStatus> = new Set(["dispatching", "executing"]);

/** True while the dispatcher or the healer still owns the run. */
export function goalIsActive(status: GoalStatus): boolean {
  return ACTIVE_EXECUTION.has(status);
}

const RUN_LABEL: Record<string, string> = {
  dispatching: "dispatching",
  executing: "executing",
  done: "done",
  failed: "failed",
  unknown: "unknown",
  rejected: "rejected"
};

/** Journal-facing run label; the goal status alone cannot say what the healer saw. */
export function goalRunLabel(run: GoalRun | null | undefined): string {
  if (!run) return "—";
  const label = RUN_LABEL[run.status] ?? run.status;
  return run.dry_run ? `${label} · dry-run` : label;
}

export function goalRiskTone(risk: GoalRisk): GoalTone {
  if (risk === "high") return "coral";
  if (risk === "medium") return "amber";
  return "mint";
}

export function goalBlockedLabel(reason: string): string {
  return BLOCKED_LABEL[reason] ?? (reason || "Plan tidak bisa diajukan.");
}

/** Plan targets are a union; the deployment field is the discriminator. */
export function isK8sPlanTarget(
  target: GoalPlanTarget | null | undefined
): target is K8sPlanTarget {
  return Boolean(target && typeof (target as K8sPlanTarget).deployment === "string");
}

export function isGuestTargetOption(
  option: GoalTargetOption
): option is GoalGuestTargetOption {
  return "vmid" in option;
}

export function isK8sTargetOption(
  option: GoalTargetOption
): option is GoalK8sTargetOption {
  return "deployment" in option;
}

/** Stable select value: vmid for guests, namespace/deployment for deployments. */
export function goalTargetOptionKey(option: GoalTargetOption): string {
  return isK8sTargetOption(option)
    ? `${option.namespace}/${option.deployment}`
    : String(option.vmid);
}

/** Remaining lifetime of a preview / approval window, in compact form. */
export function remainingLabel(expiresAt: string, nowMs: number): string {
  const date = parseTs(expiresAt);
  if (!date) return "—";
  const seconds = Math.round((date.getTime() - nowMs) / 1000);
  if (seconds <= 0) return "expired";
  return `${fmtAge(seconds)} left`;
}
