import { useEffect, useRef, useState } from "react";

import type { Evidence, ReviewEntry, ReviewField } from "../api/client";
import { confidenceBand, formatList, formatValue, paragraphs } from "../lib/format";
import { RecordView } from "./RecordView";
import { EditForm, type EditResult } from "./EditForm";
import { EvidenceChip } from "./EvidenceChip";
import { CONFIDENCE_HINT } from "./guide";
import {
  approveBlocker,
  currentEntry,
  evidenceNumber,
  failedRules,
  recordNote,
  summaryLock,
  type SummaryState,
  versionTag,
} from "./model";

export type SaveState = { kind: "saving" } | { kind: "saved" } | { kind: "failed"; message: string };
export type CardMode = "view" | "edit" | "flag";
export type Decision =
  // candidate_id names another reading of the field than the one shown ("Use this reading").
  | { decision: "approved"; candidate_id?: string }
  | { decision: "not_in_document" }
  | { decision: "flagged"; note: string }
  | { decision: "cleared" }
  | ({ decision: "edited" } & EditResult);

const PILL = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};
const BUTTON = "rounded border px-2 py-0.5 text-xs font-medium disabled:opacity-40";

const MARKER = /\[\d+\]/;

/** A long text in paragraphs. An evidence marker ("[3]") becomes a small numbered button
 * that shows the quote it stands for, so each sentence is tied to its evidence. */
function LongText({ text, onMarker, active, hint }: {
  text: string;
  onMarker: (number: number) => void;
  active: number | null;
  /** What a number stands for: the field it comes from and the words it quotes. */
  hint: (number: number) => string;
}) {
  return (
    <>
      {paragraphs(text).map((paragraph, index) => (
        <p key={index} className={index ? "mt-1" : ""}>
          {paragraph.heading && <span className="font-semibold">{paragraph.heading}: </span>}
          {paragraph.pieces.map((piece, at) =>
            "marker" in piece ? (
              <button
                key={at}
                type="button"
                data-testid="evidence-marker"
                title={hint(piece.marker)}
                className={
                  "mx-0.5 rounded px-1 align-super text-[10px] font-semibold leading-none " +
                  (active === piece.marker ? "bg-sky-700 text-white" : "bg-sky-100 text-sky-800 hover:bg-sky-200")
                }
                onClick={(event) => {
                  event.stopPropagation();
                  onMarker(piece.marker);
                }}
              >
                {piece.marker}
              </button>
            ) : (
              <span key={at}>{piece.text}</span>
            ),
          )}
        </p>
      ))}
    </>
  );
}

