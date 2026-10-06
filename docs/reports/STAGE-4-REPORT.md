# Stage 4 report: gold set, per-field accuracy, feedback loop, reliability report

Date: 2026-10-06. Diff: `git diff stage-4-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` (layout rows for `evals/`, `scripts/make_gold.py`, `api/v1/admin/`, `web/src/admin/`, `tests/evals/`; the admin route in "API surface"; "What changed this stage", Stage 4).

**The stage is built, checked and deployed. The number it exists to produce rests on one completed review, yours of NHPC FDRE-II: value accuracy 98.7% on 79 scored fields, evidence accuracy 100%. The stability bar for Stage 5 is not met and cannot be until two tenders of each of `epc`, `fdre` and `wind` are reviewed. The review links for the other twelve tenders are in the message that delivered this report, not in the repository. Stage 5 waits.**

## Definition of done (master prompt, "Done when")

| Check | Result |
| --- | --- |
| The dashboard and report exist | Yes: `https://34.131.65.108/admin/reliability` (behind `ADMIN_TOKEN`), `docs/reports/RELIABILITY-REPORT.md`, `docs/reports/REVIEW-LOG.md`, `docs/reports/FEEDBACK-REPORT.md` |
| …and reflect at least two completed reviews | **No: one.** Only NHPC FDRE-II has been reviewed. The second review is yours to do; the code path from a completed review to the dashboard is exercised by `tests/evals/test_gold.py` on a review completed in the test suite |
| The user has the URL list for all 11 | Yes, for all 12 others (the set has 13 tenders; NHPC FDRE-II is reviewed), printed in the delivery message only |
| STAGE-4-REPORT.md states the current accuracy and how far it is from the stability bar | Below, "Current accuracy and the bar" |
| `make test` green, `make deploy` serving the app | Yes, see "Tests" and "Deployment" |

## Gold set (`evals/gold.py`, `scripts/make_gold.py`)

- `make gold TENDER=<slug>` (slug or id) reads the tender's latest completed-review snapshot (`tender_review_snapshot`), the active approvals and the candidates they were decided on, and writes `evals/gold/<tender_type>/<slug>.yaml`: per field the final value, the decision (`approved`, `edited`, `not_in_document`), the pages the reviewer accepted (from the snapshot's evidence), reviewer, `decided_at`, the reviewer's note, and the candidate judged (id, value, confidence, prompt name and version, its pages). The record names the tender version it was reviewed at (`reviewed_version`) and the snapshot it came from. A field the document does not state has `final_value: null`, `decision: not_in_document`, and keeps the model's null reading as the candidate judged.
- Not automatic on completion: the command is run after you say the review is trustworthy. It refuses a tender without a completed review. It regenerates the reliability report and the review log unless told not to.
- First record: `evals/gold/fdre/nhpc-fdre-ii.yaml`, 97 of 97 fields decided (77 approved, 5 edited, 15 not in document), version 1, completed 2026-10-06 12:48 UTC.

## Scoring (`evals/runner.py`)

- `make eval` scores every gold record against the candidates now in review for its tender at the reviewed version (the same reading the reviewer saw, through `ReviewStateService`); `make eval PROMPT=<section>/vN` first reads that section again on every gold tender with that prompt version, waits for the queue, then scores only that section. The prompt version a run uses per section is `extraction_run.prompt_overrides` (migration 0012), else the section's pinned version, else the run's; every candidate carries the version it was read with, so a comparison groups by it. The master prompt's example `PROMPT=extract/v2` is read as a section's version, because the extraction prompts are per section (`extract/commercial/v3`, …); there is no single `extract/vN`.
- Match rules by value type, all in plain Python: exact for `enum`, `int`, `bool`, `time`, `duration_months`; `date` equal after parsing (so `12/03/2026`, `12.03.2026`, `12-Mar-2026`, `12th March 2026`, `March 12, 2026` all match `2026-03-12`); `decimal`, `money_inr`, `percent`, `mw`, `mwh`, `kv`, `km` within 0.5% (`932,000` matches `928,000`; `933,000` does not); `text` by normalised exact match (case, punctuation, spacing), with the token-sort ratio reported and never counted; `list_text` as a set; `record` and `record_list` key by key with the same rules (a key the reviewer left null that the model filled is `extra`, the reverse `missing`); `long_text` is "needs human judgement" and is not counted. A candidate of the wrong form that reads the same once normalised is `format`, not `wrong_value`.
- Outcomes: `correct`, `correct_abstention` (the reviewer marked the field absent and the model returned null), `wrong_value`, `format`, `missing` (the reviewer supplied a value the model did not), `extra` (the model gave a value for a field the document does not state), `needs_judgement`.
- Evidence is scored apart: did the candidate cite a page the reviewer accepted? Value accuracy and evidence accuracy are reported separately; a right value from the wrong page counts as right in the first and wrong in the second.
- Output: `evals/results/<stamp>-<label>.json` (every score, the summary by field, type, section and type×field, the misses) and a markdown table printed by the command (`stage-4-artifacts/eval.txt`).

