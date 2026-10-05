import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ReviewApi, type TenderReview } from "../api/client";
import { AMENDMENT_DOC, candidate, DOC, evidence, makeReview, SESSION } from "./fixtures";
import { ReviewScreen } from "./ReviewScreen";

vi.mock("./pdfText", () => ({
  openPdf: async () => ({ renderPage: async () => undefined, drawPage: async () => undefined, close: () => undefined }),
}));

const DEADLINE = "core.key_dates.bid_submission_deadline";
const PREBID = "core.key_dates.pre_bid_meeting_date";
const EMD = "core.guarantees.emd_inr_per_mw";
const PBG = "core.guarantees.pbg_inr_per_mw";

function fakeApi(review: TenderReview) {
  const state = { review };
  const api = {
    session: vi.fn(async () => SESSION),
    review: vi.fn(async () => state.review),
    decide: vi.fn(async (body: { candidate_id: string; decision: string }) => {
      // The server's answer to a decision: the field's current entry now carries it.
      const next = structuredClone(state.review);
      for (const field of next.fields) {
        const entry = field.current === null ? null : field.entries[field.current];
        if (entry?.state.candidate?.id !== body.candidate_id) continue;
        entry.state.approval = {
          id: `a-${body.candidate_id}`,
          candidate_id: body.candidate_id,
          decision: body.decision,
          final_value: null,
          reviewer: "Asha Rao",
          note: null,
          decided_at: "2026-10-05T10:00:00Z",
        };
        field.decided = body.decision !== "flagged";
        field.flagged = body.decision === "flagged";
      }
      next.decided = next.fields.filter((field) => field.decided).length;
      state.review = next;
      return {} as never;
    }),
    complete: vi.fn(async () => ({}) as never),
    snapshot: vi.fn(),
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
    sections: vi.fn(async () => [
      { id: "s1", start_page: 2, end_page: 2, heading: "SECTION 2: BID INFORMATION SHEET", kind: "dates", confidence: 0.9 },
    ]),
    search: vi.fn(async () => [{ page_no: 3, bbox: [72, 100, 200, 112], snippet: "Earnest Money Deposit" }]),
  };
  return { api: api as unknown as ReviewApi, calls: api, state };
}

function card(path: string) {
  return document.querySelector<HTMLElement>(`[data-field="${path}"]`)!;
}

