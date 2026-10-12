import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type AmendmentChange,
  type AmendmentVersion,
  ApiError,
  type Evidence,
  type ReviewApi,
  type ReviewSession,
  type TenderAmendments,
  type TenderReview,
} from "../api/client";
import { formatDate } from "../lib/format";
import { AmendmentCard } from "./AmendmentCard";
import type { CardMode, Decision, SaveState } from "./FieldCard";
import { documentName, firstEvidence, type PdfTarget } from "./model";
import { type Highlight, PdfPane } from "./PdfPane";

function keyOf(change: AmendmentChange): string {
  return `${change.entry.version_no}:${change.field_path}`;
}

function countLine(version: AmendmentVersion): string {
  const parts = [];
  if (version.changed) parts.push(`${version.changed} changed`);
  if (version.added) parts.push(`${version.added} added`);
  if (version.restated) parts.push(`${version.restated} restated`);
  const what = parts.length ? parts.join(", ") : "no field stated";
  return `${what} · ${version.undecided === 0 ? "all decided" : `${version.undecided} to decide`}`;
}

/** The amendments side by side with the document: per later version, each field it
 * states against what stood before, with that version's evidence and the decision on
 * its reading. Decisions are the same decisions as on the review screen. */
export function AmendmentsPage({
  api,
  session,
  review,
  reviewHref,
}: {
  api: ReviewApi;
  session: ReviewSession;
  review: TenderReview;
  reviewHref: string;
}) {
  const [data, setData] = useState<TenderAmendments | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [mode, setMode] = useState<CardMode>("view");
  const [saves, setSaves] = useState<Record<string, SaveState>>({});
  const [target, setTarget] = useState<PdfTarget | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState(
    () =>
      review.versions.find((version) => version.version_no > 1)?.documents[0]?.document_id ??
      review.versions[0]?.documents[0]?.document_id ??
      "",
  );
  const targetKey = useRef(0);
  const readOnly = session.completed_at !== null && session.completed_at !== undefined;

  const load = useCallback(async () => {
    const fresh = await api.amendments(review.tender_id);
    setData(fresh);
    return fresh;
  }, [api, review.tender_id]);
  useEffect(() => {
    load().catch(() => setFailure("The amendments could not be loaded. Reload the page."));
  }, [load]);

  const changes = useMemo(
    () => new Map((data?.versions ?? []).flatMap((version) => version.changes.map((change) => [keyOf(change), change]))),
    [data],
  );

  const show = useCallback((evidence: Evidence) => {
    setActiveEvidence(evidence.id);
    targetKey.current += 1;
    setTarget({ documentId: evidence.document_id, pageNo: evidence.page_no, bbox: evidence.bbox ?? null, key: targetKey.current });
  }, []);

  const focus = useCallback(
    (key: string | null, nextMode: CardMode = "view") => {
      setFocused(key);
      setMode(nextMode);
      const change = key ? changes.get(key) : undefined;
      const evidence = change ? firstEvidence(change.entry) : null;
      if (evidence) show(evidence);
      else setActiveEvidence(null);
    },
    [changes, show],
  );

  const decide = useCallback(
    async (change: AmendmentChange, decision: Decision) => {
      const candidate = change.entry.state.candidate;
      if (!candidate || readOnly) return;
      const key = keyOf(change);
      setSaves((before) => ({ ...before, [key]: { kind: "saving" } }));
      try {
        await api.decide({
          candidate_id: candidate.id,
          decision: decision.decision,
          previous_approval_id: change.entry.state.approval?.id ?? null,
          final_value: decision.decision === "edited" ? decision.value : null,
          note: "note" in decision ? decision.note : null,
          evidence: decision.decision === "edited" ? decision.evidence : null,
        });
        await load();
        setSaves((before) => ({ ...before, [key]: { kind: "saved" } }));
        setMode("view");
      } catch (error) {
        const stale = error instanceof ApiError && error.status === 409;
        const message =
          error instanceof ApiError
            ? stale
              ? "Changed since it was loaded. Reloaded; decide again."
              : (error.detail ?? error.message)
            : "Not saved. Check the connection and retry.";
        setSaves((before) => ({ ...before, [key]: { kind: "failed", message } }));
        if (stale) await load().catch(() => undefined);
      }
    },
    [api, load, readOnly],
  );

  const highlights = useMemo<Highlight[]>(() => {
    const change = focused ? changes.get(focused) : undefined;
    return (change?.entry.state.candidate?.evidence ?? [])
      .filter((evidence) => evidence.document_id === documentId)
      .map((evidence) => ({ pageNo: evidence.page_no, bbox: evidence.bbox ?? null, active: evidence.id === activeEvidence }));
  }, [activeEvidence, changes, documentId, focused]);

  const total = data?.versions.reduce((sum, version) => sum + version.changes.length, 0) ?? 0;
  const undecided = data?.versions.reduce((sum, version) => sum + version.undecided, 0) ?? 0;

  return (
    <div className="flex h-full flex-col font-sans text-slate-900">
      <header className="flex items-center gap-4 border-b border-slate-300 bg-white px-3 py-1.5">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold" title={review.title} data-testid="tender-title">
            Amendments · {review.title}
          </h1>
          <p className="truncate text-xs text-slate-600">
            <span className="uppercase">{review.tender_type}</span> · {review.issuing_agency} · Reviewer:{" "}
            <span data-testid="reviewer-name">{session.reviewer_name}</span>
          </p>
        </div>
        {data && (
          <span className="shrink-0 text-right text-sm tabular-nums text-slate-700" data-testid="amendments-progress">
            {total} {total === 1 ? "field" : "fields"} stated by later versions
            <span className="block text-xs text-slate-500">
              {undecided === 0 ? "none left to decide" : `${undecided} to decide`} · {data.untouched} untouched
            </span>
          </span>
        )}
        {readOnly && (
          <span className="shrink-0 rounded bg-green-100 px-2 py-1 text-xs font-medium text-green-800">Completed · read-only</span>
        )}
        <a href={reviewHref} data-testid="back-to-review" className="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Back to the review
        </a>
      </header>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 overflow-y-auto bg-white" style={{ width: "50%" }} data-testid="amendments-pane">
          {failure && (
            <p role="alert" className="border-b border-red-200 bg-red-50 px-3 py-1 text-sm text-red-800">
              {failure}
            </p>
          )}
          {!data && !failure && <p className="p-4 text-sm text-slate-600">Loading…</p>}
          {data && data.versions.length === 0 && (
            <p data-testid="no-amendments" className="p-4 text-sm text-slate-600">
              This tender has only its original version. There is nothing to compare.
            </p>
          )}
          {data?.versions.map((version) => (
            <section key={version.version_no} data-testid="amendment-version" data-version={version.version_no}>
              <div className="sticky top-0 z-10 border-y border-slate-200 bg-slate-100 px-3 py-1.5 text-sm">
                <p className="font-semibold text-slate-800">
                  v{version.version_no} {version.kind}
                  {version.issued_on ? ` · issued ${formatDate(version.issued_on)}` : ""}
                  <span className="ml-2 text-xs font-normal text-slate-600" data-testid="version-count">
                    {countLine(version)}
                  </span>
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-1 text-xs text-slate-600">
                  {version.documents.map((document) => (
                    <button
                      key={document.document_id}
                      type="button"
                      data-testid="version-document"
                      className={
                        "rounded border px-1.5 py-0.5 " +
                        (document.document_id === documentId ? "border-sky-600 bg-sky-50 text-sky-900" : "border-slate-300 bg-white hover:bg-slate-50")
                      }
                      title="Show this document"
                      onClick={() => setDocumentId(document.document_id)}
                    >
                      {document.filename}
                      {document.page_count ? ` · ${document.page_count} pp` : ""}
                    </button>
                  ))}
                  {version.sections_read.length > 0 && (
                    <span className="ml-1" data-testid="sections-read">
                      Read for: {version.sections_read.map((name) => name.replace(/_/g, " ")).join(", ")}
                    </span>
                  )}
                </p>
                {version.summary_of_change && (
                  <p className="mt-0.5 text-xs text-slate-700" data-testid="summary-of-change">
                    {version.summary_of_change}
                  </p>
                )}
              </div>
              {version.changes.length === 0 && (
                <p className="px-3 py-2 text-sm text-slate-600">
                  This version states no field the schema holds; what it changes, if anything, is for the reviewer to read.
                </p>
              )}
              <div className="divide-y divide-slate-100">
                {version.changes.map((change) => {
                  const key = keyOf(change);
                  return (
                    <AmendmentCard
                      key={key}
                      change={change}
                      focused={focused === key}
                      mode={focused === key ? mode : "view"}
                      save={saves[key]}
                      readOnly={readOnly}
                      documentName={(id) => documentName(review, id)}
                      activeEvidence={activeEvidence}
                      onFocus={() => key !== focused && focus(key)}
                      onMode={(next) => {
                        if (key !== focused) focus(key, next);
                        else setMode(next);
                      }}
                      onDecide={(decision) => void decide(change, decision)}
                      onShowEvidence={(evidence) => {
                        if (key !== focused) {
                          setFocused(key);
                          setMode("view");
                        }
                        show(evidence);
                      }}
                    />
                  );
                })}
              </div>
            </section>
          ))}
        </div>
        <div className="w-1.5 shrink-0 bg-slate-300" />
        <div className="min-w-0 flex-1">
          {documentId && (
            <PdfPane api={api} versions={review.versions} documentId={documentId} onDocument={setDocumentId} highlights={highlights} target={target} />
          )}
        </div>
      </div>
    </div>
  );
}
