import { useEffect, useState } from "react";

import { ApiError, appApi } from "../api/client";
import type { PublishedEvidence, PublishedField, PublishedTender, TenderChanges } from "../api/types5c";
import { showDate, showValue, STATE_CLASS, STATE_LABEL } from "./format";

function Chips({ evidence }: { evidence: PublishedEvidence[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (evidence.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {evidence.map((e, i) => (
        <button
          key={`${e.document_id}-${e.page_no}-${i}`}
          type="button"
          aria-expanded={open === i}
          className="min-h-[28px] rounded-full bg-[#eef3f2] px-2 font-mono text-xs text-[#0f5f5c]"
          onClick={() => setOpen(open === i ? null : i)}
        >
          {e.filename ?? "document"} p.{e.page_no}
        </button>
      ))}
      {open !== null && (
        <q className="block w-full text-xs text-slate-600">{evidence[open].quote}</q>
      )}
    </span>
  );
}

function FieldRow({ field }: { field: PublishedField }) {
  const gap = field.status === "not_reviewed";
  return (
    <tr data-testid="published-field">
      <td className="border-b border-[#e6e4dd] px-3 py-2 align-top">{field.label}</td>
      <td className="border-b border-[#e6e4dd] px-3 py-2 align-top">
        {gap ? (
          <span className="inline-block rounded-md bg-[#efeeea] px-2 py-0.5 text-xs text-slate-600" data-testid="gap">
            not reviewed — {field.gap?.reason ?? "no reviewed value"}
            {field.gap?.likely_page ? ` · likely page ${field.gap.likely_page}` : ""}
          </span>
        ) : field.withdrawn ? (
          <>
            <span className="line-through text-slate-500">{showValue(field.value, field.unit) || "value"}</span>{" "}
            <span className="inline-block rounded-full bg-[#fdecec] px-2 py-0.5 text-xs font-medium text-[#991b1b]">
              withdrawn
              {field.version_no ? ` by v${field.version_no}` : ""}
              {field.withdrawn_from_version ? ` (stood since v${field.withdrawn_from_version})` : ""}
            </span>
          </>
        ) : (
          <span className="font-medium">{showValue(field.value, field.unit)}</span>
        )}
        {field.status === "possibly_superseded" && (
          <span className="ml-2 text-xs text-[#8a4a0b]">possibly superseded by the unreviewed version</span>
        )}
      </td>
      <td className="border-b border-[#e6e4dd] px-3 py-2 align-top text-slate-600">
        {field.version_no ? `v${field.version_no}` : "—"}
        {field.set_by ? ` · ${field.set_by}` : ""}
      </td>
      <td className="border-b border-[#e6e4dd] px-3 py-2 align-top">
        <Chips evidence={field.evidence} />
      </td>
    </tr>
  );
}

function ChangesView({ changes }: { changes: TenderChanges }) {
  return (
    <section className="flex flex-col gap-4">
      {changes.versions.map((version) => (
        <article key={version.version_no} className="rounded-lg border border-[#e6e4dd] bg-white p-4" data-testid="changes-version">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">
              v{version.version_no} · {version.kind}
              {version.issued_on ? ` · ${showDate(version.issued_on)}` : ""}
            </h3>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                version.reviewed ? "bg-[#e7f2ef] text-[#0f5f5c]" : "bg-[#fdf1e3] text-[#8a4a0b]"
              }`}
            >
              {version.reviewed ? "reviewed" : "not yet reviewed"}
            </span>
          </div>
          {version.changes.length === 0 && version.pending.length === 0 && (
            <p className="mt-2 text-sm text-slate-600">No reviewed change.</p>
          )}
          <ul className="mt-2 flex flex-col gap-2 text-sm">
            {version.changes.map((change) => (
              <li key={change.field_path} className="rounded-md border border-[#e6e4dd] p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{change.label}</span>
                  {change.withdrawn && (
                    <span className="rounded-full bg-[#fdecec] px-2 py-0.5 text-xs font-medium text-[#991b1b]">removed</span>
                  )}
                </div>
                <div>
                  <span className="text-slate-500">{showValue(change.before) || "not stated"}</span> →{" "}
                  <span className="font-medium">{change.withdrawn ? "withdrawn" : showValue(change.after) || "not stated"}</span>
                </div>
                <Chips evidence={change.evidence} />
              </li>
            ))}
          </ul>
          {version.pending.length > 0 && (
            <p className="mt-2 text-xs text-slate-600">
              Read by the engine, awaiting review: {version.pending.map((p) => <code key={p}>{p} </code>)}
            </p>
          )}
        </article>
      ))}
    </section>
  );
}

/** /tenders/:id — the published view: canonical facts only, each with the version that set
 * it and its evidence; the publication state as a banner; the changelog as a tab. */
export function PublishedPage({ tenderId, tab = "facts" }: { tenderId: string; tab?: "facts" | "changes" }) {
  const [view, setView] = useState<PublishedTender | null>(null);
  const [changes, setChanges] = useState<TenderChanges | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<"facts" | "changes">(tab);

  useEffect(() => {
    let cancelled = false;
    appApi
      .published(tenderId)
      .then((v) => {
        if (!cancelled) setView(v);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught.message : "The API is not reachable.");
      });
    return () => {
      cancelled = true;
    };
  }, [tenderId]);

  useEffect(() => {
    if (shown !== "changes" || changes) return;
    let cancelled = false;
    appApi
      .changes(tenderId)
      .then((c) => {
        if (!cancelled) setChanges(c);
      })
      .catch(() => {
        if (!cancelled) setChanges({ tender_id: tenderId, title: "", reviewed_version: null, versions: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [shown, changes, tenderId]);

  if (error)
    return (
      <main className="p-8">
        <p role="alert" className="text-sm text-[#991b1b]">
          {error}
        </p>
      </main>
    );
  if (!view) return <p className="p-8 text-slate-600">Loading the tender…</p>;

  const { publication, suspension } = view;
  const state = publication.state;
  return (
    <main className="mx-auto flex w-full max-w-[1216px] flex-col gap-4 px-8 py-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <a href="/tenders" className="font-semibold text-slate-900 no-underline">
          ← Tenders
        </a>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATE_CLASS[state]}`}>{STATE_LABEL[state]}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <a
            href={`/api/v1/tenders/${view.tender_id}/published.pdf`}
            className="inline-flex min-h-[44px] items-center rounded-md border border-[#cfccc3] bg-white px-3 text-sm text-slate-900 no-underline"
          >
            Export PDF with page appendix
          </a>
          <button
            type="button"
            aria-pressed={shown === "facts"}
            className={`min-h-[44px] rounded-md border px-3 text-sm ${shown === "facts" ? "border-[#0f5f5c] bg-[#eef3f2] text-[#0f5f5c]" : "border-[#cfccc3] bg-white"}`}
            onClick={() => setShown("facts")}
          >
            Facts
          </button>
          <button
            type="button"
            aria-pressed={shown === "changes"}
            className={`min-h-[44px] rounded-md border px-3 text-sm ${shown === "changes" ? "border-[#0f5f5c] bg-[#eef3f2] text-[#0f5f5c]" : "border-[#cfccc3] bg-white"}`}
            onClick={() => setShown("changes")}
          >
            Changes
          </button>
        </div>
      </div>

      {state === "update_pending" && (
        <div role="status" className="rounded-lg border border-[#f1d7b3] bg-[#fdf1e3] px-4 py-3 text-sm text-[#6b3a08]">
          <strong>Update pending.</strong>{" "}
          {view.banner ??
            `Version ${publication.unreviewed_version?.version_no ?? ""} exists and is not yet reviewed; fields it may touch are marked possibly superseded.`}
        </div>
      )}
      {state === "publication_suspended" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-[#fdecec] px-4 py-3 text-sm text-[#991b1b]">
          <strong>Publication suspended.</strong>{" "}
          {view.banner ??
            `An unreviewed ${suspension?.kind ?? publication.unreviewed_version?.kind ?? "amendment"} (version ${suspension?.version_no ?? publication.unreviewed_version?.version_no ?? ""}${suspension?.issued_on ? `, ${showDate(suspension.issued_on)}` : ""}) touches critical fields. No value is shown until it is reviewed.`}
          {(suspension?.fields ?? publication.suspended_by).length > 0 && (
            <div className="mt-1 text-xs">
              Fields: {(suspension?.fields ?? publication.suspended_by).map((p) => <code key={p}>{p} </code>)}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
          <div>
            <h1 className="text-2xl font-semibold">{view.title}</h1>
            <div className="text-sm text-slate-600">
              {view.issuing_agency} · {view.tender_type}
              {view.external_ref ? (
                <>
                  {" · "}
                  <span className="font-mono">{view.external_ref}</span>
                </>
              ) : null}
            </div>
          </div>
          {shown === "changes" ? (
            changes ? (
              <ChangesView changes={changes} />
            ) : (
              <p className="text-slate-600">Loading the changes…</p>
            )
          ) : state === "publication_suspended" ? (
            <p className="text-sm text-slate-600">The reviewed values are withheld while the amendment is unreviewed.</p>
          ) : (
            view.sections.map((section) => (
              <section key={section.name} className="overflow-x-auto rounded-lg border border-[#e6e4dd] bg-white">
                <h2 className="border-b border-[#e6e4dd] px-3 py-3 text-sm font-semibold">{section.label}</h2>
                <table className="w-full min-w-[560px] border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
                      <th className="border-b border-[#e6e4dd] px-3 py-2 font-medium">Field</th>
                      <th className="border-b border-[#e6e4dd] px-3 py-2 font-medium">Value</th>
                      <th className="border-b border-[#e6e4dd] px-3 py-2 font-medium">Set by</th>
                      <th className="border-b border-[#e6e4dd] px-3 py-2 font-medium">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {section.fields.map((field) => (
                      <FieldRow key={field.path} field={field} />
                    ))}
                  </tbody>
                </table>
              </section>
            ))
          )}
        </div>
        <aside className="flex min-w-0 flex-[1_1_300px] flex-col gap-3 text-sm">
          <div className="flex flex-col gap-2 rounded-lg border border-[#e6e4dd] bg-white p-4">
            <div className="font-semibold">Provenance</div>
            <div>
              <span className="text-slate-600">Reviewed</span> {view.reviewed_at ? showDate(view.reviewed_at) : "not yet"}
              {view.reviewer_role ? ` by an ${view.reviewer_role}` : ""}
            </div>
            <div>
              <span className="text-slate-600">Reviewed at</span>{" "}
              {view.reviewed_version ? `version ${view.reviewed_version}` : "—"}
              {view.current_version && view.current_version !== view.reviewed_version
                ? ` of ${view.current_version}`
                : ""}
            </div>
            {view.reliability && (
              <div>
                <span className="text-slate-600">Reliability</span> {view.reliability.tender_type} fields{" "}
                {view.reliability.value_accuracy === null ? "—" : `${Math.round(view.reliability.value_accuracy * 100)}%`} value
                {view.reliability.evidence_accuracy !== null
                  ? `, ${Math.round(view.reliability.evidence_accuracy * 100)}% evidence`
                  : ""}{" "}
                on {view.reliability.n_fields} field{view.reliability.n_fields === 1 ? "" : "s"}
                {view.reliability.as_of ? ` · as of ${showDate(view.reliability.as_of)}` : ""}
              </div>
            )}
          </div>
          <p className="text-xs text-slate-600">
            {view.authority_note} A value you believe wrong opens a correction case; it never changes a value by itself.
          </p>
        </aside>
      </div>
    </main>
  );
}