function Value({ value, field, onMarker, active, hint }: {
  value: unknown;
  field: ReviewField;
  onMarker: (number: number) => void;
  active: number | null;
  hint: (number: number) => string;
}) {
  if (value === null || value === undefined)
    return <span className="italic text-slate-500">No value found</span>;
  if (field.value_type === "long_text" && typeof value === "string")
    return <LongText text={value} onMarker={onMarker} active={active} hint={hint} />;
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

/** The value the card draws. A scalar edit is told in the decision line ("Edited to X"),
 * and the card keeps the extracted value above it. A record cannot be told in a line, so
 * once a reviewer has edited one the card draws their record instead of the extracted one. */
export function shownValue(field: ReviewField, entry: ReviewEntry | null): unknown {
  const approval = entry?.state.approval;
  if (field.keys?.length && approval?.decision === "edited" && approval.final_value != null)
    return approval.final_value;
  return entry?.state.candidate?.value ?? null;
}

function decisionLine(entry: ReviewEntry, field: ReviewField): { text: string; tone: string } | null {
  const approval = entry.state.approval;
  if (!approval) return null;
  const by = ` · ${approval.reviewer}`;
  if (approval.decision === "approved") return { text: `Approved${by}`, tone: "text-green-700" };
  if (approval.decision === "edited")
    return {
      text: field.keys?.length
        ? `Edited${by}`
        : `Edited to ${formatValue(approval.final_value, field.value_type, field.unit)}${by}`,
      tone: "text-green-700",
    };
  if (approval.decision === "not_in_document")
    return { text: `Not in document${by}`, tone: "text-green-700" };
  if (approval.decision === "flagged")
    return { text: `Flagged: ${approval.note ?? "come back"}${by}`, tone: "text-amber-700" };
  // A cleared decision is no decision: the card reads as undecided.
  if (approval.decision === "cleared") return null;
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
  activeEvidence,
  summary = null,
  onFocus,
  onMode,
  onDecide,
  onShowEvidence,
  onRefresh,
}: {
  field: ReviewField;
  focused: boolean;
  mode: CardMode;
  save: SaveState | undefined;
  readOnly: boolean;
  documentName: (documentId: string) => string;
  /** The evidence span shown in the PDF just now, if it is one of this field's. */
  activeEvidence: string | null;
  /** For the summary card: where the summary stands. It is decided after the fields. */
  summary?: SummaryState | null;
  onFocus: () => void;
  onMode: (mode: CardMode) => void;
  onDecide: (decision: Decision) => void;
  onShowEvidence: (evidence: Evidence) => void;
  /** Asks the screen to read the review again now (the summary card while a text is on its way). */
  onRefresh?: () => void;
}) {
  const entry = currentEntry(field);
  const candidate = entry?.state.candidate ?? null;
  const element = useRef<HTMLDivElement>(null);
  const [note, setNote] = useState("");
  const [whole, setWhole] = useState(false);
  const [wholeReason, setWholeReason] = useState(false);
  useEffect(() => {
    if (focused) element.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  const lock = summaryLock(summary, false);
  const blocker = summaryLock(summary, true) ?? approveBlocker(entry);
  const caveat = candidate ? recordNote(candidate) : null;
  const decided = entry ? decisionLine(entry, field) : null;
  const tag = entry ? versionTag(entry) : null;
  const earlier = entry ? field.entries.filter((other) => other !== entry) : [];
  const failures = failedRules(candidate);
  const long = field.value_type === "long_text";
  const evidence = candidate?.evidence ?? [];
  const several = evidence.length > 1;
  const number = (item: Evidence) => (candidate ? evidenceNumber(candidate, item) : 0);
  const activeNumber = evidence.find((item) => item.id === activeEvidence);
  const marked = long && typeof candidate?.value === "string" && MARKER.test(candidate.value);
  // The focused field is shown in full: its text and the model's reasons.
  const showAll = whole || focused;
  const showReason = wholeReason || focused;

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
            <span className="flex cursor-help items-center gap-1" title={`Model confidence ${Math.round(candidate.confidence * 100)}%. ${CONFIDENCE_HINT}`}>
              <span data-testid="confidence-caption" className="text-[10px] text-slate-500">
                model confidence
              </span>
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

      {caveat && (
        // What the summary leaves out or was unsure of: read before the text.
        <p data-testid="record-note" className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-slate-800">
          <span className="font-semibold">Note on this summary: </span>
          {caveat}
        </p>
      )}
      <div
        data-testid="field-value"
        className={"mt-0.5 text-sm text-slate-900 " + (long && !showAll ? "line-clamp-4" : "")}
      >
        <Value
          value={shownValue(field, entry ?? null)}
          field={field}
          active={activeNumber ? number(activeNumber) : null}
          hint={(wanted) => {
            const found = evidence.find((item) => number(item) === wanted);
            if (!found) return `Evidence ${wanted}`;
            return `${found.source ?? "Evidence"} · p. ${found.page_no}: “${found.quote.slice(0, 300)}”`;
          }}
          onMarker={(wanted) => {
            const found = evidence.find((item) => number(item) === wanted);
            if (found) onShowEvidence(found);
          }}
        />
      </div>
      {long && typeof candidate?.value === "string" && candidate.value.length > 280 && !focused && (
        <button
          type="button"
          className="text-xs text-sky-700 underline"
          onClick={(event) => {
            event.stopPropagation();
            setWhole(!whole);
          }}
        >
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

      {candidate && evidence.length > 0 && !marked && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="text-xs text-slate-500">Evidence</span>
          {evidence.map((item) => (
            <EvidenceChip
              key={item.id}
              evidence={item}
              number={several ? number(item) : undefined}
              active={focused && item.id === activeEvidence}
              onShow={onShowEvidence}
            />
          ))}
        </div>
      )}
      {candidate && marked && (
        // A text whose sentences carry their numbers has no list of chips: a number shows
        // what it stands for on hover, and the one being looked at is spelled out here.
        <p data-testid="active-passage" className="mt-1 text-xs text-slate-600">
          {activeNumber ? (
            <button
              type="button"
              className="text-left hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                onShowEvidence(activeNumber);
              }}
            >
              <span className="mr-1 rounded bg-sky-700 px-1 font-semibold text-white">{number(activeNumber)}</span>
              <span className="font-semibold">{activeNumber.source ?? "Evidence"}</span> · p. {activeNumber.page_no}: “
              {activeNumber.quote.length > 220 ? `${activeNumber.quote.slice(0, 220)}…` : activeNumber.quote}”
            </button>
          ) : (
            <span className="text-slate-500">
              {evidence.length} passages. Click a number in the text to see the field it comes from and its words.
            </span>
          )}
        </p>
      )}
      {candidate && several && focused && !marked && (
        // Which claim each numbered chip supports: the words it quotes.
        <ol data-testid="evidence-quotes" className="mt-1 space-y-0.5 text-xs text-slate-600">
          {evidence.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={"text-left hover:underline " + (item.id === activeEvidence ? "font-semibold text-sky-800" : "")}
                onClick={(event) => {
                  event.stopPropagation();
                  onShowEvidence(item);
                }}
              >
                <span className="mr-1 font-semibold">{number(item)}</span>
                p. {item.page_no}: “{item.quote.length > 160 ? `${item.quote.slice(0, 160)}…` : item.quote}”
              </button>
            </li>
          ))}
        </ol>
      )}
      {candidate && !caveat && (
        <p data-testid="rationale" className={"mt-0.5 text-xs text-slate-500 " + (showReason ? "" : "line-clamp-2")}>
          {candidate.rationale}
          {!focused && candidate.rationale.length > 140 && (
            <button
              type="button"
              data-testid="rationale-toggle"
              className="ml-1 text-sky-700 underline"
              onClick={(event) => {
                event.stopPropagation();
                setWholeReason(!wholeReason);
              }}
            >
              {wholeReason ? "less" : "more"}
            </button>
          )}
        </p>
      )}

      {earlier.map((other) => (
        <p key={other.version_no} className="mt-0.5 text-xs text-slate-500">
          v{other.version_no} {other.version_kind}:{" "}
          {formatValue(other.state.candidate?.value ?? null, field.value_type, field.unit) || "no value"}
          {other.state.approval?.decision === "not_in_document" ? " (set aside)" : ""}
          {(other.state.candidate?.evidence ?? []).slice(0, 3).map((item) => (
            <span key={item.id} className="ml-1 inline-block">
              <EvidenceChip evidence={item} active={focused && item.id === activeEvidence} onShow={onShowEvidence} />
            </span>
          ))}
        </p>
      ))}

      {decided && (
        <p data-testid="decision" className={"mt-1 text-xs font-medium " + decided.tone}>
          {decided.text}
        </p>
      )}

      {(entry?.state.alternatives ?? []).map((other) => (
        // Another page window of the section, or another pass over it, read a different
        // value: the reviewer sees both and picks. Where the readings agree nothing is listed.
        <div key={other.id} data-testid="alternative" className="mt-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-1">
          <p className="text-xs font-semibold text-amber-900">
            The model also read this field differently
            <span
              className="ml-2 font-normal text-slate-600"
              title={`Model confidence ${Math.round(other.confidence * 100)}%. ${CONFIDENCE_HINT}`}
            >
              model confidence {Math.round(other.confidence * 100)}%
            </span>
          </p>
          <div data-testid="alternative-value" className="mt-0.5 text-sm text-slate-900">
            <Value value={other.value} field={field} active={null} hint={() => ""} onMarker={() => undefined} />
          </div>
          <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{other.rationale}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1" onClick={(event) => event.stopPropagation()}>
            {other.evidence.map((item) => (
              <EvidenceChip key={item.id} evidence={item} active={focused && item.id === activeEvidence} onShow={onShowEvidence} />
            ))}
            {!readOnly && (
              <button
                type="button"
                data-testid="use-reading"
                disabled={lock !== null}
                title={lock ?? "Approve this reading instead of the one above"}
                className={BUTTON + " ml-auto border-amber-700 bg-white text-amber-900 hover:bg-amber-100"}
                onClick={() => onDecide({ decision: "approved", candidate_id: other.id })}
              >
                Use this reading
              </button>
            )}
          </div>
        </div>
      ))}

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
            disabled={lock !== null}
            title={lock ?? "Edit (E)"}
            className={BUTTON + " border-slate-400 bg-white hover:bg-slate-100"}
            onClick={() => onMode("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            data-testid="not-in-document"
            disabled={lock !== null}
            title={lock ?? "Not in document (N)"}
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
          {(field.decided || field.flagged) && (
            <button
              type="button"
              data-testid="clear-decision"
              title="Undo this decision; the field is undecided again (U)"
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
      {entry && !readOnly && mode === "view" && blocker && (focused || summary) && !field.decided && (
        <p data-testid="blocker" className={"mt-0.5 text-xs " + (summary ? "font-medium text-amber-800" : "text-slate-500")}>
          {blocker}
          {summary && !summary.current && summary.waiting_for === 0 && onRefresh && (
            <button
              type="button"
              data-testid="check-again"
              className="ml-2 underline"
              onClick={(event) => {
                event.stopPropagation();
                onRefresh();
              }}
            >
              Check again
            </button>
          )}
        </p>
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
