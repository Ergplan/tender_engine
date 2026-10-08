import type { ReviewField } from "../api/client";
import { formatKey, recordOf, recordsOf, type KeyDef, type RecordValue } from "../lib/format";

function Unit({ of }: { of: KeyDef }) {
  return of.unit ? <span className="text-slate-600"> {of.unit}</span> : null;
}

/** The stated sub-keys of one list item on a line: "window start 05:00 · hours 2". */
function itemLine(row: RecordValue, keys: KeyDef[]): string {
  return keys
    .map((key) => {
      const text = formatKey(row[key.name], key);
      return text === null ? null : `${key.label.toLowerCase()} ${text}${key.unit ? ` ${key.unit}` : ""}`;
    })
    .filter(Boolean)
    .join(" · ");
}

function Rows({ record, keys, all }: { record: RecordValue; keys: KeyDef[]; all: boolean }) {
  return (
    <dl className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-sm">
      {keys.map((key) => {
        const value = record[key.name];
        const rows = key.keys && Array.isArray(value) ? (value as RecordValue[]) : null;
        const text = key.keys ? null : formatKey(value, key);
        const stated = key.keys ? !!rows?.length : text !== null;
        if (!stated && !all) return null;
        return (
          <div key={key.name} className="contents" data-testid="record-key" data-key={key.name}>
            <dt className="text-slate-600">{key.label}</dt>
            <dd className={stated ? "text-slate-900" : "italic text-slate-500"}>
              {!stated ? (
                "not stated"
              ) : rows ? (
                <ol className="list-decimal pl-4">
                  {rows.map((row, index) => (
                    <li key={index}>{itemLine(row, key.keys ?? [])}</li>
                  ))}
                </ol>
              ) : (
                <>
                  {text}
                  <Unit of={key} />
                </>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** How a derived row came about: read off a clause that names its subject ("stated"), off
 * a general clause that does not ("inherited"), or off nothing at all ("none"). Only a
 * derived table carries the key; any other record has no basis. */
export function rowBasis(record: RecordValue): "stated" | "inherited" | "none" | null {
  const basis = record["basis"];
  return basis === "stated" || basis === "inherited" || basis === "none" ? basis : null;
}

const BASIS_STYLE: Record<"stated" | "inherited" | "none", string> = {
  stated: "border-slate-200 bg-white",
  // A reviewer must see a derivation, not a printed fact: dashed, tinted, labelled.
  inherited: "border-dashed border-amber-400 bg-amber-50",
  none: "border-dotted border-slate-300 bg-slate-50 text-slate-500",
};
const BASIS_LABEL: Record<"stated" | "inherited" | "none", string | null> = {
  stated: null,
  inherited: "Derived from a general clause, not one naming this source",
  none: "No clause: not addressed",
};

/** A structured value: every key of a record with what the document states for it, or
 * "not stated"; a list of records item by item, each with the keys it states. */
export function RecordView({ field, value }: { field: ReviewField; value: unknown }) {
  const keys = (field.keys ?? []) as KeyDef[];
  if (field.value_type === "record_list") {
    return (
      <ol className="space-y-1.5" data-testid="record-list">
        {recordsOf(value).map((record, index) => {
          const basis = rowBasis(record);
          const label = basis ? BASIS_LABEL[basis] : null;
          return (
            <li
              key={index}
              data-basis={basis ?? undefined}
              className={"rounded border px-2 py-1 " + (basis ? BASIS_STYLE[basis] : "border-slate-200 bg-white")}
            >
              {label && (
                <p data-testid="row-basis" className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-amber-800">
                  {label}
                </p>
              )}
              <Rows record={record} keys={basis ? keys.filter((key) => key.name !== "basis") : keys} all={false} />
            </li>
          );
        })}
      </ol>
    );
  }
  const record = recordOf(value, keys);
  if (!record) return <span className="italic text-slate-500">No value found</span>;
  return (
    <div className="rounded border border-slate-200 bg-white px-2 py-1" data-testid="record">
      <Rows record={record} keys={keys} all />
    </div>
  );
}
