import { describe, expect, it } from "vitest";
import {
  goalBlockedLabel,
  goalIsActive,
  goalRiskTone,
  goalRunLabel,
  goalStatusLabel,
  goalStatusTone,
  goalTargetOptionKey,
  isGuestTargetOption,
  isK8sPlanTarget,
  isK8sTargetOption,
  remainingLabel
} from "./goals";
import type {
  GoalGuestTargetOption,
  GoalK8sTargetOption,
  GoalPlanTarget,
  GoalRun
} from "./types";

const K8S_TARGET: GoalK8sTargetOption = {
  namespace: "aspirasi",
  deployment: "web",
  revision: 12,
  previous_revision: 11,
  status: "degraded",
  replicas: 3,
  available: 0,
  images: ["ghcr.io/laya/web:v2"],
  previous_images: ["ghcr.io/laya/web:v1"],
  ok: true,
  allowed: true,
  protected: false
};

const GUEST_TARGET: GoalGuestTargetOption = {
  vmid: 301,
  name: "worker",
  node: "hq3",
  guest_type: "vm",
  status: "stopped",
  auto: false,
  protected: false
};

function run(overrides: Partial<GoalRun> = {}): GoalRun {
  return {
    id: "run-1",
    goal_id: "goal-1",
    plan_id: "goal-1",
    status: "done",
    claimed_at: "",
    request_sent_at: "",
    accepted_at: "",
    started_at: "",
    finished_at: "",
    heartbeat_at: "",
    last_polled_at: "",
    lease_owner: "",
    lease_expires_at: "",
    result: null,
    error: "",
    error_code: "",
    dry_run: false,
    attempts: 1,
    ...overrides
  };
}

describe("goal presentation helpers", () => {
  it("maps lifecycle status to label and tone", () => {
    expect(goalStatusLabel("pending_approval")).toBe("pending approval");
    expect(goalStatusTone("pending_approval")).toBe("amber");
    expect(goalStatusTone("succeeded")).toBe("mint");
    expect(goalStatusTone("failed")).toBe("coral");
    expect(goalStatusTone("rejected")).toBe("neutral");
  });

  it("escalates risk tone", () => {
    expect(goalRiskTone("low")).toBe("mint");
    expect(goalRiskTone("medium")).toBe("amber");
    expect(goalRiskTone("high")).toBe("coral");
  });

  it("uses a human blocked reason and falls back safely", () => {
    expect(goalBlockedLabel("protected_target")).toContain("PROTECT");
    expect(goalBlockedLabel("unknown_reason")).toBe("unknown_reason");
    expect(goalBlockedLabel("")).toContain("tidak bisa diajukan");
  });

  it("formats remaining preview and approval windows", () => {
    const now = Date.parse("2026-10-22T10:00:00Z");
    expect(remainingLabel("2026-10-22T10:05:00Z", now)).toBe("5m left");
    expect(remainingLabel("2026-10-22T09:59:59Z", now)).toBe("expired");
    expect(remainingLabel("", now)).toBe("—");
    expect(remainingLabel("not-a-date", now)).toBe("—");
  });

  it("only treats dispatching and executing as live execution", () => {
    expect(goalIsActive("dispatching")).toBe(true);
    expect(goalIsActive("executing")).toBe(true);
    expect(goalIsActive("approved")).toBe(false);
    expect(goalIsActive("unknown")).toBe(false);
    expect(goalIsActive("succeeded")).toBe(false);
  });

  it("labels the journal run and flags dry-run", () => {
    expect(goalRunLabel(null)).toBe("—");
    expect(goalRunLabel(run())).toBe("done");
    expect(goalRunLabel(run({ status: "rejected" }))).toBe("rejected");
    expect(goalRunLabel(run({ dry_run: true }))).toBe("done · dry-run");
  });

  it("distinguishes guest and deployment plan targets", () => {
    const guestPlanTarget: GoalPlanTarget = {
      vmid: 301,
      name: "worker",
      node: "hq3",
      guest_type: "vm",
      status: "stopped"
    };
    const deploymentPlanTarget: GoalPlanTarget = { ...K8S_TARGET };
    expect(isK8sPlanTarget(guestPlanTarget)).toBe(false);
    expect(isK8sPlanTarget(deploymentPlanTarget)).toBe(true);
    expect(isK8sPlanTarget(undefined)).toBe(false);
  });

  it("distinguishes guest and deployment target rows", () => {
    expect(isK8sTargetOption(K8S_TARGET)).toBe(true);
    expect(isGuestTargetOption(K8S_TARGET)).toBe(false);
    expect(isGuestTargetOption(GUEST_TARGET)).toBe(true);
    expect(isK8sTargetOption(GUEST_TARGET)).toBe(false);
  });

  it("keys the target picker per kind", () => {
    expect(goalTargetOptionKey(GUEST_TARGET)).toBe("301");
    expect(goalTargetOptionKey(K8S_TARGET)).toBe("aspirasi/web");
  });

  it("explains k8s blocked reasons", () => {
    expect(goalBlockedLabel("k8s_disabled")).toContain("K8S_ALLOW");
    expect(goalBlockedLabel("target_not_allowed")).toContain("allow-list");
  });
});
