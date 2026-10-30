import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { FieldsSnapshot, SnapshotField, TenderStatus } from "../api/client";
import { daysUntil, filterFields, headline, needsAttention, sections } from "./terms";

const KEY = "tie_live_test_key";
const TENDER = "a".repeat(32);
const DOC = "d".repeat(32);

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function field(path: string, extra: Partial<SnapshotField> = {}): SnapshotField {
  return {
    path,
    section: path.split(".")[1],
    label: path.split(".").pop()!.replace(/_/g, " "),
    value_type: "number",
    unit: null,
    state: "value",
    source: "machine",
    value: 1,
    confidence: 0.95,
    version_no: 1,
    version_kind: "original",
    withdrawn_from_version: null,
    evidence: [{ document_id: DOC, filename: "RfS.pdf", page_no: 4, quote: "the quote", located: true }],
    needs_review: false,
    ...extra,
  };
}

const FIELDS: SnapshotField[] = [
  field("sector.power.common.total_capacity_mw", { label: "Total capacity", value: 600, value_type: "mw", unit: "MW" }),
  field("core.key_dates.bid_submission_deadline", {
    label: "Bid submission deadline",
    value: "2099-01-15",
    value_type: "date",
    evidence: [{ document_id: DOC, filename: "RfS.pdf", page_no: 7, quote: "Last date of bid submission 15.01.2099", located: true }],
  }),
  field("core.guarantees.emd_per_mw_inr", { label: "EMD per MW", value: 500000, value_type: "money_inr", unit: "INR per MW", confidence: 0.6 }),
  field("sector.power.common.tariff_ceiling_inr_per_kwh", {
    label: "Tariff ceiling",
    state: "withdrawn",
    value: null,
    withdrawn_from_version: 2,
    version_no: 2,
    version_kind: "amendment",
  }),
  field("core.eligibility.net_worth", { label: "Net worth", source: "approved", confidence: null }),
  field("core.eligibility.turnover", { label: "Turnover", state: "not_stated", value: null, evidence: [] }),
  field("core.summary.plain_english_summary", {
    label: "Summary",
    value_type: "long_text",
    value: "SECI invites bids for 600 MW of solar power [1].",
  }),
];

const SNAPSHOT: FieldsSnapshot = {
  contract_version: "1",
  tender_id: TENDER,
  slug: "seci-solar",
  title: "Selection of solar power developers for 600 MW",
  issuing_agency: "SECI",
  tender_type: "solar",
  external_ref: "SECI/2026/01",
  status: "extracted",
  current_version: 2,
  reviewed_version: null,
  publication: "unpublished",
  generated_at: "2026-10-30T00:00:00Z",
  fields: FIELDS,
  approved: 1,
  machine: 5,
  not_stated: 1,
  authority_note: "",
};

const STATUS: TenderStatus = {
  tender_id: TENDER,
  slug: "seci-solar",
  status: "extracted",
  tender_type: "solar",
  type_state: "set",
  type_confidence: null,
  current_version: 2,
  reviewed_version: null,
  publication: "unpublished",
  versions: [
    { version_no: 1, kind: "original", issued_on: null, stage: "validated", documents: [], runs: [], pending_jobs: [] },
    { version_no: 2, kind: "amendment", issued_on: null, stage: "validated", documents: [], runs: [], pending_jobs: [] },
  ],
  extraction_done: true,
};

const LIST = [
  {
    id: TENDER,
    slug: "seci-solar",
    title: SNAPSHOT.title,
    issuing_agency: "SECI",
    external_ref: "SECI/2026/01",
    tender_type: "solar",
    status: "extracted",
    current_version_no: 2,
    created_at: "2026-10-29T00:00:00Z",
    created_by: "api",
    type_source: "caller",
    type_state: "set",
  },
];

type Call = { url: string; init: RequestInit };

