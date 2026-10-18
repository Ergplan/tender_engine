import type { PublishedField, PublishedTender, TenderChanges, TenderListItem } from "../api/types5c";

export const TENDER: TenderListItem = {
  id: "a".repeat(32),
  tender_type: "fdre",
  issuing_agency: "SECI",
  external_ref: "SECI/C&P/IPP/13/0002/26-27",
  title: "2,000 MW FDRE power with CfD (CfD-I)",
  slug: "seci-cfd-i",
  status: "reviewed",
  current_version_no: 5,
  created_at: "2026-10-01T00:00:00+00:00",
  created_by: "ingest",
} as TenderListItem;

export const OTHER: TenderListItem = {
  ...TENDER,
  id: "b".repeat(32),
  tender_type: "solar",
  external_ref: null,
  title: "700 MW ISTS solar (CnI-1)",
  slug: "seci-cni-1-700mw",
  status: "extracted",
  current_version_no: 3,
};

export function field(over: Partial<PublishedField> & { path: string; label: string }): PublishedField {
  return {
    section: "key_dates",
    value_type: "text",
    unit: null,
    value: null,
    version_no: 1,
    set_by: "RfS",
    withdrawn: false,
    withdrawn_from_version: null,
    status: "reviewed",
    gap: null,
    evidence: [],
    reviewed_at: "2026-10-13T10:32:00+00:00",
    reviewer_role: "approver",
    ...over,
  };
}

const AUTHORITY = "The tender document is the authoritative source; this is jouleWise's reviewed reading of it.";

export const PUBLISHED: PublishedTender = {
  tender_id: TENDER.id,
  slug: TENDER.slug,
  title: TENDER.title,
  issuing_agency: TENDER.issuing_agency,
  tender_type: TENDER.tender_type,
  external_ref: TENDER.external_ref,
  publication: {
    state: "update_pending",
    reviewed_version: 4,
    current_version: 5,
    unreviewed_version: { version_no: 5, kind: "corrigendum", issued_on: "2026-10-08", document_ids: ["d".repeat(32)] },
    possibly_superseded: ["core.key_dates.ppa_tenure_years"],
    suspended_by: [],
  },
  banner: "Version 5 (Amendment-03, 8 Oct 2026) exists and is not yet reviewed.",
  reviewed_at: "2026-10-13T10:32:00+00:00",
  reviewer_role: "approver",
  reviewed_version: 4,
  current_version: 5,
  suspension: null,
  reliability: { tender_type: "fdre", value_accuracy: 0.96, evidence_accuracy: 1, n_fields: 320, as_of: "2026-10-15" },
  authority_note: AUTHORITY,
  sections: [
    {
      name: "key_dates",
      label: "Key dates",
      fields: [
        field({
          path: "core.key_dates.bid_submission_deadline",
          label: "Bid submission deadline",
          value_type: "date",
          value: "2026-11-08",
          version_no: 4,
          set_by: "Amendment-02",
          evidence: [{ document_id: "e".repeat(32), filename: "Amendment-02.pdf", page_no: 1, quote: "extended to 08.11.2026" }],
        }),
        field({
          path: "core.key_dates.ppa_tenure_years",
          label: "PPA tenure",
          value_type: "int",
          unit: "years",
          value: 15,
          status: "possibly_superseded",
        }),
        field({
          path: "core.guarantees.emd_validity_rule",
          label: "EMD validity",
          status: "not_reviewed",
          gap: { reason: "read by v5 (clause 17), awaiting the reviewer", document_id: "d".repeat(32), likely_page: 2 },
        }),
        field({
          path: "core.commercial.tariff_ceiling_inr_per_kwh",
          label: "Tariff ceiling",
          value_type: "decimal",
          unit: "INR/kWh",
          value: 3.8,
          version_no: 5,
          set_by: "corrigendum",
          withdrawn: true,
          withdrawn_from_version: 1,
          evidence: [{ document_id: "d".repeat(32), filename: "Amendment-03.pdf", page_no: 4, quote: "stands deleted" }],
        }),
      ],
    },
  ],
};

export const SUSPENDED: PublishedTender = {
  ...PUBLISHED,
  publication: {
    state: "publication_suspended",
    reviewed_version: 4,
    current_version: 5,
    unreviewed_version: { version_no: 5, kind: "corrigendum", issued_on: "2026-10-08", document_ids: [] },
    possibly_superseded: [],
    suspended_by: ["core.key_dates.bid_submission_deadline", "core.commercial.tariff_ceiling_inr_per_kwh"],
  },
  banner: null,
  suspension: {
    fields: ["core.key_dates.bid_submission_deadline", "core.commercial.tariff_ceiling_inr_per_kwh"],
    document_ids: ["d".repeat(32)],
    version_no: 5,
    kind: "corrigendum",
    issued_on: "2026-10-08",
  },
  sections: [],
};

export const CHANGES: TenderChanges = {
  tender_id: TENDER.id,
  title: TENDER.title,
  reviewed_version: 4,
  versions: [
    {
      version_no: 1,
      kind: "original",
      issued_on: "2026-08-01",
      summary_of_change: null,
      documents: ["RfS.pdf"],
      reviewed: true,
      changes: [],
      pending: [],
    },
    {
      version_no: 4,
      kind: "amendment",
      issued_on: "2026-09-22",
      summary_of_change: "Bid deadline extended",
      documents: ["Amendment-02.pdf"],
      reviewed: true,
      changes: [
        {
          field_path: "core.key_dates.bid_submission_deadline",
          label: "Bid submission deadline",
          section: "key_dates",
          value_type: "date",
          unit: null,
          before: "2026-10-20",
          after: "2026-11-08",
          withdrawn: false,
          evidence: [{ document_id: "e".repeat(32), filename: "Amendment-02.pdf", page_no: 1, quote: "extended" }],
          decided_at: "2026-10-13T10:00:00+00:00",
          reviewer_role: "approver",
        },
      ],
      pending: [],
    },
    {
      version_no: 5,
      kind: "corrigendum",
      issued_on: "2026-10-08",
      summary_of_change: null,
      documents: ["Amendment-03.pdf"],
      reviewed: false,
      changes: [],
      pending: ["core.commercial.tariff_ceiling_inr_per_kwh", "core.key_dates.ppa_tenure_years"],
    },
  ],
};
