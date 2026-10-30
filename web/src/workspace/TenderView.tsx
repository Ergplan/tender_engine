import { useCallback, useEffect, useState } from "react";

import { ApiError, type FieldsSnapshot, type TenderStatus, type WorkspaceApi } from "../api/client";
import { paragraphs, stripMarkers } from "../lib/format";
import { Ledger, SourceMark } from "./Ledger";
import { type PageRef, PageDrawer } from "./PageDrawer";
import { AmendmentsPanel, AskPanel, ReviewPanel } from "./Panels";
import { DEADLINE_PATH, daysUntil, display, headline, STAGES, stageIndex, SUMMARY_PATH, TENDER_TYPES } from "./terms";

function typeLabel(type: string): string {
  return TENDER_TYPES.find((t) => t.value === type)?.label ?? type;
}

type Tab = "requirements" | "amendments" | "ask" | "review";
const TABS: { value: Tab; label: string }[] = [
  { value: "requirements", label: "What it requires" },
  { value: "amendments", label: "Amendments" },
  { value: "ask", label: "Ask the tender" },
  { value: "review", label: "Send for review" },
];
const POLL_MS = 5000;

/** Where the reading of the newest version stands, as the steps it goes through. */
function Progress({ status }: { status: TenderStatus }) {
  const latest = status.versions[status.versions.length - 1];
  if (!latest) return null;
  if (latest.stage === "failed") {
    const failure = latest.documents.find((d) => d.error)?.error ?? latest.runs.find((r) => r.error)?.error;
    return (
      <p role="alert" className="mt-5 rounded-md border border-[#f3c4cf] bg-[#fdf2f4] px-4 py-3 text-sm text-[#9f1239]">
        The engine could not read {latest.kind === "original" ? "this tender" : `${latest.kind} ${latest.version_no}`}
        {failure ? `: ${failure}` : "."}
      </p>
    );
  }
  if (latest.stage === "validated") return null;
  const at = stageIndex(latest.stage);
  return (
    <div className="mt-5 rounded-lg border border-[#dde4e2] bg-[#f7f9f8] px-4 py-3" aria-live="polite">
      <p className="text-sm font-medium">
        Reading {latest.kind === "original" ? "the tender" : `${latest.kind} ${latest.version_no}`}
        <span className="font-normal text-[#5b6b70]">: large tenders take 10 to 40 minutes. This page updates itself.</span>
      </p>
      <ol className="mt-3 grid grid-cols-5 gap-1" aria-label="Reading steps">
        {STAGES.map((step, i) => (
          <li key={step.stage} aria-current={i === at ? "step" : undefined}>
            <div className={`h-1.5 rounded-full ${i < at ? "bg-[#0f5f5c]" : i === at ? "animate-pulse bg-[#0f5f5c]/60" : "bg-[#dde4e2]"}`} />
            <p className={`mt-1.5 text-xs ${i <= at ? "text-[#1b2a2f]" : "text-[#8a9a9e]"}`}>{step.label}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function TenderView({ api, tenderId, onChanged }: { api: WorkspaceApi; tenderId: string; onChanged: () => void }) {
  const [snapshot, setSnapshot] = useState<FieldsSnapshot | null>(null);
  const [status, setStatus] = useState<TenderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("requirements");
  const [page, setPage] = useState<PageRef | null>(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(async () => {
    const [s, f] = await Promise.all([api.status(tenderId), api.fields(tenderId)]);
    setStatus(s);
    setSnapshot(f);
    setError(null);
    return s;
  }, [api, tenderId]);

  useEffect(() => {
    setSnapshot(null);
    setStatus(null);
    setTab("requirements");
    setPage(null);
  }, [tenderId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const run = async () => {
      try {
        const s = await load();
        if (cancelled) return;
        const busy = s.versions.some((v) => v.stage !== "validated" && v.stage !== "failed");
        if (busy) timer = window.setTimeout(run, POLL_MS);
        else onChanged();
      } catch (caught) {
        if (!cancelled) setError(caught instanceof ApiError ? caught.message : "The tender could not be loaded.");
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
    // onChanged is a refresh of the list; the poll restarts only for a new tender or version.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, tick]);

  if (error)
    return (
      <p role="alert" className="p-8 text-sm text-[#9f1239]">
        {error}
      </p>
    );
  if (!snapshot || !status) return <p className="p-8 text-sm text-[#5b6b70]">Opening the tender…</p>;

  const summary = snapshot.fields.find((f) => f.path === SUMMARY_PATH);
  const terms = headline(snapshot.fields);
  const deadline = snapshot.fields.find((f) => f.path === DEADLINE_PATH);
  const days = deadline?.state === "value" ? daysUntil(deadline.value) : null;
  const stated = snapshot.fields.filter((f) => f.state !== "not_stated").length;

  return (
    <div className="mx-auto max-w-[1100px] px-6 pb-24 pt-8 lg:px-10">
      <header>
        <p className="text-sm text-[#5b6b70]">
          {snapshot.issuing_agency}
          {snapshot.external_ref ? `, ${snapshot.external_ref}` : ""}
        </p>
        <h1 className="mt-1 max-w-[62ch] text-2xl font-semibold leading-snug text-[#1b2a2f]">{snapshot.title}</h1>
        <p className="mt-2 text-sm text-[#5b6b70]">
          {typeLabel(snapshot.tender_type)}
          {" "}tender, {status.versions.length} {status.versions.length === 1 ? "version" : "versions"}. {stated} terms read,{" "}
          {snapshot.approved} approved by a reviewer.
          {status.type_state !== "set" && (
            <span className="ml-1 text-[#b45309]">The type was detected with low confidence; a reviewer should confirm it.</span>
          )}
        </p>
        <Progress status={status} />
      </header>

      {terms.length > 0 && (
        <dl className="mt-7 grid grid-cols-2 border-y border-[#1b2a2f] sm:grid-cols-4">
          {terms.map(({ label, field }) => (
            <div key={label} className="px-1 py-3">
              <dt className="text-xs text-[#5b6b70]">{label}</dt>
              <dd className="mt-0.5">
                <button
                  type="button"
                  disabled={!field.evidence[0]}
                  onClick={() => {
                    const e = field.evidence[0];
                    if (e) setPage({ documentId: e.document_id, filename: e.filename, pageNo: e.page_no, quote: e.quote, label });
                  }}
                  className={`text-left text-lg font-semibold tabular-nums leading-tight ${
                    field.state === "withdrawn" ? "text-[#9f1239]" : "text-[#1b2a2f]"
                  } enabled:hover:text-[#0f5f5c]`}
                >
                  {display(field)}
                </button>
                {field.path === DEADLINE_PATH && days !== null && (
                  <span className={`block text-xs ${days < 0 ? "text-[#8a9a9e]" : days <= 14 ? "text-[#b45309]" : "text-[#5b6b70]"}`}>
                    {days < 0 ? "closed" : days === 0 ? "today" : `${days} days left`}
                  </span>
                )}
                {field.path !== DEADLINE_PATH && field.source === "machine" && (field.confidence ?? 1) < 0.8 && (
                  <span className="block text-xs text-[#b45309]">check this</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {summary && summary.state === "value" && typeof summary.value === "string" && (
        <section aria-label="In brief" className="mt-7 max-w-[70ch]">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">In brief</h2>
            <SourceMark field={summary} />
          </div>
          {paragraphs(stripMarkers(summary.value)).map((p, i) => (
            <p key={i} className="mt-2 text-[15px] leading-7 text-[#2c3a3e]">
              {p.heading && <span className="font-semibold">{p.heading}: </span>}
              {p.pieces.map((piece) => ("text" in piece ? piece.text : "")).join("")}
            </p>
          ))}
        </section>
      )}

      <nav aria-label="Tender views" className="mt-9 flex gap-6 overflow-x-auto border-b border-[#dde4e2]">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            aria-current={tab === t.value ? "page" : undefined}
            onClick={() => setTab(t.value)}
            className={`-mb-px whitespace-nowrap border-b-2 pb-2.5 text-sm ${
              tab === t.value ? "border-[#0f5f5c] font-semibold text-[#1b2a2f]" : "border-transparent text-[#5b6b70] hover:text-[#1b2a2f]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="mt-2">
        {tab === "requirements" &&
          (stated === 0 ? (
            <p className="py-10 text-center text-sm text-[#5b6b70]">
              No terms yet. They appear here as the engine reads each section.
            </p>
          ) : (
            <Ledger fields={snapshot.fields} onOpen={setPage} />
          ))}
        {tab === "amendments" && (
          <div className="pt-6">
            <AmendmentsPanel
              api={api}
              tenderId={tenderId}
              onOpen={setPage}
              refreshKey={tick}
              onSubmitted={() => {
                setTick((n) => n + 1);
                onChanged();
              }}
            />
          </div>
        )}
        {tab === "ask" && (
          <div className="pt-6">
            <AskPanel api={api} tenderId={tenderId} onOpen={setPage} />
          </div>
        )}
        {tab === "review" && (
          <div className="pt-6">
            <ReviewPanel api={api} tenderId={tenderId} />
          </div>
        )}
      </div>
      {page && <PageDrawer api={api} page={page} onClose={() => setPage(null)} />}
    </div>
  );
}
