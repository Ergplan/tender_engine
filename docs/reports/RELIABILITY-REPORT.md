# Reliability report

Generated 2026-10-28 19:31 UTC by `python -m evals.report` (also `make report`). Every gold record scored against the candidates now in review at the version it was reviewed at. Accuracy is value accuracy: the candidate the reviewer saw against what they decided. Evidence accuracy asks whether the candidate cited a page the reviewer accepted. Long text is not scored by rule.

## Headline (completion plan, Block 7 b)

- 97.5% field accuracy on 11 human-reviewed tenders (in-sample)
- 100.0% evidence location on 3 unseen tenders (238 of 238 values located on the page they cite; no accuracy claim)
- The question eval (Block 5 d, `make ask-eval`) has not run: the retrieval route calls the model, and no run was allowed yet.

The in-sample figure measures the engine on the tenders it was tuned on, against the reviewers' decisions; it is not a forecast for a new tender. The unseen tenders were never reviewed, so nothing about the correctness of their values is known: a located quote says the value is on the page it cites, not that it is the right value.

| Measurement | Figure | n | As of |
| --- | --- | --- | --- |
| Field accuracy, gold set (in-sample) | 97.5% | 942 scored fields of 11 tenders | 2026-10-28T19:31:44+00:00 |
| Critical fields, gold set (in-sample) | 98.8% | 249 | 2026-10-28T19:31:44+00:00 |
| Evidence accuracy, gold set | 100.0% | 634 | 2026-10-28T19:31:44+00:00 |
| Wrong readings shown at high confidence, gold set | 10 | 942 | 2026-10-28T19:31:44+00:00 |
| Evidence location, unseen tenders | 100.0% | 238 values, 3 tenders (msedcl-bess-mt-1000mw, tgredco-rtc-2000mw, sjvn-wind-4-600mw) | 2026-10-27T00:59:11.225898+00:00 |
| Deterministic rules passed, unseen tenders | 99.5% | 655 | 2026-10-27T00:59:11.225898+00:00 |
| Unlocated readings at high confidence, unseen tenders | 0 | 238 | 2026-10-27T00:59:11.225898+00:00 |
| Question eval | not run | – | – |

## Tenders reviewed

| Type | In the set | Reviewed | Tenders |
| --- | --- | --- | --- |
| bess | 3 | 1 | seci-ess-iv |
| epc | 3 | 1 | seci-gaya-60mw |
| fdre | 4 | 4 | nhpc-fdre-ii, seci-cfd-i, seci-fdre-ix, seci-fdre-rtc-v |
| generation | 1 | 1 | ntpc-phes-2000mw |
| hybrid | 1 | 1 | ntpc-hybrid-03 |
| re_rtc | 2 | 1 | wbsedcl-re-rtc-2026-01 |
| solar | 2 | 1 | seci-cni-1-700mw |
| transmission | 3 | 0 | - |
| wind | 4 | 1 | ntpc-rel-600mw-anantapur-wtg |

## Accuracy

- Value accuracy: **97%** on 942 scored fields (918 correct); 144 long-text fields need human judgement.
- Evidence accuracy: **100%** on 634 fields with a value and accepted pages (634 cited an accepted page). A right value from the wrong page counts as right above and wrong here.

| Section | Accuracy | n | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| bess_performance | 100% | 15 | 100% | stable |
| commercial | 100% | 78 | 100% | stable |
| connectivity_and_compliance | 100% | 87 | 100% | stable |
| documents | 97% | 33 | 100% | stable |
| eligibility | 100% | 119 | 100% | stable |
| epc_scope | 93% | 15 | 100% | stable |
| fdre_profile | 100% | 36 | 100% | stable |
| gen_tech | 100% | 7 | 100% | stable |
| guarantees | 98% | 105 | 100% | stable |
| hybrid_mix | 100% | 8 | 100% | stable |
| identity_and_scope | 95% | 165 | 100% | stable |
| key_dates | 96% | 164 | 100% | stable |
| penalties | 97% | 59 | 100% | stable |
| re_rtc_profile | 100% | 14 | 100% | stable |
| solar_tech | 100% | 10 | 100% | stable |
| summary | 0% | 2 | - | needs prompt work |
| supply_sources | 100% | 18 | 100% | stable |
| wind_tech | 100% | 7 | 100% | stable |

### By tender type

| Type | Accuracy | n | Evidence |
| --- | --- | --- | --- |
| bess | 99% | 90 | 100% |
| epc | 98% | 87 | 100% |
| fdre | 96% | 320 | 100% |
| generation | 98% | 92 | 100% |
| hybrid | 98% | 84 | 100% |
| re_rtc | 98% | 95 | 100% |
| solar | 98% | 85 | 100% |
| wind | 99% | 89 | 100% |

## Fields below 90%

