import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type Evidence,
  type ReviewApi,
  type ReviewField,
  type ReviewSession,
  type TenderReview,
} from "../api/client";
import { keyAction, neighbour, nextWhere } from "../lib/keyboard";
import type { CardMode, Decision, SaveState } from "./FieldCard";
import { approveBlocker, currentEntry, documentName, firstEvidence, type PdfTarget, reviewOrder } from "./model";
import { type Highlight, PdfPane } from "./PdfPane";
import { SectionList } from "./SectionList";

/** The split screen: the extracted data on the left, the document on the right. */
export function ReviewScreen({
  api,
  session,
  initial,
  onCompleted,
}: {
  api: ReviewApi;
  session: ReviewSession;
  initial: TenderReview;
  onCompleted: () => void;
}) {
  const [review, setReview] = useState(initial);
  const [focused, setFocused] = useState<string | null>(null);
  const [mode, setMode] = useState<CardMode>("view");
  const [saves, setSaves] = useState<Record<string, SaveState>>({});
  const [target, setTarget] = useState<PdfTarget | null>(null);
  const [documentId, setDocumentId] = useState(
    () => initial.versions[0]?.documents[0]?.document_id ?? "",
  );
  const [leftShare, setLeftShare] = useState(44);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const targetKey = useRef(0);
  const readOnly = session.completed_at !== null && session.completed_at !== undefined;
  const order = useMemo(() => reviewOrder(review), [review]);
  const byPath = useMemo(
    () => new Map(review.fields.map((field) => [field.field_path, field])),
    [review],
  );

  const show = useCallback((evidence: Evidence) => {
    targetKey.current += 1;
    setTarget({
      documentId: evidence.document_id,
      pageNo: evidence.page_no,
      bbox: evidence.bbox ?? null,
      key: targetKey.current,
    });
  }, []);

  // Focus always brings the PDF to the field's first evidence.
  const focus = useCallback(
    (path: string | null, nextMode: CardMode = "view") => {
      setFocused(path);
      setMode(nextMode);
      const field = path ? byPath.get(path) : undefined;
      const evidence = field ? firstEvidence(currentEntry(field)) : null;
      if (evidence) show(evidence);
    },
    [byPath, show],
  );

  const reload = useCallback(async () => {
    const fresh = await api.review(review.tender_id);
    setReview(fresh);
    return fresh;
  }, [api, review.tender_id]);

  const decide = useCallback(
    async (field: ReviewField, decision: Decision, advance: boolean) => {
      const entry = currentEntry(field);
      const candidate = entry?.state.candidate;
      if (!entry || !candidate || readOnly) return;
      const path = field.field_path;
      setSaves((before) => ({ ...before, [path]: { kind: "saving" } }));
      try {
        await api.decide({
          candidate_id: candidate.id,
          decision: decision.decision,
          previous_approval_id: entry.state.approval?.id ?? null,
          final_value: decision.decision === "edited" ? decision.value : null,
          note: "note" in decision ? decision.note : null,
          evidence: decision.decision === "edited" ? decision.evidence : null,
        });
        const fresh = await reload();
        setSaves((before) => ({ ...before, [path]: { kind: "saved" } }));
        setMode("view");
        if (advance) {
          const undecided = new Set(fresh.fields.filter((f) => !f.decided).map((f) => f.field_path));
          const next = nextWhere(order, path, (candidatePath) => undecided.has(candidatePath));
          if (next) {
            setFocused(next);
            const nextField = fresh.fields.find((f) => f.field_path === next);
            const evidence = nextField ? firstEvidence(currentEntry(nextField)) : null;
            if (evidence) show(evidence);
          }
        }
      } catch (error) {
        const stale = error instanceof ApiError && error.status === 409;
        const message =
          error instanceof ApiError
            ? stale
              ? "Changed since it was loaded. Reloaded; decide again."
              : (error.detail ?? error.message)
            : "Not saved. Check the connection and retry.";
        setSaves((before) => ({ ...before, [path]: { kind: "failed", message } }));
        if (stale) await reload().catch(() => undefined);
      }
    },
    [api, order, readOnly, reload, show],
  );

  // Keys: Enter approves and moves on, E edits, N not in document, F flags, J/K move.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const action = keyAction(event);
      if (!action || confirming) return;
      const field = focused ? byPath.get(focused) : undefined;
      if (action === "next" || action === "previous") {
        event.preventDefault();
        return focus(neighbour(order, focused, action === "next" ? 1 : -1));
      }
      if (action === "cancel") return setMode("view");
      if (!field || readOnly || mode !== "view") return;
      event.preventDefault();
      if (action === "approve") {
        const blocker = approveBlocker(currentEntry(field));
        if (blocker)
          return setSaves((before) => ({ ...before, [field.field_path]: { kind: "failed", message: blocker } }));
        void decide(field, { decision: "approved" }, true);
      } else if (action === "not_in_document") void decide(field, { decision: "not_in_document" }, true);
      else if (action === "edit") setMode("edit");
      else if (action === "flag") setMode("flag");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [byPath, confirming, decide, focus, focused, mode, order, readOnly]);

  const highlights = useMemo<Highlight[]>(() => {
    const field = focused ? byPath.get(focused) : undefined;
    return (currentEntry(field ?? ({ current: null, entries: [] } as unknown as ReviewField))?.state.candidate?.evidence ?? [])
      .filter((evidence) => evidence.document_id === documentId)
      .map((evidence) => ({ pageNo: evidence.page_no, bbox: evidence.bbox ?? null }));
  }, [byPath, documentId, focused]);

  function drag(event: React.PointerEvent) {
    const box = container.current?.getBoundingClientRect();
    if (!box) return;
    const move = (moved: PointerEvent) =>
      setLeftShare(Math.min(Math.max(((moved.clientX - box.left) / box.width) * 100, 28), 65));
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    event.preventDefault();
  }

  async function complete() {
    setConfirming(false);
    try {
      await api.complete(review.tender_id);
      onCompleted();
    } catch (error) {
      setNotice(error instanceof ApiError ? (error.detail ?? error.message) : "Could not complete the review.");
      await reload().catch(() => undefined);
    }
  }

  return (
    <div className="flex h-full flex-col font-sans text-slate-900">
      <header className="flex items-center gap-4 border-b border-slate-300 bg-white px-3 py-1.5">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold" title={review.title} data-testid="tender-title">
            {review.title}
          </h1>
          <p className="truncate text-xs text-slate-600">
            <span className="uppercase">{review.tender_type}</span> · {review.issuing_agency} · Reviewer:{" "}
            <span data-testid="reviewer-name">{session.reviewer_name}</span>
          </p>
        </div>
        <span data-testid="progress" className="shrink-0 text-sm tabular-nums text-slate-700">
          {review.decided} of {review.total} fields decided
        </span>
        {readOnly ? (
          <span className="shrink-0 rounded bg-green-100 px-2 py-1 text-xs font-medium text-green-800">
            Completed · read-only
          </span>
        ) : (
          <button
            type="button"
            data-testid="complete-review"
            disabled={!review.can_complete}
            title={
              review.can_complete
                ? "Complete the review"
                : `${review.required_undecided} required field(s) still need a decision`
            }
            className="shrink-0 rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            onClick={() => setConfirming(true)}
          >
            Complete review
          </button>
        )}
      </header>
      {notice && (
        <p role="alert" className="border-b border-red-200 bg-red-50 px-3 py-1 text-sm text-red-800">
          {notice}
        </p>
      )}
      <div ref={container} className="flex min-h-0 flex-1">
        <div className="min-w-0 overflow-y-auto bg-white" style={{ width: `${leftShare}%` }} data-testid="data-pane">
          <SectionList
            review={review}
            focused={focused}
            mode={mode}
            saves={saves}
            readOnly={readOnly}
            documentName={(id) => documentName(review, id)}
            onFocus={(path) => path !== focused && focus(path)}
            onMode={(path, next) => {
              if (path !== focused) focus(path, next);
              else setMode(next);
            }}
            onDecide={(field, decision) => void decide(field, decision, false)}
            onShowEvidence={(path, evidence) => {
              // The chip's field takes the focus, so its evidence stays marked.
              if (path !== focused) {
                setFocused(path);
                setMode("view");
              }
              show(evidence);
            }}
          />
        </div>
        <div
          role="separator"
          aria-orientation="vertical"
          data-testid="divider"
          className="w-1.5 shrink-0 cursor-col-resize bg-slate-300 hover:bg-sky-400"
          onPointerDown={drag}
        />
        <div className="min-w-0 flex-1">
          {documentId && (
            <PdfPane
              api={api}
              versions={review.versions}
              documentId={documentId}
              onDocument={setDocumentId}
              highlights={highlights}
              target={target}
            />
          )}
        </div>
      </div>
      {confirming && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40" role="dialog" aria-modal="true">
          <div className="w-96 rounded bg-white p-4 shadow-lg">
            <h2 className="text-base font-semibold">Complete this review?</h2>
            <p className="mt-2 text-sm text-slate-700">
              {review.decided} of {review.total} fields are decided
              {review.fields.some((field) => field.flagged)
                ? `, ${review.fields.filter((field) => field.flagged).length} flagged`
                : ""}
              . After completing, the review can be read but no longer changed.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="rounded border border-slate-300 px-3 py-1 text-sm" onClick={() => setConfirming(false)}>
                Keep reviewing
              </button>
              <button type="button" data-testid="confirm-complete" className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white" onClick={() => void complete()}>
                Complete review
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
