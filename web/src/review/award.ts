// An award (Stage 6) on the reviewer screen: the screen is written for a tender's review,
// and an award's review has the same field list over one version, so the award is shown
// through the tender's shape and its calls are pointed at the award routes.
import type { AwardReview, ReviewApi, TenderReview } from "../api/client";

export const AWARD_TYPE = "award";

/** The award's review in the shape the screen reads. The object id travels as the
 * screen's tender id (it is only handed back to the api wrapper below). */
export function toTenderReview(award: AwardReview): TenderReview {
  return {
    tender_id: award.award_id,
    tender_type: AWARD_TYPE,
    title: award.title,
    issuing_agency: `${award.procurer} · ${award.reference} · ${award.result_kind.replace(/_/g, " ")}`,
    status: award.status,
    versions: award.versions,
    sections: award.sections,
    fields: award.fields,
    decided: award.decided,
    total: award.total,
    required_undecided: award.required_undecided,
    can_complete: award.can_complete,
    round: null,
    summary: null,
    derived: null,
  };
}

/** The screen's api over an award: reading the review and completing it go to the award
 * routes; decisions and documents are the same calls as for a tender. */
export function awardReviewApi(api: ReviewApi, awardId: string): ReviewApi {
  return {
    ...api,
    review: async () => toTenderReview(await api.award(awardId)),
    complete: async () => {
      await api.completeAward(awardId);
      return {} as never;
    },
  };
}