async function open(review = makeReview(), session = SESSION) {
  const fake = fakeApi(review);
  const onCompleted = vi.fn();
  render(<ReviewScreen api={fake.api} session={session} initial={review} onCompleted={onCompleted} />);
  await screen.findAllByTestId("pdf-page");
  return { ...fake, onCompleted };
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const SUMMARY = "core.summary.plain_english_summary";

/** The fixture tender with a summary whose sentences carry evidence markers. */
function withSummary() {
  const review = makeReview();
  const spans = [
    evidence({ id: "s1", ordinal: 1, page_no: 1, bbox: [72, 100, 300, 112], quote: "Selection of solar power developers for 600 MW" }),
    evidence({ id: "s2", ordinal: 2, page_no: 1, bbox: [72, 140, 300, 152], quote: "Issued by Acme Renewables Agency" }),
    evidence({ id: "s3", ordinal: 3, page_no: 3, bbox: [72, 100, 300, 112], quote: "EMD of INR 928000 per MW" }),
  ];
  const found = candidate(
    "What is procured: Acme invites bids for 600 MW of solar. [1]\n\nBuyer and offtaker: Acme Renewables Agency issues the tender. [2]\n\nMoney at risk: The EMD is INR 9.28 lakh per MW. [3]",
    { id: "c-summary", evidence: spans, rationale: "Each paragraph rests on the cover page and the bid information sheet. ".repeat(4).trim() },
  );
  const template = review.fields[0];
  review.sections.unshift({ name: "summary", label: "Summary", order: 0 });
  review.fields.unshift({
    ...template,
    field_path: SUMMARY,
    label: "Plain-English summary",
    section: "summary",
    value_type: "long_text",
    review_order: 0,
    current: 0,
    entries: [{ version_no: 1, version_kind: "original", state: { ...template.entries[0].state, field_path: SUMMARY, value_type: "long_text", candidate: found, approval: null } }],
  });
  review.total = review.fields.length;
  return review;
}

describe("what the reviewer sees", () => {
  it("shows the tender, the reviewer, progress and a disabled Complete button", async () => {
    await open();
    expect(screen.getByTestId("tender-title")).toHaveTextContent("600 MW");
    expect(screen.getByTestId("reviewer-name")).toHaveTextContent("Asha Rao");
    expect(screen.getByTestId("progress")).toHaveTextContent("0 of 4 fields decided");
    expect(screen.getByTestId("complete-review")).toBeDisabled();
  });

  it("lists the sections in order with decided/total and the fields in review order", async () => {
    await open();
    const sections = screen.getAllByTestId("section");
    expect(sections.map((s) => s.dataset.section)).toEqual(["key_dates", "guarantees"]);
    expect(within(sections[0]).getByTestId("section-count")).toHaveTextContent("0/2");
    const cards = screen.getAllByTestId("field-card").map((c) => c.dataset.field);
    expect(cards).toEqual([DEADLINE, PREBID, EMD, PBG]);
  });

  it("formats values by type, tags an amended field and shows what earlier versions said", async () => {
    await open();
    const deadline = card(DEADLINE);
    expect(within(deadline).getByTestId("field-value")).toHaveTextContent("15 Apr 2026");
    expect(within(deadline).getByTestId("version-tag")).toHaveTextContent("v2 amendment");
    expect(deadline).toHaveTextContent("v1 original: 30 Mar 2026");
    expect(within(card(EMD)).getByTestId("field-value")).toHaveTextContent("₹ 9.28 lakh/MW");
    expect(within(card(EMD)).queryByTestId("version-tag")).toBeNull();
    expect(within(card(PREBID)).getByTestId("field-value")).toHaveTextContent("No value found");
  });

  it("colours confidence, shows failed rules and warnings, and one chip per evidence span", async () => {
    await open();
    expect(within(card(EMD)).getByTestId("confidence")).toHaveTextContent("90%");
    expect(within(card(EMD)).getByTestId("confidence").className).toContain("green");
    expect(within(card(PBG)).getByTestId("confidence").className).toContain("red");
    const notes = within(card(PBG)).getAllByTestId("validation-note");
    expect(notes.map((n) => n.textContent)).toEqual([
      "evidence not located on p.3",
      "queries close before the pre-bid meeting",
    ]);
    expect(notes[0].className).toContain("red");
    expect(notes[1].className).toContain("amber");
    expect(within(card(EMD)).getAllByTestId("evidence-chip")[0]).toHaveTextContent("p. 3");
    expect(within(card(PBG)).getAllByTestId("evidence-chip")[0]).toHaveTextContent("p. 3 ?");
  });

  it("does not offer Approve where there is no value or no located evidence", async () => {
    await open();
    expect(within(card(EMD)).getByTestId("approve")).toBeEnabled();
    expect(within(card(PREBID)).getByTestId("approve")).toBeDisabled();
    expect(within(card(PBG)).getByTestId("approve")).toBeDisabled();
    expect(screen.queryByText(/approve all/i)).toBeNull();
  });
});

describe("deciding", () => {
  it("approves the focused field with Enter, saves at once and moves to the next undecided", async () => {
    const { calls } = await open();
    fireEvent.click(card(DEADLINE));
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(card(DEADLINE).dataset.decided).toBe("yes"));
    expect(calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ candidate_id: "c-deadline-2", decision: "approved", previous_approval_id: null }),
    );
    expect(within(card(DEADLINE)).getByTestId("decision")).toHaveTextContent("Approved · Asha Rao");
    expect(within(card(DEADLINE)).getByTestId("save-state")).toHaveTextContent("Saved");
    expect(screen.getByTestId("progress")).toHaveTextContent("1 of 4");
    await waitFor(() => expect(card(PREBID).dataset.focused).toBe("yes"));
  });

  it("edits a date in a date input and sends the typed value with the decision it replaces", async () => {
    const { calls } = await open();
    fireEvent.click(within(card(DEADLINE)).getByTestId("edit"));
    const input = within(card(DEADLINE)).getByTestId("edit-input") as HTMLInputElement;
    expect(input.type).toBe("date");
    expect(input.value).toBe("2026-04-15");
    fireEvent.change(input, { target: { value: "2026-04-16" } });
    fireEvent.click(within(card(DEADLINE)).getByTestId("edit-save"));
    await waitFor(() => expect(calls.decide).toHaveBeenCalled());
    expect(calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ decision: "edited", final_value: "2026-04-16", evidence: null }),
    );
  });

  it("asks for the page and the words when the field has no located evidence", async () => {
    const { calls } = await open();
    fireEvent.click(within(card(PREBID)).getByTestId("edit"));
    const form = card(PREBID);
    fireEvent.change(within(form).getByTestId("edit-input"), { target: { value: "2026-03-12" } });
    fireEvent.click(within(form).getByTestId("edit-save"));
    expect(within(form).getByRole("alert")).toHaveTextContent("Give the page and the text");
    expect(calls.decide).not.toHaveBeenCalled();
    fireEvent.change(within(form).getByTestId("evidence-page"), { target: { value: "2" } });
    fireEvent.change(within(form).getByTestId("evidence-quote"), { target: { value: "held on 12.03.2026" } });
    fireEvent.click(within(form).getByTestId("edit-save"));
    await waitFor(() => expect(calls.decide).toHaveBeenCalled());
    expect(calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ final_value: "2026-03-12", evidence: [{ page_no: 2, quote: "held on 12.03.2026" }] }),
    );
  });

  it("marks not in document with N, opens edit with E and cancels with Escape", async () => {
    const { calls } = await open();
    fireEvent.click(card(PREBID));
    fireEvent.keyDown(window, { key: "e" });
    expect(within(card(PREBID)).getByTestId("edit-input")).toBeInTheDocument();
    fireEvent.keyDown(within(card(PREBID)).getByTestId("edit-input"), { key: "Escape" });
    expect(within(card(PREBID)).queryByTestId("edit-input")).toBeNull();
    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(calls.decide).toHaveBeenCalled());
    expect(calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ candidate_id: "c-prebid", decision: "not_in_document" }),
    );
  });

  it("flags with a note; a flag does not count as decided", async () => {
    const { calls } = await open();
    fireEvent.click(card(EMD));
    fireEvent.keyDown(window, { key: "f" });
    fireEvent.change(within(card(EMD)).getByTestId("flag-note"), { target: { value: "check the band" } });
    fireEvent.click(within(card(EMD)).getByTestId("flag-save"));
    await waitFor(() => expect(calls.decide).toHaveBeenCalled());
    expect(calls.decide).toHaveBeenCalledWith(
      expect.objectContaining({ decision: "flagged", note: "check the band" }),
    );
    await waitFor(() => expect(card(EMD)).toHaveTextContent("Flagged"));
    expect(card(EMD).dataset.decided).toBe("no");
    expect(screen.getByTestId("progress")).toHaveTextContent("0 of 4");
  });

  it("moves focus with J and K and tells why Enter cannot approve", async () => {
    await open();
    fireEvent.keyDown(window, { key: "j" });
    expect(card(DEADLINE).dataset.focused).toBe("yes");
    fireEvent.keyDown(window, { key: "j" });
    expect(card(PREBID).dataset.focused).toBe("yes");
    fireEvent.keyDown(window, { key: "Enter" });
    expect(within(card(PREBID)).getByTestId("save-state")).toHaveTextContent("No value was found");
    fireEvent.keyDown(window, { key: "k" });
    expect(card(DEADLINE).dataset.focused).toBe("yes");
  });

  it("reloads the field and says so when the decision was stale", async () => {
    const { calls } = await open();
    calls.decide.mockRejectedValueOnce(new ApiError(409, "conflict", "changed", null, null));
    fireEvent.click(within(card(EMD)).getByTestId("approve"));
    await waitFor(() =>
      expect(within(card(EMD)).getByTestId("save-state")).toHaveTextContent("Changed since it was loaded"),
    );
    expect(calls.review).toHaveBeenCalled();
  });

  it("shows a retryable failure when the save did not reach the server", async () => {
    const { calls } = await open();
    calls.decide.mockRejectedValueOnce(new TypeError("network"));
    fireEvent.click(within(card(EMD)).getByTestId("approve"));
    await waitFor(() => expect(within(card(EMD)).getByRole("alert")).toHaveTextContent("Not saved"));
    expect(within(card(EMD)).getByTestId("approve")).toBeEnabled();
  });
});

