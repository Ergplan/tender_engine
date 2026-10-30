import { useRef, useState } from "react";

import { ApiError, type SubmitForm } from "../api/client";
import { TENDER_TYPES } from "./terms";

const ACCEPTED = ".pdf,.docx,.xlsx";

function acceptable(file: File): string | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "A .zip pack cannot be read whole here. Drop its main RfS or RfP document.";
  if (!/\.(pdf|docx|xlsx)$/.test(name)) return `${file.name} is not a PDF, Word (.docx) or Excel (.xlsx) file.`;
  return null;
}

/** Where a tender comes in: a file dropped or chosen, or the official address it is
 * published at. The engine reads it in the background. */
export function DropZone({
  onSubmit,
  title = "Add a tender",
  hint = "Drop the RfS or RfP here",
  options = TENDER_TYPES,
  optionLabel = "Tender type",
  action = "Read this tender",
}: {
  /** The form, and the option chosen in the list (a tender type, or an amendment's kind). */
  onSubmit: (form: SubmitForm, option: string) => Promise<void>;
  title?: string;
  hint?: string;
  options?: { value: string; label: string }[];
  optionLabel?: string;
  action?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [option, setOption] = useState(options[0]?.value ?? "");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function choose(chosen: File | undefined) {
    if (!chosen) return;
    const refusal = acceptable(chosen);
    setError(refusal);
    setFile(refusal ? null : chosen);
    if (!refusal) setUrl("");
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!file && !url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ file: file ?? undefined, sourceUrl: file ? undefined : url.trim() }, option);
      setFile(null);
      setUrl("");
    } catch (caught) {
      setError(caught instanceof ApiError ? (caught.detail ?? caught.message) : "The tender could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={send} aria-label={title} className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        aria-label={`${hint}, or press to choose a file`}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          choose(e.dataTransfer.files[0]);
        }}
        className={`cursor-pointer rounded-lg border-2 border-dashed px-4 py-6 text-center outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[#0f5f5c]/40 ${
          over ? "border-[#0f5f5c] bg-[#e6f0ee]" : "border-[#c9d3d0] bg-white hover:border-[#0f5f5c]"
        }`}
      >
        <svg width="28" height="28" viewBox="0 0 24 24" aria-hidden="true" className="mx-auto text-[#0f5f5c]">
          <path
            d="M7 3h7l5 5v13H7z M14 3v5h5 M12 11v6 M9.5 13.5 12 11l2.5 2.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </svg>
        {file ? (
          <p className="mt-2 break-all text-sm font-medium text-[#1b2a2f]">{file.name}</p>
        ) : (
          <>
            <p className="mt-2 text-sm font-medium text-[#1b2a2f]">{hint}</p>
            <p className="text-xs text-[#5b6b70]">PDF, Word or Excel, up to 200 MB</p>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept={ACCEPTED}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </div>
      {!file && (
        <div>
          <label htmlFor={`${title}-url`} className="text-xs text-[#5b6b70]">
            Or paste its address on the agency's own site
          </label>
          <input
            id={`${title}-url`}
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.seci.co.in/…/RfS.pdf"
            className="mt-1 w-full rounded-md border border-[#c9d3d0] px-3 py-2 text-sm outline-none focus:border-[#0f5f5c] focus:ring-2 focus:ring-[#0f5f5c]/25"
          />
        </div>
      )}
      <div>
        <label htmlFor={`${title}-option`} className="text-xs text-[#5b6b70]">
          {optionLabel}
        </label>
        <select
          id={`${title}-option`}
          value={option}
          onChange={(e) => setOption(e.target.value)}
          className="mt-1 w-full rounded-md border border-[#c9d3d0] px-3 py-2 text-sm outline-none focus:border-[#0f5f5c]"
        >
          {options.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      {error && (
        <p role="alert" className="text-sm text-[#9f1239]">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || (!file && !url.trim())}
        className="min-h-[44px] w-full rounded-md bg-[#0f5f5c] text-sm font-medium text-white hover:bg-[#0a4341] disabled:opacity-40"
      >
        {busy ? "Sending…" : action}
      </button>
    </form>
  );
}
