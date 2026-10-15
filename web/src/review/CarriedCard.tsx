import type { ReviewField } from "../api/client";
import { formatDate, formatList, formatValue } from "../lib/format";
import { currentEntry } from "./model";

/** A field a review round carries forward: decided on an earlier version, out of the
 * round's scope. Compact — the label, the value as the reviewer left it, and where the
 * decision came from — with no decision buttons until the reviewer asks to review it
 * again (then it is the ordinary card). */
export function CarriedCard({ field, onExpand }: { field: ReviewField; onExpand: () => void }) {
  const entry = currentEntry(field);
  const approval = entry?.state.approval ?? null;
  const candidate = entry?.state.candidate ?? null;
  const value =
    approval?.decision === "edited" && approval.final_value != null ? approval.final_value : (candidate?.value ?? null);
  const shown =
    approval?.decision === "not_in_document"
      ? "Not in document"
      : candidate?.withdrawn && approval?.decision === "approved"
        ? "Withdrawn"
        : value === null || value === undefined
          ? "No value"
          : Array.isArray(value) && !field.keys?.length
            ? formatList(value).join("; ")
            : formatValue(value, field.value_type, field.unit);
  const what = approval
    ? approval.decision === "not_in_document"
      ? "set aside as not in document"
      : approval.decision
    : "undecided";
  const when = approval ? ` on ${formatDate(approval.decided_at.slice(0, 10))}` : "";
  const by = approval ? ` by ${approval.reviewer}` : "";
  const version = entry ? ` (v${entry.version_no} ${entry.version_kind})` : "";
  return (
    <div data-testid="carried" data-field={field.field_path} className="flex items-start gap-3 px-3 py-1.5 text-sm text-slate-700">
      <div className="min-w-0 flex-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{field.label}</span>
        <span className="ml-2 truncate text-slate-800">{shown}</span>
        <p data-testid="carried-provenance" className="text-xs text-slate-500">
          Carried forward · {what}
          {by}
          {when}
          {version}
        </p>
      </div>
      <button
        type="button"
        data-testid="carried-expand"
        title="Open this field to decide it again in this round"
        className="shrink-0 px-1 text-xs text-slate-600 underline"
        onClick={onExpand}
      >
        Review again
      </button>
    </div>
  );
}
