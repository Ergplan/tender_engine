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

- `make gold TENDER=<slug>` (slug or id; `POST /api/v1/admin/gold` takes either as well) reads the tender's latest completed-review snapshot (`tender_review_snapshot`), the active approvals of the version the review was completed at (a completed review is locked, so these are the decisions the snapshot was taken from), and the candidates they were decided on, and writes `evals/gold/<tender_type>/<slug>.yaml`: per field the final value, the decision (`approved`, `edited`, `not_in_document`), the pages the reviewer accepted (from the snapshot's evidence), reviewer, `decided_at`, the reviewer's note, and the candidate judged (id, value, confidence, prompt name and version, its pages). The record names the tender version it was reviewed at (`reviewed_version`) and the snapshot it came from. A field the document does not state has `final_value: null`, `decision: not_in_document`, and keeps the candidate the reviewer judged, whatever it said (a null reading scores as a correct abstention; a value scores as `extra`). The record carries `tenant_id` and is loaded per tenant.
- Not automatic on completion: the command is run after you say the review is trustworthy. It refuses a tender without a completed review. It regenerates the reliability report and the review log unless told not to.
- First record: `evals/gold/fdre/nhpc-fdre-ii.yaml`, 97 of 97 fields decided (77 approved, 5 edited, 15 not in document), version 1, completed 2026-10-06 12:48 UTC.

## Scoring (`evals/runner.py`)

- `make eval` (`POST /api/v1/admin/evals`) scores every gold record against the readings now in review for its tender at the reviewed version, through `ReviewStateService`: the reviewer's reading until a later run of the same version supersedes it, which is what "re-score against the latest extraction run" asks for. `make eval PROMPT=<section>/vN` first reads that section again on every gold tender with that prompt version, waits for those runs (and stops if one failed), then scores the readings of those runs and nothing else (`candidates_of_runs`); through the API the same is two calls, one that queues and returns the run ids and one that scores them, refused while a run is still queued or running and when one failed. Results files carry the tenant and are read per tenant. The prompt version a run uses per section is `extraction_run.prompt_overrides` (migration 0012), else the section's pinned version, else the run's; every candidate carries the version it was read with, so a comparison groups by it. The master prompt's example `PROMPT=extract/v2` is read as a section's version, because the extraction prompts are per section (`extract/commercial/v3`, …); there is no single `extract/vN`.
- Match rules by value type, all in plain Python: exact for `enum`, `int`, `bool`, `time`, `duration_months`; `date` equal after parsing (so `12/03/2026`, `12.03.2026`, `12-Mar-2026`, `12th March 2026`, `March 12, 2026` all match `2026-03-12`); `decimal`, `money_inr`, `percent`, `mw`, `mwh`, `kv`, `km` within 0.5% (`932,000` matches `928,000`; `933,000` does not); `text` by normalised exact match (case, punctuation, spacing), with the token-sort ratio reported and never counted; `list_text` without regard to order (a repeated item must be repeated); `record` and `record_list` key by key with the same rules (a key the reviewer left null that the model filled is `extra`, the reverse `missing`); `long_text` is "needs human judgement" and is not counted. A candidate of the wrong form that reads the same once normalised is `format`, not `wrong_value`.
- Outcomes: `correct`, `correct_abstention` (the reviewer marked the field absent and the model returned null), `wrong_value`, `format`, `missing` (the reviewer supplied a value the model did not), `extra` (the model gave a value for a field the document does not state), `needs_judgement`.
- Evidence is scored apart: did the candidate cite a page the reviewer accepted? Value accuracy and evidence accuracy are reported separately; a right value from the wrong page counts as right in the first and wrong in the second.
- Output: `evals/results/<stamp>-<label>.json` (every score, the summary by field, type, section and type×field, the misses) and a markdown table printed by the command (`stage-4-artifacts/eval.txt`).

## Feedback analysis (`evals/feedback_report.py`)

