# Reliability report

Generated 2026-10-13 12:42 UTC by `python -m evals.report` (also `make report`). Every gold record scored against the candidates now in review at the version it was reviewed at. Accuracy is value accuracy: the candidate the reviewer saw against what they decided. Evidence accuracy asks whether the candidate cited a page the reviewer accepted. Long text is not scored by rule.

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

- Value accuracy: **78%** on 624 scored fields (489 correct); 54 long-text fields need human judgement.
- Evidence accuracy: **100%** on 281 fields with a value and accepted pages (280 cited an accepted page). A right value from the wrong page counts as right above and wrong here.

| Section | Accuracy | n | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| bess_performance | 100% | 15 | 100% | stable |
| commercial | 71% | 62 | 100% | needs prompt work |
| connectivity_and_compliance | 77% | 60 | 100% | needs prompt work |
| documents | 67% | 21 | 100% | needs prompt work |
| eligibility | 75% | 77 | 100% | needs prompt work |
| fdre_profile | 60% | 20 | 100% | needs prompt work |
| gen_tech | 100% | 7 | 100% | stable |
| guarantees | 70% | 74 | 100% | needs prompt work |
| hybrid_mix | 100% | 8 | 100% | stable |
| identity_and_scope | 86% | 105 | 100% | needs prompt work |
| key_dates | 85% | 105 | 98% | needs prompt work |
| penalties | 81% | 42 | 100% | needs prompt work |
| solar_tech | 30% | 10 | - | needs prompt work |
| supply_sources | 91% | 11 | 100% | stable |
| wind_tech | 100% | 7 | 100% | stable |

### By tender type

| Type | Accuracy | n | Evidence |
| --- | --- | --- | --- |
| bess | 99% | 90 | 100% |
| fdre | 62% | 174 | 100% |
| generation | 98% | 92 | 100% |
| hybrid | 98% | 84 | 100% |
| solar | 34% | 95 | 92% |
| wind | 99% | 89 | 100% |

## Fields below 90%

