# Stage 7, Block 1 report: baseline on the gold set (2026-10-24)

Block 1 of the owner's completion plan (`docs/COMPLETION-PLAN.md`): review links for the
nine open fields, then the eval on the eleven gold tenders with per-type, critical-field and
confidence-calibration cuts. Run under the plan's rules of 2026-10-24 afternoon: no stop
between blocks; this report closes the block and the build continues into Block 2.

## Definition of done

| Item | State | Evidence |
| --- | --- | --- |
| (a) Review links for the nine open fields: `seci-cfd-i` v5 (4, incl. the clause 40.3 withdrawal), `seci-cni-1-700mw` v3 (4, as a review round), `seci-wind-tranche-xx` (1) | Issued; the owner's decisions are pending | `/work/stage7-links.txt` on the VM (mode 600, never in the repo): cfd-i round 1 until 2026-11-12; cni-1 round 2 from v3 until 2026-11-23 (opened by `scripts.review_token round`, Block 0); wind-xx round 1 until 2026-11-05 |
| (b) Eval on the eleven gold tenders: evidence location and accuracy per field | Done | `evals/results/20261024T155809Z-ergplan-latest.json`; `stage-7-artifacts/block-1-baseline.md` |
| (b) Per tender type | Done (was already in the runner) | `summary.by_type` |
| (b) Critical fields separately | Done, new | `summary.by_critical`; `evals.runner.is_critical` |
| (b) Confidence calibration, accuracy within each band | Done, new | `summary.by_confidence_band`, `summary.high_confidence_misses`; `evals.runner.confidence_band` |

The plan's order is "once I have decided them, run the eval". The nine decisions are the
owner's and are not in yet; the eval was run on the gold set as it stands (eleven completed
reviews) so that the baseline exists today, and `make eval` is re-run in the Block 7 report
after the decisions land (a decided field changes its gold record through `make gold`).
Nothing was tuned: Block 1 asks for the baseline; fixes to systematic errors come after the
blind test of Block 4 (plan 4c), before and after reported there.

## What the runner now measures

- **Critical fields** (`is_critical`): the publication service's set (`CRITICAL_FIELDS` in
  `tender/services/publication.py`: bid deadline, capacity MW and MWh, EMD and PBG per MW,
  tariff ceilings, SCOD months, minimum commissioned MW, net worth, turnover, liquidity),
  plus every field of value type `date`, plus every field under `core.penalties.`. That is
  the plan's list: dates, capacity, tariff/ceiling, EMD, PBG, eligibility thresholds,
  penalties.
- **Confidence bands** (`confidence_band`): the reviewer screen's (`web/src/lib/format.ts`):
  high at or above 0.8, medium at or above 0.5, low below; a gold field with no reading is
  in no band. Each `FieldScore` now carries `confidence` and `critical`; the results JSON,
  the misses table and the markdown carry them too.
- Tests: `tests/evals/test_runner.py` (`test_the_critical_fields_are_the_plan_s_list`,
  `test_confidence_bands_are_the_reviewer_screen_s`,
  `test_summary_cuts_critical_fields_and_confidence_bands`).

## The baseline (2026-10-24 15:58 UTC, no model call)

Eleven gold tenders, 1,086 gold fields with a decision; 942 scored (144 `long_text` fields
are left to human judgement and not counted). Evidence is scored where the reviewer accepted
a page (634 fields).

| Cut | Scored | Accuracy | Evidence location | Misses |
| --- | --- | --- | --- | --- |
| **All** | 942 | **97.5%** | **100%** (634/634) | 24 |
| critical | 249 | **98.8%** | 100% | 3 |
| other | 693 | 97.0% | 100% | 21 |
| confidence high (≥0.8) | 520 | 98.1% | 100% | 10 |
| confidence medium (0.5–0.8) | 105 | 93.3% | 100% | 7 |
| confidence low (<0.5) | 12 | 91.7% | 100% | 1 |

Per tender type:

