# Extraction summary

Generated 2026-10-04 15:48 UTC by `python -m scripts.ingest_tenders summary` (the same content is served by `GET /api/v1/reports/extraction-summary`). Model `claude-fable-5-1`. Candidates only: nothing here has been reviewed.

- **Evidence-location rate** = values with located evidence / values returned (target 95%).
- **Answer rate** = fields with a value / fields in the schema (reported, not targeted; a field the documents do not state returning no value is a correct answer).
- A field counts once per tender: the best live candidate of the latest version that gives a value.
- **Failing validation** = fields whose shown candidate is `needs_review` (a rule failed, or a required field has no value).

## Per tender

| Type | Tender | Versions | Documents | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Failing validation | Tokens in | Tokens out | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 1 | 1 | 137 | 89 | 55 | 55 | 100% | 62% | 1 | 820,681 | 46,428 | 10.53 |
| epc | seci-gaya-60mw (1 of 2 runs not finished) | 1 | 2 | 645 | 89 | 8 | 8 | 100% | 9% | 0 | 205,141 | 15,859 | 2.84 |
| epc | seci-ramagiri-70mw-bess (6 of 6 runs not finished) | 3 | 9 | 706 | 89 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| fdre | nhpc-fdre-ii (1 of 1 runs not finished) | 1 | 1 | 264 | 85 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| fdre | seci-cfd-i (5 of 5 runs not finished) | 4 | 5 | 341 | 85 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| fdre | seci-fdre-ix | 2 | 4 | 256 | 85 | 64 | 64 | 100% | 75% | 2 | 1,973,025 | 143,446 | 26.90 |
| fdre | seci-fdre-rtc-v (6 of 6 runs not finished) | 5 | 7 | 305 | 85 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| generation | ntpc-phes-2000mw (1 of 1 runs not finished) | 1 | 1 | 3 | 82 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| hybrid | ntpc-hybrid-03 (1 of 1 runs not finished) | 1 | 1 | 138 | 81 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| solar | seci-cni-1-700mw (3 of 3 runs not finished) | 2 | 4 | 241 | 83 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| transmission | recpdcl-beed-tbcb (1 of 1 runs not finished) | 1 | 1 | 166 | 85 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| wind | ntpc-rel-600mw-anantapur-wtg (2 of 2 runs not finished) | 1 | 2 | 14 | 80 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| wind | seci-wind-tranche-xx (3 of 3 runs not finished) | 2 | 4 | 239 | 80 | 0 | 0 | n/a | 0% | 0 | 0 | 0 | 0.00 |
| **fully extracted** | 2 of 13 tenders | 3 | 5 | 393 | 174 | 119 | 119 | 100% | 68% | 3 | 2,998,847 | 205,733 | 40.28 |

**2 of 13 tenders are fully extracted.** The last row and the tables below count only those; tokens and cost count every finished run. A run that is not finished has no token total yet.

Cost of all model calls in the database, including section maps and runs that were repeated: **USD 68.81** over 138 calls. The table counts every finished extraction run of a tender, including repeated ones.

## Per tender type

| Type | Tenders | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- | --- |
| bess | 1 | 89 | 55 | 55 | 100% | 62% |
| fdre | 1 | 85 | 64 | 64 | 100% | 75% |

## Per section, all tenders

| Section | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- |
| summary | 2 | 2 | 2 | 100% | 100% |
| identity_and_scope | 30 | 27 | 27 | 100% | 90% |
| key_dates | 28 | 10 | 10 | 100% | 36% |
| eligibility | 20 | 9 | 9 | 100% | 45% |
| guarantees | 20 | 15 | 15 | 100% | 75% |
| commercial | 16 | 11 | 11 | 100% | 69% |
| penalties | 10 | 8 | 8 | 100% | 80% |
| connectivity_and_compliance | 18 | 13 | 13 | 100% | 72% |
| documents | 6 | 6 | 6 | 100% | 100% |
| bess_performance | 14 | 9 | 9 | 100% | 64% |
| fdre_profile | 10 | 9 | 9 | 100% | 90% |

## Fields with an evidence-location rate under 95%, by tender type

None: every value returned has located evidence.
