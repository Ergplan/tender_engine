import { useState } from "react";

import type { Evidence, ReviewField, TenderReview } from "../api/client";
import { type CardMode, type Decision, FieldCard, type SaveState } from "./FieldCard";
import { fieldsOfSection, needsAttention } from "./model";

/** The sections in review order, each collapsible, with its decided/total count. */
export function SectionList({
  review,
  focused,
  mode,
  saves,
  readOnly,
  documentName,
  activeEvidence,
  onFocus,
  onMode,
  onDecide,
  onShowEvidence,
}: {
  review: TenderReview;
  focused: string | null;
  mode: CardMode;
  saves: Record<string, SaveState>;
  readOnly: boolean;
  documentName: (documentId: string) => string;
  activeEvidence: string | null;
  onFocus: (path: string) => void;
  onMode: (path: string, mode: CardMode) => void;
  onDecide: (field: ReviewField, decision: Decision) => void;
  onShowEvidence: (path: string, evidence: Evidence) => void;
}) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  return (
    <div>
      {review.sections.map((section) => {
        const fields = fieldsOfSection(review, section.name);
        if (fields.length === 0) return null;
        const decided = fields.filter((field) => field.decided).length;
        const flagged = fields.filter((field) => field.flagged).length;
        const attention = fields.filter(needsAttention).length;
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
                {decided}/{fields.length}
              </span>
            </button>
            {open && (
              <div className="divide-y divide-slate-100">
                {fields.map((field) => (
                  <FieldCard
                    key={field.field_path}
                    field={field}
                    focused={focused === field.field_path}
                    mode={focused === field.field_path ? mode : "view"}
                    save={saves[field.field_path]}
                    readOnly={readOnly}
                    documentName={documentName}
                    activeEvidence={activeEvidence}
                    onFocus={() => onFocus(field.field_path)}
                    onMode={(next) => onMode(field.field_path, next)}
                    onDecide={(decision) => onDecide(field, decision)}
                    onShowEvidence={(evidence) => onShowEvidence(field.field_path, evidence)}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
