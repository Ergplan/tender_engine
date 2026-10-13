# Reliability report

Generated 2026-10-13 13:18 UTC by `python -m evals.report` (also `make report`). Every gold record scored against the candidates now in review at the version it was reviewed at. Accuracy is value accuracy: the candidate the reviewer saw against what they decided. Evidence accuracy asks whether the candidate cited a page the reviewer accepted. Long text is not scored by rule.

## Tenders reviewed

| Type | In the set | Reviewed | Tenders |
| --- | --- | --- | --- |
| bess | 1 | 1 | seci-ess-iv |
| epc | 2 | 0 | - |
| fdre | 4 | 2 | nhpc-fdre-ii, seci-cfd-i |
| generation | 1 | 1 | ntpc-phes-2000mw |
| hybrid | 1 | 1 | ntpc-hybrid-03 |
| re_rtc | 1 | 0 | - |
| solar | 1 | 1 | seci-cni-1-700mw |
| transmission | 1 | 0 | - |
| wind | 2 | 1 | ntpc-rel-600mw-anantapur-wtg |

## Accuracy

- Value accuracy: **98%** on 598 scored fields (588 correct); 80 long-text fields need human judgement.
- Evidence accuracy: **100%** on 380 fields with a value and accepted pages (380 cited an accepted page). A right value from the wrong page counts as right above and wrong here.

| Section | Accuracy | n | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| bess_performance | 100% | 15 | 100% | stable |
| commercial | 100% | 54 | 100% | stable |
| connectivity_and_compliance | 100% | 57 | 100% | stable |
| documents | 95% | 21 | 100% | stable |
| eligibility | 100% | 73 | 100% | stable |
| fdre_profile | 100% | 18 | 100% | stable |
| gen_tech | 100% | 7 | 100% | stable |
| guarantees | 97% | 68 | 100% | stable |
| hybrid_mix | 100% | 8 | 100% | stable |
| identity_and_scope | 96% | 105 | 100% | stable |
| key_dates | 97% | 105 | 100% | stable |
| penalties | 100% | 39 | 100% | stable |
| solar_tech | 100% | 10 | 100% | stable |
| supply_sources | 100% | 11 | 100% | stable |
| wind_tech | 100% | 7 | 100% | stable |

### By tender type

| Type | Accuracy | n | Evidence |
| --- | --- | --- | --- |
| bess | 99% | 90 | 100% |
| fdre | 98% | 159 | 100% |
| generation | 98% | 92 | 100% |
| hybrid | 98% | 84 | 100% |
| solar | 99% | 84 | 100% |
| wind | 99% | 89 | 100% |

## Fields below 90%

