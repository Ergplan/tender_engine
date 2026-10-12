import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewApi, TenderAmendments } from "../api/client";
import { AmendmentsPage } from "./AmendmentsPage";
import { DOC, makeAmendments, makeReview, SESSION } from "./fixtures";

vi.mock("./pdfText", () => ({
  openPdf: async () => ({ renderPage: async () => undefined, drawPage: async () => undefined, close: () => undefined }),
}));

function fakeApi(amendments: TenderAmendments) {
  const state = { amendments };
  const api = {
    amendments: vi.fn(async () => state.amendments),
    decide: vi.fn(async (body: { candidate_id: string; decision: string; note?: string | null }) => {
      const next = structuredClone(state.amendments);
      for (const version of next.versions)
        for (const change of version.changes) {
          if (change.entry.state.candidate?.id !== body.candidate_id) continue;
          change.entry.state.approval = {
            id: `a-${body.candidate_id}`,
            candidate_id: body.candidate_id,
            decision: body.decision,
            final_value: null,
            reviewer: "Asha Rao",
            note: body.note ?? null,
            decided_at: "2026-10-12T10:00:00Z",
          };
          change.decided = body.decision !== "flagged" && body.decision !== "cleared";
          change.set_aside = body.decision === "not_in_document";
          change.flagged = body.decision === "flagged";
          change.is_current = !change.set_aside;
          version.decided = version.changes.filter((c) => c.decided).length;
          version.undecided = version.changes.length - version.decided;
        }
      state.amendments = next;
      return {} as never;
    }),
    document: vi.fn(async (id: string) => ({ id, file_url: `/files/documents/${id}.pdf` }) as never),
    pages: vi.fn(async (id: string) =>
      (id === DOC ? [1, 2, 3] : [1]).map((page_no) => ({
        page_no,
        width: 595,
        height: 842,
        has_text_layer: true,
        render_url: `/files/renders/${id}/${page_no}.png`,
      })),
    ),
    sections: vi.fn(async () => []),
    search: vi.fn(async () => []),
  };
  return { api: api as unknown as ReviewApi, calls: api, state };
}

