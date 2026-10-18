import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LibraryPage } from "./LibraryPage";
import { daysUntil, showValue } from "./format";
import { OTHER, PUBLISHED, TENDER } from "./fixtures5c";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function serve(routes: Record<string, unknown>) {
  return vi.fn((url: string) => {
    for (const [path, body] of Object.entries(routes)) if (url === `/api/v1${path}`) return Promise.resolve(respond(200, body));
    return Promise.resolve(respond(404, { error_type: "not_found", message: "no" }));
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("LibraryPage", () => {
  it("lists every tender with its publication state and review state", async () => {
    vi.stubGlobal(
      "fetch",
      serve({ "/tenders": [TENDER, OTHER], [`/tenders/${TENDER.id}/published`]: PUBLISHED }),
    );
    render(<LibraryPage />);
    const rows = await screen.findAllByTestId("tender-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("update pending")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/Completed 13 Oct 2026/)).toBeInTheDocument();
    expect(within(rows[0]).getByText(/8 Nov 2026/)).toBeInTheDocument();
    // The other tender has no published view: not published, not reviewed, no invented values.
    expect(within(rows[1]).getByText("not published")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Not reviewed")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
  });

  it("filters by search text and by type", async () => {
    vi.stubGlobal("fetch", serve({ "/tenders": [TENDER, OTHER], [`/tenders/${TENDER.id}/published`]: PUBLISHED }));
    render(<LibraryPage />);
    await screen.findAllByTestId("tender-row");
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "cni-1" } });
    expect(screen.getAllByTestId("tender-row")).toHaveLength(1);
    expect(screen.getByText("700 MW ISTS solar (CnI-1)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "fdre" } });
    expect(screen.getAllByTestId("tender-row")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "nothing of the kind" } });
    expect(screen.getByText("No tender matches.")).toBeInTheDocument();
  });

  it("shows the API's refusal in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(403, { error_type: "forbidden", message: "Not for you." })));
    render(<LibraryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Not for you.");
  });
});

describe("format", () => {
  it("prints values by their shape and counts the days to a date", () => {
    expect(showValue(928000, "INR")).toBe("9,28,000 INR");
    expect(showValue(["a", "b"])).toBe("a; b");
    expect(showValue({ basis: "per_mw", rate: 5, empty: null })).toBe("basis: per_mw · rate: 5");
    expect(showValue(true)).toBe("yes");
    expect(showValue(null)).toBe("");
    expect(daysUntil("2026-11-08", new Date(Date.UTC(2026, 9, 18)))).toBe(21);
    expect(daysUntil("2026-10-05", new Date(Date.UTC(2026, 9, 18)))).toBe(-13);
    expect(daysUntil(null)).toBeNull();
  });
});
