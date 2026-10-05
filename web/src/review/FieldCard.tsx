import { useEffect, useRef, useState } from "react";

import type { Evidence, ReviewEntry, ReviewField } from "../api/client";
import { confidenceBand, formatList, formatValue } from "../lib/format";
import { EditForm, type EditResult } from "./EditForm";
import { EvidenceChip } from "./EvidenceChip";
import { approveBlocker, currentEntry, failedRules, versionTag } from "./model";

export type SaveState = { kind: "saving" } | { kind: "saved" } | { kind: "failed"; message: string };
export type CardMode = "view" | "edit" | "flag";
export type Decision =
  | { decision: "approved" }
  | { decision: "not_in_document" }
  | { decision: "flagged"; note: string }
  | ({ decision: "edited" } & EditResult);

const PILL = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};
const BUTTON = "rounded border px-2 py-0.5 text-xs font-medium disabled:opacity-40";

function Value({ value, field }: { value: unknown; field: ReviewField }) {
  if (value === null || value === undefined)
    return <span className="italic text-slate-500">No value found</span>;
  if (Array.isArray(value))
    return (
      <ul className="list-disc pl-4">
        {formatList(value).map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    );
  return <span>{formatValue(value, field.value_type, field.unit)}</span>;
}

function decisionLine(entry: ReviewEntry, field: ReviewField): { text: string; tone: string } | null {
  const approval = entry.state.approval;
  if (!approval) return null;
  const by = ` · ${approval.reviewer}`;
  if (approval.decision === "approved") return { text: `Approved${by}`, tone: "text-green-700" };
  if (approval.decision === "edited")
    return {
      text: `Edited to ${formatValue(approval.final_value, field.value_type, field.unit)}${by}`,
      tone: "text-green-700",
    };
  if (approval.decision === "not_in_document")
    return { text: `Not in document${by}`, tone: "text-green-700" };
  if (approval.decision === "flagged")
    return { text: `Flagged: ${approval.note ?? "come back"}${by}`, tone: "text-amber-700" };
  return { text: `${approval.decision}${by}`, tone: "text-slate-600" };
}

/** One field: label, value, confidence, validation, evidence chips and the three actions. */
export function FieldCard({
  field,
  focused,
  mode,
  save,
  readOnly,
  documentName,
  onFocus,
  onMode,
  onDecide,
  onShowEvidence,
}: {
  field: ReviewField;
  focused: boolean;
  mode: CardMode;
  save: SaveState | undefined;
  readOnly: boolean;
  documentName: (documentId: string) => string;
  onFocus: () => void;
  onMode: (mode: CardMode) => void;
  onDecide: (decision: Decision) => void;
  onShowEvidence: (evidence: Evidence) => void;
}) {
  const entry = currentEntry(field);
  const candidate = entry?.state.candidate ?? null;
  const element = useRef<HTMLDivElement>(null);
  const [note, setNote] = useState("");
  const [whole, setWhole] = useState(false);
  useEffect(() => {
    if (focused) element.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  const blocker = approveBlocker(entry);
  const decided = entry ? decisionLine(entry, field) : null;
  const tag = entry ? versionTag(entry) : null;
  const earlier = entry ? field.entries.filter((other) => other !== entry) : [];
  const failures = failedRules(candidate);
  const long = field.value_type === "long_text";

  return (
    <div
      ref={element}
      data-testid="field-card"
      data-field={field.field_path}
      data-decided={field.decided ? "yes" : "no"}
      data-focused={focused ? "yes" : "no"}
      onClick={onFocus}
      className={
        "border-l-4 px-3 py-2 " +
        (focused ? "border-sky-600 bg-sky-50/60" : "border-transparent hover:bg-slate-50") +
        (field.decided ? "" : " ")
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-600" title={field.help_text}>
          {field.label}
          {field.required && <span className="text-red-600" title="Required"> *</span>}
          {field.help_text && <span className="ml-1 cursor-help text-slate-400">ⓘ</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {tag && (
            <span data-testid="version-tag" className="rounded bg-violet-100 px-1.5 py-0.5 text-[11px] font-medium text-violet-800">
              {tag}
            </span>
          )}
          {candidate && candidate.value !== null && candidate.value !== undefined && (
            <span
              data-testid="confidence"
              title={`Model confidence ${candidate.confidence.toFixed(2)}`}
              className={"rounded-full px-1.5 py-0.5 text-[11px] font-medium " + PILL[confidenceBand(candidate.confidence)]}
            >
              {Math.round(candidate.confidence * 100)}%
            </span>
          )}
        </div>
      </div>

      <div
        data-testid="field-value"
        className={"mt-0.5 text-sm text-slate-900 " + (long && !whole ? "line-clamp-4" : "")}
        onDoubleClick={() => setWhole(!whole)}
      >
        <Value value={candidate?.value ?? null} field={field} />
      </div>
      {long && candidate?.value != null && (
        <button type="button" className="text-xs text-sky-700 underline" onClick={() => setWhole(!whole)}>
          {whole ? "Show less" : "Show all"}
        </button>
      )}

      {failures.map((failure) => (
        <p
          key={failure.rule_name + failure.message}
          data-testid="validation-note"
          className={"mt-0.5 text-xs " + (failure.severity === "warning" ? "text-amber-700" : "text-red-700")}
        >
          {failure.message}
        </p>
      ))}

      {candidate && candidate.evidence.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="text-xs text-slate-500">Evidence</span>
          {candidate.evidence.map((evidence) => (
            <EvidenceChip key={evidence.id} evidence={evidence} onShow={onShowEvidence} />
          ))}
        </div>
      )}
      {candidate && (
        <p className="mt-0.5 line-clamp-2 text-xs text-slate-500" title={candidate.rationale}>
          {candidate.rationale}
        </p>
      )}

      {earlier.map((other) => (
        <p key={other.version_no} className="mt-0.5 text-xs text-slate-500">
          v{other.version_no} {other.version_kind}:{" "}
          {formatValue(other.state.candidate?.value ?? null, field.value_type, field.unit) || "no value"}
          {other.state.approval?.decision === "not_in_document" ? " (set aside)" : ""}
          {(other.state.candidate?.evidence ?? []).slice(0, 3).map((evidence) => (
            <span key={evidence.id} className="ml-1 inline-block">
              <EvidenceChip evidence={evidence} onShow={onShowEvidence} />
            </span>
          ))}
        </p>
      ))}

      {decided && (
        <p data-testid="decision" className={"mt-1 text-xs font-medium " + decided.tone}>
          {decided.text}
        </p>
      )}

      {entry && !readOnly && mode === "view" && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
          <button
            type="button"
            data-testid="approve"
            disabled={blocker !== null}
            title={blocker ?? "Approve (Enter)"}
            className={BUTTON + " border-green-600 bg-green-600 text-white hover:bg-green-700"}
            onClick={() => onDecide({ decision: "approved" })}
          >
            Approve
          </button>
          <button
            type="button"
            data-testid="edit"
            title="Edit (E)"
            className={BUTTON + " border-slate-400 bg-white hover:bg-slate-100"}
            onClick={() => onMode("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            data-testid="not-in-document"
            title="Not in document (N)"
            className={BUTTON + " border-slate-400 bg-white hover:bg-slate-100"}
            onClick={() => onDecide({ decision: "not_in_document" })}
          >
            Not in document
          </button>
          <button
            type="button"
            data-testid="flag"
            title="Unsure, come back (F)"
            className="px-1 text-xs text-amber-700 underline"
            onClick={() => onMode("flag")}
          >
            Flag
          </button>
          <span data-testid="save-state" className="ml-auto text-xs">
            {save?.kind === "saving" && <span className="text-slate-500">Saving…</span>}
            {save?.kind === "saved" && <span className="text-green-700">✓ Saved</span>}
            {save?.kind === "failed" && (
              <span role="alert" className="text-red-700">
                {save.message}
              </span>
            )}
          </span>
        </div>
      )}
      {entry && !readOnly && mode === "view" && blocker && focused && !field.decided && (
        <p className="mt-0.5 text-xs text-slate-500">{blocker}</p>
      )}
      {!entry && <p className="mt-1 text-xs text-slate-500">Nothing was extracted for this field.</p>}

      {entry && mode === "edit" && (
        <EditForm
          field={field}
          entry={entry}
          documentName={candidate ? documentName(candidate.document_id) : "the document"}
          onCancel={() => onMode("view")}
          onSave={(result) => onDecide({ decision: "edited", ...result })}
        />
      )}
      {entry && mode === "flag" && (
        <form
          className="mt-2 flex gap-2"
          onClick={(event) => event.stopPropagation()}
          onSubmit={(event) => {
            event.preventDefault();
            onDecide({ decision: "flagged", note: note.trim() || "come back" });
          }}
        >
          <input
            autoFocus
            type="text"
            data-testid="flag-note"
            placeholder="What are you unsure about?"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <button type="submit" data-testid="flag-save" className={BUTTON + " border-amber-600 bg-amber-600 text-white"}>
            Flag
          </button>
          <button type="button" className={BUTTON + " border-slate-300 bg-white"} onClick={() => onMode("view")}>
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}
