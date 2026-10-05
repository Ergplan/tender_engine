# Cost of extraction: before and after, on four tenders

Generated on 2026-10-05 from the app database. "Before" is the Stage 2 state of each tender: the calls behind its live candidates (the newest finished run per document and section) and those candidates. "After" is the same after one fresh extraction with the Stage 3 code. A field counts once per tender: the latest version that gives a value.

In the fresh extraction the published notice of a tender (one page) was read for every section; in Stage 2 it had been read for key dates and eligibility only. That is why three tenders have more calls after than before.

| Tender | Mode after | Calls | Input tokens | Read from cache | Written to cache | Output tokens | Cost USD | Fields with a value | With located evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nhpc-fdre-ii | batch | 13 → 13 | 1,016,568 → 1,016,568 | 0 | 0 | 64,808 → 58,788 | 13.41 → 6.55 | 74 → 74 of 89 | 74 → 74 |
| seci-cni-1-700mw | batch | 16 → 20 | 878,050 → 897,987 | 18,120 | 0 | 55,266 → 58,255 | 11.54 → 5.86 | 68 → 68 of 87 | 68 → 68 |
| ntpc-rel-600mw-anantapur-wtg | batch | 11 → 11 | 176,377 → 370,820 | 315,270 | 35,030 | 20,355 → 25,911 | 2.78 → 1.14 | 28 → 33 of 84 | 28 → 33 |
| ntpc-phes-2000mw | direct | 12 → 21 | 111,150 → 154,733 | 108,054 | 12,006 | 20,131 → 30,822 | 2.12 → 2.06 | 33 → 32 of 86 | 33 → 32 |

## Values, field by field

Compared after removing case, spaces and punctuation; numbers by value. Long text (summaries, clauses, lists) is rarely worded the same twice, so it is counted apart from short values.

| Tender | Answered both times | Same value | Long text worded differently | Short values that differ | Only before | Only after |
| --- | --- | --- | --- | --- | --- | --- |
| nhpc-fdre-ii | 74 | 44 | 30 | 0 | 0 | 0 |
| seci-cni-1-700mw | 67 | 38 | 27 | 2 | 1 | 1 |
| ntpc-rel-600mw-anantapur-wtg | 28 | 19 | 9 | 0 | 0 | 5 |
| ntpc-phes-2000mw | 32 | 22 | 7 | 3 | 1 | 0 |

### Short values that differ

- seci-cni-1-700mw `core.identity.issuing_agency`: before `Solar Energy Corporation of India Limited`, after `SECI`
- seci-cni-1-700mw `core.identity.portal`: before `ISN-ETS portal (https://www.bharat-electronictender.com)`, after `ETS Portal`
- ntpc-phes-2000mw `core.documents.draft_agreements_referenced`: before `['Energy Storage Service Agreement']`, after `['Energy Storage Service Agreement (on annual fixed charge basis, 25 years)']`
- ntpc-phes-2000mw `sector.power.common.delivery_point`: before `ISTS Substation (interconnecting point)`, after `Interconnecting point with ISTS Substation`
- ntpc-phes-2000mw `sector.power.generation.fuel_type`: before `Pumped hydro energy storage (PHES)`, after `Pumped hydro energy storage (PHES), ISTS connected, provided under a storage-as-a-service `

### Fields answered only once

- seci-cni-1-700mw `sector.power.common.local_content_rule`: only before (`No domestic content or Make in India rule is stated. The only related provision is that th`)
- seci-cni-1-700mw `sector.power.common.named_states_or_sites`: only after (`['Special Economic Zones (SEZs) or areas designated as Export Oriented Units (EOUs) of Ind`)
- ntpc-rel-600mw-anantapur-wtg `core.documents.annexure_formats`: only after (`['Non-Disclosure Agreement (format enclosed along with the IFB)']`)
- ntpc-rel-600mw-anantapur-wtg `core.documents.draft_agreements_referenced`: only after (`['Non-Disclosure Agreement between the bidder (Company) and NTPC Renewable Energy Limited'`)
- ntpc-rel-600mw-anantapur-wtg `core.documents.required_documents`: only after (`['Bid Security of INR 50,00,00,000/- in a separate sealed envelope (proof of e-payment in `)
- ntpc-rel-600mw-anantapur-wtg `core.guarantees.processing_fee_inr`: only after (`0.0`)
- ntpc-rel-600mw-anantapur-wtg `core.key_dates.dates_deferred_note`: only after (`The IFB prints only the issue, download, pre-bid/query, bid submission and technical openi`)
- ntpc-phes-2000mw `sector.power.generation.heat_rate_or_design_energy`: only before (`2000 MW / 12000 MWh total storage capacity; minimum 500 MW at single location with minimum`)
