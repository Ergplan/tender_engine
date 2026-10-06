import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { band, ReliabilityPage } from "./ReliabilityPage";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DATA = {
  generated_at: "2026-10-06T12:00:00Z",
  tenders_in_set: { solar: 3, fdre: 4 },
  gold_records: 1,
  tenders: [
    {
      slug: "nhpc-fdre-ii", tender_type: "fdre", issuing_agency: "NHPC", reviewer: "Asha Rao",
      completed_at: "2026-10-06T12:48:16+00:00", reviewed_version: 1, decided: 97, edited: 5, not_in_document: 15,
      edited_fields: ["sector.power.common.metering_point"],
      time: { started: "2026-10-05T17:33:00", completed: null, deciding_minutes: 54, sittings: 6, decisions: 110 },
      notable_misses: ["sector.power.common.metering_point (wrong_value)"],
    },
  ],
  summary: {
    scored: 79, value_correct: 78, value_accuracy: 0.987, evidence_scored: 64, evidence_correct: 64,
    evidence_accuracy: 1, needs_judgement: 18, by_field: {}, by_type: {}, by_section: {},
    by_type_field: {
      fdre: {
        "core.key_dates.bid_submission_deadline": { n: 1, correct: 1, accuracy: 1, evidence_n: 1, evidence_correct: 1, evidence_accuracy: 1, misses: 0 },
        "sector.power.common.metering_point": { n: 1, correct: 0, accuracy: 0, evidence_n: 1, evidence_correct: 1, evidence_accuracy: 1, misses: 1 },
      },
    },
    misses: [],
  },
  stability: {
    met: false, types_with_two_or_more_in_set: ["fdre", "solar"], types_short_of_two_reviews: ["fdre", "solar"],
    required_accuracy: 0.98, required_fields_below_floor: [], prompt_versions_seen: ["v1", "v3"],
    reasons: ["fewer than 2 reviewed tenders for: fdre, solar"],
  },
  prompt_comparison: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe("ReliabilityPage", () => {
  it("asks for the admin token, sends it in a header and shows the dashboard", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, DATA));
    vi.stubGlobal("fetch", fetchMock);
    render(<App path="/admin/reliability" />);
    fireEvent.change(screen.getByTestId("admin-token"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByText("Open"));
    expect(await screen.findByTestId("stability")).toHaveTextContent("Stability bar for Stage 5: not met");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/reliability");
    expect(init.headers["X-Admin-Token"]).toBe("s3cret");
    expect(init.headers["X-Review-Token"]).toBeUndefined();
    expect(screen.getByTestId("stability")).toHaveTextContent("fewer than 2 reviewed tenders for: fdre, solar");
    expect(screen.getByTestId("stability")).toHaveTextContent("Value accuracy 99% on 79 fields; evidence accuracy 100% on 64");
    const table = screen.getByTestId("accuracy-table");
    expect(table).toHaveTextContent("core.key_dates.bid_submission_deadline");
    expect(table).toHaveTextContent("100% (1)");
    expect(table).toHaveTextContent("0% (1)");
    expect(screen.getByTestId("tender-table")).toHaveTextContent("nhpc-fdre-ii");
    expect(screen.getByTestId("tender-table")).toHaveTextContent("54");
    expect(screen.getByText(/A comparison appears once more than one prompt version/)).toBeInTheDocument();
    expect(window.sessionStorage.getItem("admin_token")).toBe("s3cret");
  });

  it("shows the refusal and asks again when the token is wrong", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(401, { error_type: "admin_token_required", message: "An admin token is required for this page." })),
    );
    render(<ReliabilityPage />);
    fireEvent.change(screen.getByTestId("admin-token"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByText("Open"));
    expect(await screen.findByRole("alert")).toHaveTextContent("An admin token is required for this page.");
    expect(screen.getByTestId("admin-token")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("admin_token")).toBeNull();
  });

  it("bands accuracy green from 90%, amber from 75%, red below", () => {
    expect(band(0.95)).toContain("green");
    expect(band(0.9)).toContain("green");
    expect(band(0.8)).toContain("amber");
    expect(band(0.5)).toContain("red");
    expect(band(null)).toContain("slate");
  });
});