| Field | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- |
| `core.documents.draft_agreements_referenced` | 86% | 7 | 1 | wrong_value 1 |
| `core.guarantees.emd_formula` | 75% | 4 | 1 | missing 1 |
| `core.guarantees.pbg_formula` | 75% | 4 | 1 | missing 1 |
| `core.identity.portal` | 86% | 7 | 1 | extra 1 |
| `core.identity.procurement_mode` | 86% | 7 | 1 | wrong_value 1 |
| `core.key_dates.loa_timeline` | 86% | 7 | 1 | missing 1 |
| `core.key_dates.pre_bid_meeting_date` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.metering_point` | 86% | 7 | 1 | wrong_value 1 |
| `sector.power.common.named_states_or_sites` | 86% | 7 | 1 | wrong_value 1 |
| `sector.power.common.scod_reference` | 86% | 7 | 1 | wrong_value 1 |

## Structured fields by key

| Field | Key | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- | --- |
| `core.commercial.payment_security_structured` | `lc_drawable_after_days` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_months_of_billing` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_required` | 100% | 3 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_revolving` | 100% | 3 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_available` | 100% | 4 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_charge_inr_per_kwh` | 100% | 2 | 0 | - |
| `core.guarantees.emd_structured` | `basis` | 100% | 6 | 0 | - |
| `core.guarantees.emd_structured` | `cap_inr` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `cap_per` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `components` | 100% | 2 | 0 | - |
| `core.guarantees.emd_structured` | `lump_sum_inr` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `rate_inr_per_mw` | 100% | 3 | 0 | - |
| `core.guarantees.pbg_structured` | `basis` | 100% | 5 | 0 | - |
| `core.guarantees.pbg_structured` | `components` | 100% | 2 | 0 | - |
| `core.guarantees.pbg_structured` | `lump_sum_inr` | 100% | 1 | 0 | - |
| `core.guarantees.pbg_structured` | `rate_inr_per_mw` | 100% | 2 | 0 | - |
| `core.guarantees.pbg_structured` | `submitted_before` | 100% | 5 | 0 | - |
| `core.guarantees.pbg_structured` | `valid_months_after_scod` | 100% | 5 | 0 | - |
| `core.penalties.delay_ld_structured` | `basis` | 100% | 5 | 0 | - |
| `core.penalties.delay_ld_structured` | `pbg_encashed_over_months` | 100% | 5 | 0 | - |
| `core.penalties.shortfall_rules` | `default_after_years` | 100% | 2 | 0 | - |
| `core.penalties.shortfall_rules` | `default_damages_months_of_tariff` | 100% | 3 | 0 | - |
| `core.penalties.shortfall_rules` | `measured` | 100% | 5 | 0 | - |
| `core.penalties.shortfall_rules` | `metric` | 100% | 6 | 0 | - |
| `core.penalties.shortfall_rules` | `penalty_multiple_of_tariff` | 100% | 6 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_of` | 100% | 5 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_pct` | 100% | 6 | 0 | - |
| `core.penalties.shortfall_rules` | `tolerance_pct` | 100% | 2 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `augmentation_at_cost_of` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `augmentation_required` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `basis` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `end_of_term_pct` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `replacement_outage_counts` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `schedule` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `term_years` | 100% | 1 | 0 | - |
| `sector.power.bess.degradation_and_augmentation_structured` | `year_1_end_pct` | 100% | 1 | 0 | - |
| `sector.power.common.bess_charging_rule` | `co_located_required` | 100% | 1 | 0 | - |
| `sector.power.common.bess_charging_rule` | `re_only` | 100% | 4 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `backdown_threshold_hours_per_year` | 100% | 2 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_basis` | 100% | 3 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_pct_of_tariff` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `exchange_sale_share_adjusted_pct` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `grid_threshold_hours_per_year` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `payer` | 100% | 3 | 0 | - |
| `sector.power.common.source_mix_rules` | `condition` | 100% | 13 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_unit` | 100% | 8 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_value` | 100% | 8 | 0 | - |
| `sector.power.common.source_mix_rules` | `source` | 100% | 13 | 0 | - |
| `sector.power.common.source_mix_rules` | `treatment` | 100% | 13 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `basis` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_band_lower_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_band_upper_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `cuf_declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `external_sourcing_max_pct` | 100% | 2 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_availability_pct` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_blocks` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_hours_chosen_by` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `peak_hours_per_day` | 100% | 1 | 0 | - |
| `sector.power.fdre.demand_profile_structured` | `re_share_min_pct` | 100% | 2 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `above` | 100% | 2 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `price_basis` | 100% | 2 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `procurer_first_right` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_lower_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_upper_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `revision_allowed_within_years` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `above` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `price_basis` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `procurer_first_right` | 100% | 1 | 0 | - |
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

## Reviewer time per tender

| Tender | Reviewer | Sittings | Minutes deciding | Decisions | Completed |
| --- | --- | --- | --- | --- | --- |
| seci-ess-iv | venture@aayuda.energy | 1 | 23 | 107 | 2026-10-13 12:14 |
| nhpc-fdre-ii | venture@aayuda.energy | 8 | 56 | 116 | 2026-10-06 12:48 |
| seci-cfd-i | venture@aayuda.energy | 1 | 68 | 107 | 2026-10-13 10:32 |
| ntpc-phes-2000mw | venture@aayuda.energy | 2 | 36 | 105 | 2026-10-13 07:29 |
| ntpc-hybrid-03 | venture@aayuda.energy | 3 | 76 | 117 | 2026-10-13 06:26 |
| seci-cni-1-700mw | venture@aayuda.energy | 1 | 66 | 105 | 2026-10-13 11:44 |
| ntpc-rel-600mw-anantapur-wtg | venture@aayuda.energy | 1 | 29 | 104 | 2026-10-13 08:55 |

## Stability bar for Stage 5

**Not met.** Required-field value accuracy 100%.

At least 2 reviewed tenders for every type with 2 or more in the set (epc, fdre, wind); required-field value accuracy at least 90% across the last two prompt versions; no required field below 75%.

- fewer than 2 reviewed tenders for: epc, wind
- required-field accuracy by section prompt, last two versions seen: extract/bess_performance v2 100%; extract/hybrid_mix v2 100%; extract/identity_and_scope v1 100%; extract/key_dates v1 100%

