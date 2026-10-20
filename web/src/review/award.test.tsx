import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AwardReview, ReviewSession } from "../api/client";
import { awardReviewApi, toTenderReview } from "./award";
import { candidate, evidence, makeReview } from "./fixtures";
import { ReviewApp } from "./ReviewApp";

vi.mock("./pdfText", () => ({
  openPdf: async () => ({ renderPage: async () => undefined, drawPage: async () => undefined, close: () => undefined }),
}));

const AWARD = "a".repeat(32);
const DOC = "9".repeat(32);

const SESSION: ReviewSession = {
  object_type: "award",
  object_id: AWARD,
  tender_id: null,
  reviewer_name: "Asha Rao",
  expires_at: "2026-11-20T00:00:00Z",
  completed_at: null,
  round_no: 1,
  from_version: null,
};

function makeAward(): AwardReview {
  const base = makeReview();
  const winners = {
    ...base.fields[2],
    field_path: "result.award.winners",
    label: "Winners",
    section: "award_result",
    value_type: "record_list",
    required: true,
    review_order: 5,
    keys: [
      { name: "bidder", label: "Bidder", value_type: "text", unit: null, enum_values: null, min: null, max: null, keys: null },
      { name: "price", label: "Price", value_type: "decimal", unit: null, enum_values: null, min: 0, max: null, keys: null },
    ],
    entries: [
      {
        version_no: 1,
        version_kind: "original",
        state: {
          ...base.fields[2].entries[0].state,
          field_path: "result.award.winners",
          label: "Winners",
          group: "award_result",
          value_type: "record_list",
          candidate: candidate([{ bidder: "Sunsource Energy Private Limited", price: 6.95 }], {
            id: "c-winners",
            document_id: DOC,
            prompt_name: "import/re-tender-results",
            evidence: [evidence({ document_id: DOC, page_no: 1, quote: "Sunsource Energy Private Limited", ordinal: 1 })],
          }),
        },
      },
    ],
    current: 0,
    decided: false,
    flagged: false,
  } as AwardReview["fields"][number];
  return {
    award_id: AWARD,
    object_type: "award",
    title: "SECI000013_result_1.pdf",
    procurer: "SECI",
    reference: "SECI/C&P/IPP/13/0001/19-20",
    result_kind: "auction_result",
    status: "imported",
    document_id: DOC,
    source_url: "https://www.seci.co.in/Upload/Bidder/1.pdf",
    source_sha256: "f".repeat(64),
    dataset: "RE-tender-results@f6d1d33",
    verification: "Official SECI result publication",
    tender_id: null,
    tender_link_basis: null,
    tender_link_page: null,
    versions: [{ version_no: 1, kind: "original", issued_on: null, documents: [{ document_id: DOC, role: "result", filename: "SECI000013_result_1.pdf", page_count: 1 }] }],
    sections: [{ name: "award_result", label: "Award result", order: 1 }],
    fields: [winners],
    decided: 0,
    total: 1,
    required_undecided: 1,
    can_complete: false,
  };
}

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("an award on the reviewer screen", () => {
  it("is shown through the tender's shape with its object id as the screen's id", () => {
    const review = toTenderReview(makeAward());
    expect(review.tender_id).toBe(AWARD);
    expect(review.tender_type).toBe("award");
    expect(review.issuing_agency).toContain("SECI");
    expect(review.fields[0].field_path).toBe("result.award.winners");
    expect(review.round).toBeNull();
  });

  it("points the review and its completion at the award routes", async () => {
    const award = makeAward();
    const api = {
      award: vi.fn(async () => award),
      completeAward: vi.fn(async () => ({}) as never),
      review: vi.fn(),
      complete: vi.fn(),
    } as unknown as Parameters<typeof awardReviewApi>[0];
    const wrapped = awardReviewApi(api, AWARD);
    expect((await wrapped.review("ignored")).tender_id).toBe(AWARD);
    await wrapped.complete("ignored");
    expect(api.completeAward).toHaveBeenCalledWith(AWARD);
    expect(api.review).not.toHaveBeenCalled();
    expect(api.complete).not.toHaveBeenCalled();
  });

  it("opens an award link into the split screen over the publication", async () => {
    const award = makeAward();
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/review-session")) return Promise.resolve(respond(200, SESSION));
      if (url.endsWith(`/awards/${AWARD}/review`)) return Promise.resolve(respond(200, award));
      if (url.endsWith(`/documents/${DOC}`)) return Promise.resolve(respond(200, { id: DOC, file_url: `/files/documents/${DOC}.pdf` }));
      if (url.endsWith(`/documents/${DOC}/pages`))
        return Promise.resolve(respond(200, [{ page_no: 1, width: 595, height: 842, has_text_layer: true, render_url: "/r/1.png" }]));
      if (url.endsWith(`/documents/${DOC}/sections`)) return Promise.resolve(respond(200, []));
      return Promise.resolve(respond(404, { error_type: "not_found", message: "no" }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ReviewApp token={"A".repeat(32)} page="review" />);
    expect(await screen.findByTestId("tender-title")).toHaveTextContent("SECI000013_result_1.pdf");
    expect(screen.getByText("Winners")).toBeInTheDocument();
    expect(screen.getByTestId("reviewer-name")).toHaveTextContent("Asha Rao");
    const calls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(calls.some((url) => url.includes(`/awards/${AWARD}/review`))).toBe(true);
    expect(calls.some((url) => url.includes("/tenders/"))).toBe(false);
  });
});
