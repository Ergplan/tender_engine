import { useEffect, useState } from "react";

import type { AmendmentChange, Evidence, ReviewField } from "../api/client";
import { changedShare, numericDelta, wordDiff } from "../lib/diff";
import { confidenceBand, formatList, formatValue } from "../lib/format";
import { DecisionNote } from "./DecisionNote";
import { EditForm } from "./EditForm";
import { EvidenceChip } from "./EvidenceChip";
import { type CardMode, type Decision, decisionLine, type SaveState } from "./FieldCard";
import { CONFIDENCE_HINT } from "./guide";
import { approveBlocker, failedRules } from "./model";
import { RecordView } from "./RecordView";

const KIND = {
  added: { label: "Added", className: "bg-sky-100 text-sky-800" },
  changed: { label: "Changed", className: "bg-violet-100 text-violet-800" },
  restated: { label: "Restated", className: "bg-slate-200 text-slate-700" },
  // The version withdraws the provision: what stood before no longer applies.
  removed: { label: "Removed", className: "bg-red-100 text-red-800" },
};
const PILL = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};
const BUTTON = "rounded border px-2 py-0.5 text-xs font-medium disabled:opacity-40";

/** The change as a field of the review, for the edit form and the record card. */
export function fieldOf(change: AmendmentChange): ReviewField {
  return {
    field_path: change.field_path,
    label: change.label,
    section: change.section,
    value_type: change.value_type,
    unit: change.unit,
    required: change.required,
    help_text: change.help_text,
    enum_values: change.enum_values,
    keys: change.keys,
    review_order: 0,
    entries: [change.entry],
    current: 0,
    decided: change.decided,
    flagged: change.flagged,
    in_scope: true,
  };
}