async function open(amendments = makeAmendments(), session = SESSION) {
  const fake = fakeApi(amendments);
  render(<AmendmentsPage api={fake.api} session={session} review={makeReview()} reviewHref="/review/x" />);
  await screen.findAllByTestId("amendment-card").catch(() => undefined);
  await screen.findAllByTestId("pdf-page");
  return fake;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AmendmentsPage", () => {
  it("shows each later version with what it states against what stood before", async () => {
    await open();
    expect(screen.getByTestId("tender-title")).toHaveTextContent("Amendments · Selection of solar power developers for 600 MW");
    const version = screen.getByTestId("amendment-version");
    expect(version).toHaveTextContent("v2 amendment · issued 20 Mar 2026");
    expect(within(version).getByTestId("version-count")).toHaveTextContent("1 changed · 1 to decide");
    expect(within(version).getByTestId("version-document")).toHaveTextContent("amendment-01.pdf · 1 pp");
    expect(within(version).getByTestId("sections-read")).toHaveTextContent("Read for: key dates");
    expect(within(version).getByTestId("summary-of-change")).toHaveTextContent("Bid deadline extended.");
    const card = screen.getByTestId("amendment-card");
    expect(card).toHaveAttribute("data-kind", "changed");
    expect(within(card).getByTestId("change-kind")).toHaveTextContent("Changed");
    expect(within(card).getByTestId("before")).toHaveTextContent("Before · v1 original");
    expect(within(card).getByTestId("before")).toHaveTextContent("30 Mar 2026");
    expect(within(card).getByTestId("after")).toHaveTextContent("This version · v2 amendment");
    expect(within(card).getByTestId("after")).toHaveTextContent("15 Apr 2026");
    expect(within(card).getByTestId("evidence-chip")).toHaveTextContent("p. 1");
    expect(within(card).getByTestId("not-in-document")).toHaveTextContent("Not in this version");
    expect(screen.getByTestId("amendments-progress")).toHaveTextContent("1 field stated by later versions");
    expect(screen.getByTestId("amendments-progress")).toHaveTextContent("1 to decide · 3 untouched");
    expect(screen.getByTestId("back-to-review")).toHaveAttribute("href", "/review/x");
    // The amendment's document is the one on the right.
    expect(screen.getAllByTestId("pdf-page")).toHaveLength(1);
  });

  it("decides this version's reading through the same approval call and reloads", async () => {
    const fake = await open();
    const card = screen.getByTestId("amendment-card");
    fireEvent.click(within(card).getByTestId("approve"));
    await waitFor(() => expect(card).toHaveAttribute("data-decided", "yes"));
    expect(fake.calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ candidate_id: "c-deadline-2", decision: "approved", previous_approval_id: null }),
    );
    expect(within(card).getByTestId("decision")).toHaveTextContent("Approved · Asha Rao");
    expect(within(card).getByTestId("save-state")).toHaveTextContent("Saved");
    expect(screen.getByTestId("version-count")).toHaveTextContent("all decided");

    fireEvent.click(within(card).getByTestId("clear-decision"));
    await waitFor(() => expect(card).toHaveAttribute("data-decided", "no"));
    fireEvent.click(within(card).getByTestId("not-in-document"));
    await waitFor(() => expect(within(card).getByTestId("standing")).toHaveTextContent("Set aside: the field stands as v1 states it."));
    expect(fake.calls.decide).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "not_in_document" }));
  });

  it("takes a note with Not in this version", async () => {
    const fake = await open();
    const card = screen.getByTestId("amendment-card");
    fireEvent.click(within(card).getByTestId("note-toggle"));
    fireEvent.change(within(card).getByTestId("decision-note"), { target: { value: "only restates the time" } });
    fireEvent.click(within(card).getByTestId("not-in-document"));
    await waitFor(() => expect(within(card).getByTestId("decision")).toHaveTextContent("Not in document · Asha Rao — only restates the time"));
    expect(fake.calls.decide).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "not_in_document", note: "only restates the time" }));
  });

  it("flags with a note and offers the edit form on this version's reading", async () => {
    const fake = await open();
    const card = screen.getByTestId("amendment-card");
    fireEvent.click(within(card).getByTestId("flag"));
    fireEvent.change(within(card).getByTestId("flag-note"), { target: { value: "time of day differs" } });
    fireEvent.click(within(card).getByTestId("flag-save"));
    await waitFor(() => expect(within(card).getByTestId("decision")).toHaveTextContent("Flagged: time of day differs"));
    expect(fake.calls.decide).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "flagged", note: "time of day differs" }));
    fireEvent.click(within(card).getByTestId("edit"));
    expect(within(card).getByTestId("edit-save")).toBeInTheDocument();
  });

  it("answers the reviewer's keys: J focuses, Enter approves, N sets aside", async () => {
    const fake = await open();
    const card = screen.getByTestId("amendment-card");
    fireEvent.keyDown(window, { key: "j" });
    await waitFor(() => expect(card).toHaveAttribute("data-focused", "yes"));
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(card).toHaveAttribute("data-decided", "yes"));
    expect(fake.calls.decide).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "approved" }));
    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(card).toHaveAttribute("data-decided", "no"));
    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(within(card).getByTestId("standing")).toHaveTextContent("Set aside"));
  });

  it("is read-only once the review is completed", async () => {
    await open(makeAmendments(), { ...SESSION, completed_at: "2026-10-12T09:00:00Z" });
    expect(screen.getByText("Completed · read-only")).toBeInTheDocument();
    expect(screen.queryByTestId("approve")).toBeNull();
    expect(screen.queryByTestId("not-in-document")).toBeNull();
  });

  it("says so when the tender has only its original version", async () => {
    await open({ ...makeAmendments(), versions: [], untouched: 4 });
    expect(screen.getByTestId("no-amendments")).toHaveTextContent("only its original version");
    expect(screen.getByTestId("amendments-progress")).toHaveTextContent("0 fields stated by later versions");
  });
});
