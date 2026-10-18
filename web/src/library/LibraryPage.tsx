import { useEffect, useMemo, useState } from "react";

import { ApiError, appApi } from "../api/client";
import type { PublishedTender, TenderListItem } from "../api/types5c";
import { daysUntil, fieldOf, showDate, showValue, STATE_CLASS, STATE_LABEL } from "./format";

const DEADLINE = "core.key_dates.bid_submission_deadline";
const CAPACITY = "sector.power.common.total_capacity_mw";

type Row = { tender: TenderListItem; view: PublishedTender | null };

function Stat({ label, value, note, warn }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <div className="rounded-lg border border-[#e6e4dd] bg-white p-4">
      <div className="text-xs text-slate-600">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${warn ? "text-[#b45309]" : ""}`}>{value}</div>
      <div className="text-xs text-slate-600">{note}</div>
    </div>
  );
}

function reviewState(tender: TenderListItem, view: PublishedTender | null): string {
  if (view?.reviewed_at) return `Completed ${showDate(view.reviewed_at)}`;
  if (tender.status === "in_review") return "In review";
  return "Not reviewed";
}

/** /tenders: every tender of the tenant with its publication state, what the published
 * view says about it, and the way to the review or the view. */
export function LibraryPage({ filter = "" }: { filter?: string }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const tenders = await appApi.tenders();
      const views = await Promise.all(
        tenders.map((tender) => appApi.published(tender.id).catch(() => null)),
      );
      if (!cancelled) setRows(tenders.map((tender, i) => ({ tender, view: views[i] })));
    })().catch((caught: unknown) => {
      if (!cancelled) setError(caught instanceof ApiError ? caught.message : "The API is not reachable.");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const types = useMemo(() => Array.from(new Set((rows ?? []).map((r) => r.tender.tender_type))).sort(), [rows]);
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (rows ?? []).filter(({ tender, view }) => {
      if (type && tender.tender_type !== type) return false;
      if (filter === "review" && view?.reviewed_at) return false;
      if (!needle) return true;
      const hay = `${tender.title} ${tender.issuing_agency} ${tender.external_ref ?? ""} ${tender.slug ?? ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [rows, query, type, filter]);

  if (error) {
    return (
      <main className="p-8">
        <p role="alert" className="text-sm text-[#991b1b]">
          {error}
        </p>
      </main>
    );
  }
  if (!rows) return <p className="p-8 text-slate-600">Loading the tenders…</p>;

  const reviewed = rows.filter((r) => r.view?.reviewed_at).length;
  const pending = rows.filter((r) => r.view?.publication.state === "update_pending").length;
  const suspended = rows.filter((r) => r.view?.publication.state === "publication_suspended").length;
  const deadlines = rows
    .map((r) => {
      const field = fieldOf(r.view, DEADLINE);
      const days = daysUntil(typeof field?.value === "string" ? field.value : null);
      return days === null || days < 0 ? null : { days, title: r.tender.title, date: field?.value as string };
    })
    .filter((d): d is { days: number; title: string; date: string } => d !== null)
    .sort((a, b) => a.days - b.days);
  const next = deadlines[0];

  return (
    <main className="mx-auto flex w-full max-w-[1216px] flex-col gap-5 px-8 py-7">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Tenders</h1>
          <p className="text-sm text-slate-600">
            {rows.length} in the library · {reviewed} reviewed · {rows.length - reviewed} awaiting review
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-600">
            Search
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="FDRE IX, SECI BESS, 700 MW…"
              className="min-h-[44px] min-w-[240px] rounded-md border border-[#cfccc3] px-3 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-600">
            Type
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="min-h-[44px] rounded-md border border-[#cfccc3] bg-white px-3 text-sm"
            >
              <option value="">All types</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Reviews completed" value={`${reviewed} of ${rows.length}`} note="completed reviews in the library" />
        <Stat
          label="Next bid deadline"
          value={next ? `${next.days} d` : "—"}
          note={next ? `${next.title} · ${showDate(next.date)}` : "no open deadline among reviewed tenders"}
        />
        <Stat label="Update pending" value={String(pending)} note="a later version awaits review" warn={pending > 0} />
        <Stat label="Suspended" value={String(suspended)} note="an unreviewed amendment touches critical fields" warn={suspended > 0} />
      </div>

      <div className="overflow-x-auto rounded-lg border border-[#e6e4dd] bg-white">
        <table className="w-full min-w-[960px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-600">
              {["Tender", "Agency · type", "Capacity", "Bid deadline", "Version", "Publication", "Review", ""].map((h) => (
                <th key={h} className="border-b border-[#e6e4dd] px-3 py-3 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map(({ tender, view }) => {
              const state = view?.publication.state ?? "not_published";
              const deadline = fieldOf(view, DEADLINE);
              const capacity = fieldOf(view, CAPACITY);
              const days = daysUntil(typeof deadline?.value === "string" ? deadline.value : null);
              return (
                <tr key={tender.id} data-testid="tender-row">
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    <a href={`/tenders/${tender.id}`} className="font-medium text-[#0f5f5c] no-underline">
                      {tender.title}
                    </a>
                    <div className="font-mono text-xs text-slate-600">{tender.external_ref ?? tender.slug ?? ""}</div>
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    {tender.issuing_agency} · {tender.tender_type}
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    {capacity?.value != null ? showValue(capacity.value, capacity.unit ?? "MW") : "—"}
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    {deadline?.value ? (
                      <>
                        {showDate(String(deadline.value))}{" "}
                        <span className={days !== null && days < 0 ? "text-[#8a4a0b]" : "text-slate-600"}>
                          · {days === null ? "" : days < 0 ? "closed" : `${days} d`}
                        </span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    {tender.current_version_no ? `v${tender.current_version_no}` : "—"}
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATE_CLASS[state]}`}>
                      {STATE_LABEL[state]}
                    </span>
                    {view?.banner && <div className="mt-1 text-xs text-slate-600">{view.banner}</div>}
                  </td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">{reviewState(tender, view)}</td>
                  <td className="border-b border-[#e6e4dd] px-3 py-3 align-top">
                    <a href={`/tenders/${tender.id}`} className="text-[#0f5f5c]">
                      {view?.reviewed_at ? "View" : "Open"}
                    </a>
                  </td>
                </tr>
              );
            })}
            {shown.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-slate-600">
                  No tender matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-600">
        Every value on these pages is a reviewed reading of the tender document, which remains the authoritative source.
        Candidates the model produced are never shown here.
      </p>
    </main>
  );
}
