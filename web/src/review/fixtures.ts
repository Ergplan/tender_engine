// A small tender for the screen's tests: two sections, one amended field.
import type { Candidate, Evidence, ReviewEntry, ReviewField, ReviewSession, TenderAmendments, TenderReview } from "../api/client";

export const DOC = "d".repeat(32);
export const AMENDMENT_DOC = "a".repeat(32);

export function evidence(overrides: Partial<Evidence> = {}): Evidence {
  return {
    id: `e-${Math.random()}`,
    document_id: DOC,
    page_no: 3,
    bbox: [72, 100, 300, 112],
    char_start: 10,
    char_end: 40,
    quote: "Earnest Money Deposit (EMD) of INR 928000 per MW",
    resolution: "stated_page",
    match_score: 100,
    match_method: "exact",
    ...overrides,
  };
}

export function candidate(value: unknown, overrides: Partial<Candidate> = {}): Candidate {
  return {
    id: `c-${String(value)}`,
    document_id: DOC,
    value,
    confidence: 0.9,
    rationale: "Stated on the page.",
    status: "validated",
    prompt_name: "extract/guarantees",
    prompt_version: "v1",
    evidence: [evidence()],
    validation: [],
    withdrawn: false,
    ...overrides,
  };
}

/** A reading that says the document withdraws the provision: no value, the removing words. */
export function withdrawnCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return candidate(null, {
    id: "c-withdrawn",
    document_id: AMENDMENT_DOC,
    rationale: "Clause 40.3 is amended; the ceiling of INR 5.80/kWh and the summary rejection are deleted.",
    evidence: [evidence({ page_no: 4, document_id: AMENDMENT_DOC, quote: "The tariff has to be less than or equal to INR 5.80/kWh" })],
    withdrawn: true,
    ...overrides,
  });
}

function entry(field: Partial<ReviewField>, found: Candidate | null, version = 1, kind = "original"): ReviewEntry {
  return {
    version_no: version,
    version_kind: kind,
    state: {
      field_path: field.field_path!,
      label: field.label!,
      group: field.section!,
      value_type: field.value_type!,
      unit: field.unit ?? null,
      required: field.required ?? false,
      help_text: field.help_text ?? "",
      enum_values: field.enum_values ?? null,
      review_order: field.review_order ?? 0,
      candidate: found,
      alternatives: [],
      alternative_candidates: 0,
      approval: null,
    },
  };
}

function field(base: Partial<ReviewField>, entries: (f: Partial<ReviewField>) => ReviewEntry[]): ReviewField {
  const built = entries(base);
  return {
    unit: null,
    required: false,
    help_text: "",
    enum_values: null,
    review_order: 0,
    decided: false,
    flagged: false,
    in_scope: true,
    entries: built,
    current: built.length ? built.length - 1 : null,
    ...base,
  } as ReviewField;
}

/** A field decided on the original by Asha, as a round carries it forward. */
function decidedByAsha(found: ReviewField, decision = "approved"): ReviewField {
  const entry = found.entries[found.current ?? 0];
  entry.state.approval = {
    id: `a-${entry.state.candidate?.id ?? "x"}`,
    candidate_id: entry.state.candidate?.id ?? "x",
    decision,
    final_value: null,
    reviewer: "Asha Rao",
    note: null,
    decided_at: "2026-10-13T10:00:00Z",
  };
  return { ...found, decided: true, in_scope: false };
}

/** The fixture tender as round 2, opened by the amendment: the deadline it states is in
 * scope, the three other fields carry Asha's decisions on the original forward. */
export function makeRound(): TenderReview {
  const review = makeReview();
  const [deadline, prebid, emd, pbg] = review.fields;
  const fields = [
    deadline,
    decidedByAsha(prebid, "not_in_document"),
    decidedByAsha(emd),
    decidedByAsha(pbg, "edited"),
  ];
  return {
    ...review,
    status: "in_review",
    fields,
    decided: 0,
    total: 1,
    required_undecided: 1,
    can_complete: false,
    round: { round_no: 2, from_version: 2, in_scope: 1, carried: 3 },
  };
}

export const ROUND_SESSION: ReviewSession = {
  tender_id: "t".repeat(32),
  reviewer_name: "Asha Rao",
  expires_at: "2026-11-14T00:00:00Z",
  completed_at: null,
  round_no: 2,
  from_version: 2,
};

