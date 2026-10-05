// What the screen reads off the review of a tender. Pure functions over the API's types.
import type { Candidate, Evidence, ReviewEntry, ReviewField, TenderReview } from "../api/client";

export type PdfTarget = {
  documentId: string;
  pageNo: number;
  bbox: number[] | null;
  /** Changes on every request, so asking for the same place twice scrolls twice. */
  key: number;
};

export function currentEntry(field: ReviewField): ReviewEntry | null {
  return field.current === null ? null : (field.entries[field.current] ?? null);
}

export function located(evidence: Evidence): boolean {
  return evidence.char_start !== null && evidence.char_start !== undefined;
}

export function hasLocatedEvidence(candidate: Candidate | null | undefined): boolean {
  return !!candidate && candidate.evidence.some(located);
}

/** Why the value cannot simply be approved, or null when it can. */
export function approveBlocker(entry: ReviewEntry | null): string | null {
  const candidate = entry?.state.candidate;
  if (!candidate) return "There is no extracted value for this field.";
  if (candidate.value === null || candidate.value === undefined)
    return "No value was found. Edit to enter one, or mark it not in document.";
  if (!hasLocatedEvidence(candidate))
    return "The quoted text was not found in the document. Edit and give the page and the text.";
  return null;
}

export function versionTag(entry: ReviewEntry): string | null {
  return entry.version_no > 1 ? `v${entry.version_no} ${entry.version_kind}` : null;
}

/** The first place to show for a field: located evidence first. */
export function firstEvidence(entry: ReviewEntry | null): Evidence | null {
  const evidence = entry?.state.candidate?.evidence ?? [];
  return evidence.find(located) ?? evidence[0] ?? null;
}

/** The number a chip shows: the quote's place in the model's list, else its place here. */
export function evidenceNumber(candidate: Candidate, evidence: Evidence): number {
  return evidence.ordinal ?? candidate.evidence.indexOf(evidence) + 1;
}

/** Where the summary stands; it is written from the other fields and decided after them. */
export type SummaryState = { waiting_for: number; current: boolean; being_written: boolean };
export const SUMMARY_FIELD = "core.summary.plain_english_summary";

export function summaryState(review: TenderReview): SummaryState | null {
  return (review.summary as SummaryState | null | undefined) ?? null;
}

/** Why the summary cannot be decided yet, or null. `approving` asks about a plain approval:
 * an edit is the reviewer's own text and waits only for the other fields. */
export function summaryLock(state: SummaryState | null, approving: boolean): string | null {
  if (!state) return null;
  if (state.waiting_for > 0)
    return `Decide the other fields first (${state.waiting_for} to go). The summary is written from them.`;
  if (approving && !state.current)
    return state.being_written
      ? "The summary is being written again from your decisions. It will be ready in about a minute."
      : "Your decisions changed the record. The summary will be written again before it can be approved.";
  return null;
}

/** The model's note on a text written from the record: the first paragraph of its
 * rationale. What follows (which field each number comes from) stays in the record. */
export function recordNote(candidate: Candidate): string | null {
  if (!candidate.rationale.includes("\n\n")) return null;
  return candidate.rationale.split("\n\n")[0].trim() || null;
}

export const LOW_CONFIDENCE = 0.5;

/** A field that deserves an early look: not decided yet, and either flagged by a rule or
 * extracted with low confidence. */
export function needsAttention(field: ReviewField): boolean {
  const candidate = currentEntry(field)?.state.candidate;
  if (!candidate || field.decided) return false;
  const lowConfidence =
    candidate.value !== null && candidate.value !== undefined && candidate.confidence < LOW_CONFIDENCE;
  return candidate.status === "needs_review" || lowConfidence;
}

export function failedRules(candidate: Candidate | null | undefined) {
  return (candidate?.validation ?? []).filter(
    (result) => !result.passed && result.rule_name !== "evidence_located",
  );
}

export function fieldsOfSection(review: TenderReview, section: string): ReviewField[] {
  return review.fields
    .filter((field) => field.section === section)
    .sort((a, b) => a.review_order - b.review_order);
}

/** Field paths in the order the reviewer meets them. */
export function reviewOrder(review: TenderReview): string[] {
  return review.sections.flatMap((section) =>
    fieldsOfSection(review, section.name).map((field) => field.field_path),
  );
}

export function documentName(review: TenderReview, documentId: string): string {
  for (const version of review.versions)
    for (const document of version.documents)
      if (document.document_id === documentId) return document.filename;
  return "the document";
}
