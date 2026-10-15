# Feedback report

Generated 2026-10-15 17:24 UTC by `python -m evals.feedback_report` from the `feedback` table: every correction a reviewer made to a candidate, for decisions that stand. The suggestions are for a person to act on; nothing is applied automatically.

Corrections: 32 on 18 field(s), 12 tender(s).

## Corrections by kind

| Kind | Count | Meaning |
| --- | --- | --- |
| wrong_value | 17 | the reviewer gave a different value |
| format | 0 | the same value in another form |
| missing | 4 | the model found nothing; the reviewer supplied the value |
| extra | 11 | the model gave a value; the reviewer says the document has none |

## The fields with the most corrections

### `core.identity.procurement_mode`: 6 correction(s)

Kinds: wrong_value 6. Tender types: fdre 2, bess 1, epc 1, wind 1, re_rtc 1. Agencies: SECI 5, WBSEDCL 1. Prompt versions: v1 6.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-ess-iv | wrong_value | e_reverse_auction | single_stage_two_envelope |  |
| seci-fdre-ix | wrong_value | e_reverse_auction | single_stage_two_envelope |  |
| seci-fdre-rtc-v | wrong_value | e_reverse_auction | single_stage_two_envelope |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.key_dates.pre_bid_meeting_date`: 4 correction(s)

Kinds: extra 3, missing 1. Tender types: solar 2, fdre 1, wind 1. Agencies: SECI 4. Prompt versions: v1 4.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-cfd-i | extra | 2026-05-04 | null |  |
| seci-cni-1-700mw | extra | 2026-09-14 | null |  |
| seci-cni-1-700mw | missing | null | 2026-09-14 |  |

Suggested change: prompt: return null unless the pages state the value; say what wording is not a value.

### `sector.power.common.scod_reference`: 3 correction(s)

Kinds: wrong_value 3. Tender types: fdre 2, generation 1. Agencies: SECI 2, NTPC Renewable Energy Ltd 1. Prompt versions: v1 3.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-phes-2000mw | wrong_value | ppa_signing | effective_date |  |
| seci-fdre-ix | wrong_value | effective_date | ppa_signing |  |
| seci-fdre-rtc-v | wrong_value | effective_date | ppa_signing |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.penalties.shortfall_rules`: 2 correction(s)

Kinds: extra 2. Tender types: fdre 1, re_rtc 1. Agencies: SECI 1, WBSEDCL 1. Prompt versions: v3 2.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-fdre-rtc-v | extra | ["metric: peak_availability \| threshold_pct: 90 \| threshold_of: contracted_capacity \| m… | null |  |
| wbsedcl-re-rtc-2026-01 | extra | ["metric: monthly_availability \| threshold_pct: 70 \| measured: monthly \| penalty_multip… | null |  |

Suggested change: prompt: return null unless the pages state the value; say what wording is not a value.

### `sector.power.common.named_states_or_sites`: 2 correction(s)

Kinds: wrong_value 2. Tender types: fdre 2. Agencies: SECI 2. Prompt versions: v1 2.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-cfd-i | wrong_value | [] | ["Anywhere in India"] |  |
| seci-fdre-ix | wrong_value | [] | ["The Projects can be located anywhere in India at the locations chosen by the Bidder/RPD"… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `sector.power.common.ppa_signing_window_days`: 2 correction(s)

Kinds: wrong_value 2. Tender types: fdre 2. Agencies: SECI 2. Prompt versions: v1 2.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-fdre-ix | wrong_value | 30 | 0 |  |
| seci-fdre-rtc-v | wrong_value | 30 | 0 |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `sector.power.common.source_eligibility`: 2 correction(s)

Kinds: extra 2. Tender types: wind 1, epc 1. Agencies: NTPC Renewable Energy Ltd 1, SECI 1. Prompt versions: v1 2.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-rel-600mw-anantapur-wtg | extra | [{"basis": "none", "source": "solar", "status": "not_addressed", "derived_from": ""}, {"ba… | null |  |
| seci-gaya-60mw | extra | [{"basis": "none", "source": "solar", "status": "not_addressed", "derived_from": ""}, {"ba… | null |  |

Suggested change: prompt: return null unless the pages state the value; say what wording is not a value.

### `core.commercial.termination_compensation`: 1 correction(s)

Kinds: wrong_value 1. Tender types: fdre 1. Agencies: SECI 1. Prompt versions: v3 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-fdre-ix | wrong_value | Only the tail of Article 13.4 is attached: on termination for SECI Event of Default, the c… | Article 13.4 (p. 67) partially describes compensation relating to termination arising from… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.documents.draft_agreements_referenced`: 1 correction(s)

Kinds: wrong_value 1. Tender types: wind 1. Agencies: NTPC Renewable Energy Ltd 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-rel-600mw-anantapur-wtg | wrong_value | ["Non-Disclosure Agreement between the bidder (Company) and NTPC Renewable Energy Limited"… | ["Non-Disclosure Agreement between the bidder (Company) and NTPC Renewable Energy Limited.… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.guarantees.emd_formula`: 1 correction(s)

Kinds: missing 1. Tender types: hybrid 1. Agencies: NTPC 1. Prompt versions: v2 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-hybrid-03 | missing | null | EMD Amount = ₹11,60,000 × Capacity Bid (MW), at the specified rate of ₹11.60 lakh per MW. |  |

Suggested change: prompt or routing: say where the value is stated and which pages to read for it.

