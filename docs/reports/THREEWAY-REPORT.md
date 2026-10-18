# Three-way comparison: reviewer, engine, agent

Made 2026-10-18T09:10:46+00:00 by `python -m evals.threeway` (`make threeway`, `POST /api/v1/admin/threeway`) from the gold records, the readings in review and the latest finished agent pass of each gold tender at its reviewed version. Rewritten on every run; never edited by hand.

11 gold tender(s) compared. 1075 decided fields, 940 counted (135 long-text fields left to human judgement).

## The six classes

| Class | Fields | Share of counted |
| --- | --- | --- |
| All agree | 663 | 71% |
| Engine right, agent wrong | 255 | 27% |
| Agent right, engine wrong | 2 | 0% |
| Both wrong the same way | 9 | 1% |
| Both wrong, differently | 9 | 1% |
| Both abstained | 2 | 0% |

## By tender type, agency and field

### By tender type

| | n | all agree | engine right | agent right | both wrong, same | both wrong, apart | both abstained | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | 90 | 71% | 25 | 0 | 1 | 0 | 0 | 12 |
| epc | 87 | 63% | 30 | 0 | 1 | 1 | 0 | 12 |
| fdre | 319 | 65% | 102 | 0 | 5 | 6 | 0 | 71 |
| generation | 92 | 82% | 15 | 1 | 1 | 0 | 0 | 1 |
| hybrid | 84 | 73% | 21 | 0 | 0 | 0 | 2 | 10 |
| re_rtc | 95 | 74% | 23 | 0 | 1 | 1 | 0 | 14 |
| solar | 84 | 70% | 24 | 1 | 0 | 0 | 0 | 12 |
| wind | 89 | 82% | 15 | 0 | 0 | 1 | 0 | 3 |

### By agency

| | n | all agree | engine right | agent right | both wrong, same | both wrong, apart | both abstained | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NHPC | 79 | 71% | 22 | 0 | 0 | 1 | 0 | 17 |
| NTPC | 84 | 73% | 21 | 0 | 0 | 0 | 2 | 10 |
| NTPC Renewable Energy Ltd | 181 | 82% | 30 | 1 | 1 | 1 | 0 | 4 |
| SECI | 501 | 65% | 159 | 1 | 7 | 6 | 0 | 90 |
| WBSEDCL | 95 | 74% | 23 | 0 | 1 | 1 | 0 | 14 |

### Fields with any disagreement

| | n | all agree | engine right | agent right | both wrong, same | both wrong, apart | both abstained | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core.commercial.late_payment_surcharge | 11 | 45% | 6 | 0 | 0 | 0 | 0 | 0 |
| core.commercial.offtaker | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| core.commercial.payment_security_structured | 11 | 45% | 6 | 0 | 0 | 0 | 0 | 0 |
| core.documents.annexure_formats | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| core.documents.draft_agreements_referenced | 11 | 0% | 10 | 0 | 0 | 1 | 0 | 0 |
| core.documents.required_documents | 11 | 0% | 11 | 0 | 0 | 0 | 0 | 0 |
| core.eligibility.ebitda_basis | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.eligibility.liquidity_requirement_inr | 11 | 36% | 7 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.bg_validity_months | 11 | 82% | 2 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.bid_security_instruments | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.emd_form | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.emd_formula | 5 | 80% | 0 | 0 | 0 | 0 | 1 | 6 |
| core.guarantees.emd_structured | 11 | 73% | 3 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.pbg_formula | 6 | 67% | 1 | 0 | 0 | 0 | 1 | 5 |
| core.guarantees.pbg_instruments | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.pbg_structured | 11 | 55% | 5 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.processing_fee_inr | 11 | 64% | 4 | 0 | 0 | 0 | 0 | 0 |
| core.guarantees.success_charge_inr | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.identity.issuing_agency | 11 | 82% | 2 | 0 | 0 | 0 | 0 | 0 |
| core.identity.portal | 11 | 36% | 6 | 1 | 0 | 0 | 0 | 0 |
| core.identity.procurement_mode | 11 | 55% | 0 | 0 | 5 | 0 | 0 | 0 |
| core.identity.tender_number | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.identity.tender_type_as_stated | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| core.identity.title | 11 | 64% | 4 | 0 | 0 | 0 | 0 | 0 |
| core.key_dates.bid_validity | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.key_dates.bid_validity_unit | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.key_dates.loa_timeline | 11 | 18% | 8 | 0 | 0 | 1 | 0 | 0 |
| core.key_dates.nit_date | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| core.key_dates.pre_bid_meeting_date | 11 | 82% | 1 | 1 | 0 | 0 | 0 | 0 |
| core.penalties.delay_ld_structured | 11 | 82% | 1 | 0 | 1 | 0 | 0 | 0 |
| core.penalties.shortfall_rules | 11 | 36% | 6 | 0 | 0 | 1 | 0 | 0 |
| sector.power.bess.augmentation_obligation | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.bess.degradation_and_augmentation_structured | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.bess.degradation_obligation | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.bess.end_of_life_terms | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.bess.vgf_inr | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.almm_required | 11 | 82% | 2 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.bess_charging_rule | 10 | 70% | 3 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.clearances_responsibility | 11 | 0% | 11 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.deemed_generation_structured | 11 | 64% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.delivery_point | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.gna_requirement | 3 | 67% | 1 | 0 | 0 | 0 | 0 | 8 |
| sector.power.common.land_responsibility | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.line_to_pooling_station_responsibility | 11 | 9% | 10 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.max_bid_mw | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.metering_point | 11 | 18% | 8 | 0 | 0 | 1 | 0 | 0 |
| sector.power.common.min_bid_mw | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.named_states_or_sites | 11 | 64% | 2 | 0 | 0 | 2 | 0 | 0 |
| sector.power.common.net_worth_per_mw_inr | 11 | 73% | 3 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.ppa_signing_window_days | 11 | 45% | 4 | 0 | 0 | 2 | 0 | 0 |
| sector.power.common.scod_months | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.scod_reference | 11 | 73% | 0 | 0 | 3 | 0 | 0 | 0 |
| sector.power.common.source_mix_rules | 8 | 0% | 8 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.tariff_structure | 11 | 91% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.common.under_construction_counts | 11 | 64% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.boq_structure | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.drawing_approval_cycle | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.ld_delay | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.ld_performance | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.ld_performance_structured | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.milestone_payment_structured | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.price_schedule_structure | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.scope_matrix | 1 | 0% | 0 | 0 | 0 | 1 | 0 | 0 |
| sector.power.epc.taxes_duties_treatment | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.epc.warranty_terms | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.fdre.capacity_addition_flexibility | 4 | 0% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.fdre.demand_profile_structured | 4 | 0% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.fdre.excess_energy_structured | 4 | 0% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.fdre.peak_window_definition | 4 | 0% | 4 | 0 | 0 | 0 | 0 | 0 |
| sector.power.fdre.shortfall_compensation_multiple | 4 | 75% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.generation.fuel_supply_arrangement | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.generation.fuel_type | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.generation.heat_rate_or_design_energy | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.generation.tariff_two_part | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.generation.water_clearance_responsibility | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.hybrid.excess_generation_treatment | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.hybrid.storage_metering_rule | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.re_rtc.linked_capacity_obligation | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.re_rtc.peak_window | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.re_rtc.rec_obligation | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.solar.almm_list_requirement | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.solar.augmentation_rules | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.solar.excess_energy_structured | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.solar.land_type_restrictions | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.wind.hub_height_or_tech_restrictions | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.wind.resource_data_obligation | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.wind.rlmm_requirement | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |
| sector.power.wind.site_transmission_constraints | 1 | 0% | 1 | 0 | 0 | 0 | 0 | 0 |

## Error patterns

### Both wrong the same way: the schema or the document

Two models from different families read the same wrong value: the clause is ambiguous, a table and a clause disagree, or the field's definition does not fit what the document states. Look at the schema and the help text before the prompts.

