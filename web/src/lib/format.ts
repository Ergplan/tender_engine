// How a value is shown to the reviewer, by value type. Pure functions.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const NUMBER_TYPES = new Set([
  "int",
  "decimal",
  "money_inr",
  "percent",
  "duration_months",
  "mw",
  "mwh",
  "kv",
  "km",
]);
const UNIT_OF_TYPE: Record<string, string> = { mw: "MW", mwh: "MWh", kv: "kV", km: "km" };

/** An ISO date (2026-03-12) from an ISO or a day-first date (12.03.2026, 12/03/2026). */
export function toIsoDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(text);
  const dayFirst = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/.exec(text);
  const parts = iso
    ? [Number(iso[1]), Number(iso[2]), Number(iso[3])]
    : dayFirst
      ? [Number(dayFirst[3]), Number(dayFirst[2]), Number(dayFirst[1])]
      : null;
  if (!parts) return null;
  const [year, month, day] = parts;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day)
    return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** 12 Mar 2026, or the text as it is when it is not a date. */
export function formatDate(value: unknown): string {
  const iso = toIsoDate(value);
  if (!iso) return String(value);
  const [year, month, day] = iso.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const text = value.replace(/,/g, "").trim();
  return /^-?\d+(\.\d+)?$/.test(text) ? Number(text) : null;
}

function trim(number: number, digits: number): string {
  return Number(number.toFixed(digits)).toLocaleString("en-IN", { maximumFractionDigits: digits });
}

/** Rupees the Indian way: ₹ 25 lakh, ₹ 1.2 crore, ₹ 9,28,000 below one lakh steps. */
export function formatRupees(amount: number): string {
  const abs = Math.abs(amount);
  if (abs >= 1e7) return `₹ ${trim(amount / 1e7, 2)} crore`;
  if (abs >= 1e5) return `₹ ${trim(amount / 1e5, 2)} lakh`;
  return `₹ ${trim(amount, 2)}`;
}

/** "INR per MW" -> "/MW"; "INR" -> "". */
function perSuffix(unit: string | null): string {
  if (!unit) return "";
  const rest = unit.replace(/^INR\s*/i, "").trim();
  return rest ? `/${rest.replace(/^per\s+/i, "").replace(/\s+per\s+/gi, "/")}` : "";
}

export function unitSuffix(valueType: string, unit: string | null): string {
  if (valueType === "money_inr") return `₹${perSuffix(unit)}`;
  if (valueType === "percent") return "%";
  if (valueType === "duration_months") return "months";
  return UNIT_OF_TYPE[valueType] ?? (unit && !/^INR/i.test(unit) ? unit : "");
}

function label(text: string): string {
  const spaced = text.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The value as one line of text (lists joined). Null and undefined are an empty string. */
export function formatValue(value: unknown, valueType: string, unit: string | null): string {
  if (value === null || value === undefined) return "";
  if (valueType === "date") return formatDate(value);
  if (valueType === "bool") return value === true || value === "true" ? "Yes" : value === false || value === "false" ? "No" : String(value);
  if (valueType === "enum") return label(String(value));
  if (Array.isArray(value)) return formatList(value).join("; ");
  if (typeof value === "object") return formatList([value])[0];
  if (NUMBER_TYPES.has(valueType)) {
    const number = toNumber(value);
    if (number === null) return String(value);
    if (valueType === "money_inr") return `${formatRupees(number)}${perSuffix(unit)}`;
    if (valueType === "percent") return `${number.toFixed(1)}%`;
    const suffix = unitSuffix(valueType, unit);
    return `${trim(number, 3)}${suffix ? ` ${suffix}` : ""}`;
  }
  if (valueType === "long_text") return stripMarkers(String(value));
  return String(value);
}

/** A text without its evidence markers ("[3]"), for places that only show it. */
export function stripMarkers(text: string): string {
  return text.replace(/\s*\[\d+\]/g, "");
}

/** A long text as paragraphs, each cut into plain pieces and evidence markers. A paragraph
 * that opens with a short heading and a colon gives the heading apart. */
export type TextPiece = { text: string } | { marker: number };
export type Paragraph = { heading: string | null; pieces: TextPiece[] };

export function paragraphs(text: string): Paragraph[] {
  return text
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const head = /^([A-Z][A-Za-z ,/&-]{2,40}):\s+/.exec(block);
      const body = head ? block.slice(head[0].length) : block;
      const pieces: TextPiece[] = [];
      let last = 0;
      for (const found of body.matchAll(/\[(\d+)\]/g)) {
        if (found.index > last) pieces.push({ text: body.slice(last, found.index) });
        pieces.push({ marker: Number(found[1]) });
        last = found.index + found[0].length;
      }
      if (last < body.length) pieces.push({ text: body.slice(last) });
      return { heading: head ? head[1] : null, pieces };
    });
}

/** Each item of a list as text; a record as "key: value | key: value". */
export function formatList(value: unknown[]): string[] {
  return value.map((item) =>
    item && typeof item === "object"
      ? Object.entries(item as Record<string, unknown>)
          .filter(([, part]) => part !== null && part !== undefined)
          .map(([key, part]) => `${key}: ${Array.isArray(part) ? formatList(part).join(" / ") : String(part)}`)
          .join(" | ")
      : String(item),
  );
}

