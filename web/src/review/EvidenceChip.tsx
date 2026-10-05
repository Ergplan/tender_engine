import type { Evidence } from "../api/client";
import { located } from "./model";

/** "p. 47", or "2 · p. 47" when a field has several: one per evidence span. Clicking shows
 * the page and the highlighted text; the chip being shown is marked. */
export function EvidenceChip({
  evidence,
  number,
  active = false,
  onShow,
}: {
  evidence: Evidence;
  number?: number;
  active?: boolean;
  onShow: (evidence: Evidence) => void;
}) {
  const found = located(evidence);
  return (
    <button
      type="button"
      data-testid="evidence-chip"
      data-active={active ? "yes" : "no"}
      title={found ? evidence.quote : `Not located on this page: "${evidence.quote}"`}
      onClick={(event) => {
        event.stopPropagation();
        onShow(evidence);
      }}
      className={
        "rounded border px-1.5 py-0.5 text-xs font-medium " +
        (active
          ? "border-sky-700 bg-sky-700 text-white"
          : found
            ? "border-sky-300 bg-sky-50 text-sky-800 hover:bg-sky-100"
            : "border-dashed border-slate-400 bg-white text-slate-600 hover:bg-slate-50")
      }
    >
      {number !== undefined && <span className="mr-1 font-semibold">{number}</span>}
      p. {evidence.page_no}
      {found ? "" : " ?"}
    </button>
  );
}
