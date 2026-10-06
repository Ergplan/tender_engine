import { useCallback, useEffect, useState } from "react";

import { api, ApiError, type Reliability } from "../api/client";

const TOKEN_KEY = "admin_token";

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

/** Green at 90% and above, amber from 75%, red below: the bands of the stability bar. */
export function band(value: number | null | undefined): string {
  if (value === null || value === undefined) return "bg-slate-100 text-slate-500";
  if (value >= 0.9) return "bg-green-100 text-green-900";
  if (value >= 0.75) return "bg-amber-100 text-amber-900";
  return "bg-red-100 text-red-900";
}

function readToken(): string {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

/** /admin/reliability: accuracy per tender type and field, the reviewed tenders, the
 * stability bar and the prompt versions tried. Behind the admin token; no login in phase 1. */
export function ReliabilityPage() {
  const [token, setToken] = useState(readToken);
  const [draft, setDraft] = useState("");
  const [data, setData] = useState<Reliability | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (adminToken: string) => {
    setError(null);
    try {
      setData(await api.reliability(adminToken));
      try {
        window.sessionStorage.setItem(TOKEN_KEY, adminToken);
      } catch {
        /* storage may be unavailable; the page still works for this visit */
      }
    } catch (caught: unknown) {
      setData(null);
      setError(caught instanceof ApiError ? caught.message : "The API is not reachable.");
    }
  }, []);

  useEffect(() => {
    if (token) void load(token);
  }, [token, load]);

  if (!token || (error && !data)) {
    return (
      <main className="mx-auto max-w-xl p-10 font-sans text-slate-900">
        <h1 className="text-xl font-semibold">Reliability dashboard</h1>
        <p className="mt-2 text-sm text-slate-600">This page needs the admin token.</p>
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <form
          className="mt-4 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setToken(draft.trim());
          }}
        >
          <input
            data-testid="admin-token"
            type="password"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="flex-1 rounded border border-slate-400 bg-white px-2 py-1 text-sm text-slate-900"
            placeholder="admin token"
          />
          <button type="submit" className="rounded border border-slate-700 bg-slate-800 px-3 py-1 text-sm text-white">
            Open
          </button>
        </form>
      </main>
    );
  }
  if (!data) return <main className="p-10 font-sans text-slate-600">Loading…</main>;

  const types = Object.keys(data.summary.by_type_field);
  const fields = Array.from(
    new Set(types.flatMap((type) => Object.keys(data.summary.by_type_field[type] ?? {}))),
  ).sort();
  const bar = data.stability;
  return (
    <main className="mx-auto max-w-6xl p-6 font-sans text-sm text-slate-900">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">Reliability dashboard</h1>
        <span className="text-xs text-slate-500">
          {data.gold_records} gold record(s) · generated {data.generated_at.replace("T", " ").slice(0, 16)} UTC
        </span>
      </header>

      <section data-testid="stability" className={"mt-4 rounded border px-3 py-2 " + (bar.met ? "border-green-300 bg-green-50" : "border-amber-300 bg-amber-50")}>
        <p className="font-semibold">Stability bar for Stage 5: {bar.met ? "met" : "not met"}</p>
        <ul className="mt-1 list-disc pl-5 text-xs text-slate-700">
          {bar.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <p className="mt-1 text-xs text-slate-700">
          Value accuracy {pct(data.summary.value_accuracy)} on {data.summary.scored} fields; evidence accuracy{" "}
          {pct(data.summary.evidence_accuracy)} on {data.summary.evidence_scored}; required-field accuracy{" "}
          {pct(bar.required_accuracy)}.
        </p>
      </section>

      <h2 className="mt-6 font-semibold">Accuracy by tender type and field</h2>
      {fields.length === 0 ? (
        <p className="mt-1 text-slate-600">No gold record yet: complete a review, then run make gold.</p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table data-testid="accuracy-table" className="min-w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="border-b px-2 py-1 text-left">Field</th>
                {types.map((type) => (
                  <th key={type} className="border-b px-2 py-1 text-left">
                    {type}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fields.map((path) => (
                <tr key={path}>
                  <td className="border-b px-2 py-1 font-mono">{path}</td>
                  {types.map((type) => {
                    const cell = data.summary.by_type_field[type]?.[path] as
                      | { accuracy: number | null; n: number }
                      | undefined;
                    return (
                      <td key={type} className={"border-b px-2 py-1 " + (cell ? band(cell.accuracy) : "")} title={cell ? `${cell.n} reviewed` : ""}>
                        {cell ? `${pct(cell.accuracy)} (${cell.n})` : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mt-6 font-semibold">Reviewed tenders</h2>
      <table data-testid="tender-table" className="mt-2 min-w-full border-collapse text-xs">
        <thead>
          <tr>
            {["Tender", "Type", "Reviewer", "Completed", "Sittings", "Minutes deciding", "Edited", "Not in document", "Notable misses"].map((h) => (
              <th key={h} className="border-b px-2 py-1 text-left">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.tenders.map((t) => (
            <tr key={t.slug}>
              <td className="border-b px-2 py-1">{t.slug}</td>
              <td className="border-b px-2 py-1">{t.tender_type}</td>
              <td className="border-b px-2 py-1">{t.reviewer}</td>
              <td className="border-b px-2 py-1">{t.completed_at.replace("T", " ").slice(0, 16)}</td>
              <td className="border-b px-2 py-1">{t.time?.sittings ?? "–"}</td>
              <td className="border-b px-2 py-1">{t.time?.deciding_minutes ?? "–"}</td>
              <td className="border-b px-2 py-1">{t.edited}</td>
              <td className="border-b px-2 py-1">{t.not_in_document}</td>
              <td className="border-b px-2 py-1">{t.notable_misses.join(", ") || "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="mt-6 font-semibold">Prompt versions tried</h2>
      {data.prompt_comparison.length < 2 ? (
        <p className="mt-1 text-slate-600">A comparison appears once more than one prompt version has been scored.</p>
      ) : (
        <table data-testid="prompt-table" className="mt-2 min-w-full border-collapse text-xs">
          <thead>
            <tr>
              {["Result", "Prompt", "Value accuracy", "Evidence accuracy", "n"].map((h) => (
                <th key={h} className="border-b px-2 py-1 text-left">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.prompt_comparison.map((c) => (
              <tr key={String(c.file)}>
                <td className="border-b px-2 py-1">{String(c.file)}</td>
                <td className="border-b px-2 py-1">{String(c.prompt ?? "as pinned")}</td>
                <td className="border-b px-2 py-1">{pct(c.value_accuracy as number | null)}</td>
                <td className="border-b px-2 py-1">{pct(c.evidence_accuracy as number | null)}</td>
                <td className="border-b px-2 py-1">{String(c.scored ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