- `make feedback-report` reads `feedback` joined to the approval it belongs to and the tender, and counts only rows whose approval is still active: a cleared or re-decided decision leaves its row as history (KNOWN-GAPS row of 2026-10-06 closed by this). It groups by field path, delta kind, tender type, issuing agency and prompt version; `FEEDBACK-REPORT.md` lists the ten fields with the most corrections, up to three candidate/final pairs each with the reviewer's note, and a one-line suggestion by the kind that dominates (wrong value → prompt: name the governing clause; format → validator or normaliser; missing → prompt or routing; extra → prompt: return null unless stated). Nothing is applied.
- Today: one correction (`sector.power.common.metering_point`, wrong value). Your other four edits re-entered the value the model gave (`per_mw`, 6,380,000, `effective_date`, 24), so they produced no feedback row and score as correct.

## Dashboard (`/admin/reliability`)

- `GET /api/v1/admin/reliability` (`api/v1/admin/reliability.py`) scores the gold records as `make eval` does and returns the summary, the stability bar, the reviewed tenders with their time, and the prompt comparison from `evals/results/`. Beside it, `POST /admin/gold`, `POST /admin/evals`, `GET /admin/feedback` and `POST /admin/reports` (the three report files written again) make the operations of this stage API operations (invariant "API first"); the Makefile targets are their shell equivalents. `web/src/admin/ReliabilityPage.tsx` shows: the bar with its reasons; a tender type × field table, each cell `accuracy (n)` banded green at 90%, amber at 75%, red below; the reviewed tenders with reviewer, completion, sittings, minutes deciding, the count and the paths of the fields edited, not-in-document count and notable misses; the prompt-version comparison once more than one result exists.
- Access: the master prompt says "behind the same IP allowlist, no login". Port 443 is open to the world by your Stage 0 decision (access by review token only), so an allowlist does not exist to stand behind; the route is guarded by an admin token in a header instead (`ADMIN_TOKEN` in `.env`, asked for once by the page and kept in the browser session). An empty setting closes the route; a review link does not open it; the token opens nothing else. It is a credential, which operating rule 11 ("no auth, roles or login screens until Stage 5") does not foresee; it is not a login (no user, no session, no role), and the alternative was a dashboard open to the world. Your call: keep the token, or put `/admin` behind an IP allowlist in Caddy instead. Recorded in DECISIONS.md.

## Reliability report and the review log (`evals/report.py`)

`make report` (also run by `make gold`) writes `RELIABILITY-REPORT.md`: tenders reviewed by type against the set; value and evidence accuracy overall, per section with a recommendation (stable / needs prompt work / needs validator / needs schema change / not enough reviews yet), per tender type; fields below 90% with the kinds of miss and, where the misses cross agencies, that; the prompt versions tried from `evals/results/`; reviewer time per tender (from the approval rows: sittings split at gaps over fifteen minutes, minutes between decisions inside sittings); and the stability bar with each shortfall named. `REVIEW-LOG.md`: tender, type, reviewer, started, completed, decided, fields edited, not-in-document count, notable misses.

## Current accuracy and the bar

From `RELIABILITY-REPORT.md` (one gold record, NHPC FDRE-II, fdre):