function stubApi(overrides: Record<string, () => Response> = {}) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    const path = url.replace("/api/v1", "").split("?")[0];
    const method = init.method ?? "GET";
    const custom = overrides[`${method} ${path}`];
    if (custom) return Promise.resolve(custom());
    if (path === "/tenders") return Promise.resolve(respond(200, LIST));
    if (path === `/tenders/${TENDER}/status`) return Promise.resolve(respond(200, STATUS));
    if (path === `/tenders/${TENDER}/fields`) return Promise.resolve(respond(200, SNAPSHOT));
    if (path === `/tenders/${TENDER}/amendments`)
      return Promise.resolve(respond(200, { tender_id: TENDER, title: SNAPSHOT.title, untouched: 0, versions: [] }));
    if (path.endsWith("/render")) return Promise.resolve(new Response(new Blob(["png"]), { status: 200 }));
    return Promise.resolve(respond(404, { error_type: "not_found", message: "Not found." }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:page", revokeObjectURL: () => undefined }));
});
afterEach(() => vi.unstubAllGlobals());

describe("terms", () => {
  it("reads the headline terms, skipping what the tender does not state", () => {
    const shown = headline(FIELDS).map((h) => h.label);
    expect(shown).toEqual(["Capacity", "Bids due", "Tariff ceiling", "EMD"]);
  });

  it("flags withdrawn, low-confidence and unlocated readings for a second look", () => {
    const flagged = FIELDS.filter(needsAttention).map((f) => f.label);
    expect(flagged).toEqual(["EMD per MW", "Tariff ceiling"]);
    const unlocated = field("x.y.z", { evidence: [{ document_id: DOC, page_no: 1, quote: "q", located: false }] });
    expect(needsAttention(unlocated)).toBe(true);
  });

  it("filters by search, by change and leaves the summary out of the sections", () => {
    expect(filterFields(FIELDS, "changed", "").map((f) => f.label)).toEqual(["Tariff ceiling"]);
    expect(filterFields(FIELDS, "all", "deadline").map((f) => f.label)).toEqual(["Bid submission deadline"]);
    expect(filterFields(FIELDS, "all", "").some((f) => f.state === "not_stated")).toBe(false);
    expect(sections(FIELDS).flatMap((s) => s.fields).some((f) => f.path.includes("summary"))).toBe(false);
  });

  it("counts the days to a date", () => {
    expect(daysUntil("2026-11-09", new Date(2026, 9, 30))).toBe(10);
    expect(daysUntil("not a date")).toBeNull();
  });
});

