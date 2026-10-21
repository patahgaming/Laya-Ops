import { describe, expect, it } from "vitest";
import {
  goalBlockedLabel,
  goalRiskTone,
  goalStatusLabel,
  goalStatusTone,
  remainingLabel
} from "./goals";

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
});