describe("the document pane", () => {
  it("goes to the page of a clicked evidence chip and highlights it", async () => {
    await open();
    expect(screen.getByTestId("page-indicator")).toHaveTextContent("Page 1 of 3");
    fireEvent.click(within(card(EMD)).getAllByTestId("evidence-chip")[0]);
    await waitFor(() => expect(screen.getByTestId("page-indicator")).toHaveTextContent("Page 3 of 3"));
    expect(screen.getByTestId("evidence-pulse")).toBeInTheDocument();
    // The chip's field takes the focus and its evidence stays marked after the pulse.
    expect(card(EMD).dataset.focused).toBe("yes");
    await waitFor(() => expect(screen.getAllByTestId("evidence-highlight").length).toBe(1));
  });

  it("switches to the amendment when the evidence is in it", async () => {
    const { calls } = await open();
    fireEvent.click(card(DEADLINE));
    await waitFor(() => expect(calls.pages).toHaveBeenCalledWith(AMENDMENT_DOC));
    await waitFor(() => expect(screen.getByTestId("page-indicator")).toHaveTextContent("Page 1 of 1"));
    expect((screen.getByTestId("version-select") as HTMLSelectElement).value).toBe(AMENDMENT_DOC);
  });

  it("searches the document and lists its contents", async () => {
    const { calls } = await open();
    fireEvent.change(screen.getByTestId("pdf-search"), { target: { value: "earnest" } });
    fireEvent.submit(screen.getByTestId("pdf-search").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("search-count")).toHaveTextContent("1/1"));
    expect(calls.search).toHaveBeenCalledWith(DOC, "earnest");
    expect(screen.getByTestId("search-hit")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("bookmarks-toggle"));
    fireEvent.click(within(screen.getByTestId("bookmarks")).getByText(/BID INFORMATION SHEET/));
    expect(screen.getByTestId("page-indicator")).toHaveTextContent("Page 2 of 3");
  });
});