- Value accuracy **98.7%** (78 of 79 scored fields); 18 long-text fields need human judgement. Every section 100% except `identity_and_scope` at 93% (14 of 15).
- Evidence accuracy **100%** (64 of 64 fields with a value and accepted pages cited an accepted page).
- The one miss: `sector.power.common.metering_point`, `wrong_value` by rule; your edit re-ordered the model's sentence into two numbered cases ("1) Low voltage side of the CTU/STU substation (2) In case of RE parks, …" against "Low voltage side of the CTU/STU substation (for RE parks, the ISTS/In-STS pooling …"), the same content in different words. The token-sort ratio is reported beside it.
- Your time: 56 minutes deciding over 8 sittings (116 decisions including flags and clears; from 2026-10-05 17:33 to 2026-10-06 12:48 UTC). The report counts time between decisions, not time on the page.
- **Stability bar: not met.** It needs two reviewed tenders for each type with two or more in the set (`epc` 2, `fdre` 4, `wind` 2): all three are short (fdre has one). Required-field accuracy is **100%** (the one miss, `metering_point`, is an optional field); no required field is below 75%; per section prompt, required-field accuracy under the last two versions seen (in review now, or in an earlier prompt evaluation kept in `evals/results/`) is 100% for the two sections that hold required fields (`identity_and_scope` v1, `key_dates` v1), each with one version so far, so that condition holds trivially until a prompt is revised and measured. Distance to the bar: five more reviews at least (one more fdre, two epc, two wind), each at 90% or better on required fields.

## Operating the review phase

- Review links for the other twelve tenders were created on 2026-10-06 (`python -m scripts.review_token create`, reviewer `venture@aayuda.energy`) and are delivered in the message, never in the repository. NHPC FDRE-II keeps its link, now read-only.
- As each review is completed and you confirm it: `make gold TENDER=<slug>`, `make eval`, `make feedback-report`, commit the gold record, the results file and the three reports. A prompt revision goes in as a new version, is measured with `make eval PROMPT=<section>/vN`, and is pinned in the schema YAML only after that, with the before and after in DECISIONS.md.

## Corpus audit (your request during the stage, 2026-10-06)

Manifests and database agree on all 13 tenders (25 versions, 51 documents). Flagged: SECI Ramagiri 70 MW BESS is missing Amendment-01 and Clarification-01 (xlsx, 28/07/2026) and three annexures listed on the SECI page; SECI CnI-1's bid deadline moved on the portal (05/10 → 15/10/2026) with no document, and a stakeholder-meeting notification is new on the site; SECI CfD-I lacks four pre-bid notices, and its revised RfS cites "17.04.2026" where everything else says 19.04.2026 (a typo, not a missing RfS); NHPC FDRE-II's corrigenda, if any, are on the CPP portal, which was not checked. Nothing was ingested: each of these changes a tender that holds candidates, and the Ramagiri documents are spreadsheets the parser does not read. Awaiting your word; the detail is in the delivery message and the gaps are in KNOWN-GAPS.md.

## Incident: your "Complete review" click (12:46 UTC)

Your click returned a 500 (API log: `column extraction_run.prompt_overrides does not exist`). Cause: the model column added for this stage was live in the API container (source is mounted) before the app database had it; every read of a run failed. The app database was migrated, the review loaded again, and the completion was replayed through your own link at 12:48 under your name (audit row `complete_review`, actor `venture@aayuda.energy`, status `reviewed`; 97 of 97 decided). The replay called the completion route only; the approval rows carry their earlier timestamps. Recorded in DECISIONS.md; the audit row and the API log lines are in `stage-4-artifacts/incident.txt`; the rule applied from now on is to migrate the app database before saving a model change while the API is up.

## Tests

