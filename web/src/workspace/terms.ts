// What the workspace reads out of a tender's snapshot: the headline terms a bid team looks
// for first, the sections in reading order, and the fields that want a person's eye.
import type { SnapshotField, VersionStatus } from "../api/client";
import { formatValue } from "../lib/format";

export const TENDER_TYPES: { value: string; label: string }[] = [
  { value: "", label: "Detect it for me" },
  { value: "solar", label: "Solar" },
  { value: "wind", label: "Wind" },
  { value: "hybrid", label: "Hybrid" },
  { value: "fdre", label: "FDRE" },
  { value: "re_rtc", label: "RE round the clock" },
  { value: "bess", label: "Battery storage (BESS)" },
  { value: "transmission", label: "Transmission (TBCB)" },
  { value: "generation", label: "Generation" },
  { value: "epc", label: "EPC" },
  { value: "ipp", label: "Other power procurement" },
];

export const AMENDMENT_KINDS = [
  { value: "amendment", label: "Amendment" },
  { value: "corrigendum", label: "Corrigendum" },
  { value: "clarification", label: "Clarification" },
];

/** The terms on the strip, in the order a bid team reads them; the first path a tender has
 * is the one shown. */
export const HEADLINE: { label: string; paths: string[] }[] = [
  { label: "Capacity", paths: ["sector.power.common.total_capacity_mw"] },
  { label: "Storage", paths: ["sector.power.common.total_capacity_mwh"] },
  { label: "Bids due", paths: ["core.key_dates.bid_submission_deadline"] },
  {
    label: "Tariff ceiling",
    paths: ["sector.power.common.tariff_ceiling_inr_per_kwh", "sector.power.ipp.tariff_ceiling_inr_per_kwh"],
  },
  { label: "EMD", paths: ["core.guarantees.emd_per_mw_inr"] },
  { label: "PBG", paths: ["core.guarantees.pbg_per_mw_inr"] },
  { label: "PPA term", paths: ["sector.power.common.ppa_tenure_years", "sector.power.ipp.ppa_tenure_years"] },
  { label: "Commissioning", paths: ["sector.power.common.scod_months", "sector.power.ipp.scod_months"] },
];

export const SUMMARY_PATH = "core.summary.plain_english_summary";
export const DEADLINE_PATH = "core.key_dates.bid_submission_deadline";

export type Headline = { label: string; field: SnapshotField };

export function headline(fields: SnapshotField[]): Headline[] {
  const byPath = new Map(fields.map((f) => [f.path, f]));
  const shown: Headline[] = [];
  for (const term of HEADLINE) {
    const field = term.paths.map((p) => byPath.get(p)).find((f) => f && f.state !== "not_stated");
    if (field) shown.push({ label: term.label, field });
  }
  return shown;
}

export function display(field: SnapshotField): string {
  if (field.state === "withdrawn") return "Withdrawn";
  if (field.state === "not_stated") return "Not stated";
  const text = formatValue(field.value, field.value_type, field.unit ?? null);
  return text || "Not stated";
}

/** Days from today to a date value; negative once it has passed. */
export function daysUntil(value: unknown, today: Date = new Date()): number | null {
  if (typeof value !== "string") return null;
  const day = new Date(value.slice(0, 10) + "T00:00:00");
  if (Number.isNaN(day.getTime())) return null;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((day.getTime() - start.getTime()) / 86_400_000);
}

export function sectionLabel(section: string): string {
  const text = section.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export type Section = { name: string; label: string; fields: SnapshotField[] };

/** Sections in the order the snapshot lists their first field. */
export function sections(fields: SnapshotField[]): Section[] {
  const order: string[] = [];
  const grouped = new Map<string, SnapshotField[]>();
  for (const field of fields) {
    if (field.path === SUMMARY_PATH) continue;
    if (!grouped.has(field.section)) {
      grouped.set(field.section, []);
      order.push(field.section);
    }
    grouped.get(field.section)!.push(field);
  }
  return order.map((name) => ({ name, label: sectionLabel(name), fields: grouped.get(name)! }));
}

/** A field a person should look at: withdrawn by an amendment, flagged by a rule, a quote
 * that was not found on its page, or a machine reading below the high band. */
export function needsAttention(field: SnapshotField): boolean {
  if (field.state === "withdrawn") return true;
  if (field.state === "not_stated") return false;
  if (field.needs_review) return true;
  if (field.evidence.some((e) => !e.located)) return true;
  return field.source === "machine" && (field.confidence ?? 1) < 0.8;
}

export type Filter = "all" | "attention" | "changed";

export function filterFields(fields: SnapshotField[], filter: Filter, query: string): SnapshotField[] {
  const needle = query.trim().toLowerCase();
  return fields.filter((field) => {
    if (filter === "attention" && !needsAttention(field)) return false;
    if (filter === "changed" && !((field.version_no ?? 1) > 1 || field.state === "withdrawn")) return false;
    if (filter === "all" && field.state === "not_stated" && !needle) return false;
    if (!needle) return true;
    return `${field.label} ${display(field)} ${field.evidence.map((e) => e.quote).join(" ")}`
      .toLowerCase()
      .includes(needle);
  });
}

export const STAGES: { stage: VersionStatus["stage"]; label: string }[] = [
  { stage: "submitted", label: "Received" },
  { stage: "parsing", label: "Reading pages" },
  { stage: "mapping", label: "Finding sections" },
  { stage: "extracting", label: "Extracting terms" },
  { stage: "validated", label: "Checked" },
];

export function stageIndex(stage: VersionStatus["stage"]): number {
  return STAGES.findIndex((s) => s.stage === stage);
}
