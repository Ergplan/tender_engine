import { useEffect, useRef, useState } from "react";

import type { ReviewEntry, ReviewField } from "../api/client";
import {
  fromEditText,
  NUMBER_TYPES,
  recordFromEdit,
  recordOf,
  recordToEdit,
  toEditText,
  unitSuffix,
  type KeyDef,
} from "../lib/format";
import { hasLocatedEvidence } from "./model";

export type EditResult = {
  value: unknown;
  note: string | null;
  evidence: { page_no: number; quote: string }[] | null;
};

/** The text the reviewer has selected in the PDF pane, with its page and document. */
export function selectedPdfText(): { documentId: string; pageNo: number; text: string } | null {
  const selection = window.getSelection();
  const text = selection ? selection.toString().replace(/\s+/g, " ").trim() : "";
  const node = selection?.anchorNode;
  const element = node instanceof Element ? node : (node?.parentElement ?? null);
  const page = element?.closest<HTMLElement>("[data-page-no]");
  const pane = element?.closest<HTMLElement>("[data-document-id]");
  if (!text || !page || !pane) return null;
  return {
    documentId: pane.dataset.documentId ?? "",
    pageNo: Number(page.dataset.pageNo),
    text,
  };
}

const BOX = "rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900";
const INPUT = `w-full ${BOX}`;

/** An inline input typed to the field, with Save and Cancel. */
export function EditForm({
  field,
  entry,
  documentName,
  onSave,
  onCancel,
}: {
  field: ReviewField;
  entry: ReviewEntry;
  documentName: string;
  onSave: (result: EditResult) => void;
  onCancel: () => void;
}) {
  const candidate = entry.state.candidate;
  const start = entry.state.approval?.final_value ?? candidate?.value ?? null;
  const [text, setText] = useState(toEditText(start, field.value_type));
  // A record is edited key by key; a list of records line by line.
  const keys = field.value_type === "record" ? ((field.keys ?? []) as KeyDef[]) : [];
  const [texts, setTexts] = useState(() => recordToEdit(recordOf(start, keys), keys));
  const [page, setPage] = useState("");
  const [quote, setQuote] = useState("");
  const [note, setNote] = useState(entry.state.approval?.note ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  // The whole form, Save included, is brought into view when it opens.
  useEffect(() => {
    form.current?.scrollIntoView({ block: "nearest" });
  }, []);
  const needsEvidence = !hasLocatedEvidence(candidate);
  const type = field.value_type;
  const suffix = unitSuffix(type, field.unit);

  function save() {
    const value = keys.length ? recordFromEdit(texts, keys) : fromEditText(text, type);
    if (value === null) return setProblem("Enter a value, or cancel and mark it not in document.");
    const hasEvidence = page.trim() !== "" || quote.trim() !== "";
    if (needsEvidence && !(page.trim() && quote.trim()))
      return setProblem("Give the page and the text that state this value.");
    if (hasEvidence && !(Number(page) >= 1 && quote.trim()))
      return setProblem("Evidence needs both a page number and the quoted text.");
    onSave({
      value,
      note: note.trim() || null,
      evidence: hasEvidence ? [{ page_no: Number(page), quote: quote.trim() }] : null,
    });
  }

  function useSelection() {
    const selected = selectedPdfText();
    if (!selected) return setProblem("Select the text in the PDF first.");
    if (candidate && selected.documentId !== candidate.document_id)
      return setProblem(`Select the text in ${documentName}; this value is read from it.`);
    setPage(String(selected.pageNo));
    setQuote(selected.text);
    setProblem(null);
  }

  const common = {
    "data-testid": "edit-input",
    autoFocus: keys.length === 0,
    value: text,
    onChange: (event: { target: { value: string } }) => setText(event.target.value),
  };
  return (
    <form
      ref={form}
      className="mt-2 scroll-mb-3 space-y-2 rounded border border-slate-300 bg-slate-50 p-2"
      onClick={(event) => event.stopPropagation()}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      {keys.length > 0 && (
        <div className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
          {keys.map((key, index) => {
            const own = {
              "data-testid": `edit-key-${key.name}`,
              "aria-label": key.label,
              autoFocus: index === 0,
              className: INPUT,
              value: texts[key.name] ?? "",
              onChange: (event: { target: { value: string } }) =>
                setTexts({ ...texts, [key.name]: event.target.value }),
            };
            return (
              <label key={key.name} className="contents text-xs text-slate-700">
                <span>
                  {key.label}
                  {key.unit ? <span className="text-slate-500"> ({key.unit})</span> : null}
                </span>
                {key.keys ? (
                  <textarea
                    rows={3}
                    placeholder={`One per line: ${key.keys.map((sub) => `${sub.name}=…`).join("; ")}`}
                    {...own}
                  />
                ) : key.value_type === "bool" ? (
                  <select {...own}>
                    <option value="">Not stated</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                ) : key.value_type === "enum" ? (
                  <select {...own}>
                    <option value="">Not stated</option>
                    {(key.enum_values ?? []).map((option) => (
                      <option key={option} value={option}>
                        {option.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>
                ) : NUMBER_TYPES.has(key.value_type) ? (
                  <input type="number" step="any" placeholder="Not stated" {...own} />
                ) : (
                  <input type="text" placeholder="Not stated" {...own} />
                )}
              </label>
            );
          })}
        </div>
      )}
      <div className={keys.length ? "hidden" : "flex items-center gap-2"}>
        {type === "date" ? (
          <input type="date" className={INPUT} {...common} />
        ) : type === "bool" ? (
          <select className={INPUT} {...common}>
            <option value="">Choose…</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        ) : type === "enum" ? (
          <select className={INPUT} {...common}>
            <option value="">Choose…</option>
            {(field.enum_values ?? []).map((option) => (
              <option key={option} value={option}>
                {option.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        ) : NUMBER_TYPES.has(type) ? (
          <input type="number" step="any" className={INPUT} {...common} />
        ) : type === "text" ? (
          <input type="text" className={INPUT} {...common} />
        ) : (
          <textarea
            rows={type === "long_text" ? Math.min(Math.max(Math.ceil(text.length / 70), 5), 14) : 4}
            className={INPUT}
            placeholder={
              type === "record_list"
                ? "One item per line, as  key: value | key: value"
                : type === "list_text"
                  ? "One item per line"
                  : undefined
            }
            {...common}
          />
        )}
        {suffix && <span className="shrink-0 text-xs text-slate-600">{suffix}</span>}
      </div>
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>
            Where the document says so{needsEvidence ? " (needed)" : " (if it differs from the chips)"}
          </span>
          <button type="button" className="text-sky-700 underline" onClick={useSelection}>
            Use text selected in the PDF
          </button>
        </div>
        <div className="flex gap-2">
          <input
            type="number"
            min={1}
            placeholder="Page"
            aria-label="Evidence page"
            data-testid="evidence-page"
            className={`w-20 shrink-0 ${BOX}`}
            value={page}
            onChange={(event) => setPage(event.target.value)}
          />
          <input
            type="text"
            placeholder="The words on that page, copied exactly"
            aria-label="Evidence quote"
            data-testid="evidence-quote"
            className={INPUT}
            value={quote}
            onChange={(event) => setQuote(event.target.value)}
          />
        </div>
      </div>
      <input
        type="text"
        placeholder="Note (optional)"
        aria-label="Note"
        className={INPUT}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      {problem && (
        <p role="alert" className="text-xs text-red-700">
          {problem}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          data-testid="edit-save"
          className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white hover:bg-slate-700"
        >
          Save
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-100"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
