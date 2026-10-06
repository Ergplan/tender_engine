// What a reviewer needs to know before deciding. Shown in the panel at the top of the
// review screen; docs/REVIEWER-GUIDE.md says the same outside the app (a test keeps the
// two in step).

export const GUIDE = {
  purpose: {
    title: "What this review is for",
    text: [
      "The values you approve here become the canonical record of this tender and the benchmark the extraction is measured against.",
      "Nothing is published until you have approved it.",
    ],
  },
  deciding: {
    title: "How to decide a field",
    steps: [
      "Read the value, click an evidence chip, and confirm the quoted words on the page.",
      "Approve if the value is what the document says.",
      "Edit if the value is wrong or incomplete, and give the page and the words that state it.",
      "Not in document if the tender genuinely does not state it. That is a correct answer, not a gap.",
      "Flag if you are unsure, and move on. A flagged field is not counted as decided.",
    ],
  },
  confidence: {
    title: "What the confidence figure means",
    text: [
      "It is the model's own confidence in its reading, not a measure of whether the value is correct.",
      "A low figure often means the document states the field ambiguously or only in part, not that the value is likely wrong.",
      "Example: a tender number at 60% can be right when the document prints only a portal Tender ID and leaves \"RfS No.\" blank.",
      "Read the rationale under the value before treating a low figure as an error.",
    ],
  },
  keys: {
    title: "Keys",
    list: [
      ["Enter", "approve and go to the next undecided field"],
      ["E", "edit"],
      ["N", "not in document"],
      ["F / U", "flag / clear the decision"],
      ["J / K", "next / previous field"],
      ["Esc", "cancel"],
    ] as [string, string][],
  },
};

/** The hover text of the confidence figure. */
export const CONFIDENCE_HINT = GUIDE.confidence.text.join(" ");
