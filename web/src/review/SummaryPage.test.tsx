import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type ReviewApi } from "../api/client";
import { SummaryPage } from "./SummaryPage";

const SNAPSHOT = {
  id: "s1",
  tender_id: "t1",
  reviewer: "Asha Rao",
  created_at: "2026-10-05T10:00:00Z",
  snapshot: {
    title: "600 MW solar",
    issuing_agency: "Acme",
    tender_type: "solar",
    reviewer: "Asha Rao",
    completed_at: "2026-10-05T10:00:00+00:00",
    decided: 2,
    total: 3,
    flagged: [],
    view: {
      fields: [
        { field_path: "a", label: "Bid deadline", section: "key_dates", value_type: "date", unit: null, decided: true, value: "2026-04-15", version_no: 2, version_kind: "amendment", evidence: [{ page_no: 1 }] },
        { field_path: "b", label: "Pre-bid meeting", section: "key_dates", value_type: "date", unit: null, decided: true, value: null, version_no: 1, version_kind: "original", evidence: [] },
        { field_path: "c", label: "EMD per MW", section: "guarantees", value_type: "money_inr", unit: "INR per MW", decided: false, value: null, version_no: null, version_kind: null, evidence: [] },
      ],
    },
  },
};

describe("SummaryPage", () => {
  it("shows the final values read-only with a download", async () => {
    const api = { snapshot: vi.fn(async () => SNAPSHOT) } as unknown as ReviewApi;
    render(<SummaryPage api={api} tenderId="t1" reviewHref="/review/x" />);
    expect(await screen.findByText("Review completed")).toBeInTheDocument();
    expect(screen.getByText(/reviewed by Asha Rao on 5 Oct 2026 · 2 of 3 fields decided/)).toBeInTheDocument();
    const rows = screen.getAllByTestId("summary-row");
    expect(within(rows[0]).getByText("15 Apr 2026")).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent("v2 amendment · p. 1");
    expect(rows[1]).toHaveTextContent("not in document");
    expect(rows[2]).toHaveTextContent("not decided");
    expect(screen.getByTestId("download-json")).toBeEnabled();
    expect(screen.queryByTestId("approve")).toBeNull();
  });

  it("says so when the review is not completed yet", async () => {
    const api = {
      snapshot: vi.fn(async () => {
        throw new ApiError(404, "not_found", "x", null, null);
      }),
    } as unknown as ReviewApi;
    render(<SummaryPage api={api} tenderId="t1" reviewHref="/review/x" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("has not been completed yet");
  });
});