- `tests/evals/test_runner.py`: every match rule: exact types, eight printed forms of one date, the 0.5% band on money, decimals, percentages and each capacity type at its boundary (932,000 in, 933,000 out; 602.9 MW in, 603.1 out; likewise MWh, kV, km), text normalisation with the fuzzy score reported, long text uncounted, lists without regard to order, records key by key and lists of records item by item, abstention right and wrong, missing, format, evidence scored apart, the summary buckets, the results file.
- `tests/evals/test_gold.py`: a review completed through the API (one edit, the rest approved or marked absent, the summary approved) becomes a gold record with the decisions, pages and candidates judged; it refuses before completion; the YAML round-trips; scored against its own candidates the only miss is the edit; timing, tender lines, the report and the log are rendered from it.
- `tests/evals/test_feedback_report.py`: grouping, ranking, suggestions and the rendered report on fixture rows; on the database, a correction counts while its decision stands and not after it is cleared.
- `tests/evals/test_report.py`: the stability bar met and each shortfall named, including a section prompt below 90% under one of its last two versions; the recommendation per section; the report and the log on two fixture gold records with a results folder.
- `tests/api/test_admin.py`: the routes refuse without the token, with a wrong token, with a review link, and always when no token is configured; the token opens the dashboard and nothing else; through the API a completed review becomes a gold record (refused before completion, 404 for an unknown tender), the dashboard then shows it, an evaluation writes a results file, a prompt evaluation queues runs whose readings are then scored by their ids and nothing else, and the feedback route returns the one correction.
- `tests/tender/test_prompt_overrides.py`: an override reads one section with another version, is stored on the run and on every candidate, must name a group and a registered version; `candidates_of_runs` returns that run's readings within the tenant.
- `web/src/admin/ReliabilityPage.test.tsx`: the token form, the header sent, the bar, the banded table, the tender list, the refusal.
- `make check`: 545 Python tests and 71 web unit tests pass; nine checks green (`stage-4-artifacts/checks.txt`). `make test-ui`: 10 of 10 pass, 1 skipped (the real-load timing case, run on the deployed app in Stage 3) (`stage-4-artifacts/playwright.txt`). `make trace`: clean, 183 field rows as before, no change this stage (`stage-4-artifacts/trace.txt`).

## Deployment

`make deploy` on 2026-10-06 (`stage-4-artifacts/deployment.txt`): migration 0012 applied, api, worker and web rebuilt, `ADMIN_TOKEN` set in `.env`, the dashboard answers at `https://34.131.65.108/admin/reliability`.

## What was skipped and why

