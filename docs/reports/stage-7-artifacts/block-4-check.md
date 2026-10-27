# Block 4 check: the blind set read without a reviewer

Generated 2026-10-27 00:59 UTC by `python -m scripts.blind_check`. Candidates only; no value here has been reviewed, and no accuracy is claimed.

## Readings

| Tender | Type (manifest) | Complete | Versions | Docs | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | bess | yes | 4 | 5 | 215 | 112 | 81 | 81 | 100.0% | 72.3% | 13.02 |
| tgredco-rtc-2000mw | re_rtc | yes | 1 | 3 | 233 | 112 | 78 | 78 | 100.0% | 69.6% | 10.50 |
| recpdcl-bikaner-v-part-a | transmission | no | 6 | 10 | 528 | 108 | 56 | 56 | 100.0% | 51.9% | 10.76 |
| sjvn-wind-4-600mw | wind | yes | 12 | 12 | 326 | 103 | 79 | 79 | 100.0% | 76.7% | 12.38 |
| **all** | | | | | | 435 | 294 | 294 | 100.0% | 67.6% | 46.66 |

## Confidence distribution (fields with a value; located share of each band)

| Tender | High | Medium | Low | Unlocated at high confidence |
| --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | 48 (100.0% located) | 28 (100.0% located) | 5 (100.0% located) | none |
| tgredco-rtc-2000mw | 68 (100.0% located) | 9 (100.0% located) | 1 (100.0% located) | none |
| recpdcl-bikaner-v-part-a | 36 (100.0% located) | 18 (100.0% located) | 2 (100.0% located) | none |
| sjvn-wind-4-600mw | 69 (100.0% located) | 9 (100.0% located) | 1 (100.0% located) | none |

## Rule validation

| Tender | Rules run | Passed | Pass rate | Failed (error) | Failed (warning) | Fields in needs_review | Failing rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | 260 | 258 | 99.2% | 2 | 0 | 2 | range (error) ×1, type (error) ×1 |
| tgredco-rtc-2000mw | 181 | 181 | 100.0% | 0 | 0 | 0 | none |
| recpdcl-bikaner-v-part-a | 141 | 136 | 96.5% | 3 | 2 | 3 | evidence_not_located (error) ×2, date_order (warning) ×2, type (error) ×1 |
| sjvn-wind-4-600mw | 214 | 213 | 99.5% | 1 | 0 | 1 | evidence_not_located (error) ×1 |

## Type classification (the main document, against the manifest)

| Tender | Manifest | Classifier | Confidence | Band | Outcome | Document |
| --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | bess | bess | 0.98 | set | agree | v3_Final_BESS-Medium-Term_Procurement_v7-24_09_26.pdf |
| tgredco-rtc-2000mw | re_rtc | fdre | 0.7 | unsure | differ_unsure | TG_2000MW_RTC_RfS.pdf |
| recpdcl-bikaner-v-part-a | transmission | transmission | 0.98 | set | agree | RFP_Part_A_14.08.2026_bikaner.pdf |
| sjvn-wind-4-600mw | wind | wind | 0.98 | set | agree | SJVN_Wind_4_Combined.pdf |

## Amendment linking (each later document from its own pages, against the tender it was ingested under)

