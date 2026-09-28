import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, Scissors, History, type LucideIcon } from "lucide-react";
import type { Status } from "./api";

export interface StatusInfo {
  label: string;
  /** CSS custom property that holds this status's color. */
  color: string;
  icon: LucideIcon;
}

export const STATUS: Record<Status, StatusInfo> = {
  valid: { label: "valid", color: "var(--valid)", icon: CheckCircle2 },
  stale: { label: "stale", color: "var(--stale)", icon: AlertTriangle },
  rebuilding: { label: "rebuilding", color: "var(--rebuilding)", icon: Loader2 },
  retracted: { label: "retracted", color: "var(--retracted)", icon: CircleSlash },
  superseded: { label: "superseded", color: "var(--muted)", icon: History },
  equivalent: { label: "cut off", color: "var(--cutoff)", icon: Scissors },
};

/** Statuses shown as counts and filters in the top bar. */
export const COUNTED: Status[] = ["valid", "stale", "rebuilding", "retracted"];

/** Statuses shown in the graph legend. */
export const LEGEND: Status[] = ["valid", "stale", "rebuilding", "equivalent", "retracted"];

/** Map a live event kind to the node status it implies, or null if it implies none. */
export function statusFromEvent(kind: string): Status | null {
  switch (kind) {
    case "stale":
    case "rebuilding":
    case "retracted":
      return kind;
    case "rebuilt":
    case "cut_off":
    case "skipped":
      return "valid";
    default:
      return null;
  }
}

/** Color class key for an event kind in the event log. */
export function eventColor(kind: string): string {
  if (kind === "cut_off" || kind === "skipped") return STATUS.equivalent.color;
  if (kind === "rebuilt") return STATUS.valid.color;
  if (kind === "failed") return STATUS.retracted.color;
  return (STATUS as Record<string, StatusInfo>)[kind]?.color ?? "var(--muted)";
}

/** Resolve a CSS variable to a concrete color, for canvas renderers like the MiniMap. */
export function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
