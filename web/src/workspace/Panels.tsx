import { useEffect, useState } from "react";

import {
  ApiError,
  type AmendmentChange,
  type AskAnswer,
  type TenderAmendments,
  type WorkspaceApi,
} from "../api/client";
import { numericDelta, wordDiff } from "../lib/diff";
import { formatValue } from "../lib/format";
import { DropZone } from "./DropZone";
import type { PageRef } from "./PageDrawer";
import { AMENDMENT_KINDS } from "./terms";

const CHANGE_CLASS: Record<AmendmentChange["change_class"], string> = {
  value_changed: "Value changed",
  date_moved: "Date moved",
  clause_withdrawn: "Clause withdrawn",
  annexure_replaced: "Format or annexure replaced",
  requirement_added: "New requirement",
  restated: "Restated, no change",
};

function afterValue(change: AmendmentChange): unknown {
  const state = change.entry.state;
  return state.approval?.final_value ?? state.candidate?.value ?? null;
}

function ChangeRow({ change, onOpen }: { change: AmendmentChange; onOpen: (page: PageRef) => void }) {
  const before = change.before?.value ?? null;
  const after = afterValue(change);
  const show = (v: unknown) => formatValue(v, change.value_type, change.unit) || "Not stated";
  const delta = numericDelta(before, after);
  const textual = change.value_type === "long_text" || change.value_type === "text";
  const evidence = change.entry.state.candidate?.evidence[0];
  const withdrawn = change.change_class === "clause_withdrawn";
  return (
    <li className="border-t border-[#e7ecea] py-4 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <p className="text-sm font-medium">{change.label}</p>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            withdrawn ? "bg-[#fde8ec] text-[#9f1239]" : "bg-[#eef0fb] text-[#3b4aa0]"
          }`}
        >
          {CHANGE_CLASS[change.change_class]}
        </span>
        <span className="text-xs text-[#8a9a9e]">{change.section_label}</span>
      </div>
      {textual && before !== null && after !== null ? (
        <p className="mt-2 text-sm leading-6">
          {wordDiff(String(before), String(after)).map((part, i) =>
            part.kind === "same" ? (
              <span key={i}>{part.text}</span>
            ) : part.kind === "removed" ? (
              <del key={i} className="bg-[#fde8ec] text-[#9f1239]">
                {part.text}
              </del>
            ) : (
              <ins key={i} className="bg-[#e3f4ea] text-[#166534] no-underline">
                {part.text}
              </ins>
            ),
          )}
        </p>
      ) : (
        <p className="mt-2 flex flex-wrap items-baseline gap-2 text-[15px] tabular-nums">
          <span className="text-[#8a9a9e] line-through decoration-[#9f1239]/60">{show(before)}</span>
          <span aria-hidden="true" className="text-[#8a9a9e]">
            to
          </span>
          <span className={`font-semibold ${withdrawn ? "text-[#9f1239]" : ""}`}>{withdrawn ? "Withdrawn" : show(after)}</span>
          {delta && <span className="text-xs text-[#5b6b70]">({delta})</span>}
        </p>
      )}
      {change.impacts.length > 0 && (
        <ul className="mt-2 space-y-1">
          {change.impacts.map((impact) => (
            <li key={impact} className="flex gap-2 text-xs text-[#b45309]">
              <span aria-hidden="true">▲</span>
              {impact}
            </li>
          ))}
        </ul>
      )}
      {evidence && (
        <button
          type="button"
          onClick={() =>
            onOpen({ documentId: evidence.document_id, pageNo: evidence.page_no, quote: evidence.quote, label: change.label })
          }
          className="mt-2 text-xs text-[#0f5f5c] hover:underline"
        >
          See the amendment, page {evidence.page_no}
        </button>
      )}
    </li>
  );
}

/** The tender's later versions, each with what it changed against what stood before, and
 * the way to add the next one. */
export function AmendmentsPanel({
  api,
  tenderId,
  onOpen,
  onSubmitted,
  refreshKey,
}: {
  api: WorkspaceApi;
  tenderId: string;
  onOpen: (page: PageRef) => void;
  onSubmitted: () => void;
  refreshKey: number;
}) {
  const [data, setData] = useState<TenderAmendments | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .amendments(tenderId)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "The amendments could not be loaded."));
    return () => {
      cancelled = true;
    };
  }, [api, tenderId, refreshKey]);

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
      <section aria-label="Amendments">
        {error && (
          <p role="alert" className="text-sm text-[#9f1239]">
            {error}
          </p>
        )}
        {!data && !error && <p className="text-sm text-[#5b6b70]">Loading the amendments…</p>}
        {data && data.versions.length === 0 && (
          <p className="rounded-lg border border-dashed border-[#c9d3d0] p-6 text-sm text-[#5b6b70]">
            No amendment yet. When the agency issues one, add it here and every change shows against what the
            tender said before.
          </p>
        )}
        {data?.versions.map((version) => {
          const shown = version.changes.filter((c) => c.kind !== "restated");
          return (
            <article key={version.version_no} className="mb-8">
              <header className="flex flex-wrap items-baseline gap-x-3 border-b-2 border-[#1b2a2f] pb-2">
                <h3 className="text-base font-semibold capitalize">
                  {version.kind} {version.version_no}
                </h3>
                {version.issued_on && <span className="text-sm text-[#5b6b70]">issued {formatValue(version.issued_on, "date", null)}</span>}
                <span className="ml-auto text-sm text-[#5b6b70]">
                  {version.changed} changed, {version.added} added, {version.removed} withdrawn
                </span>
              </header>
              {version.summary_of_change && <p className="mt-3 text-sm leading-6 text-[#45555a]">{version.summary_of_change}</p>}
              {shown.length === 0 ? (
                <p className="mt-3 text-sm text-[#5b6b70]">This version restates the tender; no term changed.</p>
              ) : (
                <ul className="mt-1">
                  {shown.map((change) => (
                    <ChangeRow key={change.field_path} change={change} onOpen={onOpen} />
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </section>
      <aside className="h-fit rounded-lg border border-[#dde4e2] bg-[#f7f9f8] p-4">
        <h3 className="mb-3 text-sm font-semibold">Add an amendment</h3>
        <DropZone
          title="Add an amendment"
          hint="Drop the amendment, corrigendum or clarification"
          options={AMENDMENT_KINDS}
          optionLabel="What it is"
          action="Read this amendment"
          onSubmit={async (form, kind) => {
            await api.submitAmendment(tenderId, { ...form, kind });
            onSubmitted();
          }}
        />
      </aside>
    </div>
  );
}

const SUGGESTIONS = [
  "What are the financial eligibility criteria?",
  "What happens if commissioning is delayed?",
  "Can thermal or market power be used to meet the supply?",
  "What is the payment security mechanism?",
];

/** A question about this tender, answered from its pages, every claim with its page. */
export function AskPanel({ api, tenderId, onOpen }: { api: WorkspaceApi; tenderId: string; onOpen: (page: PageRef) => void }) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<AskAnswer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await api.ask(tenderId, q);
      setAsked((prev) => [answer, ...prev]);
      setQuestion("");
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 403
          ? "This access key cannot ask questions. Ask for a key with the model scope."
          : caught instanceof ApiError
            ? (caught.detail ?? caught.message)
            : "The question could not be answered.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Ask" className="max-w-3xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
        className="flex gap-2"
      >
        <label htmlFor="ask-question" className="sr-only">
          Your question
        </label>
        <input
          id="ask-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask anything this tender answers"
          className="min-w-0 flex-1 rounded-md border border-[#c9d3d0] px-3 py-2.5 text-sm outline-none focus:border-[#0f5f5c] focus:ring-2 focus:ring-[#0f5f5c]/25"
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          className="min-h-[44px] rounded-md bg-[#0f5f5c] px-5 text-sm font-medium text-white hover:bg-[#0a4341] disabled:opacity-40"
        >
          {busy ? "Reading…" : "Ask"}
        </button>
      </form>
      {asked.length === 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => void ask(s)}
              disabled={busy}
              className="rounded-full border border-[#c9d3d0] bg-white px-3 py-1.5 text-sm text-[#45555a] hover:border-[#0f5f5c] hover:text-[#0f5f5c]"
            >
              {s}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#9f1239]">
          {error}
        </p>
      )}
      <ol className="mt-6 space-y-6">
        {asked.map((a, i) => (
          <li key={`${a.question}-${asked.length - i}`} className="border-l-2 border-[#0f5f5c] pl-4">
            <p className="text-sm font-medium text-[#5b6b70]">{a.question}</p>
            <p className="mt-2 whitespace-pre-line text-[15px] leading-7">{a.answer}</p>
            <p className="mt-1 text-xs text-[#8a9a9e]">
              {a.source === "approved"
                ? "From a reviewer-approved value"
                : a.answered
                  ? "Read by the engine from the tender's pages; check the pages before relying on it"
                  : "The tender's pages did not answer this"}
            </p>
            {a.citations.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-2">
                {a.citations.map((c) => (
                  <li key={c.n}>
                    <button
                      type="button"
                      onClick={() =>
                        onOpen({ documentId: c.document_id, filename: c.filename, pageNo: c.page_no, quote: c.quote, label: a.question })
                      }
                      className={`rounded-md border px-2 py-1 text-xs ${
                        c.resolved ? "border-[#c9d3d0] text-[#0f5f5c] hover:border-[#0f5f5c]" : "border-[#f2c9a0] text-[#b45309]"
                      }`}
                      title={c.quote}
                    >
                      [{c.n}] page {c.page_no}
                      {c.resolved ? "" : ", not found on the page"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Hand the tender to a person for review: a link that opens it in the review screen. */
export function ReviewPanel({ api, tenderId }: { api: WorkspaceApi; tenderId: string }) {
  const [name, setName] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function make(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setCopied(false);
    try {
      const made = await api.reviewLink(tenderId, name.trim());
      setLink(made.url);
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 403
          ? "This access key cannot create review links. Ask for a key with the review scope."
          : caught instanceof ApiError
            ? (caught.detail ?? caught.message)
            : "The link could not be made.",
      );
    }
  }

  return (
    <section aria-label="Review" className="max-w-xl">
      <p className="text-sm leading-6 text-[#45555a]">
        Values marked "Read by engine" are the engine's reading. A reviewer opens the tender side by side with its
        pages, approves or corrects each value, and from then on it shows as Approved here and to every app that
        reads this tender.
      </p>
      <form onSubmit={make} className="mt-5 flex flex-wrap items-end gap-2">
        <div className="min-w-[220px] flex-1">
          <label htmlFor="reviewer-name" className="text-sm font-medium">
            Reviewer's name
          </label>
          <input
            id="reviewer-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded-md border border-[#c9d3d0] px-3 py-2.5 text-sm outline-none focus:border-[#0f5f5c]"
          />
        </div>
        <button
          type="submit"
          disabled={!name.trim()}
          className="min-h-[44px] rounded-md bg-[#0f5f5c] px-5 text-sm font-medium text-white hover:bg-[#0a4341] disabled:opacity-40"
        >
          Make the review link
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#9f1239]">
          {error}
        </p>
      )}
      {link && (
        <div className="mt-4 rounded-lg border border-[#dde4e2] bg-[#f7f9f8] p-4">
          <p className="text-xs text-[#5b6b70]">Send this to {name.trim()} only; it opens the review without a password.</p>
          <p className="mt-1 break-all font-mono text-sm">{link}</p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard?.writeText(link).then(() => setCopied(true));
              }}
              className="rounded-md border border-[#c9d3d0] bg-white px-3 py-1.5 text-sm"
            >
              {copied ? "Copied" : "Copy the link"}
            </button>
            <a href={link} target="_blank" rel="noreferrer" className="rounded-md px-3 py-1.5 text-sm text-[#0f5f5c] hover:underline">
              Open it
            </a>
          </div>
        </div>
      )}
    </section>
  );
}