describe("the workspace", () => {
  it("asks for an access key, checks it, and keeps it in this browser", async () => {
    const calls = stubApi();
    render(<App path="/workspace" />);
    fireEvent.change(screen.getByLabelText("Access key"), { target: { value: KEY } });
    fireEvent.click(screen.getByRole("button", { name: "Open the workspace" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Add a tender" })).toBeInTheDocument();
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe(`Bearer ${KEY}`);
    expect(window.localStorage.getItem("tender-engine.workspace-key")).toBe(KEY);
    expect(await screen.findByRole("button", { name: /Selection of solar power developers/ })).toBeInTheDocument();
  });

  it("says plainly when a key is refused", async () => {
    stubApi({ "GET /tenders": () => respond(401, { error_type: "api_key_invalid", message: "Invalid key." }) });
    render(<App path="/workspace" />);
    fireEvent.change(screen.getByLabelText("Access key"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Open the workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That key was not accepted");
  });

  it("sends a dropped tender to the engine and opens it", async () => {
    window.localStorage.setItem("tender-engine.workspace-key", KEY);
    const calls = stubApi({
      "POST /tenders/submit": () =>
        respond(202, {
          tender_id: TENDER,
          slug: "seci-solar",
          version_no: 1,
          document_id: DOC,
          created: true,
          status_path: `/api/v1/tenders/${TENDER}/status`,
        }),
    });
    render(<App path="/workspace" />);
    const zone = await screen.findByRole("button", { name: /Drop the RfS or RfP here/ });
    const file = new File(["%PDF-1.7"], "RfS.pdf", { type: "application/pdf" });
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(await screen.findByText("RfS.pdf")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Tender type"), { target: { value: "solar" } });
    fireEvent.click(screen.getByRole("button", { name: "Read this tender" }));
    expect(await screen.findByRole("heading", { level: 1, name: SNAPSHOT.title })).toBeInTheDocument();
    const submit = calls.find((c) => c.url === "/api/v1/tenders/submit")!;
    const body = submit.init.body as FormData;
    expect((body.get("file") as File).name).toBe("RfS.pdf");
    expect(body.get("tender_type")).toBe("solar");
    expect(window.location.pathname).toBe(`/workspace/${TENDER}`);
  });

  it("refuses a zip pack with the reason and what to drop instead", async () => {
    window.localStorage.setItem("tender-engine.workspace-key", KEY);
    stubApi();
    render(<App path="/workspace" />);
    const zone = await screen.findByRole("button", { name: /Drop the RfS or RfP here/ });
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["PK"], "pack.zip")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Drop its main RfS or RfP document");
  });

  it("shows the analysis: headline terms, the requirements with their words, and the page behind them", async () => {
    window.localStorage.setItem("tender-engine.workspace-key", KEY);
    const calls = stubApi();
    render(<App path={`/workspace/${TENDER}`} />);
    expect(await screen.findByRole("heading", { level: 1, name: SNAPSHOT.title })).toBeInTheDocument();
    expect(screen.getByText("SECI invites bids for 600 MW of solar power.")).toBeInTheDocument();
    const strip = screen.getByText("Bids due").closest("dl")!;
    expect(within(strip).getByText("Withdrawn")).toBeInTheDocument();
    expect(within(strip).getByText("check this")).toBeInTheDocument();
    const requirements = screen.getByRole("region", { name: "Requirements" });
    expect(within(requirements).getByText("Approved")).toBeInTheDocument();
    expect(within(requirements).queryByText("Turnover")).toBeNull();
    fireEvent.click(within(requirements).getByRole("radio", { name: /Check these/ }));
    expect(within(requirements).queryByText("Net worth")).toBeNull();
    expect(within(requirements).getByText("EMD per MW")).toBeInTheDocument();
    fireEvent.click(within(requirements).getByRole("radio", { name: /Everything stated/ }));
    fireEvent.click(within(requirements).getByText(/Last date of bid submission/));
    const drawer = await screen.findByRole("complementary", { name: "Source page" });
    expect(within(drawer).getByRole("heading", { name: /Page 7/ })).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "Page 7" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === `/api/v1/documents/${DOC}/pages/7/render`)).toBe(true);
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary", { name: "Source page" })).toBeNull();
  });

  it("asks the tender a question and lists the pages the answer rests on", async () => {
    window.localStorage.setItem("tender-engine.workspace-key", KEY);
    const calls = stubApi({
      [`POST /tenders/${TENDER}/ask`]: () =>
        respond(200, {
          tender_id: TENDER,
          question: "What is the payment security?",
          version_no: 2,
          mode: "retrieval",
          source: "machine",
          answered: true,
          answer: "A letter of credit of one month's billing.",
          claims: [],
          citations: [{ n: 1, document_id: DOC, filename: "RfS.pdf", page_no: 31, quote: "letter of credit", resolved: true }],
          citations_resolved: 1,
          citations_total: 1,
        }),
    });
    render(<App path={`/workspace/${TENDER}`} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ask the tender" }));
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "What is the payment security?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("A letter of credit of one month's billing.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[1] page 31" })).toBeInTheDocument();
    const ask = calls.find((c) => c.url.endsWith("/ask"))!;
    expect(JSON.parse(ask.init.body as string)).toEqual({ question: "What is the payment security?" });
    expect((ask.init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("makes a review link for a named reviewer", async () => {
    window.localStorage.setItem("tender-engine.workspace-key", KEY);
    stubApi({
      [`POST /tenders/${TENDER}/review-link`]: () =>
        respond(201, { url: "https://engine/review/abc", tender_id: TENDER, reviewer_name: "Asha", expires_at: null }),
    });
    render(<App path={`/workspace/${TENDER}`} />);
    fireEvent.click(await screen.findByRole("button", { name: "Send for review" }));
    fireEvent.change(screen.getByLabelText("Reviewer's name"), { target: { value: "Asha" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the review link" }));
    expect(await screen.findByText("https://engine/review/abc")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Send this to Asha only/)).toBeInTheDocument());
  });
});
