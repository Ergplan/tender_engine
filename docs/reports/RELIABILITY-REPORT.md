# Reliability report

Generated 2026-10-06 13:58 UTC by `python -m evals.report` (also `make report`). Every gold record scored against the candidates now in review at the version it was reviewed at. Accuracy is value accuracy: the candidate the reviewer saw against what they decided. Evidence accuracy asks whether the candidate cited a page the reviewer accepted. Long text is not scored by rule.

## Tenders reviewed

| Type | In the set | Reviewed | Tenders |
| --- | --- | --- | --- |
| bess | 1 | 0 | - |
| epc | 2 | 0 | - |
| fdre | 4 | 1 | nhpc-fdre-ii |
| generation | 1 | 0 | - |
| hybrid | 1 | 0 | - |
| solar | 1 | 0 | - |
| transmission | 1 | 0 | - |
| wind | 2 | 0 | - |

## Accuracy

- Value accuracy: **99%** on 79 scored fields (78 correct); 18 long-text fields need human judgement.
- Evidence accuracy: **100%** on 64 fields with a value and accepted pages (64 cited an accepted page). A right value from the wrong page counts as right above and wrong here.

| Section | Accuracy | n | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| commercial | 100% | 6 | 100% | stable |
| connectivity_and_compliance | 100% | 8 | 100% | stable |
| documents | 100% | 3 | 100% | stable |
| eligibility | 100% | 10 | 100% | stable |
| fdre_profile | 100% | 9 | 100% | stable |
| guarantees | 100% | 8 | 100% | stable |
| identity_and_scope | 93% | 15 | 100% | stable |
| key_dates | 100% | 15 | 100% | stable |
| penalties | 100% | 5 | 100% | stable |

### By tender type

| Type | Accuracy | n | Evidence |
| --- | --- | --- | --- |
| fdre | 99% | 79 | 100% |

## Fields below 90%

| Field | Accuracy | n | Misses | What the misses look like |
| --- | --- | --- | --- | --- |
| `sector.power.common.metering_point` | 0% | 1 | 1 | wrong_value 1 |

## Prompt versions tried

| Result | Prompt | Value accuracy | Evidence accuracy | n |
| --- | --- | --- | --- | --- |
| 20261006T135652Z-latest.json | as pinned | 99% | 100% | 79 |

## Reviewer time per tender

| Tender | Reviewer | Sittings | Minutes deciding | Decisions | Completed |
| --- | --- | --- | --- | --- | --- |
| nhpc-fdre-ii | venture@aayuda.energy | 8 | 56 | 116 | 2026-10-06 12:48 |

## Stability bar for Stage 5

**Not met.** Required-field value accuracy 100%.

At least 2 reviewed tenders for every type with 2 or more in the set (epc, fdre, wind); required-field value accuracy at least 90% across the last two prompt versions; no required field below 75%.

- fewer than 2 reviewed tenders for: epc, fdre, wind
- required-field accuracy by section prompt, last two versions seen: extract/identity_and_scope v1 100%; extract/key_dates v1 100%

