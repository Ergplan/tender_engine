import { useEffect, useRef, useState } from "react";

import type { WorkspaceApi } from "../api/client";

export type PageRef = { documentId: string; filename?: string | null; pageNo: number; quote: string; label?: string };

/** The page an answer comes from, beside the analysis: the quote as the tender words it,
 * and the page itself to read around it. */
export function PageDrawer({ api, page, onClose }: { api: WorkspaceApi; page: PageRef; onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pageNo, setPageNo] = useState(page.pageNo);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => setPageNo(page.pageNo), [page]);
  useEffect(() => closeButton.current?.focus(), [page]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setSrc(null);
    setError(null);
    api
      .pageImage(page.documentId, pageNo)
      .then((made) => {
        url = made;
        if (cancelled) URL.revokeObjectURL(made);
        else setSrc(made);
      })
      .catch(() => {
        if (!cancelled) setError("This page's image is not available yet.");
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, page.documentId, pageNo]);

  return (
    <aside
      aria-label="Source page"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-[640px] flex-col border-l border-[#dde4e2] bg-white shadow-2xl"
    >
      <header className="flex items-start gap-3 border-b border-[#dde4e2] px-5 py-4">
        <div className="min-w-0 flex-1">
          {page.label && <p className="text-xs text-[#5b6b70]">{page.label}</p>}
          <h2 className="truncate text-base font-semibold">
            Page {pageNo}
            {page.filename ? <span className="font-normal text-[#5b6b70]"> of {page.filename}</span> : null}
          </h2>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous page"
            disabled={pageNo <= 1}
            onClick={() => setPageNo((n) => Math.max(1, n - 1))}
            className="h-9 w-9 rounded-md border border-[#dde4e2] text-lg disabled:opacity-30"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Next page"
            onClick={() => setPageNo((n) => n + 1)}
            className="h-9 w-9 rounded-md border border-[#dde4e2] text-lg"
          >
            ›
          </button>
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            className="ml-2 h-9 rounded-md border border-[#dde4e2] px-3 text-sm"
          >
            Close
          </button>
        </div>
      </header>
      {page.quote && pageNo === page.pageNo && (
        <blockquote className="mx-5 mt-4 rounded-md bg-[#fff8db] px-4 py-3 font-serif text-[15px] leading-7 text-[#3b3320]">
          <span className="bg-[#fde68a] box-decoration-clone px-0.5">{page.quote}</span>
        </blockquote>
      )}
      <div className="flex-1 overflow-auto bg-[#eef1f0] p-5">
        {error ? (
          <p role="alert" className="text-sm text-[#9f1239]">
            {error}
          </p>
        ) : src ? (
          <img src={src} alt={`Page ${pageNo}`} className="mx-auto w-full max-w-[560px] bg-white shadow" />
        ) : (
          <p className="text-sm text-[#5b6b70]">Loading the page…</p>
        )}
      </div>
    </aside>
  );
}
