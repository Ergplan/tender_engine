import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { GUIDE } from "./guide";
import { GuidePanel } from "./GuidePanel";

afterEach(() => window.localStorage.clear());

describe("GuidePanel", () => {
  it("is open the first time and says what the review is for and how to decide", () => {
    render(<GuidePanel />);
    expect(screen.getByTestId("guide").dataset.open).toBe("yes");
    expect(screen.getByText(/become the canonical record/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is published until you have approved it/)).toBeInTheDocument();
    expect(screen.getByText(/That is a correct answer, not a gap/)).toBeInTheDocument();
    expect(screen.getByText(/not a measure of whether the value is correct/)).toBeInTheDocument();
    expect(screen.getByText(/portal Tender ID/)).toBeInTheDocument();
    expect(screen.getByText("approve and go to the next undecided field")).toBeInTheDocument();
  });

  it("stays as the reviewer left it", () => {
    const first = render(<GuidePanel />);
    fireEvent.click(screen.getByTestId("guide-toggle"));
    expect(screen.getByTestId("guide").dataset.open).toBe("no");
    expect(screen.queryByText(/become the canonical record/)).toBeNull();
    first.unmount();
    render(<GuidePanel />);
    expect(screen.getByTestId("guide").dataset.open).toBe("no");
    fireEvent.click(screen.getByTestId("guide-toggle"));
    expect(screen.getByTestId("guide").dataset.open).toBe("yes");
  });
});

describe("docs/REVIEWER-GUIDE.md", () => {
  it("says everything the panel says", () => {
    const guide = readFileSync(resolve(__dirname, "../../../docs/REVIEWER-GUIDE.md"), "utf8");
    const lines = [
      ...GUIDE.purpose.text,
      ...GUIDE.deciding.steps,
      ...GUIDE.confidence.text,
      ...GUIDE.keys.list.map(([, action]) => action),
    ];
    for (const line of lines) expect(guide).toContain(line);
  });
});