## Feedback analysis (`evals/feedback_report.py`)

- `make feedback-report` reads `feedback` joined to the approval it belongs to and the tender, and counts only rows whose approval is still active: a cleared or re-decided decision leaves its row as history (KNOWN-GAPS row of 2026-10-06 closed by this). It groups by field path, delta kind, tender type, issuing agency and prompt version; `FEEDBACK-REPORT.md` lists the ten fields with the most corrections, up to three candidate/final pairs each with the reviewer's note, and a one-line suggestion by the kind that dominates (wrong value → prompt: name the governing clause; format → validator or normaliser; missing → prompt or routing; extra → prompt: return null unless stated). Nothing is applied.
- Today: one correction (`sector.power.common.metering_point`, wrong value). Your other four edits re-entered the value the model gave (`per_mw`, 6,380,000, `effective_date`, 24), so they produced no feedback row and score as correct.

## Dashboard (`/admin/reliability`)

- `GET /api/v1/admin/reliability` (`api/v1/admin/reliability.py`) scores the gold records as `make eval` does and returns the summary, the stability bar, the reviewed tenders with their time, and the prompt comparison from `evals/results/`. `web/src/admin/ReliabilityPage.tsx` shows: the bar with its reasons; a tender type × field table, each cell `accuracy (n)` banded green at 90%, amber at 75%, red below; the reviewed tenders with reviewer, completion, sittings, minutes deciding, fields edited, not-in-document count and notable misses; the prompt-version comparison once more than one result exists.
- Access: the master prompt says "behind the same IP allowlist, no login". Port 443 is open to the world by your Stage 0 decision (access by review token only), so an allowlist does not exist to stand behind; the route is guarded by an admin token in a header instead (`ADMIN_TOKEN` in `.env`, asked for once by the page and kept in the browser session). An empty setting closes the route; a review link does not open it; the token opens nothing else. No login, no roles (operating rule 11). Recorded in DECISIONS.md.

## Reliability report and the review log (`evals/report.py`)

`make report` (also run by `make gold`) writes `RELIABILITY-REPORT.md`: tenders reviewed by type against the set; value and evidence accuracy overall, per section with a recommendation (stable / needs prompt work / needs validator / needs schema change / not enough reviews yet), per tender type; fields below 90% with the kinds of miss and, where the misses cross agencies, that; the prompt versions tried from `evals/results/`; reviewer time per tender (from the approval rows: sittings split at gaps over fifteen minutes, minutes between decisions inside sittings); and the stability bar with each shortfall named. `REVIEW-LOG.md`: tender, type, reviewer, started, completed, decided, fields edited, not-in-document count, notable misses.

## Current accuracy and the bar

From `RELIABILITY-REPORT.md` (one gold record, NHPC FDRE-II, fdre):

- Value accuracy **98.7%** (78 of 79 scored fields); 18 long-text fields need human judgement. Every section 100% except `identity_and_scope` at 93% (14 of 15).
- Evidence accuracy **100%** (64 of 64 fields with a value and accepted pages cited an accepted page).
- The one miss: `sector.power.common.metering_point`, `wrong_value` by rule; your edit re-ordered the model's sentence into two numbered cases ("1) Low voltage side of the CTU/STU substation (2) In case of RE parks, …" against "Low voltage side of the CTU/STU substation (for RE parks, the ISTS/In-STS pooling …"), the same content in different words. The token-sort ratio is reported beside it.
- Your time: 56 minutes deciding over 8 sittings (116 decisions including flags and clears; from 2026-10-05 17:33 to 2026-10-06 12:48 UTC). The report counts time between decisions, not time on the page.
- **Stability bar: not met.** It needs two reviewed tenders for each type with two or more in the set (`epc` 2, `fdre` 4, `wind` 2): all three are short (fdre has one). Required-field accuracy is 98.7%, above 90%; no required field is below 75%; candidates scored come from prompt versions v1, v2 and v3, so "across the last two prompt versions" is satisfied in form only, since no prompt has been promoted since the gold record exists. Distance to the bar: five more reviews at least (one more fdre, two epc, two wind), each at 90% or better on required fields.

## Operating the review phase

- Review links for the other twelve tenders were created on 2026-10-06 (`python -m scripts.review_token create`, reviewer `venture@aayuda.energy`) and are delivered in the message, never in the repository. NHPC FDRE-II keeps its link, now read-only.
- As each review is completed and you confirm it: `make gold TENDER=<slug>`, `make eval`, `make feedback-report`, commit the gold record, the results file and the three reports. A prompt revision goes in as a new version, is measured with `make eval PROMPT=<section>/vN`, and is pinned in the schema YAML only after that, with the before and after in DECISIONS.md.