| Field | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- |
| `core.guarantees.emd_formula` | 80% | 5 | 1 | missing 1 |
| `core.guarantees.pbg_formula` | 83% | 6 | 1 | missing 1 |
| `core.identity.procurement_mode` | 55% | 11 | 5 | wrong_value 5; across agencies SECI, WBSEDCL |
| `core.summary.plain_english_summary` | 0% | 2 | 2 | missing 2 |
| `sector.power.common.named_states_or_sites` | 82% | 11 | 2 | wrong_value 2 |
| `sector.power.common.ppa_signing_window_days` | 82% | 11 | 2 | wrong_value 2 |
| `sector.power.common.scod_reference` | 73% | 11 | 3 | wrong_value 3; across agencies SECI, NTPC Renewable Energy Ltd |
| `sector.power.epc.scope_matrix` | 0% | 1 | 1 | wrong_value 1 |

## Structured fields by key

| Field | Key | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- | --- |
| `core.commercial.payment_security_structured` | `lc_drawable_after_days` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_months_of_billing` | 100% | 3 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_required` | 100% | 6 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_revolving` | 100% | 6 | 0 | - |
| `core.commercial.payment_security_structured` | `payment_due_days` | 100% | 2 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_available` | 100% | 6 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_charge_inr_per_kwh` | 100% | 4 | 0 | - |
| `core.guarantees.bid_security_instruments` | `instrument` | 100% | 5 | 0 | - |
| `core.guarantees.bid_security_instruments` | `issuer` | 100% | 5 | 0 | - |
| `core.guarantees.emd_structured` | `basis` | 100% | 10 | 0 | - |
| `core.guarantees.emd_structured` | `cap_inr` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `cap_per` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `components` | 100% | 4 | 0 | - |
| `core.guarantees.emd_structured` | `lump_sum_inr` | 100% | 2 | 0 | - |
| `core.guarantees.emd_structured` | `rate_inr_per_mw` | 100% | 4 | 0 | - |
| `core.guarantees.pbg_instruments` | `instrument` | 100% | 2 | 0 | - |
| `core.guarantees.pbg_structured` | `basis` | 100% | 7 | 0 | - |
| `core.guarantees.pbg_structured` | `components` | 100% | 3 | 0 | - |
| `core.guarantees.pbg_structured` | `lump_sum_inr` | 100% | 1 | 0 | - |
| `core.guarantees.pbg_structured` | `rate_inr_per_mw` | 100% | 3 | 0 | - |
| `core.guarantees.pbg_structured` | `submitted_before` | 100% | 8 | 0 | - |
| `core.guarantees.pbg_structured` | `valid_months_after_scod` | 100% | 6 | 0 | - |
| `core.penalties.delay_ld_structured` | `basis` | 100% | 8 | 0 | - |
| `core.penalties.delay_ld_structured` | `cap_pct_of_contract_price` | 100% | 1 | 0 | - |
| `core.penalties.delay_ld_structured` | `pbg_encashed_over_months` | 100% | 7 | 0 | - |
| `core.penalties.delay_ld_structured` | `pct_per_week` | 100% | 1 | 0 | - |
| `core.penalties.shortfall_rules` | `default_after_years` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `default_damages_months_of_tariff` | 100% | 5 | 0 | - |
| `core.penalties.shortfall_rules` | `measured` | 100% | 8 | 0 | - |
| `core.penalties.shortfall_rules` | `metric` | 100% | 9 | 0 | - |
| `core.penalties.shortfall_rules` | `penalty_multiple_of_tariff` | 100% | 9 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_of` | 100% | 7 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_pct` | 100% | 8 | 0 | - |
| `core.penalties.shortfall_rules` | `tolerance_pct` | 100% | 3 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `augmentation_at_cost_of` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `augmentation_required` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `basis` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `end_of_term_pct` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `replacement_outage_counts` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `schedule` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `term_years` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `year_1_end_pct` | 100% | 1 | 0 | - |
| `sector.power.common.bess_charging_rule` | `co_located_required` | 100% | 3 | 0 | - |
| `sector.power.common.bess_charging_rule` | `re_only` | 100% | 7 | 0 | - |
| `sector.power.common.bess_charging_rule` | `regulation_reference` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `backdown_threshold_hours_per_year` | 100% | 4 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_basis` | 100% | 6 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_pct_of_tariff` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `exchange_sale_share_adjusted_pct` | 100% | 3 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `grid_threshold_hours_per_year` | 100% | 3 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `payer` | 100% | 6 | 0 | - |
| `sector.power.common.source_mix_rules` | `condition` | 100% | 27 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_unit` | 100% | 10 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_value` | 100% | 10 | 0 | - |
| `sector.power.common.source_mix_rules` | `source` | 100% | 27 | 0 | - |
| `sector.power.common.source_mix_rules` | `treatment` | 100% | 27 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `annual_cap_pct` | 100% | 1 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `cap_basis` | 100% | 1 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `discount_rate_pct` | 100% | 1 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `horizon_years` | 100% | 1 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `ld_tariff_inr_per_kwh` | 100% | 1 | 0 | - |
| `sector.power.epc.ld_performance_structured` | `metric` | 100% | 1 | 0 | - |
| `sector.power.epc.milestone_payment_structured` | `against` | 100% | 4 | 0 | - |
| `sector.power.epc.milestone_payment_structured` | `bg_required` | 100% | 1 | 0 | - |
| `sector.power.epc.milestone_payment_structured` | `contract` | 100% | 4 | 0 | - |
| `sector.power.epc.milestone_payment_structured` | `milestone` | 100% | 4 | 0 | - |
| `sector.power.epc.milestone_payment_structured` | `pct_of_contract_price` | 100% | 3 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `basis` | 100% | 3 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_band_lower_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_band_upper_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `external_sourcing_max_pct` | 100% | 3 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_availability_pct` | 100% | 2 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_blocks` | 100% | 2 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_energy_kwh_per_mw_per_day` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_hours_chosen_by` | 100% | 3 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_hours_per_day` | 100% | 3 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `re_share_min_pct` | 100% | 3 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `above` | 100% | 4 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `pct_of_tariff` | 100% | 1 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `price_basis` | 100% | 4 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `procurer_first_right` | 100% | 2 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_lower_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_upper_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `revision_allowed_within_years` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `above` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `price_basis` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `procurer_first_right` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.linked_capacity_obligation` | `consequence` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.linked_capacity_obligation` | `location` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.linked_capacity_obligation` | `multiple_of_contracted` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.linked_capacity_obligation` | `stages` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.linked_capacity_obligation` | `technology` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.non_re_tariff_split` | `fixed_charge_payable_when_not_scheduled` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.non_re_tariff_split` | `fixed_pct` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.non_re_tariff_split` | `merit_order_treatment` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.non_re_tariff_split` | `variable_pct` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.peak_window` | `hours_per_day` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.peak_window` | `set_by` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.peak_window` | `stretches` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.rec_obligation` | `applies_to` | 100% | 1 | 0 | - |
| `sector.power.re_rtc.rec_obligation` | `cost_borne_by` | 100% | 1 | 0 | - |
| `sector.power.solar.cuf_terms` | `band_lower_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.solar.cuf_terms` | `band_upper_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.solar.cuf_terms` | `declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.solar.cuf_terms` | `revision_allowed_within_years` | 100% | 1 | 0 | - |
| `sector.power.solar.excess_energy_structured` | `above` | 100% | 1 | 0 | - |
| `sector.power.solar.excess_energy_structured` | `price_basis` | 100% | 1 | 0 | - |

## Prompt versions tried

| Result | Prompt | Value accuracy | Evidence accuracy | n |
| --- | --- | --- | --- | --- |
| 20261006T172902Z-ergplan-latest.json | as pinned | 99% | 100% | 79 |
| 20261013T124146Z-ergplan-latest.json | as pinned | 78% | 100% | 624 |
| 20261013T131813Z-ergplan-latest.json | as pinned | 98% | 100% | 598 |
| 20261015T172301Z-ergplan-latest.json | as pinned | 97% | 100% | 942 |
| 20261024T155809Z-ergplan-latest.json | as pinned | 97% | 100% | 942 |
| 20261028T193144Z-ergplan-latest.json | as pinned | 97% | 100% | 942 |
| review-emphasis-ergplan.json | as pinned | - | - | None |

## Reviewer time per tender

| Tender | Reviewer | Sittings | Minutes deciding | Decisions | Completed |
| --- | --- | --- | --- | --- | --- |
| seci-ess-iv | venture@aayuda.energy | 1 | 23 | 107 | 2026-10-13 12:14 |
| seci-gaya-60mw | venture@aayuda.energy | 1 | 45 | 102 | 2026-10-15 06:16 |
| nhpc-fdre-ii | venture@aayuda.energy | 8 | 56 | 116 | 2026-10-06 12:48 |
| seci-cfd-i | venture@aayuda.energy | 1 | 68 | 107 | 2026-10-13 10:32 |
| seci-fdre-ix | venture@aayuda.energy | 2 | 55 | 100 | 2026-10-14 06:19 |
| seci-fdre-rtc-v | venture@aayuda.energy | 6 | 41 | 106 | 2026-10-14 12:33 |
| ntpc-phes-2000mw | venture@aayuda.energy | 2 | 36 | 105 | 2026-10-13 07:29 |
| ntpc-hybrid-03 | venture@aayuda.energy | 3 | 76 | 117 | 2026-10-13 06:26 |
| wbsedcl-re-rtc-2026-01 | venture@aayuda.energy | 1 | 24 | 114 | 2026-10-15 06:49 |
| seci-cni-1-700mw | venture@aayuda.energy | 1 | 66 | 105 | 2026-10-13 11:44 |
| ntpc-rel-600mw-anantapur-wtg | venture@aayuda.energy | 1 | 29 | 104 | 2026-10-13 08:55 |

## Stability bar for Stage 5

**Not met.** Required-field value accuracy 96%.

At least 2 reviewed tenders for every type with 2 or more in the set (bess, epc, fdre, re_rtc, solar, transmission, wind); required-field value accuracy at least 90% across the last two prompt versions; no required field below 75%.

- fewer than 2 reviewed tenders for: bess, epc, re_rtc, solar, transmission, wind
- required fields below 75%: 1
- required-field accuracy by section prompt, last two versions seen: extract/bess_performance v2 100%; extract/hybrid_mix v2 100%; extract/identity_and_scope v1 100%; extract/key_dates v1 100%; extract/re_rtc_profile v1 100%

