import type { Decision, HourBucket, Severity } from "./types";

export function parseTs(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function timeOf(value?: string | null): string {
  const date = parseTs(value);
  if (!date) return "—";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function clockOf(date: Date): string {
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

export function ageSeconds(value?: string | null): number | null {
  const date = parseTs(value);
  return date ? Math.max(0, (Date.now() - date.getTime()) / 1000) : null;
}

export function fmtAge(seconds?: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function severityTone(severity: Severity): "coral" | "amber" | "blue" | "neutral" {
  switch (severity) {
    case "critical":
      return "coral";
    case "warning":
      return "amber";
    case "info":
      return "blue";
    default:
      return "neutral";
  }
}

export function severityLabel(severity: Severity): string {
  return severity === "none" ? "watchdog" : severity;
}

export function severityClass(severity: Severity): string {
  switch (severity) {
    case "critical":
      return "critical";
    case "warning":
      return "warning";
    case "info":
      return "info";
    default:
      return "resolved";
  }
}

export function resultTone(hasil: string): "mint" | "coral" | "amber" | "neutral" {
  if (hasil === "pulih") return "mint";
  if (hasil === "gagal") return "coral";
  if (hasil === "eskalasi") return "amber";
  return "neutral";
}

export function jobIcon(job: string): [string, string] {
  const value = job.toLowerCase();
  if (value.includes("healer")) return ["i-box", "tone-mint"];
  if (value.includes("alertmanager")) return ["i-bell", "tone-orange"];
  if (value.includes("prometheus")) return ["i-torch", "tone-orange"];
  if (value.includes("dns")) return ["i-wifi", "tone-violet"];
  if (value.includes("apiserver")) return ["i-terminal", "tone-blue"];
  if (value.includes("kube")) return ["i-wheel", "tone-blue"];
  if (value.includes("node")) return ["i-server", "tone-mint"];
  return ["i-layers", "tone-amber"];
}

/** Decisions per hour for the last `hours` hours, oldest first. */
export function hourlyBuckets(decisions: Decision[], hours = 24): HourBucket[] {
  const top = new Date();
  top.setMinutes(0, 0, 0);
  const buckets: HourBucket[] = Array.from({ length: hours }, (_, index) => {
    const date = new Date(top.getTime() - (hours - 1 - index) * 3_600_000);
    return {
      label: `${String(date.getHours()).padStart(2, "0")}:00`,
      total: 0,
      escalated: 0
    };
  });
  for (const decision of decisions) {
    const date = parseTs(decision.ts);
    if (!date) continue;
    const bucketStart = new Date(date);
    bucketStart.setMinutes(0, 0, 0);
    const index = hours - 1 - Math.round((top.getTime() - bucketStart.getTime()) / 3_600_000);
    if (index < 0 || index >= hours) continue;
    buckets[index].total += 1;
    if (decision.aksi === "escalate") buckets[index].escalated += 1;
  }
  return buckets;
}

export function guestLabel(guest: { name?: string | null; vmid: number }): string {
  return guest.name || `guest ${guest.vmid}`;
}

export function safeCopy(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}
