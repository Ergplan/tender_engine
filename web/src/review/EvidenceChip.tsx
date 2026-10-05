import type { Evidence } from "../api/client";
import { located } from "./model";

/** "p. 47": one per evidence span. Clicking shows the page and the highlighted text. */
export function EvidenceChip({
  evidence,
  onShow,
}: {
  evidence: Evidence;
  onShow: (evidence: Evidence) => void;
}) {
  const found = located(evidence);
  return (
    <button
      type="button"
      data-testid="evidence-chip"
      title={found ? evidence.quote : `Not located on this page: "${evidence.quote}"`}
      onClick={(event) => {
        event.stopPropagation();
        onShow(evidence);
      }}
      className={
        "rounded border px-1.5 py-0.5 text-xs font-medium " +
        (found
          ? "border-sky-300 bg-sky-50 text-sky-800 hover:bg-sky-100"
          : "border-dashed border-slate-400 bg-white text-slate-600 hover:bg-slate-50")
      }
    >
      p. {evidence.page_no}
      {found ? "" : " ?"}
    </button>
  );
}