| Field | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- |
| `core.commercial.change_in_law_clause` | 67% | 6 | 2 | missing 2 |
| `core.commercial.late_payment_surcharge` | 71% | 7 | 2 | missing 2 |
| `core.commercial.offtaker` | 71% | 7 | 2 | missing 2 |
| `core.commercial.payment_security_mechanism` | 50% | 4 | 2 | missing 2 |
| `core.commercial.payment_security_structured` | 71% | 7 | 2 | missing 2 |
| `core.commercial.termination_compensation` | 67% | 6 | 2 | missing 2 |
| `core.documents.annexure_formats` | 71% | 7 | 2 | missing 2 |
| `core.documents.draft_agreements_referenced` | 57% | 7 | 3 | missing 2, wrong_value 1; across agencies SECI, NTPC Renewable Energy Ltd |
| `core.documents.required_documents` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.consortium_allowed` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.liquidity_basis` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.liquidity_requirement_inr` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.parent_affiliate_credentials_allowed` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.shareholding_lock_in` | 50% | 4 | 2 | missing 2 |
| `core.eligibility.technical_experience_requirement` | 33% | 3 | 2 | missing 2 |
| `core.eligibility.turnover_basis` | 71% | 7 | 2 | missing 2 |
| `core.eligibility.turnover_requirement_inr` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.bg_release_conditions` | 50% | 4 | 2 | missing 2 |
| `core.guarantees.bg_validity_months` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.emd_form` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.emd_formula` | 60% | 5 | 2 | missing 2; across agencies SECI, NTPC |
| `core.guarantees.emd_per_mw_inr` | 86% | 7 | 1 | missing 1 |
| `core.guarantees.emd_structured` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.pbg_formula` | 60% | 5 | 2 | missing 2; across agencies SECI, NTPC |
| `core.guarantees.pbg_per_mw_inr` | 86% | 7 | 1 | missing 1 |
| `core.guarantees.pbg_schedule` | 50% | 4 | 2 | missing 2 |
| `core.guarantees.pbg_structured` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.processing_fee_inr` | 71% | 7 | 2 | missing 2 |
| `core.guarantees.success_charge_inr` | 71% | 7 | 2 | missing 2 |
| `core.identity.portal` | 71% | 7 | 2 | missing 1, extra 1; across agencies SECI, NTPC Renewable Energy Ltd |
| `core.identity.procurement_mode` | 71% | 7 | 2 | wrong_value 1, missing 1 |
| `core.key_dates.bid_validity` | 71% | 7 | 2 | missing 2 |
| `core.key_dates.bid_validity_unit` | 71% | 7 | 2 | missing 2 |
| `core.key_dates.loa_timeline` | 86% | 7 | 1 | missing 1 |
| `core.key_dates.pre_bid_meeting_date` | 86% | 7 | 1 | extra 1 |
| `core.penalties.delay_ld_structured` | 86% | 7 | 1 | missing 1 |
| `core.penalties.max_scod_extension_months` | 86% | 7 | 1 | missing 1 |
| `core.penalties.pbg_encashment_triggers` | 67% | 3 | 1 | missing 1 |
| `core.penalties.shortfall_penalty_basis` | 50% | 4 | 2 | missing 2 |
| `core.penalties.shortfall_rules` | 71% | 7 | 2 | missing 2 |
| `core.penalties.termination_delay_months` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.almm_required` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.clearances_responsibility` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.connectivity_responsibility` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.dcr_required` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.deemed_generation_clause` | 50% | 4 | 2 | missing 2 |
| `sector.power.common.deemed_generation_structured` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.delivery_point` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.financial_closure_months` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.financial_closure_reference` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.gna_requirement` | 50% | 4 | 2 | missing 2 |
| `sector.power.common.land_responsibility` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.line_to_pooling_station_responsibility` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.local_content_rule` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.max_bid_mw` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.metering_point` | 57% | 7 | 3 | missing 2, wrong_value 1; across agencies NHPC, SECI |
| `sector.power.common.min_bid_mw` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.named_states_or_sites` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.net_worth_per_mw_inr` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.ppa_signing_window_days` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.ppa_tenure_years` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.scod_months` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.scod_reference` | 71% | 7 | 2 | wrong_value 1, missing 1; across agencies NTPC Renewable Energy Ltd, SECI |
| `sector.power.common.source_mix_rules` | 80% | 5 | 1 | missing 1 |
| `sector.power.common.tariff_ceiling_inr_per_kwh` | 86% | 7 | 1 | missing 1 |
| `sector.power.common.tariff_structure` | 71% | 7 | 2 | missing 2 |
| `sector.power.common.under_construction_counts` | 86% | 7 | 1 | missing 1 |
| `sector.power.fdre.assured_availability_percent` | 50% | 2 | 1 | missing 1 |
| `sector.power.fdre.availability_shortfall_penalty` | 0% | 1 | 1 | missing 1 |
| `sector.power.fdre.capacity_addition_flexibility` | 50% | 2 | 1 | missing 1 |
| `sector.power.fdre.component_disclosure_required` | 50% | 2 | 1 | missing 1 |
| `sector.power.fdre.excess_energy_structured` | 50% | 2 | 1 | missing 1 |
| `sector.power.fdre.firmness_definition` | 0% | 1 | 1 | missing 1 |
| `sector.power.fdre.peak_window_definition` | 50% | 2 | 1 | missing 1 |
| `sector.power.fdre.shortfall_compensation_multiple` | 50% | 2 | 1 | missing 1 |
| `sector.power.solar.almm_list_requirement` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.augmentation_rules` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.cuf_terms` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.excess_energy_structured` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.land_type_restrictions` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.min_cuf_percent` | 0% | 1 | 1 | missing 1 |
| `sector.power.solar.repowering_allowed` | 0% | 1 | 1 | missing 1 |

## Structured fields by key

