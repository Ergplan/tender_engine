# Feedback report

Generated 2026-10-13 12:28 UTC by `python -m evals.feedback_report` from the `feedback` table: every correction a reviewer made to a candidate, for decisions that stand. The suggestions are for a person to act on; nothing is applied automatically.

Corrections: 15 on 13 field(s), 7 tender(s).

## Corrections by kind

| Kind | Count | Meaning |
| --- | --- | --- |
| wrong_value | 6 | the reviewer gave a different value |
| format | 0 | the same value in another form |
| missing | 4 | the model found nothing; the reviewer supplied the value |
| extra | 5 | the model gave a value; the reviewer says the document has none |

## The fields with the most corrections

### `core.key_dates.pre_bid_meeting_date`: 3 correction(s)

Kinds: extra 2, missing 1. Tender types: solar 2, fdre 1. Agencies: SECI 3. Prompt versions: v1 3.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-cfd-i | extra | 2026-05-04 | null |  |
| seci-cni-1-700mw | extra | 2026-09-14 | null |  |
| seci-cni-1-700mw | missing | null | 2026-09-14 |  |

Suggested change: prompt: return null unless the pages state the value; say what wording is not a value.

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

### `core.guarantees.pbg_formula`: 1 correction(s)

Kinds: missing 1. Tender types: hybrid 1. Agencies: NTPC 1. Prompt versions: v2 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-hybrid-03 | missing | null | PBG Amount = ₹29,00,000 × Awarded Contracted Capacity (MW), calculated separately for each… |  |

Suggested change: prompt or routing: say where the value is stated and which pages to read for it.

### `core.identity.portal`: 1 correction(s)

Kinds: extra 1. Tender types: generation 1. Agencies: NTPC Renewable Energy Ltd 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-phes-2000mw | extra | https://www.bharat-electronictender.com | null |  |

Suggested change: prompt: return null unless the pages state the value; say what wording is not a value.

### `core.identity.procurement_mode`: 1 correction(s)

Kinds: wrong_value 1. Tender types: bess 1. Agencies: SECI 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-ess-iv | wrong_value | e_reverse_auction | single_stage_two_envelope |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.key_dates.dates_deferred_note`: 1 correction(s)

Kinds: wrong_value 1. Tender types: generation 1. Agencies: NTPC Renewable Energy Ltd 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| ntpc-phes-2000mw | wrong_value | Pre-bid meeting, query deadline, bid submission deadline, bid opening and e-reverse auctio… | The NTPC tender-portal notice specifies the bid submission deadline as 21 July 2026 at 15:… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `core.key_dates.loa_timeline`: 1 correction(s)

Kinds: missing 1. Tender types: fdre 1. Agencies: SECI 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-cfd-i | missing | null | end of selection process |  |

Suggested change: prompt or routing: say where the value is stated and which pages to read for it.

### `sector.power.common.metering_point`: 1 correction(s)

Kinds: wrong_value 1. Tender types: fdre 1. Agencies: NHPC 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| nhpc-fdre-ii | wrong_value | Low voltage side of the CTU/STU substation (for RE parks, the ISTS/In-STS pooling station … | 1) Low voltage side of the CTU/STU substation (2) In case of RE parks, the ISTS/In-STS poo… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

### `sector.power.common.named_states_or_sites`: 1 correction(s)

Kinds: wrong_value 1. Tender types: fdre 1. Agencies: SECI 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| seci-cfd-i | wrong_value | [] | ["Anywhere in India"] |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