| Type | Tenders | Scored | Accuracy | Evidence | Misses |
| --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 90 | 98.9% | 100% | 1 |
| epc | seci-gaya-60mw | 87 | 97.7% | 100% | 2 |
| fdre | nhpc-fdre-ii, seci-cfd-i, seci-fdre-ix, seci-fdre-rtc-v | 320 | 96.3% | 100% | 12 |
| generation | ntpc-phes-2000mw | 92 | 97.8% | 100% | 2 |
| hybrid | ntpc-hybrid-03 | 84 | 97.6% | 100% | 2 |
| re_rtc | wbsedcl-re-rtc-2026-01 | 95 | 97.9% | 100% | 2 |
| solar | seci-cni-1-700mw | 85 | 97.6% | 100% | 2 |
| wind | ntpc-rel-600mw-anantapur-wtg | 89 | 98.9% | 100% | 1 |

Against the plan's Block 4 targets (stated here for orientation; Block 4 measures them on
eight unseen tenders): evidence location ≥95% **met** (100%); overall accuracy ≥95%
**met** (97.5%); critical ≥99% **not met** (98.8%, three misses); "every wrong reading
below the high-confidence band" **not met** (ten wrong readings at 0.8 or above).

### The three critical misses

| Tender | Field | Outcome | Confidence | What happened |
| --- | --- | --- | --- | --- |
| seci-fdre-ix | `core.penalties.delay_ld_structured` | extra | 0.70 | The engine read a structured LD (PBG encashment per day over 6 months); the reviewer marked the field not in document |
| wbsedcl-re-rtc-2026-01 | `core.penalties.shortfall_rules` | extra | 0.65 | Same shape: a structured shortfall rule read, reviewer said not in document |
| seci-cni-1-700mw | `core.key_dates.pre_bid_meeting_date` | missing | — | No reading; the reviewer found 2026-09-14 |

Both `extra` misses are the engine finding a penalty table the reviewer judged not to be
the tender's; both are medium confidence. The missing date is one of the fields the Block
4 windowing work (plan 2d) should catch.

### The ten high-confidence misses (calibration)

| Field | Count | Tenders | Note |
| --- | --- | --- | --- |
| `core.identity.procurement_mode` | 5 (0.90–0.95) | seci-ess-iv, seci-gaya-60mw, seci-fdre-ix, seci-fdre-rtc-v, wbsedcl-re-rtc-2026-01 | Engine `e_reverse_auction`, reviewer `single_stage_two_envelope`: the enum mixes the stage structure with the price discovery and both are true of these tenders. One systematic error, fixed by a prompt or enum change in Block 4c, not here |
| `sector.power.common.scod_reference` | 2 (0.90, 0.95) | seci-fdre-ix, ntpc-phes-2000mw | `effective_date` against `ppa_signing` and the reverse: the reference the document names is the one the reviewer took |
| `sector.power.common.named_states_or_sites` | 2 (0.80, 0.85) | seci-cfd-i, seci-fdre-ix | Engine `[]`, reviewer "anywhere in India" |
| `sector.power.common.metering_point` | 1 (0.80) | nhpc-fdre-ii | Text, same clause, reviewer's wording |

Of the 24 misses, 15 are `wrong_value`, 6 `missing` (two of them the plain-English summary,
which is written by the reviewer, not read), 3 `extra`. One field, `procurement_mode`,
accounts for five of them.

## Tests

`make check` green (`.ci/status.json`, `stage-7-artifacts/check-run3.log`); `tests/evals/test_runner.py` 56 tests (three new).

## Deployment

The eval runs inside the `api` container from the mounted source; no service change. The
Block 0 deploy of 15:41 UTC stands.

## Independent review (operating rule 15)

Pending with Block 0's: the OpenAI key in `.env` is invalid (HTTP 401 `invalid_api_key` at
15:50 UTC after the owner's replacement, and `expired_secret_key` before). The owner
replaces the key and says so; the review then runs over `stage-7-start..HEAD` with
`docs/STAGE-7-COMPLETION.md` as the instruction, and this section is completed.

## Costs

No model call in this block.

## Decisions pending from the owner

- The nine open fields (links in `/work/stage7-links.txt`).
- The OpenAI key for the rule-15 review.
- The bucket and `tender-backup` key (Block 0 report, Cloud Shell block).