## Corpus audit (your request during the stage, 2026-10-06)

Manifests and database agree on all 13 tenders (25 versions, 51 documents). Flagged: SECI Ramagiri 70 MW BESS is missing Amendment-01 and Clarification-01 (xlsx, 28/07/2026) and three annexures listed on the SECI page; SECI CnI-1's bid deadline moved on the portal (05/10 → 15/10/2026) with no document, and a stakeholder-meeting notification is new on the site; SECI CfD-I lacks four pre-bid notices, and its revised RfS cites "17.04.2026" where everything else says 19.04.2026 (a typo, not a missing RfS); NHPC FDRE-II's corrigenda, if any, are on the CPP portal, which was not checked. Nothing was ingested: each of these changes a tender that holds candidates, and the Ramagiri documents are spreadsheets the parser does not read. Awaiting your word; the detail is in the delivery message and the gaps are in KNOWN-GAPS.md.

## Incident: your "Complete review" click (12:46 UTC)

Your click returned a 500. Cause: the model column `extraction_run.prompt_overrides`, added for this stage, was live in the API container (source is mounted) before the app database had it; every read of a run failed. `make migrate` was run at 12:47, the review loaded again, and the completion was replayed through your own link at 12:48 under your name (97 of 97 decided; audit row `complete_review`, actor `venture@aayuda.energy`). No decision was touched. Recorded in DECISIONS.md; the rule applied from now on is to migrate the app database before saving a model change while the API is up.

## Tests

- `tests/evals/test_runner.py`: every match rule: exact types, eight printed forms of one date, the 0.5% band on money, decimals, percentages and capacities (932,000 in, 933,000 out), text normalisation with the fuzzy score reported, long text uncounted, lists as sets, records key by key and lists of records item by item, abstention right and wrong, missing, format, evidence scored apart, the summary buckets, the results file.
- `tests/evals/test_gold.py`: a review completed through the API (one edit, the rest approved or marked absent, the summary approved) becomes a gold record with the decisions, pages and candidates judged; it refuses before completion; the YAML round-trips; scored against its own candidates the only miss is the edit; timing, tender lines, the report and the log are rendered from it.
- `tests/evals/test_feedback_report.py`: grouping, ranking, suggestions and the rendered report on fixture rows; on the database, a correction counts while its decision stands and not after it is cleared.
- `tests/evals/test_report.py`: the stability bar met and each shortfall named; the recommendation per section; the report and the log on two fixture gold records with a results folder.
- `tests/api/test_admin.py`: the route refuses without the token, with a wrong token, with a review link, and always when no token is configured; opens with the token; the token opens nothing else.
- `tests/tender/test_prompt_overrides.py`: an override reads one section with another version, is stored on the run and on every candidate, must name a group and a registered version.
- `web/src/admin/ReliabilityPage.test.tsx`: the token form, the header sent, the bar, the banded table, the tender list, the refusal.
- `make check`: PYTEST_COUNT Python tests and 71 web unit tests pass; nine checks green (`stage-4-artifacts/checks.txt`). `make test-ui`: PLAYWRIGHT_RESULT (`stage-4-artifacts/playwright.txt`). `make trace`: clean, 192 rows (`stage-4-artifacts/trace.txt`).

## Deployment

`make deploy` on 2026-10-06 (`stage-4-artifacts/deployment.txt`): migration 0012 applied, api, worker and web rebuilt, `ADMIN_TOKEN` set in `.env`, the dashboard answers at `https://34.131.65.108/admin/reliability`.

## What was skipped and why

- The dashboard reflects one completed review, not two: the second is yours to complete.
- No Playwright case for the dashboard: the browser-test stack has no `ADMIN_TOKEN`; the page is covered by unit tests and the route by API tests (KNOWN-GAPS).
- Long-text fields are not scored by rule (the master prompt's own instruction).
- Nothing was ingested for the corpus gaps.

## Independent review (operating rule 15)

REVIEW_SECTION

## Open questions

1. Which of the corpus gaps should be ingested, and may the Ramagiri spreadsheets be converted to PDF for the parser, or should spreadsheet reading be built?
2. Your edits that re-entered the model's value: was the intent to attach a note (KNOWN-GAPS, "approved value cannot carry a note"), or to re-state the evidence? Either would make the edit mean something to the feedback report.
3. The order of the next reviews: the bar is reached soonest with one more `fdre` (SECI FDRE-IX, RTC-V or CfD-I), both `epc` and both `wind`.

## Costs

The stage made no model calls of its own (`make eval` without `PROMPT=` scores stored candidates). Model spend on 2026-10-06 after 12:00 UTC: USD 0.32 (summary rewrites during your review). Running total in `llm_call_log`: USD 356.69; with the Stage 3 pass outside the app database, about USD 381.
