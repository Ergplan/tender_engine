import { useState } from "react";

import type { Evidence, ReviewField, TenderReview } from "../api/client";
import { CarriedCard } from "./CarriedCard";
import { type CardMode, type Decision, FieldCard, type SaveState } from "./FieldCard";
import { fieldsOfSection, needsAttention, SUMMARY_FIELD, summaryState } from "./model";

/** The sections in review order, each collapsible, with its decided/total count. In a
 * round, a field carried forward from an earlier review is a compact row until the
 * reviewer opens it, and the counts are over the round's scope. */
export function SectionList({
  review,
  focused,
  mode,
  saves,
  readOnly,
  documentName,
  activeEvidence,
  expanded = new Set(),
  onExpand,
  onFocus,
  onMode,
  onDecide,
  onShowEvidence,
  onRefresh,
}: {
  review: TenderReview;
  focused: string | null;
  mode: CardMode;
  saves: Record<string, SaveState>;
  readOnly: boolean;
  documentName: (documentId: string) => string;
  activeEvidence: string | null;
  /** Carried fields the reviewer opened to decide again. */
  expanded?: Set<string>;
  onExpand?: (path: string) => void;
  onFocus: (path: string) => void;
  onMode: (path: string, mode: CardMode) => void;
  onDecide: (field: ReviewField, decision: Decision) => void;
  onShowEvidence: (path: string, evidence: Evidence) => void;
  onRefresh: () => void;
}) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const inRound = !!review.round;
  return (
    <div>
      {review.sections.map((section) => {
        const fields = fieldsOfSection(review, section.name);
        if (fields.length === 0) return null;
        const counted = inRound ? fields.filter((field) => field.in_scope) : fields;
        const carried = fields.length - counted.length;
        const decided = counted.filter((field) => field.decided).length;
        const flagged = counted.filter((field) => field.flagged).length;
        const attention = counted.filter(needsAttention).length;
        // A section that holds the focused field is shown even when collapsed.
        const open = !closed[section.name] || fields.some((field) => field.field_path === focused);
        return (
          <section key={section.name} data-testid="section" data-section={section.name}>
            <button
              type="button"
              className="sticky top-0 z-10 flex w-full items-center justify-between border-y border-slate-200 bg-slate-100 px-3 py-1.5 text-left text-sm font-semibold text-slate-800"
              onClick={() => setClosed({ ...closed, [section.name]: open })}
            >
              <span>
                {open ? "▾" : "▸"} {section.label}
              </span>
              <span className="text-xs font-normal text-slate-600" data-testid="section-count">
                {attention > 0 && (
                  <span
                    data-testid="section-attention"
                    title="Undecided fields that a validation rule flagged or that have low model confidence"
                    className="mr-2 rounded bg-red-100 px-1.5 py-0.5 font-medium text-red-800"
                  >
                    {attention} need a closer look
                  </span>
                )}
                {flagged > 0 && <span className="mr-2 text-amber-700">{flagged} flagged by you</span>}
                {decided}/{counted.length}
                {carried > 0 && (
                  <span data-testid="section-carried" className="ml-2 text-slate-500">
                    · {carried} carried forward
                  </span>
                )}
              </span>
            </button>
            {open && (
              <div className="divide-y divide-slate-100">
                {fields.map((field) =>
                  inRound && !field.in_scope && !expanded.has(field.field_path) ? (
                    <CarriedCard key={field.field_path} field={field} onExpand={() => onExpand?.(field.field_path)} />
                  ) : (
                  <FieldCard
                    key={field.field_path}
                    field={field}
                    focused={focused === field.field_path}
                    mode={focused === field.field_path ? mode : "view"}
                    save={saves[field.field_path]}
                    readOnly={readOnly}
                    documentName={documentName}
                    activeEvidence={activeEvidence}
                    summary={field.field_path === SUMMARY_FIELD ? summaryState(review) : null}
                    onFocus={() => onFocus(field.field_path)}
                    onMode={(next) => onMode(field.field_path, next)}
                    onDecide={(decision) => onDecide(field, decision)}
                    onShowEvidence={(evidence) => onShowEvidence(field.field_path, evidence)}
                    onRefresh={onRefresh}
                  />
                  ),
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
