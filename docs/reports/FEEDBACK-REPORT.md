# Feedback report

Generated 2026-10-06 13:58 UTC by `python -m evals.feedback_report` from the `feedback` table: every correction a reviewer made to a candidate, for decisions that stand. The suggestions are for a person to act on; nothing is applied automatically.

Corrections: 1 on 1 field(s), 1 tender(s).

## Corrections by kind

| Kind | Count | Meaning |
| --- | --- | --- |
| wrong_value | 1 | the reviewer gave a different value |
| format | 0 | the same value in another form |
| missing | 0 | the model found nothing; the reviewer supplied the value |
| extra | 0 | the model gave a value; the reviewer says the document has none |

## The fields with the most corrections

### `sector.power.common.metering_point`: 1 correction(s)

Kinds: wrong_value 1. Tender types: fdre 1. Agencies: NHPC 1. Prompt versions: v1 1.

| Tender | Kind | Candidate | Final | Reviewer's note |
| --- | --- | --- | --- | --- |
| nhpc-fdre-ii | wrong_value | Low voltage side of the CTU/STU substation (for RE parks, the ISTS/In-STS pooling station … | 1) Low voltage side of the CTU/STU substation (2) In case of RE parks, the ISTS/In-STS poo… |  |

Suggested change: prompt: name the clause that governs and the figure to prefer when a table and a clause disagree.

