/**
 * The four MCP Apps widgets render their fixtures in a real DOM with their own scripts:
 * the tool result arrives by the host's postMessage notification, the not_reviewed gap is
 * visible with its reason (never a blank cell), and a bridge call goes out as JSON-RPC.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

const WIDGETS = resolve(__dirname, "../../../mcp/widgets");

function load(name: string) {
  const html = readFileSync(resolve(WIDGETS, `${name}.html`), "utf8");
  const fixture = JSON.parse(readFileSync(resolve(WIDGETS, "fixtures", `${name}.json`), "utf8"));
  const posted: unknown[] = [];
  const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
  // The host side of the bridge: whatever the iframe posts to its parent lands here.
  const parent = { postMessage: (m: unknown) => posted.push(m) };
  Object.defineProperty(dom.window, "parent", { value: parent });
  return { dom, fixture, posted };
}

function answer(dom: JSDOM, posted: unknown[], result: unknown) {
  // The host answers the widget's last tools/call with a result carrying a data: image.
  const call = [...posted].reverse().find((m: any) => m.method === "tools/call") as any;
  dom.window.dispatchEvent(
    new dom.window.MessageEvent("message", { data: { jsonrpc: "2.0", id: call.id, result: { structuredContent: result } } }),
  );
  return call;
}

const PAGE = { image_data_url: "data:image/png;base64,iVBORw0KGgo=", text: "Clause 40.3 stands deleted. Bidders shall quote the tariff without any ceiling", quote_located: true };

function deliver(dom: JSDOM, data: unknown) {
  dom.window.dispatchEvent(
    new dom.window.MessageEvent("message", {
      data: { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: { structuredContent: data } },
    }),
  );
}

describe("tender_card", () => {
  it("renders the fixture: banner, fields, the gap with its reason, the footer", () => {
    const { dom, fixture, posted } = load("tender_card");
    deliver(dom, fixture);
    const doc: Document = dom.window.document;
    expect(doc.querySelector("h1")?.textContent).toContain("CfD-I");
    expect(doc.querySelector(".banner")?.textContent).toContain("not yet reviewed");
    const gap = doc.querySelector(".gap");
    expect(gap?.textContent).toContain("Not reviewed");
    expect(gap?.textContent).toContain("page 12");
    expect(doc.querySelectorAll(".chip").length).toBeGreaterThan(2);
    expect(doc.body.textContent).toContain("possibly superseded");
    expect(doc.body.textContent).toContain("Reliability: fdre 96% on 320 fields");
    expect(doc.body.textContent).toContain("The tender document is the authoritative source");
    // The handshake is posted while the script loads, before this test can stand in for the
    // host; the Python widget test asserts its presence in the file.
    expect(posted.filter((m: any) => m.method === "tools/call")).toEqual([]);
  });

  it("asks the host for a page through the bridge when a chip is clicked", () => {
    const { dom, fixture, posted } = load("tender_card");
    deliver(dom, fixture);
    const chip = dom.window.document.querySelector("button.chip") as HTMLButtonElement;
    chip.click();
    const call = answer(dom, posted, { ...PAGE, text: "The last date of bid submission is extended to 08.11.2026 at 15:00 hrs" });
    expect(call.params.name).toBe("get_document_page");
    expect(call.params.arguments).toEqual({ document_id: "c".repeat(32), page_no: 1, quote: "The last date of bid submission is extended to 08.11.2026" });
    return new Promise<void>((done) => setTimeout(() => {
      const img = dom.window.document.querySelector(".page img") as HTMLImageElement;
      expect(img.getAttribute("src")?.startsWith("data:")).toBe(true);
      expect(dom.window.document.querySelector(".page mark")?.textContent).toContain("08.11.2026");
      done();
    }, 20));
  });

  it("accepts the result wrapped under a key as well as flat", () => {
    const { dom, fixture } = load("tender_card");
    deliver(dom, { tender: fixture });
    expect(dom.window.document.querySelector("h1")?.textContent).toContain("CfD-I");
  });
});

describe("financial_model", () => {
  it("locks the fixed parameters, marks assumptions assumed, shows the gap and the outputs", () => {
    const { dom, fixture, posted } = load("financial_model");
    deliver(dom, fixture);
    const doc: Document = dom.window.document;
    expect(doc.querySelector(".panel.fixed")?.textContent).toContain("CUF floor");
    expect(doc.querySelector(".panel.fixed .gap")?.textContent).toContain("not reviewed — the reviewer has not decided");
    expect(doc.querySelector(".panel.fixed")?.textContent).toContain("not in schema");
    expect(doc.querySelector(".panel.fixed .chip")?.textContent).toBe("RfS p.1");
    expect(doc.querySelector(".panel.assume")?.textContent).toContain("assumed, not from the tender");
    expect(doc.querySelectorAll("input[type=range]").length).toBe(11);
    expect(doc.querySelector("#outputs")?.textContent).toContain("Project IRR");
    expect(doc.querySelector("#outputs")?.textContent).toContain("9.17%");
    expect(doc.querySelector("svg")).not.toBeNull();
    expect(doc.body.textContent).toContain("indicative");
    (doc.querySelector(".panel.fixed .chip") as HTMLButtonElement).click();
    const call = answer(dom, posted, PAGE);
    expect(call.params.arguments).toEqual({ document_id: "a".repeat(32), page_no: 1, quote: "700 MW ISTS-connected Solar PV" });
    return new Promise<void>((done) => setTimeout(() => {
      expect((doc.querySelector(".panel.fixed .page img") as HTMLImageElement).getAttribute("src")?.startsWith("data:")).toBe(true);
      done();
    }, 20));
  });

  it("shows a provisional figure from its own engine and asks the server for the real one", () => {
    const { dom, fixture, posted } = load("financial_model");
    deliver(dom, fixture);
    const w = dom.window as any;
    w.__provisional();
    expect(dom.window.document.querySelector("#outputs")?.textContent).toContain("(provisional)");
    const own = w.TenderFinance.powerProjectFinance(
      { capacity_mw: 700, tariff_inr_per_kwh: null, cuf_floor_percent: 17, cuf_ceiling_percent: 30, ppa_tenure_years: 25, degradation_cap_percent: 0.5, sources: {} },
      fixture.assumptions,
    );
    expect(own.used.tariff).toBe("assumed");
    expect(own.project_irr_percent).toBeGreaterThan(0);
    return new Promise<void>((done) => {
      setTimeout(() => {
        const call = posted.find((m: any) => m.method === "tools/call" && m.params.name === "model_tender") as any;
        expect(call.params.arguments.model_type).toBe("power_project_finance");
        expect(call.params.arguments.tender_id).toBe(fixture.tender_id);
        done();
      }, 600);
    });
  });
});

describe("changes_view", () => {
  it("renders the timeline, the selected version's changes with evidence, and pending paths", () => {
    const { dom, fixture, posted } = load("changes_view");
    deliver(dom, fixture);
    const doc: Document = dom.window.document;
    expect(doc.querySelectorAll(".timeline button").length).toBe(4);
    // The latest version is selected first: unreviewed, paths only.
    expect(doc.querySelector(".banner")?.textContent).toContain("not yet reviewed");
    expect(doc.querySelector(".pending:not(.summary)")?.textContent).toContain("core.commercial.tariff_ceiling_inr_per_kwh");
    expect(doc.querySelectorAll(".change").length).toBe(0);
    (doc.querySelectorAll(".timeline button")[2] as HTMLButtonElement).click();
    expect(doc.querySelectorAll(".change").length).toBe(1);
    expect(doc.querySelector(".change")?.textContent).toContain("2026-10-20");
    expect(doc.querySelector(".change")?.textContent).toContain("2026-11-08");
    expect(doc.querySelector(".change .chip")?.textContent).toContain("Amendment-02 p.1");
    (doc.querySelector(".change .chip") as HTMLButtonElement).click();
    const call = answer(dom, posted, { ...PAGE, text: "The last date of bid submission is extended to 08.11.2026" });
    expect(call.params.name).toBe("get_document_page");
    return new Promise<void>((done) => setTimeout(() => {
      expect((doc.querySelector(".change .page img") as HTMLImageElement).getAttribute("src")?.startsWith("data:")).toBe(true);
      done();
    }, 20));
  });

  it("accepts the changelog wrapped under a key", () => {
    const { dom, fixture } = load("changes_view");
    deliver(dom, { changelog: fixture });
    expect(dom.window.document.querySelectorAll(".timeline button").length).toBe(4);
  });
});

describe("comparison_table", () => {
  it("renders tenders as columns, marks the gaps, sorts by a column, and exports its own CSV", () => {
    const { dom, fixture, posted } = load("comparison_table");
    deliver(dom, fixture);
    const doc: Document = dom.window.document;
    expect(doc.querySelectorAll("thead th").length).toBe(3);
    expect(doc.querySelectorAll("tbody tr").length).toBe(4);
    expect(doc.querySelectorAll("td .gap").length).toBe(2);
    expect(doc.body.textContent).toContain("Left out");
    const rowsBefore = Array.from(doc.querySelectorAll("tbody tr td:first-child .path")).map((e: Element) => e.textContent);
    (doc.querySelectorAll("thead th button")[1] as HTMLButtonElement).click();
    const rowsAfter = Array.from(doc.querySelectorAll("tbody tr td:first-child .path")).map((e: Element) => e.textContent);
    expect(rowsAfter).not.toEqual(rowsBefore);
    // The second button is the CnI-1 column: its not_reviewed cell sorts last.
    expect(rowsAfter[rowsAfter.length - 1]).toBe("core.commercial.tariff_ceiling_inr_per_kwh");
    expect(doc.querySelector("#export")).not.toBeNull();
    (doc.querySelector("td .chip") as HTMLButtonElement).click();
    const call = answer(dom, posted, { ...PAGE, text: "2000 MW FDRE power" });
    expect(call.params.name).toBe("get_document_page");
    expect(Object.keys(call.params.arguments).sort()).toEqual(["document_id", "page_no", "quote"]);
    return new Promise<void>((done) => setTimeout(() => {
      expect((doc.querySelector("td .page img") as HTMLImageElement).getAttribute("src")?.startsWith("data:")).toBe(true);
      done();
    }, 20));
  });

  it("accepts the comparison wrapped under a key", () => {
    const { dom, fixture } = load("comparison_table");
    deliver(dom, { comparison: fixture });
    expect(dom.window.document.querySelectorAll("thead th").length).toBe(3);
  });
});
