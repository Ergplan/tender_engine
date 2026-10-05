# Extraction summary

Generated 2026-10-05 12:19 UTC by `python -m scripts.ingest_tenders summary` (the same content is served by `GET /api/v1/reports/extraction-summary`). Model `claude-fable-5-1`. Candidates only: nothing here has been reviewed.

- **Evidence-location rate** = values with located evidence / values returned (target 95%).
- **Answer rate** = fields with a value / fields in the schema (reported, not targeted; a field the documents do not state returning no value is a correct answer).
- A field counts once per tender: the best live candidate of the latest version that gives a value.
- **Failing validation** = fields whose shown candidate is `needs_review` (a rule failed, or a required field has no value).

## Per tender

| Type | Tender | Versions | Documents | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Failing validation | Tokens in | Tokens out | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 1 | 2 | 138 | 93 | 66 | 66 | 100% | 71% | 0 | 1,050,014 | 74,352 | 13.50 |
| epc | seci-gaya-60mw | 1 | 3 | 646 | 91 | 59 | 59 | 100% | 65% | 0 | 1,613,844 | 106,494 | 20.85 |
| epc | seci-ramagiri-70mw-bess | 3 | 10 | 707 | 91 | 61 | 61 | 100% | 67% | 1 | 2,144,753 | 163,463 | 28.79 |
| fdre | nhpc-fdre-ii | 1 | 1 | 264 | 89 | 74 | 74 | 100% | 83% | 1 | 2,317,538 | 151,689 | 23.33 |
| fdre | seci-cfd-i | 4 | 6 | 342 | 89 | 78 | 78 | 100% | 88% | 1 | 2,377,682 | 180,652 | 31.31 |
| fdre | seci-fdre-ix | 2 | 5 | 257 | 89 | 76 | 76 | 100% | 85% | 1 | 2,202,432 | 170,263 | 29.94 |
| fdre | seci-fdre-rtc-v | 5 | 8 | 306 | 89 | 75 | 73 | 97% | 84% | 2 | 2,153,985 | 184,042 | 29.98 |
| generation | ntpc-phes-2000mw | 1 | 2 | 4 | 86 | 32 | 32 | 100% | 37% | 0 | 461,581 | 95,244 | 8.37 |
| hybrid | ntpc-hybrid-03 | 1 | 1 | 138 | 85 | 66 | 66 | 100% | 78% | 0 | 977,404 | 79,422 | 12.92 |
| solar | seci-cni-1-700mw | 2 | 5 | 242 | 87 | 68 | 68 | 100% | 78% | 0 | 1,971,736 | 134,834 | 19.83 |
| transmission | recpdcl-beed-tbcb | 1 | 1 | 166 | 89 | 51 | 51 | 100% | 57% | 1 | 1,091,275 | 73,536 | 14.02 |
| wind | ntpc-rel-600mw-anantapur-wtg | 1 | 2 | 14 | 84 | 33 | 33 | 100% | 39% | 0 | 603,610 | 58,172 | 4.87 |
| wind | seci-wind-tranche-xx | 2 | 5 | 240 | 84 | 67 | 67 | 100% | 80% | 0 | 1,189,052 | 84,373 | 15.51 |
| **fully extracted** | 13 of 13 tenders | 25 | 51 | 3464 | 1146 | 806 | 804 | 100% | 70% | 7 | 20,154,906 | 1,556,536 | 253.22 |

**13 of 13 tenders are fully extracted.** The last row and the tables below count only those; tokens and cost count every finished run. A run that is not finished has no token total yet.

Cost of all model calls in the database, including section maps and runs that were repeated: **USD 269.27** over 539 calls. The table counts every finished extraction run of a tender, including repeated ones.

## Per tender type

| Type | Tenders | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- | --- |
| bess | 1 | 93 | 66 | 66 | 100% | 71% |
| epc | 2 | 182 | 120 | 120 | 100% | 66% |
| fdre | 4 | 356 | 303 | 301 | 99% | 85% |
| generation | 1 | 86 | 32 | 32 | 100% | 37% |
| hybrid | 1 | 85 | 66 | 66 | 100% | 78% |
| solar | 1 | 87 | 68 | 68 | 100% | 78% |
| transmission | 1 | 89 | 51 | 51 | 100% | 57% |
| wind | 2 | 168 | 100 | 100 | 100% | 60% |

## Per section, all tenders

| Section | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- |
| summary | 13 | 13 | 13 | 100% | 100% |
| identity_and_scope | 195 | 152 | 150 | 99% | 78% |
| key_dates | 206 | 141 | 141 | 100% | 68% |
| eligibility | 156 | 103 | 103 | 100% | 66% |
| guarantees | 130 | 82 | 82 | 100% | 63% |
| commercial | 102 | 64 | 64 | 100% | 63% |
| penalties | 65 | 37 | 37 | 100% | 57% |
| connectivity_and_compliance | 117 | 74 | 74 | 100% | 63% |
| documents | 39 | 37 | 37 | 100% | 95% |
| bess_performance | 14 | 9 | 9 | 100% | 64% |
| epc_scope | 28 | 25 | 25 | 100% | 89% |
| fdre_profile | 40 | 36 | 36 | 100% | 90% |
| gen_tech | 7 | 4 | 4 | 100% | 57% |
| hybrid_mix | 6 | 5 | 5 | 100% | 83% |
| solar_tech | 8 | 5 | 5 | 100% | 62% |
| tbcb_elements | 10 | 10 | 10 | 100% | 100% |
| wind_tech | 10 | 9 | 9 | 100% | 90% |

## Fields with an evidence-location rate under 95%, by tender type

| Type | Field | Values returned | Located | Rate | Tenders where not located |
| --- | --- | --- | --- | --- | --- |
| fdre | `sector.power.common.min_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
| fdre | `sector.power.common.max_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
