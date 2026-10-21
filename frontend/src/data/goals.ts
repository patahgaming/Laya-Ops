import { fmtAge, parseTs } from "./format";
import type { GoalRisk, GoalStatus } from "./types";

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
  no_safe_action: "Planner tidak menemukan aksi aman; eskalasi ke manusia.",
  healer_state_unavailable: "State healer tidak tersedia; preview tidak bisa dibuat.",
  healer_knobs_unavailable: "Knob healer tidak tersedia; PROTECT tidak bisa diverifikasi."
};

export function goalStatusTone(status: GoalStatus): GoalTone {
  return STATUS_TONE[status] ?? "neutral";
}

export function goalStatusLabel(status: GoalStatus): string {
  return STATUS_LABEL[status] ?? status;
}

export function goalRiskTone(risk: GoalRisk): GoalTone {
  if (risk === "high") return "coral";
  if (risk === "medium") return "amber";
  return "mint";
}

export function goalBlockedLabel(reason: string): string {
  return BLOCKED_LABEL[reason] ?? (reason || "Plan tidak bisa diajukan.");
}

/** Remaining lifetime of a preview / approval window, in compact form. */
export function remainingLabel(expiresAt: string, nowMs: number): string {
  const date = parseTs(expiresAt);
  if (!date) return "—";
  const seconds = Math.round((date.getTime() - nowMs) / 1000);
  if (seconds <= 0) return "expired";
  return `${fmtAge(seconds)} left`;
}