describe("completing", () => {
  it("asks for confirmation, completes and hands over to the summary", async () => {
    const review = makeReview();
    review.can_complete = true;
    review.required_undecided = 0;
    const { calls, onCompleted } = await open(review);
    fireEvent.click(screen.getByTestId("complete-review"));
    expect(screen.getByRole("dialog")).toHaveTextContent("no longer changed");
    await act(async () => {
      fireEvent.click(screen.getByTestId("confirm-complete"));
    });
    expect(calls.complete).toHaveBeenCalledWith(review.tender_id);
    expect(onCompleted).toHaveBeenCalled();
  });

  it("is read-only once completed: no actions and no Complete button", async () => {
    await open(makeReview(), { ...SESSION, completed_at: "2026-10-05T10:00:00Z" });
    expect(screen.queryByTestId("complete-review")).toBeNull();
    expect(screen.queryByTestId("approve")).toBeNull();
    expect(screen.queryByTestId("guide")).toBeNull();
    fireEvent.click(card(EMD));
    fireEvent.keyDown(window, { key: "Enter" });
    expect(screen.getByText(/read-only/)).toBeInTheDocument();
  });
});

describe("orientation and reading aids", () => {
  it("opens with the guide expanded", async () => {
    await open();
    expect(screen.getByTestId("guide").dataset.open).toBe("yes");
    expect(screen.getByTestId("guide")).toHaveTextContent("How to decide a field");
  });

  it("labels the confidence figure as the model's and explains a low one on hover", async () => {
    await open();
    expect(within(card(EMD)).getByTestId("confidence-caption")).toHaveTextContent("model confidence");
    const hint = within(card(PBG)).getByTestId("confidence").parentElement!.getAttribute("title")!;
    expect(hint).toContain("Model confidence 30%");
    expect(hint).toContain("not a measure of whether the value is correct");
    expect(hint).toContain("ambiguously or only in part");
    expect(hint).toContain("portal Tender ID");
    expect(hint).toContain("Read the rationale");
  });

  it("says in a section header how many undecided fields need a closer look", async () => {
    await open();
    const [dates, guarantees] = screen.getAllByTestId("section");
    expect(within(dates).queryByTestId("section-attention")).toBeNull();
    expect(within(guarantees).getByTestId("section-attention")).toHaveTextContent("1 need a closer look");
  });

  it("counts what is left, and estimates the time once it knows the pace", async () => {
    const now = vi.spyOn(Date, "now");
    const review = makeReview();
    // Eight fields that can be approved one after another.
    const emd = review.fields[2];
    review.fields = Array.from({ length: 8 }, (_, index) => ({
      ...structuredClone(emd),
      field_path: `core.guarantees.field_${index}`,
      review_order: index,
      entries: [{ ...structuredClone(emd.entries[0]), state: { ...structuredClone(emd.entries[0].state), candidate: candidate(index, { id: `c-${index}` }) } }],
    }));
    review.total = 8;
    await open(review);
    expect(screen.getByTestId("remaining")).toHaveTextContent("8 to go");
    expect(screen.queryByTestId("time-left")).toBeNull();
    fireEvent.keyDown(window, { key: "j" });
    for (let done = 1; done <= 5; done += 1) {
      now.mockReturnValue(1_000_000 + done * 30_000);
      fireEvent.keyDown(window, { key: "Enter" });
      await waitFor(() => expect(screen.getByTestId("progress")).toHaveTextContent(`${done} of 8`));
    }
    expect(screen.getByTestId("remaining")).toHaveTextContent("3 to go");
    expect(screen.getByTestId("time-left")).toHaveTextContent("about 2 min left");
  });

  it("shows the rationale in full for the focused field and on request elsewhere", async () => {
    await open(withSummary());
    const reason = within(card(SUMMARY)).getByTestId("rationale");
    expect(reason.className).toContain("line-clamp-2");
    fireEvent.click(within(card(SUMMARY)).getByTestId("rationale-toggle"));
    expect(within(card(SUMMARY)).getByTestId("rationale").className).not.toContain("line-clamp-2");
    fireEvent.click(within(card(SUMMARY)).getByTestId("rationale-toggle"));
    fireEvent.click(card(SUMMARY));
    expect(within(card(SUMMARY)).getByTestId("rationale").className).not.toContain("line-clamp-2");
    expect(within(card(SUMMARY)).queryByTestId("rationale-toggle")).toBeNull();
  });
});