export function makeReview(): TenderReview {
  const fields: ReviewField[] = [
    field(
      { field_path: "core.key_dates.bid_submission_deadline", label: "Bid submission deadline", section: "key_dates", value_type: "date", required: true, review_order: 1, help_text: "Last date to submit the bid." },
      (f) => [
        entry(f, candidate("30.03.2026", { id: "c-deadline-1", evidence: [evidence({ page_no: 2 })] })),
        entry(f, candidate("15.04.2026", { id: "c-deadline-2", document_id: AMENDMENT_DOC, evidence: [evidence({ page_no: 1, document_id: AMENDMENT_DOC })] }), 2, "amendment"),
      ],
    ),
    field(
      { field_path: "core.key_dates.pre_bid_meeting_date", label: "Pre-bid meeting", section: "key_dates", value_type: "date", review_order: 2 },
      (f) => [entry(f, candidate(null, { id: "c-prebid", status: "not_found", confidence: 0, evidence: [] }))],
    ),
    field(
      { field_path: "core.guarantees.emd_inr_per_mw", label: "EMD per MW", section: "guarantees", value_type: "money_inr", unit: "INR per MW", required: true, review_order: 3 },
      (f) => [entry(f, candidate(928000, { id: "c-emd" }))],
    ),
    field(
      { field_path: "core.guarantees.pbg_inr_per_mw", label: "PBG per MW", section: "guarantees", value_type: "money_inr", unit: "INR per MW", review_order: 4 },
      (f) => [
        entry(
          f,
          candidate(2320000, {
            id: "c-pbg",
            confidence: 0.3,
            status: "needs_review",
            evidence: [evidence({ char_start: null, char_end: null, bbox: null, resolution: "unresolved" })],
            validation: [
              { rule_name: "evidence_not_located", passed: false, message: "evidence not located on p.3", severity: "error" },
              { rule_name: "date_order", passed: false, message: "queries close before the pre-bid meeting", severity: "warning" },
            ],
          }),
        ),
      ],
    ),
  ];
  return {
    tender_id: "t".repeat(32),
    tender_type: "solar",
    title: "Selection of solar power developers for 600 MW",
    issuing_agency: "Acme Renewables Agency",
    status: "extracted",
    versions: [
      { version_no: 1, kind: "original", issued_on: null, documents: [{ document_id: DOC, role: "rfs", filename: "rfs.pdf", page_count: 3 }] },
      { version_no: 2, kind: "amendment", issued_on: "2026-03-20", documents: [{ document_id: AMENDMENT_DOC, role: "amendment", filename: "amendment-01.pdf", page_count: 1 }] },
    ],
    sections: [
      { name: "key_dates", label: "Key dates", order: 1 },
      { name: "guarantees", label: "Guarantees", order: 2 },
    ],
    fields,
    decided: 0,
    total: fields.length,
    required_undecided: 2,
    can_complete: false,
  };
}

export const SESSION: ReviewSession = {
  tender_id: "t".repeat(32),
  reviewer_name: "Asha Rao",
  expires_at: "2026-11-04T00:00:00Z",
  completed_at: null,
  round_no: 1,
  from_version: null,
};

/** The amendments of the fixture tender: version 2 moves the bid deadline. */
export function makeAmendments(): TenderAmendments {
  const review = makeReview();
  const deadline = review.fields[0];
  return {
    tender_id: review.tender_id,
    title: review.title,
    untouched: 3,
    versions: [
      {
        version_no: 2,
        kind: "amendment",
        issued_on: "2026-03-20",
        summary_of_change: "Bid deadline extended.",
        documents: review.versions[1].documents,
        sections_read: ["key_dates"],
        changes: [
          {
            field_path: deadline.field_path,
            label: deadline.label,
            section: "key_dates",
            section_label: "Key dates",
            value_type: "date",
            unit: null,
            required: true,
            help_text: deadline.help_text,
            enum_values: null,
            keys: null,
            kind: "changed",
            before: { version_no: 1, version_kind: "original", value: "30.03.2026", decision: null },
            entry: deadline.entries[1],
            is_current: true,
            decided: false,
            set_aside: false,
            flagged: false,
            changes_decided: false,
            impacts: [],
          },
        ],
        added: 0,
        changed: 1,
        restated: 0,
        removed: 0,
        decided: 0,
        undecided: 1,
      },
    ],
  };
}
