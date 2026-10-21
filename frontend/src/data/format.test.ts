import { describe, expect, it } from "vitest";
import { fmtAge, hourlyBuckets, resultTone, severityClass, severityTone, timeOf } from "./format";
import type { Decision } from "./types";

function decision(ts: Date, aksi = "reset", hasil = "pulih"): Decision {
  return {
    ts: ts.toISOString(),
    time: "",
    target: "guest 201",
    aksi,
    sumber: "aturan",
    hasil,
    alasan: "",
    ket: "",
    vmid: 201,
    nama: null,
    node: "hq2",
    jenis: "mati",
    tingkat: "minor",
    izin: "minor",
    jenis_guest: "ct",
    status: "stopped",
    agent: true,
    oleh: "",
    state: "",
    dry: false
  };
}

describe("format helpers", () => {
  it("formats ages", () => {
    expect(fmtAge(null)).toBe("—");
    expect(fmtAge(42)).toBe("42s");
    expect(fmtAge(600)).toBe("10m");
    expect(fmtAge(3 * 3600)).toBe("3.0h");
    expect(fmtAge(2 * 86400)).toBe("2.0d");
  });

  it("formats local HH:MM", () => {
    const date = new Date();
    date.setHours(9, 5, 0, 0);
    expect(timeOf(date.toISOString())).toBe("09:05");
    expect(timeOf("not-a-date")).toBe("—");
    expect(timeOf(null)).toBe("—");
  });

  it("maps severity and result tones", () => {
    expect(severityTone("critical")).toBe("coral");
    expect(severityTone("none")).toBe("neutral");
    expect(severityClass("warning")).toBe("warning");
    expect(severityClass("none")).toBe("resolved");
    expect(resultTone("pulih")).toBe("mint");
    expect(resultTone("gagal")).toBe("coral");
    expect(resultTone("eskalasi")).toBe("amber");
    expect(resultTone("lain")).toBe("neutral");
  });

  it("buckets decisions into the last 24 hours", () => {
    const now = new Date();
    const buckets = hourlyBuckets([decision(now), decision(now, "escalate", "eskalasi")], 24);
    expect(buckets).toHaveLength(24);
    expect(buckets[23].total).toBe(2);
    expect(buckets[23].escalated).toBe(1);
    expect(buckets.reduce((sum, bucket) => sum + bucket.total, 0)).toBe(2);

    const old = new Date(now.getTime() - 48 * 3_600_000);
    const outside = hourlyBuckets([decision(old)], 24);
    expect(outside.reduce((sum, bucket) => sum + bucket.total, 0)).toBe(0);
  });
});