describe("evidence on a text of several sentences", () => {
  it("numbers the chips and ties each sentence to its chip", async () => {
    await open(withSummary());
    const summary = card(SUMMARY);
    const chips = within(summary).getAllByTestId("evidence-chip");
    expect(chips.map((chip) => chip.textContent)).toEqual(["1p. 1", "2p. 1", "3p. 3"]);
    expect(within(summary).getByText("What is procured:")).toBeInTheDocument();
    const markers = within(summary).getAllByTestId("evidence-marker");
    expect(markers.map((marker) => marker.textContent)).toEqual(["1", "2", "3"]);
    expect(within(summary).getByTestId("field-value").textContent).not.toContain("[1]");
    // A single chip is not numbered.
    expect(within(card(EMD)).getAllByTestId("evidence-chip")[0]).toHaveTextContent(/^p\. 3$/);
  });

  it("highlights only the passage of the chip being shown and dims the others", async () => {
    await open(withSummary());
    const summary = card(SUMMARY);
    fireEvent.click(within(summary).getAllByTestId("evidence-marker")[1]);
    await waitFor(() => expect(card(SUMMARY).dataset.focused).toBe("yes"));
    const chips = within(card(SUMMARY)).getAllByTestId("evidence-chip");
    expect(chips.map((chip) => chip.dataset.active)).toEqual(["no", "yes", "no"]);
    // Page 1 holds two of the three passages: one is marked, the other is faint.
    await waitFor(() => expect(screen.getAllByTestId("evidence-highlight")).toHaveLength(1));
    expect(screen.getAllByTestId("evidence-highlight-dim")).toHaveLength(2);
    fireEvent.click(chips[2]);
    await waitFor(() => expect(screen.getByTestId("page-indicator")).toHaveTextContent("Page 3 of 3"));
    expect(within(card(SUMMARY)).getAllByTestId("evidence-chip")[2].dataset.active).toBe("yes");
    expect(screen.getAllByTestId("evidence-highlight")).toHaveLength(1);
  });

  it("lists the words each numbered chip quotes when the text has no markers", async () => {
    const review = withSummary();
    const found = review.fields[0].entries[0].state.candidate!;
    found.value = "Acme invites bids for 600 MW of solar. Acme Renewables Agency issues the tender.";
    await open(review);
    expect(within(card(SUMMARY)).queryByTestId("evidence-quotes")).toBeNull();
    fireEvent.click(card(SUMMARY));
    const quotes = within(card(SUMMARY)).getByTestId("evidence-quotes");
    expect(within(quotes).getAllByRole("listitem")).toHaveLength(3);
    expect(quotes).toHaveTextContent("2p. 1: “Issued by Acme Renewables Agency”");
  });
});

