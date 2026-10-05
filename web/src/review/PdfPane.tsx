import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { PageInfo, ReviewApi, ReviewVersion, SearchHit, SectionInfo } from "../api/client";
import type { PdfTarget } from "./model";
import type { TextSource } from "./pdfText";

/** A passage of the focused field's evidence. The one being shown is `active`; the others
 * are drawn faintly, so that several passages on one page can be told apart. */
export type Highlight = { pageNo: number; bbox: number[] | null; active?: boolean };
const GAP = 12;

function Box({ bbox, page, scale, className, testId }: {
  bbox: number[] | null;
  page: PageInfo;
  scale: number;
  className: string;
  testId: string;
}) {
  // No box: the quote was not located, so the whole page is outlined.
  const [x0, top, x1, bottom] = bbox ?? [0, 0, page.width, page.height];
  return (
    <div
      data-testid={testId}
      className={"pointer-events-none absolute " + className + (bbox ? "" : " border-2 border-dashed bg-transparent")}
      style={{
        left: x0 * scale - 2,
        top: top * scale - 2,
        width: (x1 - x0) * scale + 4,
        height: (bottom - top) * scale + 4,
      }}
    />
  );
}

/** The PDF: continuous scroll, thumbnails, search, bookmarks and the highlight layer. */
export function PdfPane({
  api,
  versions,
  documentId,
  onDocument,
  highlights,
  target,
}: {
  api: ReviewApi;
  versions: ReviewVersion[];
  documentId: string;
  onDocument: (documentId: string) => void;
  highlights: Highlight[];
  target: PdfTarget | null;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [sections, setSections] = useState<SectionInfo[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [width, setWidth] = useState(700);
  const [zoom, setZoom] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [panel, setPanel] = useState<"none" | "thumbnails" | "bookmarks">("none");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [hitIndex, setHitIndex] = useState(0);
  const [pulse, setPulse] = useState<(Highlight & { key: number }) | null>(null);
  const [visible, setVisible] = useState<Set<number>>(new Set());
  const source = useRef<Promise<TextSource> | null>(null);

  // The document: its pages (sizes first, so the layout is known before anything is drawn).
  useEffect(() => {
    let cancelled = false;
    setPages([]);
    setHits(null);
    setQuery("");
    setFailure(null);
    setVisible(new Set());
    source.current = null;
    Promise.all([api.pages(documentId), api.document(documentId), api.sections(documentId)])
      .then(([pageList, info, sectionList]) => {
        if (cancelled) return;
        setPages(pageList);
        setFileUrl(info.file_url);
        setSections(sectionList);
      })
      .catch(() => !cancelled && setFailure("The document could not be loaded. Reload the page."));
    return () => {
      cancelled = true;
      void source.current?.then((opened) => opened.close()).catch(() => undefined);
    };
  }, [api, documentId]);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const widest = useMemo(() => Math.max(1, ...pages.map((page) => page.width)), [pages]);
  const scale = (Math.max(width - 2 * GAP - 16, 200) / widest) * zoom;
  const offsets = useMemo(() => {
    const tops: number[] = [];
    let top = GAP;
    for (const page of pages) {
      tops.push(top);
      top += page.height * scale + GAP;
    }
    return tops;
  }, [pages, scale]);

  const scrollTo = useCallback(
    (pageNo: number, bbox: number[] | null) => {
      const element = scroller.current;
      const index = pages.findIndex((page) => page.page_no === pageNo);
      if (!element || index === -1) return;
      const within = bbox ? bbox[1] * scale - element.clientHeight / 3 : -GAP / 2;
      element.scrollTop = Math.max(offsets[index] + within, 0);
      setCurrentPage(pageNo);
    },
    [pages, offsets, scale],
  );

  // A request to show a place: switch document if needed, then scroll and pulse.
  const shown = useRef<number | null>(null);
  useEffect(() => {
    if (!target || shown.current === target.key) return;
    if (target.documentId !== documentId) return onDocument(target.documentId);
    if (pages.length === 0) return;
    shown.current = target.key;
    scrollTo(target.pageNo, target.bbox);
    setPulse({ pageNo: target.pageNo, bbox: target.bbox, key: target.key });
  }, [target, documentId, pages, scrollTo, onDocument]);

  // Which pages are on screen: the current page number, and the pages that get their text.
  const onScroll = useCallback(() => {
    const element = scroller.current;
    if (!element || pages.length === 0) return;
    const top = element.scrollTop;
    const bottom = top + element.clientHeight;
    const middle = top + element.clientHeight / 3;
    const on = new Set<number>();
    let current = pages[0].page_no;
    pages.forEach((page, index) => {
      const start = offsets[index];
      const end = start + page.height * scale;
      if (end >= top - 400 && start <= bottom + 400) on.add(page.page_no);
      if (start <= middle) current = page.page_no;
    });
    setCurrentPage(current);
    setVisible((before) =>
      before.size === on.size && [...on].every((page) => before.has(page)) ? before : on,
    );
  }, [pages, offsets, scale]);
  useEffect(onScroll, [onScroll]);

  async function search(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (query.trim().length < 2) return setHits(null);
    try {
      const found = await api.search(documentId, query.trim());
      setHits(found);
      setHitIndex(0);
      if (found.length > 0) showHit(found, 0);
    } catch {
      setHits([]);
    }
  }
  function showHit(list: SearchHit[], index: number) {
    const hit = list[index];
    setHitIndex(index);
    scrollTo(hit.page_no, hit.bbox ?? null);
    setPulse({ pageNo: hit.page_no, bbox: hit.bbox ?? null, key: Date.now() });
  }

  const textSource = useCallback((): Promise<TextSource> | null => {
    if (!fileUrl) return null;
    if (!source.current) source.current = import("./pdfText").then((module) => module.openPdf(fileUrl));
    return source.current;
  }, [fileUrl]);

  const documentCount = versions.reduce((count, version) => count + version.documents.length, 0);
  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-200" data-testid="pdf-pane" data-document-id={documentId}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-300 bg-white px-2 py-1 text-xs">
        {documentCount > 1 ? (
          <select
            data-testid="version-select"
            aria-label="Version and document"
            className="max-w-[16rem] rounded border border-slate-300 px-1 py-0.5"
            value={documentId}
            onChange={(event) => onDocument(event.target.value)}
          >
            {versions.map((version) => (
              <optgroup key={version.version_no} label={`v${version.version_no} ${version.kind}${version.issued_on ? ` · ${version.issued_on}` : ""}`}>
                {version.documents.map((document) => (
                  <option key={document.document_id} value={document.document_id}>
                    v{version.version_no} · {document.filename}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        ) : (
          <span className="max-w-[16rem] truncate font-medium">{versions[0]?.documents[0]?.filename}</span>
        )}
        <span data-testid="page-indicator" data-page={currentPage} className="tabular-nums text-slate-700">
          Page {currentPage} of {pages.length}
        </span>
        <button type="button" className="rounded border border-slate-300 px-1.5" title="Zoom out" onClick={() => setZoom(Math.max(zoom - 0.2, 0.6))}>−</button>
        <button type="button" className="rounded border border-slate-300 px-1.5" title="Zoom in" onClick={() => setZoom(Math.min(zoom + 0.2, 2.4))}>+</button>
        <button type="button" className={"rounded border px-1.5 " + (panel === "thumbnails" ? "border-sky-500 bg-sky-50" : "border-slate-300")} onClick={() => setPanel(panel === "thumbnails" ? "none" : "thumbnails")}>
          Pages
        </button>
        <button type="button" data-testid="bookmarks-toggle" className={"rounded border px-1.5 " + (panel === "bookmarks" ? "border-sky-500 bg-sky-50" : "border-slate-300")} onClick={() => setPanel(panel === "bookmarks" ? "none" : "bookmarks")}>
          Contents
        </button>
        <form className="ml-auto flex items-center gap-1" onSubmit={search}>
          <input
            type="search"
            data-testid="pdf-search"
            aria-label="Search the document"
            placeholder="Search the document"
            className="w-40 rounded border border-slate-300 px-1.5 py-0.5"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {hits && (
            <span data-testid="search-count" className="text-slate-600">
              {hits.length === 0 ? "not found" : `${hitIndex + 1}/${hits.length}`}
            </span>
          )}
          {hits && hits.length > 1 && (
            <>
              <button type="button" className="rounded border border-slate-300 px-1" title="Previous" onClick={() => showHit(hits, (hitIndex - 1 + hits.length) % hits.length)}>↑</button>
              <button type="button" className="rounded border border-slate-300 px-1" title="Next" onClick={() => showHit(hits, (hitIndex + 1) % hits.length)}>↓</button>
            </>
          )}
        </form>
      </div>
      <div className="flex min-h-0 flex-1">
        {panel === "thumbnails" && (
          <div className="w-28 shrink-0 overflow-y-auto border-r border-slate-300 bg-slate-100 p-1.5" data-testid="thumbnails">
            {pages.map((page) => (
              <button
                key={page.page_no}
                type="button"
                className={"mb-1.5 block w-full border-2 bg-white " + (page.page_no === currentPage ? "border-sky-500" : "border-transparent")}
                onClick={() => scrollTo(page.page_no, null)}
              >
                {page.render_url && (
                  <img src={page.render_url} loading="lazy" alt="" width={96} height={Math.round((96 * page.height) / page.width)} />
                )}
                <span className="block text-center text-[10px] text-slate-600">{page.page_no}</span>
              </button>
            ))}
          </div>
        )}
        {panel === "bookmarks" && (
          <div className="w-56 shrink-0 overflow-y-auto border-r border-slate-300 bg-white p-1.5 text-xs" data-testid="bookmarks">
            {sections.length === 0 && <p className="text-slate-500">No contents for this document.</p>}
            {sections.map((section) => (
              <button
                key={section.id}
                type="button"
                className="block w-full truncate rounded px-1 py-0.5 text-left hover:bg-slate-100"
                title={section.heading}
                onClick={() => scrollTo(section.start_page, null)}
              >
                <span className="mr-1 tabular-nums text-slate-500">{section.start_page}</span>
                {section.heading}
              </button>
            ))}
          </div>
        )}
        <div ref={scroller} className="min-w-0 flex-1 overflow-auto" onScroll={onScroll} data-testid="pdf-scroller">
          {failure && <p role="alert" className="p-4 text-sm text-red-700">{failure}</p>}
          {pages.map((page) => (
            <div
              key={page.page_no}
              data-page-no={page.page_no}
              data-testid="pdf-page"
              className="relative mx-auto bg-white shadow"
              style={{ width: page.width * scale, height: page.height * scale, marginTop: GAP, marginBottom: GAP }}
            >
              {page.render_url ? (
                <img
                  src={page.render_url}
                  loading={page.page_no <= 2 ? "eager" : "lazy"}
                  alt={`Page ${page.page_no}`}
                  draggable={false}
                  className="absolute inset-0 h-full w-full select-none"
                />
              ) : (
                visible.has(page.page_no) && <DrawnPage pageNo={page.page_no} scale={scale} source={textSource} />
              )}
              {visible.has(page.page_no) && page.has_text_layer && (
                <TextLayer pageNo={page.page_no} scale={scale} source={textSource} />
              )}
              {(hits ?? [])
                .filter((hit) => hit.page_no === page.page_no && hit.bbox)
                .map((hit, index) => (
                  <Box key={`hit-${index}`} bbox={hit.bbox ?? null} page={page} scale={scale} className="bg-yellow-300/40" testId="search-hit" />
                ))}
              {highlights
                .filter((highlight) => highlight.pageNo === page.page_no)
                .map((highlight, index) => (
                  <Box
                    key={`mark-${index}`}
                    bbox={highlight.bbox}
                    page={page}
                    scale={scale}
                    className={
                      highlight.active
                        ? "rounded-sm border border-sky-600 bg-sky-400/30"
                        : "rounded-sm border border-dashed border-slate-400 bg-slate-400/10"
                    }
                    testId={highlight.active ? "evidence-highlight" : "evidence-highlight-dim"}
                  />
                ))}
              {pulse && pulse.pageNo === page.page_no && (
                <Box key={pulse.key} bbox={pulse.bbox} page={page} scale={scale} className="animate-pulse-once rounded-sm border-amber-500 bg-amber-300/40" testId="evidence-pulse" />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TextLayer({ pageNo, scale, source }: {
  pageNo: number;
  scale: number;
  source: () => Promise<TextSource> | null;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    const container = element.current;
    const opened = source();
    if (!container || !opened) return;
    opened
      .then((pdf) => (cancelled ? undefined : pdf.renderPage(pageNo, container, scale)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pageNo, scale, source]);
  return <div ref={element} className="textLayer" data-testid="text-layer" />;
}

function DrawnPage({ pageNo, scale, source }: {
  pageNo: number;
  scale: number;
  source: () => Promise<TextSource> | null;
}) {
  const element = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = element.current;
    const opened = source();
    if (!canvas || !opened) return;
    opened.then((pdf) => pdf.drawPage(pageNo, canvas, scale)).catch(() => undefined);
  }, [pageNo, scale, source]);
  return <canvas ref={element} className="absolute inset-0 h-full w-full" />;
}
