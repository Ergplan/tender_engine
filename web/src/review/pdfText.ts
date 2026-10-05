// pdf.js, loaded only when a page's text layer is first needed. The page images come
// pre-rendered from the server, so the first page shows before pdf.js has started; pdf.js
// reads the PDF by range requests and lays the selectable text over the images.
import type { PDFDocumentProxy } from "pdfjs-dist";

type PdfJs = typeof import("pdfjs-dist");
let library: Promise<PdfJs> | null = null;

function pdfjs(): Promise<PdfJs> {
  if (!library) {
    library = Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
    ]).then(([lib, worker]) => {
      lib.GlobalWorkerOptions.workerSrc = worker.default;
      return lib;
    });
  }
  return library;
}

export type TextSource = {
  /** Lay the page's selectable text into `container`, sized for `scale` px per PDF point. */
  renderPage: (pageNo: number, container: HTMLElement, scale: number) => Promise<void>;
  /** Draw the page itself, for a page that has no server-side image. */
  drawPage: (pageNo: number, canvas: HTMLCanvasElement, scale: number) => Promise<void>;
  close: () => void;
};

export async function openPdf(url: string): Promise<TextSource> {
  const lib = await pdfjs();
  const task = lib.getDocument({
    url,
    withCredentials: true,
    rangeChunkSize: 262144,
    disableAutoFetch: true,
    disableStream: true,
  });
  const document: PDFDocumentProxy = await task.promise;
  return {
    async renderPage(pageNo, container, scale) {
      const page = await document.getPage(pageNo);
      const viewport = page.getViewport({ scale });
      container.replaceChildren();
      container.style.setProperty("--scale-factor", String(scale));
      container.style.setProperty("--total-scale-factor", String(scale));
      const layer = new lib.TextLayer({
        textContentSource: page.streamTextContent(),
        container,
        viewport,
      });
      await layer.render();
    },
    async drawPage(pageNo, canvas, scale) {
      const page = await document.getPage(pageNo);
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await page.render({ canvas, viewport }).promise;
    },
    close: () => void task.destroy(),
  };
}