export type Confidence = "high" | "medium" | "low";

/** Green from 0.8, amber from 0.5, red below. */
export function confidenceBand(confidence: number): Confidence {
  return confidence >= 0.8 ? "high" : confidence >= 0.5 ? "medium" : "low";
}

/** The text an edit starts from, and the value it sends, by value type. */
export function toEditText(value: unknown, valueType: string): string {
  if (value === null || value === undefined) return "";
  if (valueType === "date") return toIsoDate(value) ?? "";
  if (valueType === "bool") return value === true ? "yes" : value === false ? "no" : "";
  if (Array.isArray(value)) return formatList(value).join("\n");
  if (NUMBER_TYPES.has(valueType)) {
    const number = toNumber(value);
    return number === null ? "" : String(number);
  }
  return String(value);
}

export function fromEditText(text: string, valueType: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (valueType === "bool") return trimmed === "yes";
  if (NUMBER_TYPES.has(valueType)) return toNumber(trimmed) ?? trimmed;
  if (valueType === "list_text" || valueType === "record_list")
    return trimmed
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  return trimmed;
}

/** One typed key of a structured field; `keys` makes it a list of sub-records. */
export type KeyDef = {
  name: string;
  label: string;
  value_type: string;
  unit?: string | null;
  enum_values?: string[] | null;
  keys?: KeyDef[] | null;
};
export type RecordValue = Record<string, unknown>;

const UNSTATED = new Set(["", "null", "none", "not stated", "n/a"]);

function pairsOf(text: string, outer: string, inner: string): RecordValue {
  const record: RecordValue = {};
  for (const part of text.split(outer)) {
    const at = part.indexOf(inner);
    if (at < 0) continue;
    const value = part.slice(at + inner.length).trim();
    if (!UNSTATED.has(value.toLowerCase())) record[part.slice(0, at).trim().toLowerCase()] = value;
  }
  return record;
}

/** A record from what is stored: the record itself (after a decision) or the model's
 * lines, `key: value`, with a list key written once per item as `key: sub=value; sub=value`. */
export function recordOf(value: unknown, keys: KeyDef[]): RecordValue | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value)) return typeof value === "object" ? (value as RecordValue) : null;
  const lists = new Set(keys.filter((key) => key.keys).map((key) => key.name));
  const record: RecordValue = {};
  for (const line of value) {
    const text = String(line);
    const at = text.indexOf(":");
    if (at < 0) continue;
    const name = text.slice(0, at).trim().toLowerCase();
    const rest = text.slice(at + 1).trim();
    if (lists.has(name)) {
      const row = pairsOf(rest, ";", "=");
      if (Object.keys(row).length) record[name] = [...((record[name] as RecordValue[]) ?? []), row];
    } else if (!UNSTATED.has(rest.toLowerCase())) record[name] = rest;
  }
  return record;
}

/** The records of a list: each a record itself or a line `key: value | key: value`. */
export function recordsOf(value: unknown): RecordValue[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) =>
    item && typeof item === "object" ? (item as RecordValue) : pairsOf(String(item), "|", ":"),
  );
}

/** One key's value as the reviewer reads it, or null when the document does not state it. */
export function formatKey(value: unknown, key: KeyDef): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (key.value_type === "bool")
    return value === true || value === "yes" || value === "true" ? "Yes" : "No";
  if (key.value_type === "money_inr") {
    const number = toNumber(value);
    return number === null ? String(value) : formatRupees(number);
  }
  if (NUMBER_TYPES.has(key.value_type)) {
    const number = toNumber(value);
    return number === null ? String(value) : trim(number, 4);
  }
  return formatValue(value, key.value_type, null);
}

/** A record as an edit sends it: numbers as numbers, yes/no as booleans, nothing for a key
 * left empty. A list key is edited as lines `sub=value; sub=value`. */
export function recordFromEdit(texts: Record<string, string>, keys: KeyDef[]): RecordValue | null {
  const record: RecordValue = {};
  for (const key of keys) {
    const text = (texts[key.name] ?? "").trim();
    if (text === "") continue;
    if (key.keys) {
      const rows = text
        .split("\n")
        .map((line) => pairsOf(line, ";", "="))
        .filter((row) => Object.keys(row).length);
      if (rows.length) record[key.name] = rows;
    } else if (key.value_type === "bool") record[key.name] = text === "yes";
    else if (NUMBER_TYPES.has(key.value_type)) record[key.name] = toNumber(text) ?? text;
    else record[key.name] = text;
  }
  return Object.keys(record).length ? record : null;
}

/** The text each key's input starts from. */
export function recordToEdit(record: RecordValue | null, keys: KeyDef[]): Record<string, string> {
  const texts: Record<string, string> = {};
  for (const key of keys) {
    const value = record?.[key.name];
    if (value === null || value === undefined) texts[key.name] = "";
    else if (key.keys)
      texts[key.name] = (value as RecordValue[])
        .map((row) =>
          Object.entries(row)
            .filter(([, part]) => part !== null && part !== undefined)
            .map(([name, part]) => `${name}=${String(part)}`)
            .join("; "),
        )
        .join("\n");
    else if (key.value_type === "bool")
      texts[key.name] = value === true || value === "yes" || value === "true" ? "yes" : "no";
    else texts[key.name] = String(value);
  }
  return texts;
}