| Tender | Field | Reviewer | Engine | Agent |
| --- | --- | --- | --- | --- |
| seci-ess-iv | `core.identity.procurement_mode` | single_stage_two_envelope | e_reverse_auction | e_reverse_auction |
| seci-fdre-ix | `core.identity.procurement_mode` | single_stage_two_envelope | e_reverse_auction | e_reverse_auction |
| seci-fdre-rtc-v | `core.identity.procurement_mode` | single_stage_two_envelope | e_reverse_auction | e_reverse_auction |
| seci-gaya-60mw | `core.identity.procurement_mode` | single_stage_two_envelope | e_reverse_auction | e_reverse_auction |
| wbsedcl-re-rtc-2026-01 | `core.identity.procurement_mode` | single_stage_two_envelope | e_reverse_auction | e_reverse_auction |
| seci-fdre-ix | `core.penalties.delay_ld_structured` | null | ["basis: pbg_encashment_per_day", "pbg_encashed_over_mont… | {"basis": "pbg_encashment_per_day", "pct_per_week": null,… |
| ntpc-phes-2000mw | `sector.power.common.scod_reference` | effective_date | ppa_signing | ppa_signing |
| seci-fdre-ix | `sector.power.common.scod_reference` | ppa_signing | effective_date | effective_date |
| seci-fdre-rtc-v | `sector.power.common.scod_reference` | ppa_signing | effective_date | effective_date |

### The models disagree: candidates for a mandatory second pass

One model right and the other wrong, or both wrong apart: in production these fields earn a second reading before they are shown, whatever their confidence.

| Tender | Field | Reviewer | Engine | Agent |
| --- | --- | --- | --- | --- |
| nhpc-fdre-ii | `core.commercial.late_payment_surcharge` | Late Payment Surcharge on outstanding payment at the base… | Late Payment Surcharge on outstanding payment at the base… | SBI one-year MCLR as on 1 April of relevant financial yea… |
| seci-cfd-i | `core.commercial.late_payment_surcharge` | Payable by the defaulting party (RPD or SECI) on the outs… | Payable by the defaulting party (RPD or SECI) on the outs… | SBI one-year MCLR applicable on 1 April of the financial … |
| seci-cni-1-700mw | `core.commercial.late_payment_surcharge` | On delay in payment of a Monthly Bill beyond the Due Date… | On delay in payment of a Monthly Bill beyond the Due Date… | One-year SBI MCLR applicable on 1 April of relevant FY +5… |
| seci-fdre-ix | `core.commercial.late_payment_surcharge` | For delay in payment of a Monthly Bill beyond the Due Dat… | For delay in payment of a Monthly Bill beyond the Due Dat… | SBI one-year MCLR as on 1 April of relevant financial yea… |
| seci-fdre-rtc-v | `core.commercial.late_payment_surcharge` | If SECI delays payment of a Monthly Bill beyond the Due D… | If SECI delays payment of a Monthly Bill beyond the Due D… | SBI one-year MCLR applicable on 1 April of relevant FY pl… |
| wbsedcl-re-rtc-2026-01 | `core.commercial.late_payment_surcharge` | Payments delayed beyond the period set in the Agreement a… | Payments delayed beyond the period set in the Agreement a… | Delayed payment recovery in accordance with applicable Mi… |
| nhpc-fdre-ii | `core.commercial.offtaker` | NHPC Limited as Intermediary Procurer/trading licensee un… | NHPC Limited as Intermediary Procurer/trading licensee un… | NHPC Limited (intermediary procurer); onward sale to Stat… |
| ntpc-hybrid-03 | `core.commercial.offtaker` | NTPC Limited (intermediary procurer under the PPA), selli… | NTPC Limited (intermediary procurer under the PPA), selli… | NTPC Limited (intermediary purchaser), for onward sale to… |
| ntpc-phes-2000mw | `core.commercial.offtaker` | NTPC Renewable Energy Limited (NTPC REL) – avails the pum… | NTPC Renewable Energy Limited (NTPC REL) – avails the pum… | NTPC Renewable Energy Limited (NTPC REL) |
| ntpc-rel-600mw-anantapur-wtg | `core.commercial.offtaker` | NTPC Renewable Energy Limited (NTPC REL), a subsidiary of… | NTPC Renewable Energy Limited (NTPC REL), a subsidiary of… | NTPC Renewable Energy Limited (NTPC REL), equipment procu… |
| seci-cfd-i | `core.commercial.offtaker` | Power Exchanges (market buyers on GDAM/DAM/HPDAM/RTM); SE… | Power Exchanges (market buyers on GDAM/DAM/HPDAM/RTM); SE… | Power sold in markets through Power Exchanges; SECI is Cf… |
| seci-cni-1-700mw | `core.commercial.offtaker` | Solar Energy Corporation of India Limited (SECI) as Inter… | Solar Energy Corporation of India Limited (SECI) as Inter… | SECI as intermediary procurer; onward sale to an unnamed … |
| seci-ess-iv | `core.commercial.offtaker` | Solar Energy Corporation of India Limited (SECI) as inter… | Solar Energy Corporation of India Limited (SECI) as inter… | SECI as intermediary procurer, on behalf of Buying Entiti… |
| seci-fdre-ix | `core.commercial.offtaker` | SECI (intermediary procurer), selling to West Bengal Stat… | SECI (intermediary procurer), selling to West Bengal Stat… | SECI as intermediary procurer; onward buyers West Bengal … |
| seci-fdre-rtc-v | `core.commercial.offtaker` | SECI (intermediary procurer, PPA tariff plus SECI's tradi… | SECI (intermediary procurer, PPA tariff plus SECI's tradi… | Solar Energy Corporation of India Limited (SECI), interme… |
| seci-gaya-60mw | `core.commercial.offtaker` | Solar Energy Corporation of India Limited (SECI), as Owne… | Solar Energy Corporation of India Limited (SECI), as Owne… | Solar Energy Corporation of India Limited (Owner/Employer) |
| nhpc-fdre-ii | `core.commercial.payment_security_structured` | {"lc_required": true, "lc_revolving": true, "psf_availabl… | ["lc_required: yes", "lc_revolving: yes", "lc_drawable_af… | {"lc_required": true, "lc_revolving": true, "psf_availabl… |
| ntpc-hybrid-03 | `core.commercial.payment_security_structured` | {"lc_required": null, "lc_revolving": null, "psf_availabl… | ["psf_available: yes", "psf_charge_inr_per_kwh: 0.02"] | {"lc_required": null, "lc_revolving": null, "psf_availabl… |
| seci-cfd-i | `core.commercial.payment_security_structured` | {"lc_required": true, "lc_revolving": true, "psf_availabl… | ["lc_required: yes", "lc_revolving: yes", "psf_available:… | {"lc_required": true, "lc_revolving": true, "psf_availabl… |
| seci-cni-1-700mw | `core.commercial.payment_security_structured` | {"lc_required": true, "lc_revolving": true, "psf_availabl… | ["lc_required: yes", "lc_months_of_billing: 1.1", "lc_rev… | {"lc_required": true, "lc_revolving": true, "psf_availabl… |
| seci-fdre-ix | `core.commercial.payment_security_structured` | {"lc_required": true, "lc_revolving": true, "psf_availabl… | ["lc_required: yes", "lc_months_of_billing: 1.1", "lc_rev… | {"lc_required": true, "lc_revolving": true, "psf_availabl… |
| wbsedcl-re-rtc-2026-01 | `core.commercial.payment_security_structured` | {"lc_required": true, "lc_revolving": true, "psf_availabl… | ["lc_required: yes", "lc_revolving: yes", "payment_due_da… | {"lc_required": true, "lc_revolving": true, "psf_availabl… |
| nhpc-fdre-ii | `core.documents.annexure_formats` | ["Format 6.1 – Format of Covering Letter", "Format 6.2 – … | ["Format 6.1 – Format of Covering Letter", "Format 6.2 – … | ["6.1 Covering Letter", "6.2 Power of Attorney", "6.3A / … |
| ntpc-hybrid-03 | `core.documents.annexure_formats` | ["Format 6.1 – Format of Covering Letter", "Format 6.2 – … | ["Format 6.1 – Format of Covering Letter", "Format 6.2 – … | ["6.1 Covering letter", "6.2 Power of attorney", "6.3A EM… |
| ntpc-rel-600mw-anantapur-wtg | `core.documents.annexure_formats` | ["Non-Disclosure Agreement (format enclosed along with th… | ["Non-Disclosure Agreement (format enclosed along with th… | ["Non Disclosure Agreement"] |
| seci-cfd-i | `core.documents.annexure_formats` | ["Format 7.1: Covering Letter", "Format 7.2: Format for P… | ["Format 7.1: Covering Letter", "Format 7.2: Format for P… | ["7.1 Covering letter", "7.2 Power of attorney", "7.3A EM… |
| seci-cni-1-700mw | `core.documents.annexure_formats` | ["Appendix-II to Covering Letter: Tentative Average Hourl… | ["Appendix-II to Covering Letter: Tentative Average Hourl… | ["7.1 Covering Letter (with generation-profile Appendices… |
| seci-ess-iv | `core.documents.annexure_formats` | ["Format 7.3 D: Format for Performance Bank Guarantee (PB… | ["Format 7.3 D: Format for Performance Bank Guarantee (PB… | ["7.1 Covering Letter", "7.2 Power of Attorney", "7.3A EM… |
| seci-fdre-ix | `core.documents.annexure_formats` | ["Format 7.3A: Format for Bank Guarantee towards Earnest … | ["Format 7.3A: Format for Bank Guarantee towards Earnest … | ["7.1 Covering Letter", "7.2 Power of Attorney", "7.3A/B/… |
| seci-fdre-rtc-v | `core.documents.annexure_formats` | ["Format-7.1: Covering Letter", "Annexure-I: Undertaking … | ["Format-7.1: Covering Letter", "Annexure-I: Undertaking … | ["7.1 Covering letter", "7.2 Power of attorney", "7.3A/B/… |
| seci-gaya-60mw | `core.documents.annexure_formats` | ["F-1: Covering Letter", "F-2: Bidder's General Informati… | ["F-1: Covering Letter", "F-2: Bidder's General Informati… | ["F1 Covering letter", "F2 Bidder general information", "… |
| wbsedcl-re-rtc-2026-01 | `core.documents.annexure_formats` | ["Appendix I: Letter Comprising the Application for Quali… | ["Appendix I: Letter Comprising the Application for Quali… | ["RFQ Appendix I: Letter Comprising the Application for Q… |
| nhpc-fdre-ii | `core.documents.draft_agreements_referenced` | ["Power Purchase Agreement (PPA) between NHPC and success… | ["Power Purchase Agreement (PPA) between NHPC and success… | ["Power Purchase Agreement (PPA)", "Power Sale Agreement … |
| ntpc-hybrid-03 | `core.documents.draft_agreements_referenced` | ["Power Purchase Agreement (PPA) between NTPC and the Sel… | ["Power Purchase Agreement (PPA) between NTPC and the Sel… | ["Standard Power Purchase Agreement (PPA), Annexure 3, en… |
| ntpc-phes-2000mw | `core.documents.draft_agreements_referenced` | ["Energy Storage Service Agreement (on annual fixed charg… | ["Energy Storage Service Agreement (on annual fixed charg… | ["Energy Storage Service Agreement"] |
| ntpc-rel-600mw-anantapur-wtg | `core.documents.draft_agreements_referenced` | ["Non-Disclosure Agreement between the bidder (Company) a… | ["Non-Disclosure Agreement between the bidder (Company) a… | ["Non Disclosure Agreement"] |
| seci-cfd-i | `core.documents.draft_agreements_referenced` | ["CfDA (Contract for Difference Agreement)"] | ["CfDA (Contract for Difference Agreement)"] | ["Standard Contract for Difference Agreement (CfDA) betwe… |
| seci-cni-1-700mw | `core.documents.draft_agreements_referenced` | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (SECI–SPD)", "Standar… |
| seci-ess-iv | `core.documents.draft_agreements_referenced` | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (PPA): SECI and BESSD… |
| seci-fdre-ix | `core.documents.draft_agreements_referenced` | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (PPA) between SECI an… | ["Standard Power Purchase Agreement (SECI–RPD PPA)", "Sta… |
| seci-fdre-rtc-v | `core.documents.draft_agreements_referenced` | ["Power Purchase Agreement (PPA)", "Power Sale Agreement … | ["Power Purchase Agreement (PPA)", "Power Sale Agreement … | ["Standard Power Purchase Agreement (PPA) between SECI an… |
| seci-gaya-60mw | `core.documents.draft_agreements_referenced` | ["Contract Agreement (to be executed with Owner within 30… | ["Contract Agreement (to be executed with Owner within 30… | ["Contract Agreement", "Operation & Maintenance Agreement… |
| wbsedcl-re-rtc-2026-01 | `core.documents.draft_agreements_referenced` | ["Draft Power Purchase Agreement (PPA) / Agreement for Pr… | ["Draft Power Purchase Agreement (PPA) / Agreement for Pr… | ["Draft Power Purchase Agreement (PPA) / Agreement for Su… |
| nhpc-fdre-ii | `core.documents.required_documents` | ["Processing Fee (Demand Draft in favour of NHPC Limited,… | ["Processing Fee (Demand Draft in favour of NHPC Limited,… | ["Processing-fee demand draft", "Original EMD security an… |
| ntpc-hybrid-03 | `core.documents.required_documents` | ["Details of Processing Fee submitted through Electronic … | ["Details of Processing Fee submitted through Electronic … | ["Offline: processing-fee transfer details; original EMD … |
| ntpc-phes-2000mw | `core.documents.required_documents` | null | null | ["Envelope-I: Techno-Commercial Bid", "Envelope-II: Price… |
| ntpc-rel-600mw-anantapur-wtg | `core.documents.required_documents` | ["Bid Security of INR 50,00,00,000/- in a separate sealed… | ["Bid Security of INR 50,00,00,000/- in a separate sealed… | ["Techno-commercial bid and price bid", "Bid security in … |
| seci-cfd-i | `core.documents.required_documents` | ["Covering Letter as per Format 7.1", "Power of Attorney … | ["Covering Letter as per Format 7.1", "Power of Attorney … | ["Format 7.1 covering letter and project capacity/locatio… |
| seci-cni-1-700mw | `core.documents.required_documents` | ["Covering Letter as per Format 7.1 (with Appendix-I and … | ["Covering Letter as per Format 7.1 (with Appendix-I and … | ["Format 7.1 covering letter with project breakup, genera… |
| seci-ess-iv | `core.documents.required_documents` | ["Covering Letter (Format 7.1)", "Power of Attorney in fa… | ["Covering Letter (Format 7.1)", "Power of Attorney in fa… | ["Format 7.1 covering letter with final connectivity gran… |
| seci-fdre-ix | `core.documents.required_documents` | ["Covering Letter as per Format 7.1 (with proof of applic… | ["Covering Letter as per Format 7.1 (with proof of applic… | ["Covering letter Format 7.1 including component capaciti… |
| seci-fdre-rtc-v | `core.documents.required_documents` | ["Copy of in-principle/ final grant of connectivity at th… | ["Copy of in-principle/ final grant of connectivity at th… | ["Format 7.1 covering letter with installed-component con… |
| seci-gaya-60mw | `core.documents.required_documents` | ["Covering Letter on Bidder's Letterhead (in Original) as… | ["Covering Letter on Bidder's Letterhead (in Original) as… | ["F1 covering letter", "F2 bidder general information", "… |
| wbsedcl-re-rtc-2026-01 | `core.documents.required_documents` | ["Application in the prescribed format (Appendix-I) along… | ["Application in the prescribed format (Appendix-I) along… | ["RFQ Appendix I application with annexes and supporting … |
| wbsedcl-re-rtc-2026-01 | `core.eligibility.ebitda_basis` | per MW of the capacity the Bidder is willing to bid, at t… | per MW of the capacity the Bidder is willing to bid, at t… | Per MW of capacity bid, at the close of the preceding fin… |
| nhpc-fdre-ii | `core.eligibility.liquidity_requirement_inr` | 1276000 | 1276000.0 | 1594000 |
| ntpc-hybrid-03 | `core.eligibility.liquidity_requirement_inr` | 1230800 | 1230800.0 | 1538500 |
| seci-cfd-i | `core.eligibility.liquidity_requirement_inr` | 847380 | 847380.0 | 1059225 |
| seci-cni-1-700mw | `core.eligibility.liquidity_requirement_inr` | 745110 | 745110.0 | 931390 |
| seci-ess-iv | `core.eligibility.liquidity_requirement_inr` | 1750280 | 1750280.0 | 2187850 |
| seci-fdre-ix | `core.eligibility.liquidity_requirement_inr` | 1648900 | 1648900.0 | 2061125 |
| seci-fdre-rtc-v | `core.eligibility.liquidity_requirement_inr` | 8000000 | 8000000.0 | 10000000 |
| seci-gaya-60mw | `core.guarantees.bg_validity_months` | 7 | 7 | null |
| wbsedcl-re-rtc-2026-01 | `core.guarantees.bg_validity_months` | 6 | 6 | null |
| wbsedcl-re-rtc-2026-01 | `core.guarantees.bid_security_instruments` | [{"issuer": "nationalized bank or Scheduled Bank in India… | ["instrument: bank_guarantee | issuer: nationalized bank … | [{"issuer": "Nationalized bank or Scheduled Bank in India… |
| ntpc-rel-600mw-anantapur-wtg | `core.guarantees.emd_form` | other | other | cash |
| seci-cfd-i | `core.guarantees.emd_structured` | {"basis": "per_component", "cap_inr": null, "cap_per": nu… | ["basis: per_component", "components: component=solar; ra… | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-fdre-ix | `core.guarantees.emd_structured` | {"basis": "per_component", "cap_inr": null, "cap_per": nu… | ["basis: per_component", "components: component=solar; ra… | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-fdre-rtc-v | `core.guarantees.emd_structured` | {"basis": "per_component", "cap_inr": null, "cap_per": nu… | ["basis: per_component", "components: component=solar; ra… | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-gaya-60mw | `core.guarantees.pbg_formula` | null | null | First stage: 10% of total Supply & Service Contract value… |
| wbsedcl-re-rtc-2026-01 | `core.guarantees.pbg_instruments` | [{"issuer": null, "instrument": "bank_guarantee"}, {"issu… | ["instrument: bank_guarantee", "instrument: payment_on_or… | [{"issuer": "Scheduled Bank", "instrument": "bank_guarant… |
| seci-cfd-i | `core.guarantees.pbg_structured` | {"basis": "per_component", "cap_inr": null, "cap_per": nu… | ["basis: per_component", "components: component=solar; ra… | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-fdre-ix | `core.guarantees.pbg_structured` | {"basis": "per_component", "cap_inr": null, "cap_per": nu… | ["basis: per_component", "components: component=solar; ra… | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-fdre-rtc-v | `core.guarantees.pbg_structured` | {"basis": null, "cap_inr": null, "cap_per": null, "percen… | ["submitted_before: ppa_signing"] | {"basis": "per_component", "cap_inr": null, "cap_per": nu… |
| seci-gaya-60mw | `core.guarantees.pbg_structured` | null | null | {"basis": "percent", "cap_inr": null, "cap_per": null, "p… |
| wbsedcl-re-rtc-2026-01 | `core.guarantees.pbg_structured` | {"basis": "per_mw", "cap_inr": null, "cap_per": null, "pe… | ["basis: per_mw", "rate_inr_per_mw: 2000000", "submitted_… | {"basis": "per_mw", "cap_inr": null, "cap_per": null, "pe… |
| seci-cfd-i | `core.guarantees.processing_fee_inr` | 20000 | 20000.0 | null |
| seci-ess-iv | `core.guarantees.processing_fee_inr` | 20000 | 20000.0 | 1000000 |
| seci-fdre-ix | `core.guarantees.processing_fee_inr` | 20000 | 20000.0 | null |
| seci-fdre-rtc-v | `core.guarantees.processing_fee_inr` | 20000 | 20000.0 | null |
| seci-ess-iv | `core.guarantees.success_charge_inr` | null | null | 400000 |
| ntpc-rel-600mw-anantapur-wtg | `core.identity.issuing_agency` | NTPC Renewable Energy Limited (NTPC REL) | NTPC Renewable Energy Limited (NTPC REL) | NTPC Renewable Energy Limited |
| seci-cni-1-700mw | `core.identity.issuing_agency` | SECI | SECI | Solar Energy Corporation of India Limited |
| nhpc-fdre-ii | `core.identity.portal` | Central Public Procurement (CPP) Portal http://eprocure.g… | Central Public Procurement (CPP) Portal http://eprocure.g… | http://eprocure.gov.in/eprocure/app |
| ntpc-phes-2000mw | `core.identity.portal` | null | https://www.bharat-electronictender.com | null |
| ntpc-rel-600mw-anantapur-wtg | `core.identity.portal` | ISN Electronic Tender Services (ETS) portal, https://www.… | ISN Electronic Tender Services (ETS) portal, https://www.… | https://www.bharat-electronictender.com |
| seci-cni-1-700mw | `core.identity.portal` | ETS Portal | ETS Portal | https://www.bharat-electronictender.com (ISN-ETS) |
| seci-ess-iv | `core.identity.portal` | ISN-ETS portal (https://www.bharat-electronictender.com) … | ISN-ETS portal (https://www.bharat-electronictender.com) … | ISN-ETS Portal (https://www.bharat-electronictender.com) |
| seci-fdre-ix | `core.identity.portal` | ISN-ETS portal (https://www.bharat-electronictender.com) | ISN-ETS portal (https://www.bharat-electronictender.com) | https://www.bharat-electronictender.com (ISN-ETS) |
| seci-gaya-60mw | `core.identity.portal` | ISN-ETS portal, https://www.bharat-electronictender.com | ISN-ETS portal, https://www.bharat-electronictender.com | ISN-ETS: https://www.bharat-electronictender.com |
| nhpc-fdre-ii | `core.identity.tender_number` | 2024_NHPC_800202_1 | 2024_NHPC_800202_1 | NH/CCW/CC-III/CO-301/PR16923/45 dated 28.02.2024 |
| nhpc-fdre-ii | `core.identity.tender_type_as_stated` | Firm & Dispatchable (FDRE) power from ISTS connected Rene… | Firm & Dispatchable (FDRE) power from ISTS connected Rene… | Firm and Dispatchable RE power coupled with energy storag… |
| ntpc-hybrid-03 | `core.identity.tender_type_as_stated` | ISTS-connected Wind-Solar Hybrid Power Projects with or w… | ISTS-connected Wind-Solar Hybrid Power Projects with or w… | ISTS-connected Wind-Solar Hybrid Power Projects with or w… |
| ntpc-phes-2000mw | `core.identity.tender_type_as_stated` | ISTS Connected Pump Hydro Energy Storage Solutions under … | ISTS Connected Pump Hydro Energy Storage Solutions under … | PHES AS SERVICE MODEL |
| ntpc-rel-600mw-anantapur-wtg | `core.identity.tender_type_as_stated` | Supply and Installation of Wind Turbine Generators (WTG) … | Supply and Installation of Wind Turbine Generators (WTG) … | SUPPLY AND INSTALLATION OF WIND TURBINE GENERATORS (WTG) |
| seci-cfd-i | `core.identity.tender_type_as_stated` | Selection of RE Power Developers under Contract for Diffe… | Selection of RE Power Developers under Contract for Diffe… | Contract for Difference (CfD) Mechanism for assured Peak … |
| seci-cni-1-700mw | `core.identity.tender_type_as_stated` | ISTS-connected Solar PV Power Projects under Tariff-based… | ISTS-connected Solar PV Power Projects under Tariff-based… | ISTS-connected Solar PV Power Projects |
| seci-ess-iv | `core.identity.tender_type_as_stated` | Standalone Battery Energy Storage Systems (BESS), ISTS-co… | Standalone Battery Energy Storage Systems (BESS), ISTS-co… | Standalone Battery Energy Storage Systems (BESS) |
| seci-fdre-ix | `core.identity.tender_type_as_stated` | FDRE (assured Peak Supply from ISTS-Connected RE Projects… | FDRE (assured Peak Supply from ISTS-Connected RE Projects… | SECI-FDRE-IX |
| seci-gaya-60mw | `core.identity.tender_type_as_stated` | EPC / LSTK (Lump Sum Turnkey) – Design, Engineering, Supp… | EPC / LSTK (Lump Sum Turnkey) – Design, Engineering, Supp… | Design, Engineering, Supply, Construction, Erection, Test… |
| wbsedcl-re-rtc-2026-01 | `core.identity.tender_type_as_stated` | Round The Clock (RTC) RE Power with greenshoe option, und… | Round The Clock (RTC) RE Power with greenshoe option, und… | Round The Clock(RTC) RE Power |
| nhpc-fdre-ii | `core.identity.title` | Request for Selection Document for Selection of RE Power … | Request for Selection Document for Selection of RE Power … | Supply of 1200MW ‘Firm & Dispatchable’ power from ISTS co… |
| ntpc-hybrid-03 | `core.identity.title` | Selection of Hybrid Power Generators for Supply of 1200 M… | Selection of Hybrid Power Generators for Supply of 1200 M… | REQUEST FOR SELECTION DOCUMENT FOR SELECTION OF HYBRID PO… |
| seci-cfd-i | `core.identity.title` | RfS for Selection of RE Power Developers under Contract f… | RfS for Selection of RE Power Developers under Contract f… | Selection of RE Power Developers under Contract for Diffe… |
| seci-cni-1-700mw | `core.identity.title` | 700 MW ISTS-Connected Solar PV Power Projects in India un… | 700 MW ISTS-Connected Solar PV Power Projects in India un… | Selection of Solar Power Developers for Setting up of 700… |
| seci-gaya-60mw | `core.key_dates.bid_validity` | null | null | 180 |
| seci-gaya-60mw | `core.key_dates.bid_validity_unit` | null | null | days |
| nhpc-fdre-ii | `core.key_dates.loa_timeline` | null | null | At the end of selection process, a Letter of Award (LOA) … |
| ntpc-hybrid-03 | `core.key_dates.loa_timeline` | At the end of selection process, a Letter of Award (LoA) … | At the end of selection process, a Letter of Award (LoA) … | At the end of selection process, for each Project; for a … |
| seci-cfd-i | `core.key_dates.loa_timeline` | end of selection process | null | At the end of selection process, LoAs will be issued to s… |
| seci-cni-1-700mw | `core.key_dates.loa_timeline` | null | null | At the end of selection process, LoAs will be issued to s… |
| seci-ess-iv | `core.key_dates.loa_timeline` | null | null | At the end of selection process. |
| seci-fdre-ix | `core.key_dates.loa_timeline` | null | null | At the end of selection process, for each Project. |
| seci-fdre-rtc-v | `core.key_dates.loa_timeline` | null | null | At the end of selection process, LoAs will be issued to t… |
| seci-gaya-60mw | `core.key_dates.loa_timeline` | null | null | Prior to expiry of the Period of Bid Validity. |
| wbsedcl-re-rtc-2026-01 | `core.key_dates.loa_timeline` | Placement of LOA scheduled on 20.11.2026 as per the sched… | Placement of LOA scheduled on 20.11.2026 as per the sched… | Placement of LOA: 20.11.2026; after selection, issued in … |
| seci-cfd-i | `core.key_dates.nit_date` | 2026-04-19 | 2026-04-19 | 2026-07-15 |
| seci-cfd-i | `core.key_dates.pre_bid_meeting_date` | null | null | 2026-05-04 |
| seci-cni-1-700mw | `core.key_dates.pre_bid_meeting_date` | 2026-09-14 | null | 2026-09-14 |
| seci-cfd-i | `core.penalties.delay_ld_structured` | {"basis": "pbg_encashment_per_day", "pct_per_week": null,… | ["basis: pbg_encashment_per_day", "pbg_encashed_over_mont… | {"basis": "other", "pct_per_week": null, "rate_inr_per_mw… |
| seci-cfd-i | `core.penalties.shortfall_rules` | [{"metric": "guaranteed_generation", "measured": null, "t… | ["metric: guaranteed_generation | threshold_pct: 90 | thr… | [{"metric": "guaranteed_generation", "measured": null, "t… |
| seci-cni-1-700mw | `core.penalties.shortfall_rules` | [{"metric": "annual_cuf", "measured": "annual", "threshol… | ["metric: annual_cuf | threshold_pct: 85 | threshold_of: … | [{"metric": "annual_cuf", "measured": "annual", "threshol… |
| seci-ess-iv | `core.penalties.shortfall_rules` | [{"metric": "monthly_availability", "measured": "monthly"… | ["metric: monthly_availability | threshold_pct: 85 | meas… | [{"metric": "monthly_availability", "measured": "monthly"… |
| seci-fdre-ix | `core.penalties.shortfall_rules` | [{"metric": "peak_availability", "measured": "monthly", "… | ["metric: peak_availability | tolerance_pct: 10 | measure… | [{"metric": "guaranteed_generation", "measured": "monthly… |
| seci-fdre-rtc-v | `core.penalties.shortfall_rules` | [{"metric": "peak_availability", "measured": "monthly", "… | ["metric: peak_availability | threshold_pct: 90 | thresho… | [{"metric": "peak_availability", "measured": "monthly", "… |
| seci-gaya-60mw | `core.penalties.shortfall_rules` | null | null | [{"metric": "guaranteed_generation", "measured": "annual"… |
| wbsedcl-re-rtc-2026-01 | `core.penalties.shortfall_rules` | null | ["metric: monthly_availability | threshold_pct: 70 | meas… | [{"metric": "annual_cuf", "measured": "annual", "threshol… |
| seci-ess-iv | `sector.power.bess.augmentation_obligation` | BESSD must make periodic replacements/replenishments of s… | BESSD must make periodic replacements/replenishments of s… | BESSD must periodically replace/replenish capacity as nee… |
| seci-ess-iv | `sector.power.bess.degradation_and_augmentation_structured` | {"basis": "pct_of_cod_capacity", "schedule": [{"contract_… | ["basis: pct_of_cod_capacity", "year_1_end_pct: 98.5", "e… | {"basis": "pct_of_cod_capacity", "schedule": [{"contract_… |
| seci-ess-iv | `sector.power.bess.degradation_obligation` | Minimum dispatchable capacity at the end of each Contract… | Minimum dispatchable capacity at the end of each Contract… | Minimum dispatchable capacity as percentage of beginning-… |
| seci-ess-iv | `sector.power.bess.end_of_life_terms` | After expiry of the 20-year PPA term, BESSD is free to op… | After expiry of the 20-year PPA term, BESSD is free to op… | BESSD disposes of defective/non-operational/non-repairabl… |
| seci-ess-iv | `sector.power.bess.vgf_inr` | null | null | 0 |
| ntpc-hybrid-03 | `sector.power.common.almm_required` | null | null | true |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.common.almm_required` | true | true | null |
| seci-cfd-i | `sector.power.common.bess_charging_rule` | {"re_only": true, "co_located_required": null, "regulatio… | ["re_only: yes"] | {"re_only": true, "co_located_required": false, "regulati… |
| seci-ess-iv | `sector.power.common.bess_charging_rule` | {"re_only": false, "co_located_required": false, "regulat… | ["re_only: no", "co_located_required: no"] | {"re_only": false, "co_located_required": null, "regulati… |
| seci-fdre-rtc-v | `sector.power.common.bess_charging_rule` | {"re_only": true, "co_located_required": null, "regulatio… | ["re_only: yes"] | {"re_only": true, "co_located_required": true, "regulatio… |
| nhpc-fdre-ii | `sector.power.common.clearances_responsibility` | The Generator/REPD is responsible for obtaining all clear… | The Generator/REPD is responsible for obtaining all clear… | RPD obtains all approvals, permits and clearances for pro… |
| ntpc-hybrid-03 | `sector.power.common.clearances_responsibility` | The HPG (Generator) obtains all clearances, permits and l… | The HPG (Generator) obtains all clearances, permits and l… | Generator obtains all clearances, permits and licences, i… |
| ntpc-phes-2000mw | `sector.power.common.clearances_responsibility` | Bidder - required clearances for under-construction/not-y… | Bidder - required clearances for under-construction/not-y… | Bidder must already have obtained required clearances for… |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.common.clearances_responsibility` | Contractor (bidder) provides inputs for statutory approva… | Contractor (bidder) provides inputs for statutory approva… | WTG bidder provides inputs for statutory approvals and cl… |
| seci-cfd-i | `sector.power.common.clearances_responsibility` | The RPD (developer) obtains all approvals, permits and cl… | The RPD (developer) obtains all approvals, permits and cl… | RPD obtains all project and transmission approvals, permi… |
| seci-cni-1-700mw | `sector.power.common.clearances_responsibility` | SPD (developer) - all approvals, permits and clearances f… | SPD (developer) - all approvals, permits and clearances f… | SPD obtains all licences, approvals, permits and statutor… |
| seci-ess-iv | `sector.power.common.clearances_responsibility` | BESSD (developer): all approvals, permits and clearances … | BESSD (developer): all approvals, permits and clearances … | BESSD obtains all necessary statutory approvals, permits … |
| seci-fdre-ix | `sector.power.common.clearances_responsibility` | RPD (developer) - all approvals, permits and clearances f… | RPD (developer) - all approvals, permits and clearances f… | RPD obtains all approvals, permits and clearances for pro… |
| seci-fdre-rtc-v | `sector.power.common.clearances_responsibility` | The RPD (RE Power Developer) obtains all approvals, permi… | The RPD (RE Power Developer) obtains all approvals, permi… | RPD obtains all statutory approvals, permits and clearanc… |
| seci-gaya-60mw | `sector.power.common.clearances_responsibility` | Contractor obtains all permits, approvals and licenses (o… | Contractor obtains all permits, approvals and licenses (o… | Contractor obtains statutory approvals/clearances on Owne… |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.clearances_responsibility` | null | null | Supplier procures Applicable Permits required for supply;… |
| nhpc-fdre-ii | `sector.power.common.deemed_generation_structured` | {"payer": "buying entity / Discom (Procurer)", "compensat… | ["grid_threshold_hours_per_year: 175", "backdown_threshol… | {"payer": "Buying entity / DISCOM", "compensation_basis":… |
| seci-ess-iv | `sector.power.common.deemed_generation_structured` | {"payer": "Buying Entity", "compensation_basis": "percent… | ["compensation_basis: percent_of_tariff", "compensation_p… | {"payer": "Buying Entity; grid unavailability and Force M… |
| seci-fdre-rtc-v | `sector.power.common.deemed_generation_structured` | {"payer": "Buying Entity(ies)", "compensation_basis": "fu… | ["grid_threshold_hours_per_year: 175", "backdown_threshol… | {"payer": "Buying Entity(ies); no claim against SECI", "c… |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.deemed_generation_structured` | {"payer": "Procurer", "compensation_basis": "full_tariff"… | ["compensation_basis: full_tariff", "payer: Procurer"] | {"payer": "Procurer (WBSEDCL)", "compensation_basis": "ot… |
| nhpc-fdre-ii | `sector.power.common.delivery_point` | The point at 220 kV or above at the CTU Sub Station where… | The point at 220 kV or above at the CTU Sub Station where… | Single or multiple points at 220 kV or above where projec… |
| ntpc-hybrid-03 | `sector.power.common.delivery_point` | ISTS substation at which the project is interconnected (D… | ISTS substation at which the project is interconnected (D… | Single or multiple points at 220 kV or above where the hy… |
| ntpc-phes-2000mw | `sector.power.common.delivery_point` | Interconnecting point with ISTS Substation | Interconnecting point with ISTS Substation | null |
| seci-cfd-i | `sector.power.common.delivery_point` | Inter-connection point: a single point at 220 kV or above… | Inter-connection point: a single point at 220 kV or above… | Single point at 220 kV or above of the ISTS substation, i… |
| seci-cni-1-700mw | `sector.power.common.delivery_point` | Single or multiple points at 220 kV or above where power … | Single or multiple points at 220 kV or above where power … | ISTS substation, at 220 kV or above where project power i… |
| seci-ess-iv | `sector.power.common.delivery_point` | ISTS substation (by default); an InSTS/STU substation onl… | ISTS substation (by default); an InSTS/STU substation onl… | Single point at 220 kV or above at the identified ISTS su… |
| seci-fdre-ix | `sector.power.common.delivery_point` | A single point at 220 kV or above where the power from th… | A single point at 220 kV or above where the power from th… | ISTS substation by default; InSTS or STU substation only … |
| seci-fdre-rtc-v | `sector.power.common.delivery_point` | ISTS substation at 220 kV or above where the power from t… | ISTS substation at 220 kV or above where the power from t… | ISTS substation by default; InSTS or STU substation only … |
| seci-gaya-60mw | `sector.power.common.delivery_point` | null | null | 132 kV Bay at the 400kV/220kV/132 kV PGCIL Sub-station at… |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.delivery_point` | Single / multiple points where the power from the Project… | Single / multiple points where the power from the Project… | Single/multiple points where project power is injected in… |
| seci-gaya-60mw | `sector.power.common.gna_requirement` | null | null | Contractor supplies technical connection data under Detai… |
| nhpc-fdre-ii | `sector.power.common.land_responsibility` | Developer (RPD/RE-PG) is solely responsible, at its own c… | Developer (RPD/RE-PG) is solely responsible, at its own c… | RPD/RE-PG acquires land at its own responsibility and dem… |
| ntpc-hybrid-03 | `sector.power.common.land_responsibility` | The HPG (Generator) identifies and arranges the land for … | The HPG (Generator) identifies and arranges the land for … | Bidder/HPG identifies and purchases or leases project lan… |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.common.land_responsibility` | null | null | NTPC REL shall make wind farm land available to bidders. |
| seci-cfd-i | `sector.power.common.land_responsibility` | The RPD (developer) identifies and arranges the land; pro… | The RPD (developer) identifies and arranges the land; pro… | RPD identifies and arranges land at own cost, risk and re… |
| seci-cni-1-700mw | `sector.power.common.land_responsibility` | SPD (developer) - identification of land for the Project … | SPD (developer) - identification of land for the Project … | SPD identifies and arranges land in SEZ/EOU areas at its … |
| seci-ess-iv | `sector.power.common.land_responsibility` | BESSD (developer): identification of land is in the BESSD… | BESSD (developer): identification of land is in the BESSD… | BESSD identifies and obtains land at own cost, risk and r… |
| seci-fdre-ix | `sector.power.common.land_responsibility` | RPD (developer) - Clause 14 requires the RPD to set up th… | RPD (developer) - Clause 14 requires the RPD to set up th… | RPD identifies and arranges land at its own cost, risk an… |
| seci-fdre-rtc-v | `sector.power.common.land_responsibility` | The RPD (RE Power Developer) identifies and arranges the … | The RPD (RE Power Developer) identifies and arranges the … | RE Power Developer identifies and arranges land at its ow… |
| seci-gaya-60mw | `sector.power.common.land_responsibility` | Project land is identified/provided by the Owner; the Con… | Project land is identified/provided by the Owner; the Con… | SECI leases project land (Land Leased by SECI); contracto… |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.land_responsibility` | Selected Bidder (developer), in its own name or that of i… | Selected Bidder (developer), in its own name or that of i… | Selected bidder arranges binding land documents in its or… |
| nhpc-fdre-ii | `sector.power.common.line_to_pooling_station_responsibility` | The REPD/RPD builds and pays for the dedicated transmissi… | The REPD/RPD builds and pays for the dedicated transmissi… | RPD/RE-PG builds, maintains and pays for dedicated transm… |
| ntpc-hybrid-03 | `sector.power.common.line_to_pooling_station_responsibility` | The HPG builds and pays for the dedicated transmission li… | The HPG builds and pays for the dedicated transmission li… | HPG builds, maintains and pays for transmission up to int… |
| ntpc-phes-2000mw | `sector.power.common.line_to_pooling_station_responsibility` | PHES Bidder (developer) - connectivity and transmission t… | PHES Bidder (developer) - connectivity and transmission t… | PHES Bidder: transmission till ISTS Substation is within … |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.common.line_to_pooling_station_responsibility` | null | null | Power evacuation system and pooling substation are exclud… |
| seci-cfd-i | `sector.power.common.line_to_pooling_station_responsibility` | The RPD builds, pays for and maintains the transmission l… | The RPD builds, pays for and maintains the transmission l… | RPD builds, pays for and maintains transmission network u… |
| seci-cni-1-700mw | `sector.power.common.line_to_pooling_station_responsibility` | SPD builds, maintains and bears the entire cost of the tr… | SPD builds, maintains and bears the entire cost of the tr… | SPD builds, pays for and maintains transmission up to and… |
| seci-ess-iv | `sector.power.common.line_to_pooling_station_responsibility` | The BESSD builds and bears the entire cost of the transmi… | The BESSD builds and bears the entire cost of the transmi… | BESSD constructs, pays and maintains transmission line an… |
| seci-fdre-ix | `sector.power.common.line_to_pooling_station_responsibility` | The RPD builds, pays for and maintains the transmission l… | The RPD builds, pays for and maintains the transmission l… | RPD constructs, pays for and maintains transmission netwo… |
| seci-fdre-rtc-v | `sector.power.common.line_to_pooling_station_responsibility` | The RPD builds and pays for the transmission line from th… | The RPD builds and pays for the transmission line from th… | RPD constructs and maintains transmission network from Pr… |
| seci-gaya-60mw | `sector.power.common.line_to_pooling_station_responsibility` | Contractor: scope under GCC 32.1.1 includes the interconn… | Contractor: scope under GCC 32.1.1 includes the interconn… | Contractor designs and constructs power evacuation to des… |
| ntpc-hybrid-03 | `sector.power.common.max_bid_mw` | 600 | 600.0 | 900 |
| nhpc-fdre-ii | `sector.power.common.metering_point` | 1) Low voltage side of the CTU/STU substation (2) In case… | Low voltage side of the CTU/STU substation (for RE parks,… | Low voltage side of the CTU/STU substation; for RE parks,… |
| ntpc-hybrid-03 | `sector.power.common.metering_point` | Low voltage side of the CTU / STU substation at which pow… | Low voltage side of the CTU / STU substation at which pow… | At the interconnection/injection point into ISTS (Deliver… |
| seci-cfd-i | `sector.power.common.metering_point` | At the inter-connection point where power is injected int… | At the inter-connection point where power is injected int… | Interconnection point where power is injected into the IS… |
| seci-cni-1-700mw | `sector.power.common.metering_point` | At the interconnection point (220 kV or above) where the … | At the interconnection point (220 kV or above) where the … | Interconnection point where power is injected into the id… |
| seci-ess-iv | `sector.power.common.metering_point` | The interconnection point at 220 kV or above where power … | The interconnection point at 220 kV or above where power … | At the interconnection point where power is injected into… |
| seci-fdre-ix | `sector.power.common.metering_point` | At the interconnection/delivery point where the power is … | At the interconnection/delivery point where the power is … | Delivery Point (ISTS substation); additional individual p… |
| seci-fdre-rtc-v | `sector.power.common.metering_point` | At the interconnection/delivery point where power is inje… | At the interconnection/delivery point where power is inje… | Injection point at the ISTS substation; sub-meters at poo… |
| seci-gaya-60mw | `sector.power.common.metering_point` | null | null | At the Point of Interconnection |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.metering_point` | At the Interconnection Point / Delivery Point (LV side of… | At the Interconnection Point / Delivery Point (LV side of… | Interconnection Point / Delivery Point (LV side of ISTS s… |
| nhpc-fdre-ii | `sector.power.common.min_bid_mw` | 50 | 50.0 | 30 |
| seci-cfd-i | `sector.power.common.named_states_or_sites` | ["Anywhere in India"] | [] | null |
| seci-cni-1-700mw | `sector.power.common.named_states_or_sites` | ["Special Economic Zones (SEZs) or areas designated as Ex… | ["Special Economic Zones (SEZs) or areas designated as Ex… | ["Special Economic Zones (SEZs) or Export Oriented Units … |
| seci-fdre-ix | `sector.power.common.named_states_or_sites` | ["The Projects can be located anywhere in India at the lo… | [] | null |
| seci-gaya-60mw | `sector.power.common.named_states_or_sites` | ["Gaya, Bihar, India"] | ["Gaya, Bihar, India"] | ["Habibpur, Dariaura & Adjacent Villages (Adjacent to Dob… |
| seci-cfd-i | `sector.power.common.net_worth_per_mw_inr` | 9680000 | 9680000.0 | null |
| seci-fdre-ix | `sector.power.common.net_worth_per_mw_inr` | 9680000 | 9680000.0 | null |
| seci-fdre-rtc-v | `sector.power.common.net_worth_per_mw_inr` | 9540000 | 9540000.0 | null |
| ntpc-hybrid-03 | `sector.power.common.ppa_signing_window_days` | null | null | 90 |
| ntpc-phes-2000mw | `sector.power.common.ppa_signing_window_days` | 90 | 90 | null |
| seci-ess-iv | `sector.power.common.ppa_signing_window_days` | 30 | 30 | null |
| seci-fdre-ix | `sector.power.common.ppa_signing_window_days` | 0 | 30 | null |
| seci-fdre-rtc-v | `sector.power.common.ppa_signing_window_days` | 0 | 30 | null |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.ppa_signing_window_days` | null | null | 30 |
| seci-gaya-60mw | `sector.power.common.scod_months` | null | null | 18 |
| ntpc-hybrid-03 | `sector.power.common.source_mix_rules` | [{"source": "wind", "condition": "rated power capacity of… | ["source: wind | treatment: required | limit_value: 33 | … | [{"source": "solar", "condition": "Minimum rated AC capac… |
| ntpc-phes-2000mw | `sector.power.common.source_mix_rules` | [{"source": "pumped_storage", "condition": "ISTS connecte… | ["source: pumped_storage | treatment: required | conditio… | [{"source": "pumped_storage", "condition": "ISTS-connecte… |
| seci-cfd-i | `sector.power.common.source_mix_rules` | [{"source": "bess", "condition": "ESS of X MW/2X MWh per … | ["source: bess | treatment: required | limit_value: 2 | l… | [{"source": "solar", "condition": "ALMM modules/cells and… |
| seci-cni-1-700mw | `sector.power.common.source_mix_rules` | [{"source": "solar", "condition": "SPD undertakes to sell… | ["source: solar | treatment: required | condition: SPD un… | [{"source": "solar", "condition": "Solar PV project under… |
| seci-ess-iv | `sector.power.common.source_mix_rules` | [{"source": "bess", "condition": "BESSD shall set up, ope… | ["source: bess | treatment: required | condition: BESSD s… | [{"source": "bess", "condition": "Contracted power suppli… |
| seci-fdre-ix | `sector.power.common.source_mix_rules` | [{"source": "bess", "condition": "ESS mandatory part of t… | ["source: bess | treatment: required | condition: ESS man… | [{"source": "solar", "condition": "Solar generating compo… |
| seci-fdre-rtc-v | `sector.power.common.source_mix_rules` | [{"source": "bess", "condition": "ESS mandatory part of P… | ["source: bess | treatment: required | condition: ESS man… | [{"source": "solar", "condition": "Solar PV component of … |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.source_mix_rules` | [{"source": "solar", "condition": "green power from RE pr… | ["source: solar | treatment: allowed | condition: green p… | [{"source": "solar", "condition": "Counts as Traceable Gr… |
| wbsedcl-re-rtc-2026-01 | `sector.power.common.tariff_structure` | fixed | fixed | two_part |
| ntpc-hybrid-03 | `sector.power.common.under_construction_counts` | null | null | true |
| ntpc-phes-2000mw | `sector.power.common.under_construction_counts` | null | null | true |
| seci-cfd-i | `sector.power.common.under_construction_counts` | false | false | null |
| seci-fdre-rtc-v | `sector.power.common.under_construction_counts` | false | false | null |
| seci-gaya-60mw | `sector.power.epc.boq_structure` | No item-rate bill of quantities; the bidder quotes a lump… | No item-rate bill of quantities; the bidder quotes a lump… | Lump-sum turnkey SOR rather than remeasurement BoQ: full … |
| seci-gaya-60mw | `sector.power.epc.drawing_approval_cycle` | Contractor must incorporate modifications/corrections not… | Contractor must incorporate modifications/corrections not… | Master Drawing List within 14 days of Zero Date. Project … |
| seci-gaya-60mw | `sector.power.epc.ld_delay` | 0.5% per week of the Contract Price for the whole of the … | 0.5% per week of the Contract Price for the whole of the … | 0.5% of total facilities Contract Price per week for dela… |
| seci-gaya-60mw | `sector.power.epc.ld_performance` | OTGT shortfall (OTF<1): LD equal to the NPV of the estima… | OTGT shortfall (OTF<1): LD equal to the NPV of the estima… | Acceptance OTGT (OTF<1 after second chance): NPV of 25-ye… |
| seci-gaya-60mw | `sector.power.epc.ld_performance_structured` | {"metric": "generation", "cap_basis": "revenue from the T… | ["metric: generation", "ld_tariff_inr_per_kwh: 3.60", "di… | {"metric": "generation", "cap_basis": "OTGT acceptance: 2… |
| seci-gaya-60mw | `sector.power.epc.milestone_payment_structured` | [{"against": "certification by Project Manager/Engineer-i… | ["milestone: Civil works progress payment | contract: civ… | [{"against": "CA acceptance, proforma invoice and advance… |
| seci-gaya-60mw | `sector.power.epc.price_schedule_structure` | Schedule No. 1: Plant and Mandatory Spare Parts Supplied … | Schedule No. 1: Plant and Mandatory Spare Parts Supplied … | SOR1: EXW plant and mandatory spares supplied within Owne… |
| seci-gaya-60mw | `sector.power.epc.scope_matrix` | [{"om": "yes", "item": "Solar PV Modules", "supply": "no"… | ["item: Solar PV Modules | supply: no | erection: yes | c… | [{"om": "True", "item": "Solar PV modules", "supply": "Tr… |
| seci-gaya-60mw | `sector.power.epc.taxes_duties_treatment` | Quoted prices must clearly indicate GST components (Centr… | Quoted prices must clearly indicate GST components (Centr… | Quote GST components in SOR; EPC/O&M and e-RA evaluated i… |
| seci-gaya-60mw | `sector.power.epc.warranty_terms` | Equipment warranties against material/manufacturing defec… | Equipment warranties against material/manufacturing defec… | Modules: minimum 25-year output warranty to bidder's degr… |
| nhpc-fdre-ii | `sector.power.fdre.capacity_addition_flexibility` | Configuration (Installed Capacity proposed) is fixed from… | Configuration (Installed Capacity proposed) is fixed from… | Configuration fixed through LoA, changeable after LoA unt… |
| seci-cfd-i | `sector.power.fdre.capacity_addition_flexibility` | Project configuration (Installed Capacity proposed) can b… | Project configuration (Installed Capacity proposed) can b… | Installed configuration may change until SCD; revised PBG… |
| seci-fdre-ix | `sector.power.fdre.capacity_addition_flexibility` | Project configuration (Installed Capacity of RE generatin… | Project configuration (Installed Capacity of RE generatin… | Installed component configuration may change up to SCSD/e… |
| seci-fdre-rtc-v | `sector.power.fdre.capacity_addition_flexibility` | The Project configuration (identical to the connectivity … | The Project configuration (identical to the connectivity … | Installed configuration may change until SCSD/extended SC… |
| nhpc-fdre-ii | `sector.power.fdre.demand_profile_structured` | {"basis": "availability_pct", "peak_blocks": [{"hours": 2… | ["basis: availability_pct", "peak_availability_pct: 90", … | {"basis": "availability_pct", "peak_blocks": [{"hours": 2… |
| seci-cfd-i | `sector.power.fdre.demand_profile_structured` | {"basis": null, "peak_blocks": null, "re_share_min_pct": … | ["re_share_min_pct: 100", "external_sourcing_max_pct: 25"] | {"basis": "energy_per_mw_per_day", "peak_blocks": [{"hour… |
| seci-fdre-ix | `sector.power.fdre.demand_profile_structured` | {"basis": "energy_per_mw_per_day", "peak_blocks": null, "… | ["basis: energy_per_mw_per_day", "peak_hours_per_day: 4",… | {"basis": "energy_per_mw_per_day", "peak_blocks": [{"hour… |
| seci-fdre-rtc-v | `sector.power.fdre.demand_profile_structured` | {"basis": "rtc", "peak_blocks": [{"hours": 6, "window_end… | ["basis: rtc", "peak_availability_pct: 90", "peak_hours_p… | {"basis": "rtc", "peak_blocks": [{"hours": 6, "window_end… |
| nhpc-fdre-ii | `sector.power.fdre.excess_energy_structured` | {"above": "contracted_capacity", "price_basis": "not_purc… | ["above: contracted_capacity", "price_basis: not_purchase… | {"above": "max_cuf", "price_basis": "ppa_tariff", "pct_of… |
| seci-cfd-i | `sector.power.fdre.excess_energy_structured` | {"above": "contracted_energy", "price_basis": "not_purcha… | ["above: contracted_energy", "price_basis: not_purchased"] | {"above": "contracted_energy", "price_basis": "not_purcha… |
| seci-fdre-ix | `sector.power.fdre.excess_energy_structured` | {"above": "contracted_capacity", "price_basis": "not_purc… | ["above: contracted_capacity", "price_basis: not_purchased"] | {"above": "contracted_energy", "price_basis": "ppa_tariff… |
| seci-fdre-rtc-v | `sector.power.fdre.excess_energy_structured` | {"above": "contracted_capacity", "price_basis": "ppa_tari… | ["above: contracted_capacity", "price_basis: ppa_tariff",… | {"above": "contracted_capacity", "price_basis": "pct_of_t… |
| nhpc-fdre-ii | `sector.power.fdre.peak_window_definition` | Four hours out of 24 hours daily: 2 hours in the morning … | Four hours out of 24 hours daily: 2 hours in the morning … | Four hours daily: two morning hours within05:00–10:00 and… |
| seci-cfd-i | `sector.power.fdre.peak_window_definition` | Peak Hours are energy scheduling hours between 18:00 Hrs.… | Peak Hours are energy scheduling hours between 18:00 Hrs.… | Any two hours chosen day-ahead by RPD between and includi… |
| seci-fdre-ix | `sector.power.fdre.peak_window_definition` | Peak Hours are the 4 hours per day chosen by the Buying E… | Peak Hours are the 4 hours per day chosen by the Buying E… | Any four hours chosen daily by Buying Entity between non-… |
| seci-fdre-rtc-v | `sector.power.fdre.peak_window_definition` | Peak Hours are any 6 hours per day chosen by the Buying E… | Peak Hours are any 6 hours per day chosen by the Buying E… | Any six hours chosen daily by Buying Entity between 18:00… |
| seci-cfd-i | `sector.power.fdre.shortfall_compensation_multiple` | 1.5 | 1.5 | null |
| ntpc-phes-2000mw | `sector.power.generation.fuel_supply_arrangement` | Charging/pumping power is provided by NTPC REL from power… | Charging/pumping power is provided by NTPC REL from power… | NTPC REL provides input/charging power from RE projects o… |
| ntpc-phes-2000mw | `sector.power.generation.fuel_type` | Pumped hydro energy storage (PHES), ISTS connected, provi… | Pumped hydro energy storage (PHES), ISTS connected, provi… | Pumped hydro energy storage (PHES) |
| ntpc-phes-2000mw | `sector.power.generation.heat_rate_or_design_energy` | null | null | Minimum single-cycle time of 6 hours generation through d… |
| ntpc-phes-2000mw | `sector.power.generation.tariff_two_part` | false | false | null |
| ntpc-phes-2000mw | `sector.power.generation.water_clearance_responsibility` | Bidder: required clearances for the project are to be obt… | Bidder: required clearances for the project are to be obt… | null |
| ntpc-hybrid-03 | `sector.power.hybrid.excess_generation_treatment` | Energy above the maximum CUF (120% of declared CUF) may b… | Energy above the maximum CUF (120% of declared CUF) may b… | Energy above maximum CUF may be sold to another entity su… |
| ntpc-hybrid-03 | `sector.power.hybrid.storage_metering_rule` | ESS may be included, but ESS charged using a source other… | ESS may be included, but ESS charged using a source other… | ESS charged using a source other than Wind Solar Hybrid p… |
| wbsedcl-re-rtc-2026-01 | `sector.power.re_rtc.linked_capacity_obligation` | {"stages": [{"documents": "both", "share_pct": 50, "month… | ["technology: solar", "multiple_of_contracted: 2", "locat… | {"stages": [{"documents": "both", "share_pct": 50, "month… |
| wbsedcl-re-rtc-2026-01 | `sector.power.re_rtc.peak_window` | {"notice": null, "set_by": "procurer", "stretches": "proc… | ["hours_per_day: 4", "stretches: procurer_discretion", "s… | {"notice": "Declared for each calendar month and intimate… |
| wbsedcl-re-rtc-2026-01 | `sector.power.re_rtc.rec_obligation` | {"rec_type": null, "applies_to": "all_non_re_energy", "co… | ["applies_to: all_non_re_energy", "cost_borne_by: supplier"] | {"rec_type": "Renewable Energy Certificates under CERC (T… |
| seci-cni-1-700mw | `sector.power.solar.almm_list_requirement` | Exempted: Projects set up under the SEZ/EOU framework are… | Exempted: Projects set up under the SEZ/EOU framework are… | Exempt from ALMM compliance for SEZ/EOU solar projects su… |
| seci-cni-1-700mw | `sector.power.solar.augmentation_rules` | Higher DC capacity arrays, so as to achieve the AC capaci… | Higher DC capacity arrays, so as to achieve the AC capaci… | SPD may design/install higher DC capacity and repower dur… |
| seci-cni-1-700mw | `sector.power.solar.excess_energy_structured` | {"above": "contracted_capacity", "price_basis": "not_purc… | ["above: contracted_capacity", "price_basis: not_purchased"] | {"above": "max_cuf", "price_basis": "ppa_tariff", "pct_of… |
| seci-cni-1-700mw | `sector.power.solar.land_type_restrictions` | Projects must be set up in Special Economic Zones (SEZs) … | Projects must be set up in Special Economic Zones (SEZs) … | Project must be located in Special Economic Zones (SEZs) … |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.wind.hub_height_or_tech_restrictions` | WTGs must be ALMM (Wind) listed with any rating of 3.0 MW… | WTGs must be ALMM (Wind) listed with any rating of 3.0 MW… | Offered WTGs must be latest ALMM (Wind)-listed models of … |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.wind.resource_data_obligation` | Site specific wind data for certification of AEP is made … | Site specific wind data for certification of AEP is made … | NTPC REL supplies site-specific wind data for AEP certifi… |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.wind.rlmm_requirement` | Turbines must be ALMM (Wind) listed: scope requires suppl… | Turbines must be ALMM (Wind) listed: scope requires suppl… | Latest MNRE ALMM (Wind) listing required for the offered … |
| ntpc-rel-600mw-anantapur-wtg | `sector.power.wind.site_transmission_constraints` | Project located in Andhra Pradesh (Anantapur) at 200 loca… | Project located in Andhra Pradesh (Anantapur) at 200 loca… | ISTS-connected project in Anantapur, Andhra Pradesh, nomi… |

### The agent caught what the engine missed: prompt work

Where the agent read the right value and the engine did not, the agent's path to the evidence (its search, the page it cited) is what to fold into the section's extract prompt, then `make eval PROMPT=<section>/vN` to measure it.

| Tender | Field | Reviewer | Engine | Agent |
| --- | --- | --- | --- | --- |
| ntpc-phes-2000mw | `core.identity.portal` | null | https://www.bharat-electronictender.com | null |
| seci-cni-1-700mw | `core.key_dates.pre_bid_meeting_date` | 2026-09-14 | null | 2026-09-14 |

### Both abstained: the reviewer found what neither model did

The value is in the document (the reviewer cited its page) and neither model returned it: routing, a scanned page, or a clause written in words the prompts do not expect.

| Tender | Field | Reviewer | Engine | Agent |
| --- | --- | --- | --- | --- |
| ntpc-hybrid-03 | `core.guarantees.emd_formula` | EMD Amount = ₹11,60,000 × Capacity Bid (MW), at the speci… | null | null |
| ntpc-hybrid-03 | `core.guarantees.pbg_formula` | PBG Amount = ₹29,00,000 × Awarded Contracted Capacity (MW… | null | null |

## Production confidence rule

A field is shown with low-review emphasis only when reviewer, engine and agent agree on at least 97% of at least 15 gold instances. It changes the reviewer screen's default emphasis and nothing else: there is no auto-approval. Written to `evals/results/review-emphasis-<tenant>.json`.

Fields that qualify today: 0. The most instances any field has is 11; the rule needs 15.

| Field | Instances | Agreement | Emphasis |
| --- | --- | --- | --- |
| `core.eligibility.consortium_allowed` | 11 | 100% | full review |
| `core.eligibility.liquidity_basis` | 11 | 100% | full review |
| `core.eligibility.max_consortium_members` | 11 | 100% | full review |
| `core.eligibility.parent_affiliate_credentials_allowed` | 11 | 100% | full review |
| `core.eligibility.turnover_basis` | 11 | 100% | full review |
| `core.eligibility.turnover_requirement_inr` | 11 | 100% | full review |
| `core.guarantees.emd_per_mw_inr` | 11 | 100% | full review |
| `core.guarantees.pbg_per_mw_inr` | 11 | 100% | full review |
| `core.key_dates.bid_submission_deadline` | 11 | 100% | full review |
| `core.key_dates.era_date` | 11 | 100% | full review |
| `core.key_dates.query_deadline` | 11 | 100% | full review |
| `core.key_dates.technical_opening_date` | 11 | 100% | full review |
| `core.penalties.delay_ld_per_mw_per_day_inr` | 11 | 100% | full review |
| `core.penalties.max_scod_extension_months` | 11 | 100% | full review |
| `core.penalties.termination_delay_months` | 11 | 100% | full review |
| `sector.power.common.connectivity_responsibility` | 11 | 100% | full review |
| `sector.power.common.dcr_required` | 11 | 100% | full review |
| `sector.power.common.financial_closure_months` | 11 | 100% | full review |
| `sector.power.common.financial_closure_reference` | 11 | 100% | full review |
| `sector.power.common.ists_waiver_cutoff_date` | 11 | 100% | full review |
| `sector.power.common.location_constraint` | 11 | 100% | full review |
| `sector.power.common.max_projects_per_bidder` | 11 | 100% | full review |
| `sector.power.common.min_commissioned_mw` | 11 | 100% | full review |
| `sector.power.common.total_capacity_mw` | 11 | 100% | full review |
| `sector.power.common.total_capacity_mwh` | 11 | 100% | full review |
| `sector.power.common.ppa_tenure_years` | 10 | 100% | full review |
| `sector.power.common.tariff_ceiling_inr_per_kwh` | 10 | 100% | full review |
| `sector.power.common.local_content_rule` | 7 | 100% | full review |
| `core.commercial.change_in_law_clause` | 4 | 100% | full review |
| `core.commercial.termination_compensation` | 4 | 100% | full review |
| `sector.power.fdre.assured_availability_percent` | 4 | 100% | full review |
| `sector.power.fdre.component_disclosure_required` | 4 | 100% | full review |
| `sector.power.fdre.excess_energy_price_inr_per_kwh` | 4 | 100% | full review |
| `sector.power.fdre.storage_mandatory` | 4 | 100% | full review |
| `core.eligibility.shareholding_lock_in` | 3 | 100% | full review |
| `sector.power.common.deemed_generation_clause` | 3 | 100% | full review |
| `core.commercial.payment_security_mechanism` | 2 | 100% | full review |
| `core.guarantees.bg_release_conditions` | 2 | 100% | full review |
| `core.guarantees.pbg_schedule` | 2 | 100% | full review |
| `core.penalties.pbg_encashment_triggers` | 2 | 100% | full review |
| `core.penalties.shortfall_penalty_basis` | 2 | 100% | full review |
| `core.eligibility.ebitda_requirement_inr` | 1 | 100% | full review |
| `core.eligibility.experience_period_end_date` | 1 | 100% | full review |
| `core.eligibility.min_continuous_operation_years` | 1 | 100% | full review |
| `core.eligibility.min_single_station_mw` | 1 | 100% | full review |
| `core.eligibility.technical_experience_requirement` | 1 | 100% | full review |
| `sector.power.bess.availability_floor_percent` | 1 | 100% | full review |
| `sector.power.bess.capacity_charge_inr_lakh_per_mw_month` | 1 | 100% | full review |
| `sector.power.bess.capacity_mw` | 1 | 100% | full review |
| `sector.power.bess.capacity_mwh` | 1 | 100% | full review |
| `sector.power.bess.cycles_per_day` | 1 | 100% | full review |
| `sector.power.bess.dispatch_control` | 1 | 100% | full review |
| `sector.power.bess.round_trip_efficiency_guarantee_percent` | 1 | 100% | full review |
| `sector.power.bess.soc_constraints` | 1 | 100% | full review |
| `sector.power.bess.soc_constraints_structured` | 1 | 100% | full review |
| `sector.power.bess.warranty_years` | 1 | 100% | full review |
| `sector.power.epc.defect_liability_months` | 1 | 100% | full review |
| `sector.power.epc.om_period_months` | 1 | 100% | full review |
| `sector.power.epc.performance_ratio_guarantee_percent` | 1 | 100% | full review |
| `sector.power.epc.retention_percent` | 1 | 100% | full review |
| `sector.power.epc.supply_service_split` | 1 | 100% | full review |
| `sector.power.generation.availability_norm_percent` | 1 | 100% | full review |
| `sector.power.generation.capacity_charge_recovery_rule` | 1 | 100% | full review |
| `sector.power.hybrid.combined_cuf_floor_percent` | 1 | 100% | full review |
| `sector.power.hybrid.cuf_terms` | 1 | 100% | full review |
| `sector.power.hybrid.excess_energy_structured` | 1 | 100% | full review |
| `sector.power.hybrid.min_share_per_resource_percent` | 1 | 100% | full review |
| `sector.power.hybrid.oversizing_allowance_percent` | 1 | 100% | full review |
| `sector.power.hybrid.storage_permitted` | 1 | 100% | full review |
| `sector.power.re_rtc.cuf_annual_min_pct` | 1 | 100% | full review |
| `sector.power.re_rtc.cuf_monthly_min_pct` | 1 | 100% | full review |
| `sector.power.re_rtc.cuf_peak_min_pct` | 1 | 100% | full review |
| `sector.power.re_rtc.greenshoe_capacity_mw` | 1 | 100% | full review |
| `sector.power.re_rtc.greenshoe_exercise_deadline` | 1 | 100% | full review |
| `sector.power.re_rtc.greenshoe_ppa_signing_days` | 1 | 100% | full review |
| `sector.power.re_rtc.greenshoe_ssd` | 1 | 100% | full review |
| `sector.power.re_rtc.greenshoe_tariff_basis` | 1 | 100% | full review |
| `sector.power.re_rtc.non_re_tariff_split` | 1 | 100% | full review |
| `sector.power.re_rtc.supply_start_date` | 1 | 100% | full review |
| `sector.power.re_rtc.traceable_green_min_pct` | 1 | 100% | full review |
| `sector.power.solar.annual_degradation_cap_percent` | 1 | 100% | full review |
| `sector.power.solar.cuf_terms` | 1 | 100% | full review |
| `sector.power.solar.dcr_share_percent` | 1 | 100% | full review |
| `sector.power.solar.max_cuf_percent` | 1 | 100% | full review |
| `sector.power.solar.min_cuf_percent` | 1 | 100% | full review |
| `sector.power.solar.repowering_allowed` | 1 | 100% | full review |
| `sector.power.wind.cuf_terms` | 1 | 100% | full review |
| `sector.power.wind.excess_energy_structured` | 1 | 100% | full review |
| `sector.power.wind.min_cuf_percent` | 1 | 100% | full review |
| `core.guarantees.emd_form` | 11 | 91% | full review |
| `core.guarantees.success_charge_inr` | 11 | 91% | full review |
| `core.identity.tender_number` | 11 | 91% | full review |
| `core.key_dates.bid_validity` | 11 | 91% | full review |
| `core.key_dates.bid_validity_unit` | 11 | 91% | full review |
| `core.key_dates.nit_date` | 11 | 91% | full review |
| `sector.power.common.max_bid_mw` | 11 | 91% | full review |
| `sector.power.common.min_bid_mw` | 11 | 91% | full review |
| `sector.power.common.scod_months` | 11 | 91% | full review |
| `sector.power.common.tariff_structure` | 11 | 91% | full review |
| `core.guarantees.bg_validity_months` | 11 | 82% | full review |
| `core.identity.issuing_agency` | 11 | 82% | full review |
| `core.key_dates.pre_bid_meeting_date` | 11 | 82% | full review |
| `core.penalties.delay_ld_structured` | 11 | 82% | full review |
| `sector.power.common.almm_required` | 11 | 82% | full review |
| `core.guarantees.emd_formula` | 5 | 80% | full review |
| `sector.power.fdre.shortfall_compensation_multiple` | 4 | 75% | full review |
| `core.guarantees.emd_structured` | 11 | 73% | full review |
| `sector.power.common.net_worth_per_mw_inr` | 11 | 73% | full review |
| `sector.power.common.scod_reference` | 11 | 73% | full review |
| `sector.power.common.bess_charging_rule` | 10 | 70% | full review |
| `core.guarantees.pbg_formula` | 6 | 67% | full review |
| `sector.power.common.gna_requirement` | 3 | 67% | full review |
| `core.guarantees.processing_fee_inr` | 11 | 64% | full review |
| `core.identity.title` | 11 | 64% | full review |
| `sector.power.common.deemed_generation_structured` | 11 | 64% | full review |
| `sector.power.common.named_states_or_sites` | 11 | 64% | full review |
| `sector.power.common.under_construction_counts` | 11 | 64% | full review |
| `core.guarantees.pbg_structured` | 11 | 55% | full review |
| `core.identity.procurement_mode` | 11 | 55% | full review |
| `core.commercial.late_payment_surcharge` | 11 | 45% | full review |
| `core.commercial.payment_security_structured` | 11 | 45% | full review |
| `sector.power.common.ppa_signing_window_days` | 11 | 45% | full review |
| `core.eligibility.liquidity_requirement_inr` | 11 | 36% | full review |
| `core.identity.portal` | 11 | 36% | full review |
| `core.penalties.shortfall_rules` | 11 | 36% | full review |
| `core.key_dates.loa_timeline` | 11 | 18% | full review |
| `sector.power.common.metering_point` | 11 | 18% | full review |
| `core.commercial.offtaker` | 11 | 9% | full review |
| `core.documents.annexure_formats` | 11 | 9% | full review |
| `core.identity.tender_type_as_stated` | 11 | 9% | full review |
| `sector.power.common.delivery_point` | 11 | 9% | full review |
| `sector.power.common.land_responsibility` | 11 | 9% | full review |
| `sector.power.common.line_to_pooling_station_responsibility` | 11 | 9% | full review |
| `core.documents.draft_agreements_referenced` | 11 | 0% | full review |
| `core.documents.required_documents` | 11 | 0% | full review |
| `sector.power.common.clearances_responsibility` | 11 | 0% | full review |
| `sector.power.common.source_mix_rules` | 8 | 0% | full review |
| `sector.power.fdre.capacity_addition_flexibility` | 4 | 0% | full review |
| `sector.power.fdre.demand_profile_structured` | 4 | 0% | full review |
| `sector.power.fdre.excess_energy_structured` | 4 | 0% | full review |
| `sector.power.fdre.peak_window_definition` | 4 | 0% | full review |
| `core.eligibility.ebitda_basis` | 1 | 0% | full review |
| `core.guarantees.bid_security_instruments` | 1 | 0% | full review |
| `core.guarantees.pbg_instruments` | 1 | 0% | full review |
| `sector.power.bess.augmentation_obligation` | 1 | 0% | full review |
| `sector.power.bess.degradation_and_augmentation_structured` | 1 | 0% | full review |
| `sector.power.bess.degradation_obligation` | 1 | 0% | full review |
| `sector.power.bess.end_of_life_terms` | 1 | 0% | full review |
| `sector.power.bess.vgf_inr` | 1 | 0% | full review |
| `sector.power.epc.boq_structure` | 1 | 0% | full review |
| `sector.power.epc.drawing_approval_cycle` | 1 | 0% | full review |
| `sector.power.epc.ld_delay` | 1 | 0% | full review |
| `sector.power.epc.ld_performance` | 1 | 0% | full review |
| `sector.power.epc.ld_performance_structured` | 1 | 0% | full review |
| `sector.power.epc.milestone_payment_structured` | 1 | 0% | full review |
| `sector.power.epc.price_schedule_structure` | 1 | 0% | full review |
| `sector.power.epc.scope_matrix` | 1 | 0% | full review |
| `sector.power.epc.taxes_duties_treatment` | 1 | 0% | full review |
| `sector.power.epc.warranty_terms` | 1 | 0% | full review |
| `sector.power.generation.fuel_supply_arrangement` | 1 | 0% | full review |
| `sector.power.generation.fuel_type` | 1 | 0% | full review |
| `sector.power.generation.heat_rate_or_design_energy` | 1 | 0% | full review |
| `sector.power.generation.tariff_two_part` | 1 | 0% | full review |
| `sector.power.generation.water_clearance_responsibility` | 1 | 0% | full review |
| `sector.power.hybrid.excess_generation_treatment` | 1 | 0% | full review |
| `sector.power.hybrid.storage_metering_rule` | 1 | 0% | full review |
| `sector.power.re_rtc.linked_capacity_obligation` | 1 | 0% | full review |
| `sector.power.re_rtc.peak_window` | 1 | 0% | full review |
| `sector.power.re_rtc.rec_obligation` | 1 | 0% | full review |
| `sector.power.solar.almm_list_requirement` | 1 | 0% | full review |
| `sector.power.solar.augmentation_rules` | 1 | 0% | full review |
| `sector.power.solar.excess_energy_structured` | 1 | 0% | full review |
| `sector.power.solar.land_type_restrictions` | 1 | 0% | full review |
| `sector.power.wind.hub_height_or_tech_restrictions` | 1 | 0% | full review |
| `sector.power.wind.resource_data_obligation` | 1 | 0% | full review |
| `sector.power.wind.rlmm_requirement` | 1 | 0% | full review |
| `sector.power.wind.site_transmission_constraints` | 1 | 0% | full review |
