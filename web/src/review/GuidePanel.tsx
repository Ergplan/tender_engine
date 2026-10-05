import { useState } from "react";

import { GUIDE } from "./guide";

const KEY = "review-guide-closed";

function remembered(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "yes";
  } catch {
    return false;
  }
}

/** The orientation panel: open the first time, then as the reviewer left it. */
export function GuidePanel() {
  const [closed, setClosed] = useState(remembered);
  function toggle() {
    const next = !closed;
    setClosed(next);
    try {
      window.localStorage.setItem(KEY, next ? "yes" : "no");
    } catch {
      // Without storage the panel simply opens again next time.
    }
  }
  return (
    <section data-testid="guide" data-open={closed ? "no" : "yes"} className="border-b border-slate-300 bg-amber-50 text-slate-900">
      <button
        type="button"
        data-testid="guide-toggle"
        aria-expanded={!closed}
        className="flex w-full items-center justify-between px-3 py-1 text-left text-xs font-semibold text-slate-800"
        onClick={toggle}
      >
        <span>{closed ? "▸" : "▾"} How to review</span>
        <span className="font-normal text-slate-600">{closed ? "Show" : "Hide"}</span>
      </button>
      {!closed && (
        <div className="grid grid-cols-[1fr_1.5fr_1.4fr_0.9fr] gap-4 px-3 pb-2 text-xs leading-snug">
          <div>
            <h2 className="font-semibold">{GUIDE.purpose.title}</h2>
            {GUIDE.purpose.text.map((line) => (
              <p key={line} className="mt-0.5">{line}</p>
            ))}
          </div>
          <div>
            <h2 className="font-semibold">{GUIDE.deciding.title}</h2>
            <ol className="mt-0.5 list-decimal pl-4">
              {GUIDE.deciding.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
          <div>
            <h2 className="font-semibold">{GUIDE.confidence.title}</h2>
            {GUIDE.confidence.text.map((line) => (
              <p key={line} className="mt-0.5">{line}</p>
            ))}
          </div>
          <div>
            <h2 className="font-semibold">{GUIDE.keys.title}</h2>
            <dl className="mt-0.5">
              {GUIDE.keys.list.map(([key, action]) => (
                <div key={key} className="flex gap-1.5">
                  <dt className="shrink-0 font-mono font-semibold">{key}</dt>
                  <dd>{action}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}
