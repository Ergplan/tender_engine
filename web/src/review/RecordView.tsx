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

/** A structured value: every key of a record with what the document states for it, or
 * "not stated"; a list of records item by item, each with the keys it states. */
export function RecordView({ field, value }: { field: ReviewField; value: unknown }) {
  const keys = (field.keys ?? []) as KeyDef[];
  if (field.value_type === "record_list") {
    return (
      <ol className="space-y-1.5" data-testid="record-list">
        {recordsOf(value).map((record, index) => (
          <li key={index} className="rounded border border-slate-200 bg-white px-2 py-1">
            <Rows record={record} keys={keys} all={false} />
          </li>
        ))}
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
