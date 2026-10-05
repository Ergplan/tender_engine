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
