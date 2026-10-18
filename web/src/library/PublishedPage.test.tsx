import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CHANGES, PUBLISHED, SUSPENDED, TENDER } from "./fixtures5c";
import { PublishedPage } from "./PublishedPage";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("PublishedPage", () => {
  it("shows reviewed facts with evidence, the gap with its reason, and the withdrawn value", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(respond(200, url.endsWith("/changes") ? CHANGES : PUBLISHED)),
      ),
    );
    render(<PublishedPage tenderId={TENDER.id} />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("2,000 MW FDRE power with CfD");
    expect(screen.getByRole("status")).toHaveTextContent("Update pending.");
    const rows = screen.getAllByTestId("published-field");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("8 Nov 2026".length ? "2026-11-08" : "")).toBeInTheDocument();
    const chip = within(rows[0]).getByRole("button", { name: "Amendment-02.pdf p.1" });
    fireEvent.click(chip);
    expect(within(rows[0]).getByText("extended to 08.11.2026")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/possibly superseded/)).toBeInTheDocument();
    expect(within(rows[2]).getByTestId("gap")).toHaveTextContent(
      "not reviewed — read by v5 (clause 17), awaiting the reviewer · likely page 2",
    );
    expect(within(rows[3]).getByText(/withdrawn by v5 \(stood since v1\)/)).toBeInTheDocument();
    expect(within(rows[3]).getByText("3.8 INR/kWh")).toHaveClass("line-through");
    expect(screen.getByText(/by an approver/)).toBeInTheDocument();
    expect(screen.getByText(/fdre fields 96% value, 100% evidence on 320 fields/)).toBeInTheDocument();
    expect(screen.getByText(/jouleWise's reviewed reading/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export PDF with page appendix" })).toHaveAttribute(
      "href",
      `/api/v1/tenders/${TENDER.id}/published.pdf`,
    );
  });

  it("withholds every value while publication is suspended and names the fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(200, SUSPENDED)));
    render(<PublishedPage tenderId={TENDER.id} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Publication suspended.");
    expect(screen.getByRole("alert")).toHaveTextContent("corrigendum (version 5, 8 Oct 2026)");
    expect(screen.getByRole("alert")).toHaveTextContent("core.key_dates.bid_submission_deadline");
    expect(screen.queryAllByTestId("published-field")).toHaveLength(0);
    expect(screen.queryByText("2026-11-08")).not.toBeInTheDocument();
    expect(screen.getByText("suspended")).toBeInTheDocument();
  });

  it("shows the changelog: old to new, removed, and what awaits review", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => Promise.resolve(respond(200, url.endsWith("/changes") ? CHANGES : PUBLISHED))),
    );
    render(<PublishedPage tenderId={TENDER.id} tab="changes" />);
    const versions = await screen.findAllByTestId("changes-version");
    expect(versions).toHaveLength(3);
    expect(within(versions[1]).getByText("Bid submission deadline")).toBeInTheDocument();
    expect(within(versions[1]).getByText("2026-10-20")).toBeInTheDocument();
    expect(within(versions[1]).getByText("2026-11-08")).toBeInTheDocument();
    expect(within(versions[2]).getByText("not yet reviewed")).toBeInTheDocument();
    expect(within(versions[2]).getByText(/awaiting review/)).toHaveTextContent("core.commercial.tariff_ceiling_inr_per_kwh");
    fireEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(screen.getAllByTestId("published-field")).toHaveLength(4);
  });
});
