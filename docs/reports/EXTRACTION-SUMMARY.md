# Extraction summary

Generated 2026-10-05 16:56 UTC by `python -m scripts.ingest_tenders summary` (the same content is served by `GET /api/v1/reports/extraction-summary`). Model `claude-fable-5-1`. Candidates only: nothing here has been reviewed.

- **Evidence-location rate** = values with located evidence / values returned (target 95%).
- **Answer rate** = fields with a value / fields in the schema (reported, not targeted; a field the documents do not state returning no value is a correct answer).
- A field counts once per tender: the best live candidate of the latest version that gives a value.
- **Failing validation** = fields whose shown candidate is `needs_review` (a rule failed, or a required field has no value).

## Per tender

| Type | Tender | Versions | Documents | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Failing validation | Tokens in | Tokens out | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 1 | 2 | 138 | 101 | 73 | 73 | 100% | 72% | 0 | 1,392,726 | 112,595 | 16.44 |
| epc | seci-gaya-60mw | 1 | 3 | 646 | 99 | 63 | 63 | 100% | 64% | 0 | 2,465,677 | 172,795 | 27.15 |
| epc | seci-ramagiri-70mw-bess | 3 | 10 | 707 | 99 | 65 | 65 | 100% | 66% | 2 | 3,204,628 | 259,627 | 36.87 |
| fdre | nhpc-fdre-ii | 1 | 1 | 264 | 97 | 82 | 82 | 100% | 85% | 2 | 2,774,678 | 200,960 | 30.36 |
| fdre | seci-cfd-i | 4 | 6 | 342 | 97 | 85 | 85 | 100% | 88% | 1 | 3,245,396 | 265,070 | 37.87 |
| fdre | seci-fdre-ix | 2 | 5 | 257 | 97 | 84 | 84 | 100% | 87% | 4 | 2,722,054 | 226,609 | 34.33 |
| fdre | seci-fdre-rtc-v | 5 | 8 | 306 | 97 | 83 | 81 | 98% | 86% | 3 | 3,164,968 | 295,769 | 37.01 |
| generation | ntpc-phes-2000mw | 1 | 2 | 4 | 92 | 32 | 32 | 100% | 35% | 0 | 520,547 | 106,409 | 9.04 |
| hybrid | ntpc-hybrid-03 | 1 | 1 | 138 | 93 | 72 | 72 | 100% | 77% | 1 | 1,255,627 | 103,640 | 15.25 |
| solar | seci-cni-1-700mw | 2 | 5 | 242 | 95 | 76 | 76 | 100% | 80% | 1 | 2,413,789 | 176,122 | 23.42 |
| transmission | recpdcl-beed-tbcb | 1 | 1 | 166 | 97 | 54 | 54 | 100% | 56% | 3 | 1,388,477 | 102,772 | 16.55 |
| wind | ntpc-rel-600mw-anantapur-wtg | 1 | 2 | 14 | 92 | 33 | 33 | 100% | 36% | 0 | 700,370 | 72,417 | 5.92 |
| wind | seci-wind-tranche-xx | 2 | 5 | 240 | 92 | 74 | 74 | 100% | 80% | 1 | 1,710,429 | 128,827 | 19.58 |
| **fully extracted** | 13 of 13 tenders | 25 | 51 | 3464 | 1248 | 876 | 874 | 100% | 70% | 18 | 26,959,366 | 2,223,612 | 309.79 |

**13 of 13 tenders are fully extracted.** The last row and the tables below count only those; tokens and cost count every finished run. A run that is not finished has no token total yet.

Cost of all model calls in the database, including section maps and runs that were repeated: **USD 325.85** over 711 calls. The table counts every finished extraction run of a tender, including repeated ones.

## Per tender type

| Type | Tenders | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- | --- |
| bess | 1 | 101 | 73 | 73 | 100% | 72% |
| epc | 2 | 198 | 128 | 128 | 100% | 65% |
| fdre | 4 | 388 | 334 | 332 | 99% | 86% |
| generation | 1 | 92 | 32 | 32 | 100% | 35% |
| hybrid | 1 | 93 | 72 | 72 | 100% | 77% |
| solar | 1 | 95 | 76 | 76 | 100% | 80% |
| transmission | 1 | 97 | 54 | 54 | 100% | 56% |
| wind | 2 | 184 | 107 | 107 | 100% | 58% |

## Per section, all tenders

| Section | Fields | With a value | Located | Evidence-location rate | Answer rate |
| --- | --- | --- | --- | --- | --- |
| summary | 13 | 13 | 13 | 100% | 100% |
| identity_and_scope | 195 | 152 | 150 | 99% | 78% |
| key_dates | 206 | 141 | 141 | 100% | 68% |
| eligibility | 156 | 103 | 103 | 100% | 66% |
| guarantees | 156 | 101 | 101 | 100% | 65% |
| commercial | 128 | 77 | 77 | 100% | 60% |
| penalties | 91 | 56 | 56 | 100% | 62% |
| connectivity_and_compliance | 117 | 74 | 74 | 100% | 63% |
| documents | 39 | 37 | 37 | 100% | 95% |
| bess_performance | 16 | 10 | 10 | 100% | 62% |
| epc_scope | 32 | 28 | 28 | 100% | 88% |
| fdre_profile | 48 | 44 | 44 | 100% | 92% |
| gen_tech | 7 | 4 | 4 | 100% | 57% |
| hybrid_mix | 8 | 7 | 7 | 100% | 88% |
| solar_tech | 10 | 7 | 7 | 100% | 70% |
| tbcb_elements | 12 | 12 | 12 | 100% | 100% |
| wind_tech | 14 | 10 | 10 | 100% | 71% |

## Fields with an evidence-location rate under 95%, by tender type

| Type | Field | Values returned | Located | Rate | Tenders where not located |
| --- | --- | --- | --- | --- | --- |
| fdre | `sector.power.common.min_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
| fdre | `sector.power.common.max_bid_mw` | 4 | 3 | 75% | seci-fdre-rtc-v |