| Tender | Version | Kind | Document | Outcome | Method | Confidence | References found |
| --- | --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | v2 | corrigendum | v1_Corrigendum-1_MT_BESS-tender.pdf | linked_to_own | title | 1.00 | 1 |
| msedcl-bess-mt-1000mw | v3 | amendment | Final-Addendum_15.10.2026.pdf | linked_to_own | title | 1.00 | 1 |
| msedcl-bess-mt-1000mw | v4 | amendment | Addendum-2_18.10.2026-1.pdf | linked_to_own | reference | 0.98 | 2 |
| recpdcl-bikaner-v-part-a | v2 | clarification | Postponement_of_Pre-bid_meeting_Bikaner_Part_A_04092026.pdf | ask | title | 0.83 | 0 |
| recpdcl-bikaner-v-part-a | v3 | clarification | Notice_for_Pre-bid_Meeting_Bikaner_Part_A_18092026.pdf | ask | title | 0.83 | 0 |
| recpdcl-bikaner-v-part-a | v4 | amendment | Amendment-I_dated_21.09.2026_Bikaner_Part_A.pdf | linked_to_own | title | 0.87 | 0 |
| recpdcl-bikaner-v-part-a | v5 | amendment | Amendment-II_dated_10082026_Bikaner_Part_A.pdf | ask | title | 0.65 | 0 |
| recpdcl-bikaner-v-part-a | v6 | amendment | Amendment-III_dated_16102026_Bikaner_Part_A.pdf | ask | title | 0.78 | 1 |
| sjvn-wind-4-600mw | v2 | corrigendum | Corigerndum_1_WIND_4_17102025.pdf | linked_to_own | title | 0.95 | 1 |
| sjvn-wind-4-600mw | v3 | corrigendum | Corrigendum_2_WIND_4_Date_Extension_upto_181125_published.pdf | linked_to_own | reference | 0.98 | 11 |
| sjvn-wind-4-600mw | v4 | corrigendum | Corrigendum_3_WIND_4_Date_Extension_upto_091225_published.pdf | linked_to_own | reference | 0.98 | 23 |
| sjvn-wind-4-600mw | v5 | corrigendum | Corrigendum_4_WIND_4_Date_Extension_upto_301225_uploaded.pdf | linked_to_own | reference | 0.98 | 23 |
| sjvn-wind-4-600mw | v6 | corrigendum | Corrigendum_5_WIND_4_Date_Extension_upto_130126_published.pdf | linked_to_own | reference | 0.98 | 24 |
| sjvn-wind-4-600mw | v7 | corrigendum | Corrigendum_6_WIND_4_Date_Extension_upto_270126_UPLOADED.pdf | linked_to_own | reference | 0.98 | 24 |
| sjvn-wind-4-600mw | v8 | corrigendum | Corrigendum_7_WIND_4_Date_Extension_upto_100226_PUBLISHED.pdf | linked_to_own | reference | 0.98 | 24 |
| sjvn-wind-4-600mw | v9 | corrigendum | Corrigendum_8_WIND_4_Date_Extension_upto_240226_epublish.pdf | linked_to_own | reference | 0.98 | 30 |
| sjvn-wind-4-600mw | v10 | corrigendum | Corrigendum_9_WIND_4_Date_Extension_upto_170326_Published.pdf | linked_to_own | reference | 0.98 | 26 |
| sjvn-wind-4-600mw | v11 | corrigendum | Corrigendum_10_WIND_4_Date_Extension_upto_070426_PUBLISHED.pdf | linked_to_own | reference | 0.98 | 28 |
| sjvn-wind-4-600mw | v12 | corrigendum | Corrigendum_11_WIND_4_Date_Extension_upto_280426.pdf | linked_to_own | reference | 0.98 | 3 |

Linking outcomes: linked_to_own 15, ask 4

## Change classes (the amendments view, per later version)

| Tender | Version | Kind | Issued | Changes | By class |
| --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | v2 | corrigendum | 2026-10-06 | 13 | date_moved 2, restated 5, value_changed 6 |
| msedcl-bess-mt-1000mw | v3 | amendment | 2026-10-15 | 56 | annexure_replaced 2, date_moved 2, requirement_added 6, restated 19, value_changed 27 |
| msedcl-bess-mt-1000mw | v4 | amendment | 2026-10-18 | 27 | clause_withdrawn 2, restated 14, value_changed 11 |
| recpdcl-bikaner-v-part-a | v2 | clarification | 2026-09-04 | 3 | clause_withdrawn 1, requirement_added 1, restated 1 |
| recpdcl-bikaner-v-part-a | v3 | clarification | 2026-09-18 | 0 | - |
| recpdcl-bikaner-v-part-a | v4 | amendment | 2026-09-21 | 0 | - |
| recpdcl-bikaner-v-part-a | v5 | amendment | 2026-10-07 | 0 | - |
| recpdcl-bikaner-v-part-a | v6 | amendment | 2026-10-16 | 0 | - |
| sjvn-wind-4-600mw | v2 | corrigendum | 2025-10-17 | 9 | date_moved 2, restated 3, value_changed 4 |
| sjvn-wind-4-600mw | v3 | corrigendum | 2025-11-03 | 11 | date_moved 2, restated 3, value_changed 6 |
| sjvn-wind-4-600mw | v4 | corrigendum | 2025-11-13 | 12 | date_moved 3, restated 7, value_changed 2 |
| sjvn-wind-4-600mw | v5 | corrigendum | 2025-12-03 | 12 | date_moved 2, restated 7, value_changed 3 |
| sjvn-wind-4-600mw | v6 | corrigendum | 2025-12-29 | 12 | annexure_replaced 1, date_moved 2, restated 7, value_changed 2 |
| sjvn-wind-4-600mw | v7 | corrigendum | 2026-01-13 | 12 | annexure_replaced 1, date_moved 2, restated 5, value_changed 4 |
| sjvn-wind-4-600mw | v8 | corrigendum | 2026-01-23 | 10 | date_moved 2, restated 6, value_changed 2 |
| sjvn-wind-4-600mw | v9 | corrigendum | 2026-02-09 | 5 | date_moved 3, restated 2 |
| sjvn-wind-4-600mw | v10 | corrigendum | 2026-02-24 | 11 | date_moved 3, restated 7, value_changed 1 |
| sjvn-wind-4-600mw | v11 | corrigendum | 2026-03-13 | 12 | date_moved 2, restated 9, value_changed 1 |
| sjvn-wind-4-600mw | v12 | corrigendum | 2026-04-03 | 8 | date_moved 2, restated 4, value_changed 2 |

Changes by class over the set: date_moved 29, restated 99, value_changed 71, annexure_replaced 4, requirement_added 7, clause_withdrawn 3
