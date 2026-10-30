import { useMemo, useState } from "react";

import type { SnapshotField } from "../api/client";
import type { PageRef } from "./PageDrawer";
import { display, filterFields, type Filter, needsAttention, sections } from "./terms";

/** Who stands behind a value: a reviewer, or the engine's reading with its confidence. */
export function SourceMark({ field }: { field: SnapshotField }) {
  if (field.state === "not_stated") return null;
  if (field.source === "approved")
    return <span className="rounded-full bg-[#e6f0ee] px-2 py-0.5 text-xs font-medium text-[#0f5f5c]">Approved</span>;
  const confidence = field.confidence ?? null;
  const low = confidence !== null && confidence < 0.8;
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${low ? "bg-[#fdf1e3] text-[#b45309]" : "bg-[#eef1f0] text-[#45555a]"}`}
      title="Read by the engine; not yet approved by a reviewer"
    >
      Read by engine{confidence !== null ? `, ${Math.round(confidence * 100)}%` : ""}
    </span>
  );
}

function Row({ field, onOpen }: { field: SnapshotField; onOpen: (page: PageRef) => void }) {
  const first = field.evidence[0];
  const value = display(field);
  const long = field.value_type === "long_text" || value.length > 90;
  return (
    <li className="grid gap-x-6 gap-y-2 border-t border-[#e7ecea] py-4 first:border-t-0 md:grid-cols-[minmax(180px,240px)_1fr]">
      <div>
        <p className="text-sm font-medium text-[#1b2a2f]">{field.label}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <SourceMark field={field} />
          {(field.version_no ?? 1) > 1 && field.state !== "withdrawn" && (
            <span className="rounded-full bg-[#eef0fb] px-2 py-0.5 text-xs text-[#3b4aa0]">
              Set by {field.version_kind ?? "version"} {field.version_no}
            </span>
          )}
        </div>
      </div>
      <div className="min-w-0">
        <p
          className={`${long ? "text-sm leading-6" : "text-[15px] font-semibold tabular-nums"} ${
            field.state === "withdrawn" ? "text-[#9f1239]" : field.state === "not_stated" ? "text-[#8a9a9e]" : "text-[#1b2a2f]"
          }`}
        >
          {value}
          {field.state === "withdrawn" && field.withdrawn_from_version ? (
            <span className="ml-2 text-xs font-normal">by version {field.withdrawn_from_version}</span>
          ) : null}
        </p>
        {first && (
          <button
            type="button"
            onClick={() =>
              onOpen({ documentId: first.document_id, filename: first.filename, pageNo: first.page_no, quote: first.quote, label: field.label })
            }
            className="group mt-2 block w-full text-left"
          >
            <span className="font-serif text-[14px] leading-6 text-[#3f4a4d]">
              <span className="bg-[#fef3c7] box-decoration-clone px-0.5 group-hover:bg-[#fde68a]">
                “{first.quote.length > 260 ? `${first.quote.slice(0, 257)}…` : first.quote}”
              </span>
            </span>
            <span className="mt-1 block text-xs text-[#0f5f5c] group-hover:underline">
              Page {first.page_no}
              {first.filename ? `, ${first.filename}` : ""}
              {first.located ? "" : ". The quote was not found on the page; check it"}
              {field.evidence.length > 1 ? ` (and ${field.evidence.length - 1} more)` : ""}
            </span>
          </button>
        )}
      </div>
    </li>
  );
}

/** Everything the tender asks for, section by section, each value with the words it rests on. */
export function Ledger({ fields, onOpen }: { fields: SnapshotField[]; onOpen: (page: PageRef) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const shown = useMemo(() => filterFields(fields, filter, query), [fields, filter, query]);
  const grouped = useMemo(() => sections(shown), [shown]);
  const attention = useMemo(() => fields.filter(needsAttention).length, [fields]);
  const changed = useMemo(
    () => fields.filter((f) => (f.version_no ?? 1) > 1 || f.state === "withdrawn").length,
    [fields],
  );
  const filters: { value: Filter; label: string }[] = [
    { value: "all", label: "Everything stated" },
    { value: "attention", label: `Check these (${attention})` },
    { value: "changed", label: `Changed by amendments (${changed})` },
  ];

  return (
    <section aria-label="Requirements">
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-[#dde4e2] bg-white/95 py-3 backdrop-blur">
        <div role="radiogroup" aria-label="Show" className="flex flex-wrap gap-1 rounded-lg bg-[#eef1f0] p-1">
          {filters.map((f) => (
            <button
              key={f.value}
              type="button"
              role="radio"
              aria-checked={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                filter === f.value ? "bg-white font-medium text-[#1b2a2f] shadow-sm" : "text-[#5b6b70] hover:text-[#1b2a2f]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          aria-label="Search the requirements"
          placeholder="Search, e.g. net worth, penalty, greenshoe"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="ml-auto min-w-[220px] flex-1 rounded-md border border-[#c9d3d0] px-3 py-2 text-sm outline-none focus:border-[#0f5f5c] md:max-w-xs"
        />
      </div>
      {grouped.length === 0 ? (
        <p className="py-10 text-center text-sm text-[#5b6b70]">
          {filter === "attention" ? "Nothing here needs a second look." : "Nothing matches. Clear the search to see every term."}
        </p>
      ) : (
        grouped.map((section) => (
          <section key={section.name} aria-labelledby={`sec-${section.name}`} className="mt-6">
            <h3 id={`sec-${section.name}`} className="text-[13px] font-semibold text-[#0f5f5c]">
              {section.label}
              <span className="ml-2 font-normal text-[#8a9a9e]">{section.fields.length}</span>
            </h3>
            <ul className="mt-1">
              {section.fields.map((field) => (
                <Row key={field.path} field={field} onOpen={onOpen} />
              ))}
            </ul>
          </section>
        ))
      )}
    </section>
  );
}