describe("a summary with many passages", () => {
  it("keeps the chips behind a toggle and shows the one being looked at", async () => {
    const review = withSummary();
    const found = review.fields[0].entries[0].state.candidate!;
    found.evidence = Array.from({ length: 14 }, (_, index) =>
      evidence({ id: `m${index + 1}`, ordinal: index + 1, page_no: (index % 3) + 1, bbox: [72, 100 + index * 20, 300, 112 + index * 20] }),
    );
    found.value = "What is procured: Acme invites bids. [1][2]\n\nMoney at risk: The EMD is set. [14]";
    await open(review);
    const summary = card(SUMMARY);
    expect(within(summary).queryAllByTestId("evidence-chip")).toHaveLength(0);
    expect(within(summary).getByTestId("chips-toggle")).toHaveTextContent("14 passages, numbered in the text");
    fireEvent.click(within(summary).getAllByTestId("evidence-marker")[2]);
    await waitFor(() => expect(within(card(SUMMARY)).getAllByTestId("evidence-chip")).toHaveLength(1));
    expect(within(card(SUMMARY)).getByTestId("evidence-chip")).toHaveTextContent("14p. 2");
    fireEvent.click(within(card(SUMMARY)).getByTestId("chips-toggle"));
    expect(within(card(SUMMARY)).getAllByTestId("evidence-chip")).toHaveLength(14);
  });
});
