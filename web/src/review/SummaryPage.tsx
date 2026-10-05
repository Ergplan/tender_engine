import { useEffect, useState } from "react";

import { ApiError, type ReviewApi, type Snapshot } from "../api/client";
import { formatDate, formatValue } from "../lib/format";
import { MessagePage } from "./MessagePage";

type ViewField = {
  field_path: string;
  label: string;
  section: string;
  value_type: string;
  unit: string | null;
  decided: boolean;
  value: unknown;
  version_no: number | null;
  version_kind: string | null;
  evidence: { page_no?: number; kind?: string }[];
};

function download(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** The read-only view of a completed review, with the final values to download. */
export function SummaryPage({ api, tenderId, reviewHref }: {
  api: ReviewApi;
  tenderId: string;
  reviewHref: string;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => {
    api
      .snapshot(tenderId)
      .then(setSnapshot)
      .catch((error: unknown) =>
        setFailure(
          error instanceof ApiError && error.status === 404
            ? "This review has not been completed yet."
            : "The summary could not be loaded. Reload the page.",
        ),
      );
  }, [api, tenderId]);
  if (failure) return <MessagePage title="Review summary" message={failure} />;
  if (!snapshot) return <p className="p-8 text-slate-600">Loading…</p>;
  const data = snapshot.snapshot as {
    title: string;
    issuing_agency: string;
    tender_type: string;
    reviewer: string;
    completed_at: string;
    decided: number;
    total: number;
    flagged: string[];
    view: { fields: ViewField[] };
  };
  const sections: string[] = [];
  for (const field of data.view.fields) if (!sections.includes(field.section)) sections.push(field.section);
  return (
    <main className="mx-auto max-w-4xl p-6 font-sans text-slate-900" data-testid="summary">
      <p className="text-sm font-medium text-green-700">Review completed</p>
      <h1 className="mt-1 text-xl font-semibold">{data.title}</h1>
      <p className="mt-1 text-sm text-slate-600">
        {data.issuing_agency} · {data.tender_type} · reviewed by {data.reviewer} on{" "}
        {formatDate(data.completed_at.slice(0, 10))} · {data.decided} of {data.total} fields decided
      </p>
      <div className="mt-3 flex gap-3">
        <button
          type="button"
          data-testid="download-json"
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
          onClick={() => download(`review-${tenderId}.json`, snapshot.snapshot)}
        >
          Download JSON
        </button>
        <a href={reviewHref} className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          Open the review (read-only)
        </a>
      </div>
      {sections.map((section) => (
        <section key={section} className="mt-5">
          <h2 className="border-b border-slate-300 pb-1 text-sm font-semibold capitalize">
            {section.replace(/_/g, " ")}
          </h2>
          <table className="mt-1 w-full text-sm">
            <tbody>
              {data.view.fields
                .filter((field) => field.section === section)
                .map((field) => (
                  <tr key={field.field_path} className="border-b border-slate-100 align-top" data-testid="summary-row" data-field={field.field_path}>
                    <td className="w-1/3 py-1 pr-3 text-slate-600">{field.label}</td>
                    <td className="py-1">
                      {!field.decided ? (
                        <span className="italic text-slate-400">not decided</span>
                      ) : field.value === null ? (
                        <span className="italic text-slate-500">not in document</span>
                      ) : (
                        formatValue(field.value, field.value_type, field.unit)
                      )}
                    </td>
                    <td className="w-28 py-1 text-right text-xs text-slate-500">
                      {field.version_no && field.version_no > 1 ? `v${field.version_no} ${field.version_kind} · ` : ""}
                      {[...new Set(field.evidence.filter((e) => e.page_no).map((e) => `p. ${e.page_no}`))].slice(0, 3).join(", ")}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      ))}
    </main>
  );
}
