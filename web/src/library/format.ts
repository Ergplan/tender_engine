import type { PublishedField, PublishedTender, PublicationState } from "../api/types5c";

const DAY_MS = 24 * 60 * 60 * 1000;

/** A value as the published view prints it: lists joined, objects as key: value pairs,
 * numbers with the field's unit. Never a blank: a null is the caller's gap to render. */
export function showValue(value: unknown, unit: string | null = null): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((item) => showValue(item)).join("; ");
  if (typeof value === "object")
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${showValue(v)}`)
      .join(" · ");
  if (typeof value === "number") return `${value.toLocaleString("en-IN")}${unit ? ` ${unit}` : ""}`;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

export function showDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Days from today to a date (UTC), negative when past; null when there is no date. */
export function daysUntil(value: string | null | undefined, today: Date = new Date()): number | null {
  if (!value) return null;
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return null;
  const start = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((date.getTime() - start) / DAY_MS);
}

export function fieldOf(view: PublishedTender | null | undefined, path: string): PublishedField | undefined {
  if (!view) return undefined;
  for (const section of view.sections) for (const field of section.fields) if (field.path === path) return field;
  return undefined;
}

export const STATE_LABEL: Record<PublicationState, string> = {
  published: "published",
  update_pending: "update pending",
  publication_suspended: "suspended",
  not_published: "not published",
};

export const STATE_CLASS: Record<PublicationState, string> = {
  published: "bg-[#e7f2ef] text-[#0f5f5c]",
  update_pending: "bg-[#fdf1e3] text-[#8a4a0b]",
  publication_suspended: "bg-[#fdecec] text-[#991b1b]",
  not_published: "bg-[#efeeea] text-slate-600",
};