| Field | Key | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- | --- |
| `core.commercial.payment_security_structured` | `lc_drawable_after_days` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_required` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `lc_revolving` | 100% | 1 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_available` | 100% | 3 | 0 | - |
| `core.commercial.payment_security_structured` | `psf_charge_inr_per_kwh` | 100% | 2 | 0 | - |
| `core.guarantees.emd_structured` | `basis` | 100% | 4 | 0 | - |
| `core.guarantees.emd_structured` | `cap_inr` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `cap_per` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `components` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `lump_sum_inr` | 100% | 1 | 0 | - |
| `core.guarantees.emd_structured` | `rate_inr_per_mw` | 100% | 2 | 0 | - |
| `core.guarantees.pbg_structured` | `basis` | 100% | 3 | 0 | - |
| `core.guarantees.pbg_structured` | `components` | 100% | 1 | 0 | - |
| `core.guarantees.pbg_structured` | `lump_sum_inr` | 100% | 1 | 0 | - |
| `core.guarantees.pbg_structured` | `rate_inr_per_mw` | 100% | 1 | 0 | - |
| `core.guarantees.pbg_structured` | `submitted_before` | 100% | 3 | 0 | - |
| `core.guarantees.pbg_structured` | `valid_months_after_scod` | 100% | 3 | 0 | - |
| `core.penalties.delay_ld_structured` | `basis` | 100% | 4 | 0 | - |
| `core.penalties.delay_ld_structured` | `pbg_encashed_over_months` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `default_after_years` | 100% | 1 | 0 | - |
| `core.penalties.shortfall_rules` | `default_damages_months_of_tariff` | 100% | 2 | 0 | - |
| `core.penalties.shortfall_rules` | `measured` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `metric` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `penalty_multiple_of_tariff` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_of` | 100% | 3 | 0 | - |
| `core.penalties.shortfall_rules` | `threshold_pct` | 100% | 4 | 0 | - |
| `core.penalties.shortfall_rules` | `tolerance_pct` | 100% | 1 | 0 | - |
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
| `sector.power.common.deemed_generation_structured` | `backdown_threshold_hours_per_year` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_basis` | 100% | 2 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `compensation_pct_of_tariff` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `exchange_sale_share_adjusted_pct` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `grid_threshold_hours_per_year` | 100% | 1 | 0 | - |
| `sector.power.common.deemed_generation_structured` | `payer` | 100% | 2 | 0 | - |
| `sector.power.common.source_mix_rules` | `condition` | 100% | 12 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_unit` | 100% | 8 | 0 | - |
| `sector.power.common.source_mix_rules` | `limit_value` | 100% | 8 | 0 | - |
| `sector.power.common.source_mix_rules` | `source` | 100% | 12 | 0 | - |
| `sector.power.common.source_mix_rules` | `treatment` | 100% | 12 | 0 | - |
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
| `sector.power.fdre.excess_energy_structured` | `above` | 100% | 1 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `price_basis` | 100% | 1 | 0 | - |
| `sector.power.fdre.excess_energy_structured` | `procurer_first_right` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_lower_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `band_upper_pct_of_declared` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `declared_min_pct` | 100% | 1 | 0 | - |
| `sector.power.hybrid.cuf_terms` | `revision_allowed_within_years` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `above` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `price_basis` | 100% | 1 | 0 | - |
| `sector.power.hybrid.excess_energy_structured` | `procurer_first_right` | 100% | 1 | 0 | - |

## Prompt versions tried

| Result | Prompt | Value accuracy | Evidence accuracy | n |
| --- | --- | --- | --- | --- |
| 20261006T172902Z-ergplan-latest.json | as pinned | 99% | 100% | 79 |
| 20261013T124146Z-ergplan-latest.json | as pinned | 78% | 100% | 624 |

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

**Not met.** Required-field value accuracy 97%.

At least 2 reviewed tenders for every type with 2 or more in the set (epc, fdre, wind); required-field value accuracy at least 90% across the last two prompt versions; no required field below 75%.

- fewer than 2 reviewed tenders for: epc, wind
- required fields below 75%: 1
- below 90% on required fields under: extract/fdre_profile v2 (0%)
- required-field accuracy by section prompt, last two versions seen: extract/bess_performance v2 100%; extract/fdre_profile v2 0%; extract/hybrid_mix v2 100%; extract/identity_and_scope v1 100%; extract/key_dates v1 100%