function Shown({ value, field }: { value: unknown; field: ReviewField }) {
  if (value === null || value === undefined) return <span className="italic text-slate-500">No value</span>;
  if (field.keys?.length) return <RecordView field={field} value={value} />;
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

const NUMERIC_TYPES = new Set(["int", "decimal", "percent", "money_inr", "mw", "mwh", "days", "months", "years"]);

/** What a change means, under the two readings: the numeric delta or the word diff, and
 * the impact cues — a decided value replaced, a required field, the derived tables that
 * are written again from it. */
export function ChangeDetail({ change, field, after }: { change: AmendmentChange; field: ReviewField; after: unknown }) {
  const before = change.before?.value;
  const delta = NUMERIC_TYPES.has(field.value_type) ? numericDelta(before, after) : null;
  const textual =
    typeof before === "string" && typeof after === "string" && !field.keys?.length ? wordDiff(before, after) : null;
  const share = textual ? changedShare(textual) : 1;
  const impacts = change.impacts ?? [];
  const cues: string[] = [];
  if (change.kind === "removed") cues.push("removes the value that stood before");
  if (change.changes_decided) cues.push(change.kind === "removed" ? "a value you decided" : "replaces a value you decided");
  if (change.required) cues.push("required field");
  if (impacts.length) cues.push(`read by ${impacts.join(", ")} (written again from it)`);
  if (!delta && !(textual && share < 0.8) && cues.length === 0) return null;
  return (
    <div data-testid="change-detail" className="mt-1 rounded border border-violet-200 bg-white px-2 py-1 text-xs">
      {delta && (
        <p data-testid="delta" className="font-medium text-violet-900">
          {formatValue(before, field.value_type, field.unit)} → {formatValue(after, field.value_type, field.unit)}{" "}
          <span className="font-normal text-slate-600">({delta})</span>
        </p>
      )}
      {textual && share < 0.8 && (
        <p data-testid="word-diff" className="leading-5 text-slate-800">
          {textual.map((part, index) =>
            part.kind === "same" ? (
              <span key={index}>{part.text}</span>
            ) : part.kind === "removed" ? (
              <del key={index} className="rounded bg-red-100 px-0.5 text-red-800">
                {part.text}
              </del>
            ) : (
              <ins key={index} className="rounded bg-green-100 px-0.5 text-green-800 no-underline">
                {part.text}
              </ins>
            ),
          )}
        </p>
      )}
      {cues.length > 0 && (
        <p data-testid="impact" className="mt-0.5 text-slate-600">
          <span className="font-medium text-slate-700">Impact:</span> {cues.join(" · ")}
        </p>
      )}
    </div>
  );
}

/** One field a later version states: what stood before it on the left, this version's
 * reading on the right with its evidence, and the decision on that reading. */
export function AmendmentCard({
  change,
  focused,
  mode,
  save,
  readOnly,
  documentName,
  activeEvidence,
  onFocus,
  onMode,
  onDecide,
  onShowEvidence,
}: {
  change: AmendmentChange;
  focused: boolean;
  mode: CardMode;
  save: SaveState | undefined;
  readOnly: boolean;
  documentName: (documentId: string) => string;
  activeEvidence: string | null;
  onFocus: () => void;
  onMode: (mode: CardMode) => void;
  onDecide: (decision: Decision) => void;
  onShowEvidence: (evidence: Evidence) => void;
}) {
  const [note, setNote] = useState("");
  const [noting, setNoting] = useState(false);
  const [remark, setRemark] = useState("");
  useEffect(() => {
    if (change.decided) {
      setNoting(false);
      setRemark("");
    }
  }, [change.decided]);
  const withNote = noting && remark.trim() ? { note: remark.trim() } : {};
  const field = fieldOf(change);
  const entry = change.entry;
  const candidate = entry.state.candidate;
  const approval = entry.state.approval;
  const kind = KIND[change.kind];
  const blocker = approveBlocker(entry);
  const failures = failedRules(candidate);
  const evidence = candidate?.evidence ?? [];
  const decided = decisionLine(entry, field);
  const after =
    approval?.decision === "edited" && approval.final_value != null ? approval.final_value : (candidate?.value ?? null);
  const standing = change.set_aside
    ? `Set aside: the field stands as v${change.before?.version_no ?? 1} states it.`
    : !change.is_current
      ? "A later version states this field again; the decision is taken there."
      : null;

  return (
    <div
      data-testid="amendment-card"
      data-field={change.field_path}
      data-version={entry.version_no}
      data-kind={change.kind}
      data-decided={change.decided ? "yes" : "no"}
      data-focused={focused ? "yes" : "no"}
      onClick={onFocus}
      className={"border-l-4 px-3 py-2 " + (focused ? "border-sky-600 bg-sky-50/60" : "border-transparent hover:bg-slate-50")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-600" title={change.help_text}>
          {change.label}
          {change.required && <span className="text-red-600" title="Required"> *</span>}
          <span className="ml-2 font-normal normal-case tracking-normal text-slate-400">{change.section_label}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span data-testid="change-kind" className={"rounded px-1.5 py-0.5 text-[11px] font-medium " + kind.className}>
            {kind.label}
          </span>
          {candidate && candidate.value !== null && candidate.value !== undefined && (
            <span className="flex cursor-help items-center gap-1" title={`Model confidence ${Math.round(candidate.confidence * 100)}%. ${CONFIDENCE_HINT}`}>
              <span className="text-[10px] text-slate-500">model confidence</span>
              <span
                data-testid="confidence"
                className={"rounded-full px-1.5 py-0.5 text-[11px] font-medium " + PILL[confidenceBand(candidate.confidence)]}
              >
                {Math.round(candidate.confidence * 100)}%
              </span>
            </span>
          )}
        </div>
      </div>

      <div className="mt-1 grid grid-cols-2 gap-3 text-sm">
        <div data-testid="before" className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">
            Before{change.before ? ` · v${change.before.version_no} ${change.before.version_kind}` : ""}
          </p>
          <div className="mt-0.5 text-slate-800">
            {change.before ? <Shown value={change.before.value} field={field} /> : <span className="italic text-slate-500">Not stated before</span>}
          </div>
          {change.before?.decision && (
            <p className="mt-0.5 text-[11px] text-slate-500">
              {change.before.decision === "not_in_document" ? "set aside" : change.before.decision}
            </p>
          )}
        </div>
        <div
          data-testid="after"
          className={
            "rounded border px-2 py-1 " +
            (change.kind === "restated" ? "border-slate-200" : change.kind === "removed" ? "border-red-300 bg-red-50/60" : "border-violet-300 bg-violet-50/40")
          }
        >
          <p className={"text-[11px] uppercase tracking-wide " + (change.kind === "removed" ? "text-red-800" : "text-violet-800")}>
            This version · v{entry.version_no} {entry.version_kind}
          </p>
          <div className="mt-0.5 text-slate-900">
            {change.kind === "removed" ? (
              <span data-testid="withdrawn" className="font-medium text-red-800">
                Withdrawn by this version
              </span>
            ) : (
              <Shown value={after} field={field} />
            )}
          </div>
        </div>
      </div>

      {(change.kind === "changed" || change.kind === "removed") && change.before && (
        <ChangeDetail change={change} field={field} after={after} />
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
      {candidate && evidence.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="text-xs text-slate-500">Evidence</span>
          {evidence.map((item, index) => (
            <EvidenceChip
              key={item.id}
              evidence={item}
              number={evidence.length > 1 ? (item.ordinal ?? index + 1) : undefined}
              active={focused && item.id === activeEvidence}
              onShow={onShowEvidence}
            />
          ))}
        </div>
      )}
      {candidate && (
        <p data-testid="rationale" className={"mt-0.5 text-xs text-slate-500 " + (focused ? "" : "line-clamp-2")}>
          {candidate.rationale}
        </p>
      )}
      {standing && (
        <p data-testid="standing" className="mt-1 text-xs text-slate-600">
          {standing}
        </p>
      )}
      {decided && (
        <p data-testid="decision" className={"mt-1 text-xs font-medium " + decided.tone}>
          {decided.text}
        </p>
      )}

      {!readOnly && mode === "view" && noting && (
        <DecisionNote
          value={remark}
          onChange={setRemark}
          onSubmit={() => {
            if (blocker === null) onDecide({ decision: "approved", ...withNote });
          }}
        />
      )}
      {!readOnly && mode === "view" && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
          <button
            type="button"
            data-testid="approve"
            disabled={blocker !== null}
            title={
              blocker ??
              (change.kind === "removed"
                ? "Approve the removal: what stood before will no longer apply"
                : "Approve this version's reading")
            }
            className={BUTTON + " border-green-600 bg-green-600 text-white hover:bg-green-700"}
            onClick={() => onDecide({ decision: "approved", ...withNote })}
          >
            {change.kind === "removed" ? "Approve removal" : "Approve"}
          </button>
          <button
            type="button"
            data-testid="edit"
            title="Edit this version's reading"
            className={BUTTON + " border-slate-400 bg-white hover:bg-slate-100"}
            onClick={() => onMode("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            data-testid="not-in-document"
            title="This version does not state the field: the earlier reading stands"
            className={BUTTON + " border-slate-400 bg-white hover:bg-slate-100"}
            onClick={() => onDecide({ decision: "not_in_document", ...withNote })}
          >
            Not in this version
          </button>
          <button
            type="button"
            data-testid="flag"
            title="Unsure, come back"
            className="px-1 text-xs text-amber-700 underline"
            onClick={() => onMode("flag")}
          >
            Flag
          </button>
          {!change.decided && (
            <button
              type="button"
              data-testid="note-toggle"
              title="Keep the value and say something about it; the note is stored with your decision"
              className={"px-1 text-xs underline " + (noting ? "text-sky-800" : "text-slate-600")}
              onClick={() => setNoting(!noting)}
            >
              {noting ? "No note" : "Add a note"}
            </button>
          )}
          {(change.decided || change.flagged) && (
            <button
              type="button"
              data-testid="clear-decision"
              title="Undo this decision; the reading is undecided again"
              className="px-1 text-xs text-slate-600 underline"
              onClick={() => onDecide({ decision: "cleared" })}
            >
              Clear decision
            </button>
          )}
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
      {!readOnly && mode === "view" && blocker && focused && !change.decided && (
        <p data-testid="blocker" className="mt-0.5 text-xs text-slate-500">
          {blocker}
        </p>
      )}

      {mode === "edit" && (
        <EditForm
          field={field}
          entry={entry}
          documentName={candidate ? documentName(candidate.document_id) : "the document"}
          onCancel={() => onMode("view")}
          onSave={(result) => onDecide({ decision: "edited", ...result })}
        />
      )}
      {mode === "flag" && (
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
