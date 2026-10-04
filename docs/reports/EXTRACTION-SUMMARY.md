# Extraction summary

Generated 2026-10-04 16:35 UTC by `python -m scripts.ingest_tenders summary` (the same content is served by `GET /api/v1/reports/extraction-summary`). Model `claude-fable-5-1`. Candidates only: nothing here has been reviewed.

- **Evidence-location rate** = values with located evidence / values returned (target 95%).
- **Answer rate** = fields with a value / fields in the schema (reported, not targeted; a field the documents do not state returning no value is a correct answer).
- A field counts once per tender: the best live candidate of the latest version that gives a value.
- **Failing validation** = fields whose shown candidate is `needs_review` (a rule failed, or a required field has no value).

## Per tender

| Type | Tender | Versions | Documents | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Failing validation | Tokens in | Tokens out | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 1 | 1 | 137 | 89 | 55 | 55 | 100% | 62% | 1 | 820,681 | 46,428 | 10.53 |
| epc | seci-gaya-60mw | 1 | 2 | 645 | 89 | 56 | 56 | 100% | 63% | 2 | 1,399,681 | 81,072 | 18.05 |
| epc | seci-ramagiri-70mw-bess | 3 | 9 | 706 | 89 | 58 | 58 | 100% | 65% | 3 | 1,824,112 | 129,388 | 24.71 |
| fdre | nhpc-fdre-ii | 1 | 1 | 264 | 85 | 68 | 68 | 100% | 80% | 3 | 1,015,807 | 63,637 | 13.34 |
| fdre | seci-cfd-i | 4 | 5 | 341 | 85 | 66 | 66 | 100% | 78% | 2 | 1,894,730 | 126,249 | 25.26 |
| fdre | seci-fdre-ix | 2 | 4 | 256 | 85 | 64 | 64 | 100% | 75% | 2 | 1,973,025 | 143,446 | 26.90 |
| fdre | seci-fdre-rtc-v | 5 | 7 | 305 | 85 | 63 | 61 | 97% | 74% | 4 | 1,698,744 | 138,276 | 23.90 |
| generation | ntpc-phes-2000mw | 1 | 1 | 3 | 82 | 31 | 31 | 100% | 38% | 1 | 97,513 | 17,262 | 1.84 |
| hybrid | ntpc-hybrid-03 | 1 | 1 | 138 | 81 | 59 | 59 | 100% | 73% | 0 | 650,033 | 40,434 | 8.52 |
| solar | seci-cni-1-700mw | 2 | 4 | 241 | 83 | 59 | 59 | 100% | 71% | 0 | 870,662 | 52,252 | 11.32 |
| transmission | recpdcl-beed-tbcb | 1 | 1 | 166 | 85 | 50 | 50 | 100% | 59% | 2 | 838,528 | 51,168 | 10.94 |
| wind | ntpc-rel-600mw-anantapur-wtg | 1 | 2 | 14 | 80 | 26 | 26 | 100% | 32% | 0 | 175,616 | 20,455 | 2.78 |
| wind | seci-wind-tranche-xx | 2 | 4 | 239 | 80 | 56 | 56 | 100% | 70% | 1 | 963,817 | 58,329 | 12.55 |
| **fully extracted** | 13 of 13 tenders | 25 | 42 | 3455 | 1098 | 711 | 709 | 100% | 65% | 21 | 14,222,949 | 968,396 | 190.65 |

**13 of 13 tenders are fully extracted.** The last row and the tables below count only those; tokens and cost count every finished run. A run that is not finished has no token total yet.

Cost of all model calls in the database, including section maps and runs that were repeated: **USD 203.31** over 339 calls. The table counts every finished extraction run of a tender, including repeated ones.

## Per tender type

| Type | Tenders | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- | --- |
| bess | 1 | 89 | 55 | 55 | 100% | 62% |
| epc | 2 | 178 | 114 | 114 | 100% | 64% |
| fdre | 4 | 340 | 261 | 259 | 99% | 77% |
| generation | 1 | 82 | 31 | 31 | 100% | 38% |
| hybrid | 1 | 81 | 59 | 59 | 100% | 73% |
| solar | 1 | 83 | 59 | 59 | 100% | 71% |
| transmission | 1 | 85 | 50 | 50 | 100% | 59% |
| wind | 2 | 160 | 82 | 82 | 100% | 51% |

## Per section, all tenders

| Section | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- |
| summary | 13 | 13 | 13 | 100% | 100% |
| identity_and_scope | 195 | 151 | 149 | 99% | 77% |
| key_dates | 182 | 90 | 90 | 100% | 49% |
| eligibility | 130 | 62 | 62 | 100% | 48% |
| guarantees | 130 | 81 | 81 | 100% | 62% |
| commercial | 104 | 64 | 64 | 100% | 62% |
| penalties | 65 | 37 | 37 | 100% | 57% |
| connectivity_and_compliance | 117 | 75 | 75 | 100% | 64% |
| documents | 39 | 34 | 34 | 100% | 87% |
| bess_performance | 14 | 9 | 9 | 100% | 64% |
| epc_scope | 28 | 25 | 25 | 100% | 89% |
| fdre_profile | 40 | 36 | 36 | 100% | 90% |
| gen_tech | 7 | 5 | 5 | 100% | 71% |
| hybrid_mix | 6 | 5 | 5 | 100% | 83% |
| solar_tech | 8 | 5 | 5 | 100% | 62% |
| tbcb_elements | 10 | 10 | 10 | 100% | 100% |
| wind_tech | 10 | 9 | 9 | 100% | 90% |

## Fields with an evidence-location rate under 95%, by tender type

| Type | Field | Values returned | Located | Rate | Tenders where not located |
| --- | --- | --- | --- | --- | --- |
| fdre | `sector.power.common.min_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
| fdre | `sector.power.common.max_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