- The dashboard reflects one completed review, not two: the second is yours to complete.
- No Playwright case for the dashboard: the browser-test stack has no `ADMIN_TOKEN`; the page is covered by unit tests and the route by API tests (KNOWN-GAPS).
- Long-text fields are not scored by rule (the master prompt's own instruction).
- Nothing was ingested for the corpus gaps.

## Independent review (operating rule 15)

Reviewer: OpenAI `gpt-6.1-sol` through `scripts/independent_review.py`, fresh context, given the stage diff, CLAUDE.md and the Stage 4 prompt (`stage-4-artifacts/review-gpt-6.1-sol-runN.txt`).

**Run 1** (on commit 1e97704): two invariant findings, one audit note, thirteen report claims.

Code defects found and fixed:

- *Tenant scoping* (invariant "everything is audited and tenant-scoped"): the candidate and evidence queries of the gold builder, the tender join of the feedback report, the tender-set query of the report, the tender lookup and the queue polling of the runner filtered by nothing; gold records and results carried no tenant. Fixed: every query filters by `tenant_id`; `GoldRecord.tenant_id`; `load_all(tenant_id)` everywhere it is read, the dashboard included.
- *API first*: evaluation, prompt evaluation, gold and the feedback report existed only as commands. Fixed: `POST /api/v1/admin/gold`, `POST /api/v1/admin/evals` (score; or queue a prompt reading and return run ids; or score named runs), `GET /api/v1/admin/feedback`, with tests; the Makefile targets remain as shell equivalents.
- Gold took every active approval of the tender, not only those of the reviewed version (e3). Fixed: `Approval.object_version == reviewed_version`.
- A prompt evaluation scored whatever was in review after the queue drained, without tying the scores to the runs it queued or checking they succeeded (e6). Fixed: `candidates_of_runs` scores the queued runs' readings only; `finished_runs` raises when a run failed; the API form returns the run ids and scores by them.
- The "last two prompt versions" condition counted distinct version strings across all sections (e11). Fixed: per section prompt, the last two versions by number, each judged on required-field accuracy; the report and the bar name any below 90%.
- The dashboard showed the count of edited fields, not the fields (e8). Fixed: paths beside the count.
- Report claims corrected: the candidate kept for an absent field is whatever the reviewer judged (e4); scoring uses the reading in review at the reviewed version, the reviewer's until a later run supersedes it (e5); lists compare without regard to order, not as sets (e7); required-field accuracy is 100%, not 98.7%, the miss being optional (e10); the trace has 183 field rows, unchanged (e13); placeholders filled.

Not resolvable by code, listed with a rationale:

- The admin token is a credential and rule 11 says no auth until Stage 5 (e9): by design, a dashboard open to the world was the alternative; your decision whether to keep it or move `/admin` behind a Caddy IP allowlist.
- Deployment, link delivery, the corpus audit, the incident and the costs are statements a diff cannot prove (e1, e2, e12, e13): the artifacts folder holds `deployment.txt`, `incident.txt` (audit row and API log lines), `checks.txt`, `playwright.txt`, `eval.txt`; the links are in the delivery message by design; the audit's evidence is the agency pages and the database, quoted in the message.
- Candidate-write audit coverage is outside the diff (c1): unchanged code, `core/services/extract.py` stores candidates through the audited path of Stage 1.

**Run 2** (on commit 59d697d): no invariant breach beyond one, four smaller code points, twelve report claims.

Code defects found and fixed:

- Results files carried no tenant and were read for every tenant (a1). Fixed: `tenant_id` in every results file; `prompt_comparison(tenant_id)` and the new `evaluated_scores(tenant_id)` read only the tenant's.
- `POST /admin/gold` took an id only where the command takes a slug or an id (e4). Fixed: either.
- Scoring by run ids did not check the runs had finished or succeeded (e5). Fixed: refused with `runs_not_finished` (409) while queued or running, `validation_failed` when one failed.
- The bar's prompt condition read only the candidates in review, so a version superseded by a later run dropped out (e6). Fixed: scores of earlier prompt evaluations in `evals/results/` count for the last-two-versions condition.
- `make report` and `make feedback-report` had no API equivalent (e7). Fixed: `POST /admin/reports` writes the three files.
- Report corrected: lists compare without regard to order (e11); the capacity types are tested at the band's edge (e11, tests added); the incident paragraph says what the artifact shows (e10); costs are in `costs.txt` (e12).

Listed with a rationale, not resolved by code:

- Gold reads the active approvals of the reviewed version rather than decisions frozen in the snapshot (e3): by design; a completed review is locked (decisions are refused with `review_completed`), so those approvals are the ones the snapshot was taken from; the snapshot itself is kept and named in the record.
- The admin token is application authentication (e8): as in run 1, your decision.
- Deployment, links, the corpus audit (e1, e2, e9): statements a diff cannot prove; `deployment.txt` now holds the deploy log and the live responses (401 without the token, the dashboard's data with it, the page at 200, migration 0012 applied).
- Candidate-write audit coverage outside the diff (c1): unchanged code.

**Run 3**: not run; the session reached its usage limit after run 2 was fixed and committed. The next session runs it (`scripts.independent_review --stage 4`) before the stage is closed.

## Open questions

1. Which of the corpus gaps should be ingested, and may the Ramagiri spreadsheets be converted to PDF for the parser, or should spreadsheet reading be built?
2. Your edits that re-entered the model's value: was the intent to attach a note (KNOWN-GAPS, "approved value cannot carry a note"), or to re-state the evidence? Either would make the edit mean something to the feedback report.
3. The order of the next reviews: the bar is reached soonest with one more `fdre` (SECI FDRE-IX, RTC-V or CfD-I), both `epc` and both `wind`.

## Costs

The stage made no model calls of its own: `make eval` without `PROMPT=` scores stored candidates, and no prompt evaluation was run (one would read a section again on every gold tender). `stage-4-artifacts/costs.txt` (from `llm_call_log`): one call on 2026-10-06 after 12:00 UTC, USD 0.32, a `summary_record` rewrite during your review; running total USD 356.69 over 806 calls; with the Stage 3 pass outside the app database, about USD 381.
