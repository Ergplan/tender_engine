# Stage 3 report: reviewer UI and review tokens

Date: 2026-10-05. Diff: `git diff stage-3-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` ("Cost of extraction", "Review tokens and what a request may reach", "The reviewer's view of a tender", "Reviewer screen", "What changed this stage"). Artifacts: `docs/reports/stage-3-artifacts/`.

**The stage is built and deployed. One check of the definition of done is yours: completing one real review from a link, unaided.** How to get the link and what I need back from you are in the last section.

## Definition of done (master prompt, row 3)

| Check | Result |
| --- | --- |
| Playwright suite green | Yes. `make test-ui`: 5 of 5 pass (`web/e2e/review.spec.ts`), in Chromium at 1366x768 against a seeded stack behind the same proxy routes as the deployed app. Output: `stage-3-artifacts/playwright.txt` |
| User completes one real review from a token URL unaided | **Open: this is your step** |
| First PDF page under 3 s on the VM | Yes, on a quiet VM. `web/e2e/real-load.spec.ts` on the deployed app, Chromium on the VM, nothing cached in the browser: SECI Ramagiri (91 fields, 10 documents, first document 266 pages) first meaningful paint 1.0 s, first PDF page 1.3 s (`stage-3-artifacts/real-tender-load.txt`). Earlier runs of the same test, whose output I did not keep, gave 1.4 s and 1.7 s for SECI Gaya (first document 305 pages), and, while the test watcher was running the full suite on the two cores, up to 4.8 s and 6.2 s. The selectable text layer of the first page arrives later, 3.7 s after the start on the quiet VM. The largest document of the set has 373 pages; none has 400. Not measured from a reviewer's own connection |
| No bulk-approve exists | Yes. The screen has Approve, Edit, Not in document and Flag per field and nothing else; the API has no route that decides more than one field (`POST /approvals` takes one candidate). Both the unit test and the browser test assert that no "approve all" exists |
| `make trace` is clean and every schema field has a complete FIELD-TRACE row | Yes (`stage-3-artifacts/trace.txt`). `docs/FIELD-TRACE.md` has 163 rows, one per field path of the nine tender types; the watcher's `field_trace` check regenerates it and fails on a difference or on a field without a UI component, route or column |
| `make test` green | 404 Python tests and 37 web unit tests pass; the nine checks are green (`stage-3-artifacts/checks.txt`) |
| `make deploy` serves the app | Yes, see "Deployment" |

## Before the UI: cost of extraction

### What was built

- **Shared page windows as a cached prefix.** Sections of one run are read from one shared window when that is cheaper by arithmetic on page counts (`core/services/extract_plan.py`). The window's PDF is sent with a cache mark, the system prompt is the text all section prompts inherit, and the section's own prompt text follows the PDF. The prompt files are unchanged.
- **Batch API.** A run has a mode. `python -m scripts.ingest_tenders extract` now extracts in batch mode (`--sync` for direct calls); the API default stays direct and takes `"mode": "batch"`. A batch run is two batches: the calls that write a shared window to the cache and all unshared calls first, the calls that read the cache second. The worker does not wait on a batch; it looks again every minute.
- **`llm_call_log`** records the mode, the batch id, the tokens written to and read from the cache, and the cost of each call with the factors that applied (cache read 0.025, cache write 1.25 or 2 for the one-hour cache, batch 0.5).
- **An answered call is not paid for again.** Before every call the run looks in the log for an identical call that was already answered. This is how batch results are read and how an interrupted run resumes. A collection that was interrupted is repeated without logging a call twice. One gap remains: a batch that was handed to the provider but whose row was not saved (a crash between the two) is submitted again (KNOWN-GAPS.md).
- **`python -m scripts.ingest_tenders cost-plan`** prints the page plan of every tender without calling the model.

### Three things the first real runs showed

1. **Calls with different output schemas did not share a cache entry.** In the first run, with one typed schema per section, every call wrote the window to the cache again (at 1.25 times the price), each a different number of tokens, and none read it; with one schema for all of them, the second call onwards read it. I conclude that the provider caches the output schema ahead of the pages. One schema holding all sections was refused ("The compiled grammar is too large, which would cause performance issues", the two error rows at 05:11 in `stage-3-artifacts/model-calls.txt`; the rows from 05:03 show every call writing and none reading; from 05:17, one write and then reads). Calls on a shared window therefore send one generic schema (a list of entries: key, value, confidence, rationale, evidence), and the answer is checked in Python against the section's typed model; an answer that fails is thrown away and the call is repeated alone with the typed model. Unshared windows are sent exactly as in Stage 2. On the real runs after this change (45 calls on shared windows, the end-to-end test included), 1 was repeated (eligibility on a notice page, the two rows at 05:22): its logged answer holds an extra entry `shareholding_lock-in` beside `shareholding_lock_in`. Such an extra entry is now dropped instead.
2. **The page-subset PDFs were not byte-identical between builds** (a fresh file id each time), which would have defeated both the cache and the matching of batch results. Fixed and tested.
3. **Caching saves little on the large documents.** The assumption in the stage prompt, that pages are re-sent across the field groups, holds only partly: the 13 tenders send 4,847 pages for 3,464 distinct pages, and the windows of different sections mostly cover different pages. Sharing pays where sections read the same few pages: notices, amendments, short documents.

### Measured, before and after

"Before" is the Stage 2 state of each tender (the calls behind its live candidates); "after" is one fresh extraction. Full table and field-by-field comparison: `stage-3-artifacts/cost-measurement.md`; runs: `stage-3-artifacts/extraction-runs.txt`; every model call of the stage with its mode, wave, tokens, cost and duration: `stage-3-artifacts/model-calls.txt`.

| Tender | Mode after | Calls | Input tokens | Read from cache | Output tokens | Cost USD | Fields with a value | Located |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nhpc-fdre-ii (264 pages) | batch | 13 → 13 | 1,016,568 → 1,016,568 | 0 | 64,808 → 58,788 | 13.41 → 6.55 | 74 → 74 of 89 | 74 → 74 |
| seci-cni-1-700mw (5 documents, 2 versions) | batch | 16 → 20 | 878,050 → 897,987 | 18,120 | 55,266 → 58,255 | 11.54 → 5.86 | 68 → 68 of 87 | 68 → 68 |
| ntpc-rel-600mw-anantapur-wtg (14 pages) | batch | 11 → 11 | 176,377 → 370,820 | 315,270 | 20,355 → 25,911 | 2.78 → 1.14 | 28 → 33 of 84 | 28 → 33 |
| ntpc-phes-2000mw (4 pages) | direct | 12 → 21 | 111,150 → 154,733 | 108,054 | 20,131 → 30,822 | 2.12 → 2.06 | 33 → 32 of 86 | 33 → 32 |

- **Cost.** The three tenders extracted in batch mode cost USD 13.55 against USD 27.73 before: 51% less.
- **Cache alone, like for like.** The 3-page NTPC notice, same ten sections, direct calls: USD 1.84 in Stage 2, USD 1.14 now (38% less), with 77% of its input read from the cache. Through a batch (the end-to-end test): USD 0.57, 69% less.
- **Cache hits inside batches.** All 13 second-wave calls read the window the first wave wrote.
- **Wall-clock.** The three batch tenders (7 runs, 44 calls) were queued at 05:30:23 UTC and all validated by 05:37:16: under 7 minutes with one worker. NHPC FDRE-II alone took 5 min 52 s from queue to validated; its 13 calls add up to 743 s (12 min 23 s) of model time in Stage 2. A batch may take up to an hour at the provider; these did not. Direct calls take as long as before: 22 s per call on the NTPC notice in Stage 2, 19 s now (`cost-measurement.md`, "Time spent in model calls").
- **The candidates are not worse.** Evidence-location rate 100% before and after on all four tenders. Fields with a value: 74 → 74, 68 → 68, 28 → 33, 33 → 32. Of 201 fields answered both times, 123 have the same value after normalisation, 73 are long text worded differently, and 5 short values differ, which the artifact lists: none is a number or a date. The comparison says the values agree, not that they are right; nothing has been reviewed yet.
- **One side effect of the fresh extraction, not of the cache.** A full extraction reads a published notice for every section its role allows (Stage 2 had read the notices for key dates and eligibility only). That is why three tenders show more calls, and on seci-cni-1-700mw two identity fields now show the notice's shorter wording ("SECI", "ETS Portal") as the current entry, with the RfS wording beside it as the earlier version. See open question 2.

### What to expect for the whole set

`cost-plan` for all 13 tenders (`stage-3-artifacts/cost-plan.md`, made after the fresh extractions, in which three notices are read for more sections than in Stage 2): input priced in uncached pages falls from 4,847 to 4,436 with direct calls (8% less) and to 2,308 in batch mode (52% less); output is halved in batch mode. A full extraction that cost USD 190.65 in Stage 2 should cost about USD 95 through the batch API. That is a projection from page counts, not a measurement.

## What was built for review

- **Migrations 0008 and 0009.** `review_token`, `tender_review_snapshot`; the `canonical_fact` guard now names the decisions that may carry a fact, and looks up the approval of a retired fact within the tenant.
- **Tokens.** 32 random url-safe characters, 30 days, one live per tender; creating a second revokes the first (`tender/services/tokens.py`). `POST /api/v1/review-tokens` returns the URL; `python -m scripts.review_token create --tender <slug> --reviewer "Name"` prints it; `revoke` and `list` beside it.
- **Token middleware** (`api/middleware/review_token.py`). A token is its reviewer and reaches only the review routes of its own tender; another tender is 404, any other route 403. Unknown, revoked and expired links answer with a plain sentence that the screen shows. A request from outside without a token reaches nothing but `/health`. `api/middleware/audit.py` writes one audit line per change request.
- **The reviewer's view** (`GET /tenders/{id}/review`): every field once; the entry to decide is the latest version that states the field, tagged "v2 amendment"; earlier versions' values are shown beside it.
- **Decisions.** `POST /approvals` gained the decision `flagged` (a note, no fact) and the stale-write check (`previous_approval_id`, 409 when the field was decided again).
- **Complete review** (`POST /tenders/{id}/complete-review`): refused while a required field that has a candidate is undecided (a required field for which nothing was extracted cannot be decided and does not block; DECISIONS.md); then the token is completed, the tender is `reviewed`, and the current view is stored in `tender_review_snapshot`. `GET /tenders/{id}/snapshot` returns it.
- **The screen** (`web/src/review/`): two panes at 44% and 56% with a draggable divider; header with title, type, agency, reviewer, "37 of 92 fields decided" and Complete review; sections in review order with decided/total; cards with label, help, value formatted by type, confidence pill, red and amber rule lines, evidence chips; the PDF with continuous scroll, thumbnails, search, contents from the section map and highlights; version and document selector; Approve, Edit, Not in document, Flag; Enter, E, N, F, J, K, Escape; immediate save with a tick or the reason; read-only summary with Download JSON.
- **FIELD-TRACE** generated by `make trace`, checked by the watcher.
- **Playwright suite** on its own stack (`make test-ui`), nightly in GitHub Actions.

## Things that went differently from the stage prompt

- **A completed token still reads.** The prompt says completed tokens are rejected and also asks for a read-only summary at the same link. A completed link reads everything and is refused every change (409).
- **The PDF pages are the images rendered at parse time; pdf.js supplies the selectable text layer.** The image of the first page is on screen at 1.3 s; pdf.js, reading the same PDF by range requests, has the first page's text ready at 3.7 s. I did not build and time a viewer that draws the pages with pdf.js alone. Highlights come from the stored boxes and do not depend on pdf.js. A page without an image is drawn by pdf.js.
- **A highlight needs a box.** The prompt asks for the matched line to be highlighted when evidence has only character offsets. Every located span in the database has a box (3,592 of 3,592), so that case is not built: evidence without a box, which today means a quote that was not located, outlines its page.
- **A list of records is edited as text**, one record per line as `key: value | key: value`. The screen sends the lines; the existing value type parses them into records when the decision is stored (`_record_list` in `tender/domain_packs/core/value_types.py`, unchanged this stage). Not exercised in a browser test.
- **Stored files are served by Caddy under `/files/` after asking the API** whether the token may see the file, not straight from `/data`.
- **Port 443 is open to the world**, so the token middleware also closes every non-review route to outside requests. Creating tenders, uploading, extracting and creating links work only from inside the VM. `curl https://34.131.65.108/api/v1/tenders` from anywhere now answers 401.
- **A tender with amendments is reviewed once per field, not once per version.** Marking an amendment's entry "not in document" brings the earlier version's entry back.
- **Keyboard focus scrolls the PDF only when the field has evidence.**
- **FIELD-TRACE has one row per field path (163), not per tender type and field (759).** What is the same for every field (routes, middleware, services, tables) is stated once above the table.
- **The watcher was stopped** during the build (the VM still has 2 cores); every commit was preceded by a full `make check`. It is running again since the deployment.

## Tests

- **Python: 404 pass.** New: the window plan (10), the LLM client's cost, cache layout, replay and batch (4), extraction with shared windows and batches (9), tokens, scoping, the reviewer's view, completion, viewer endpoints, request audit and the link command through HTTP (12), flag and stale decisions, the fact guard under a flag, FIELD-TRACE (5), the cost plan.
- **Web unit: 37 pass** (formatting, keys, the screen with a fake API, the summary, the link).
- **Browser: 5 pass**: a replaced link and a wrong link; the layout at 1366x768 without sideways scroll and the load times; an evidence chip scrolling the PDF and highlighting, the amendment's document, search; approve with Enter, edit a date, not in document, flag, and the same after a reload; complete by keyboard and the snapshot endpoint returning the final values, then read-only.
- **End-to-end with the real model** (`tests/e2e/test_review_flow.py`, run once, `stage-3-artifacts/e2e-real-model.txt`): the 3-page NTPC notice extracted through the batch API (waves of 1 and 9 calls, 77% of input read from the cache, USD 0.57, 299 s), 31 of 31 values with located evidence, then reviewed and completed through a review link, with the snapshot holding the tender number and its evidence. The Stage 1 and Stage 2 real-model tests were not rerun.
- **Evidence resolver corpus: 218 of 220** (`make evidence-corpus`, `stage-3-artifacts/evidence-corpus.txt`), unchanged. The two known failures are `real-0080` (a watermark through a heading) and `real-0142` (a wrapped table cell without a number).

Two defects the browser tests found that the unit tests had not: the browser cached a 410 answer and showed it for the next link (every API answer is now `no-store`), and an effect returned the promise Chrome gives from `scrollIntoView`, which blanked the page when the edit form opened (fixed; the screen now also has an error boundary that says to reload).

## The two numbers

From the regenerated `EXTRACTION-SUMMARY.md` (13 tenders, 25 versions, 51 documents): **evidence-location rate 99.8%** (804 of 806 values; the two misses are the same two as in Stage 2, in SECI FDRE-RTC-V Amendment-01); **answer rate 70%** (806 of 1,146 fields), from 37% to 88% per tender. Eight fields are flagged for review by validation. These are candidates; no accuracy number exists until reviews are completed.

## Cost

| Item | USD |
| --- | --- |
| Measurement runs on four tenders, including the two probes that showed the cache was not being read | 19.05 |
| End-to-end test | 0.60 |
| **Stage 3** | **about 20** |
| Running total since Stage 1 | **about 280** |

From `llm_call_log.cost_usd` at the configured prices, not the provider's invoice. The independent reviewer's OpenAI calls are not included.

## Deployment

`make deploy` ran on the screen as built; the tenant filters added after the first independent review are live through the mounted source (the API reloads; the worker was restarted). Probes: `stage-3-artifacts/deployment.txt`. Images rebuilt, migrations applied (`alembic_version` is `0009` after the second review), containers recreated, health probe `{"status":"ok","tenant_id":"ergplan","database":"ok"}` on `https://34.131.65.108/health`. Checked from the VM through the public address: `/health` 200; `/api/v1/tenders` without a link 401; a stored PDF under `/files/` without a link 401; `/review/<anything>` serves the screen, which shows the plain message for a link that is not valid. With temporary links for SECI Gaya and SECI Ramagiri (both revoked afterwards) the screen loaded all 91 fields and the first document; two screenshots are in `stage-3-artifacts/`. Not checked from a browser outside the VM.

## Independent review (operating rule 15)

Reviewer: `scripts/independent_review.py` on `gpt-6.1-sol`, given only the stage diff, CLAUDE.md and the stage prompt. Outputs: `stage-3-artifacts/review-gpt-6.1-sol-run*.txt`.

**Run 1** (on the draft of this report): (a) 1 finding, (b) none, (c) 1, (d) 1, (e) 11.

| # | Finding | Outcome |
| --- | --- | --- |
| a1 | Queries without a tenant filter: the review-token lookups by id in two routes, the update that marks a batch collected, the document lookup of `cost-plan` | Fixed: each filters by `tenant_id`; the joins of the file and document checks do too |
| c1 | Audit of candidate, approval, fact and feedback writes cannot be verified from the diff, because those functions did not change this stage | Not resolvable by code: the writes and their audit calls are in unchanged code (`ExtractService._add_candidate`, `ApprovalService.approve`, `TenderService.add_version`). The one new decision, a flag, takes the same path; `test_a_flag_is_recorded_without_a_fact_and_withdraws_an_earlier_decision` covers it |
| d1 | `make trace` exists and is checked, but no run of it was shown | The run is now an artifact (`trace.txt`: regenerated, no changed file), as is the output of all nine checks (`checks.txt`) |
| e1, e2, e10, e11 | Test results, deployment, load times, the watcher's history, the corpus run and cost totals are not provable from code | Statements of this report. Outputs added as artifacts: `checks.txt`, `playwright.txt`, `real-tender-load.txt`, `deployment.txt`, `evidence-corpus.txt` |
| e3 | "A call is never paid twice" is stronger than the code: a batch submitted but not recorded, or collected part-way, can be paid again | Report corrected to what the code does; the two gaps are in KNOWN-GAPS.md |
| e4, e5 | Provider cache behaviour, the repeated call and the second-wave hits lack recorded evidence | `model-calls.txt` now lists every model call of the stage with its wave and its cache tokens |
| e6 | The projection quoted numbers that differ from the cost-plan artifact | Report corrected to the artifact (the plan had been regenerated after the fresh extractions) |
| e7 | Completion is not refused for a required field that has no candidate | By design (DECISIONS.md); the report now says so where it describes completion |
| e8 | "As specified" hides two differences: evidence with offsets but no box outlines the page; a record list is edited as text | Report corrected: both are listed under "Things that went differently" |
| e9 | Nothing shows that pdf.js alone would be slower | Report corrected: it gives the two measured times and says the comparison was not made |

**Run 2** (after those fixes): (a) 2, (b) none, (c) 1, (d) none, (e) 7.

| # | Finding | Outcome |
| --- | --- | --- |
| a1 | The link listing joins `tender` without a tenant filter; the fact guard's lookup of the approval of a retired fact has no tenant predicate | Fixed: the listing filters both tables; migration 0009 adds the predicate to the trigger (the lookup dates from Stage 1) |
| a2, c1 | Invariants and audit of candidate, approval, fact, feedback and version writes cannot be certified from the diff, because that code did not change | As in run 1: not resolvable by code |
| e1 | The report said an interrupted collection submits the batch again; the code collects it again and would log calls twice | Fixed in code: `collect_batch` skips calls of the batch that are already logged (test added); report corrected |
| e2 | Load times for SECI Gaya and under load have no artifact | Report corrected: it names the one run that is kept and says the others were not |
| e3 | The refusal message was cut off in the artifact; the reason for the repeated call was not recorded; "never share a cache entry" is more than the runs show | `model-calls.txt` now holds the full message; the report gives the extra key from the logged answer and states the cache finding as what was observed |
| e4 | The Stage 2 durations had no evidence | `cost-measurement.md` now has the seconds of model calls before and after |
| e5 | Turning edited lines back into records is not in the diff | It is in unchanged code; the report names the function and says no browser test exercises it |
| e6 | The watcher's history and where the two defects were found are not provable | Statements of this report |
| e7 | The review link was missing from the draft | The last section now says where the link is; the link itself is kept out of the repository |

## Open questions

1. **Your review.** See below.
2. **Published notices on a fresh extraction.** A full extraction reads a notice page for every section its role allows, and where the notice is attached to a later version its short wording becomes the current entry of identity fields (seen on seci-cni-1-700mw). Restricting the role `nit` to key dates would be a schema change, and the `v1` schemas are frozen. Do you want a `v2` that reads notices for key dates only, or leave it for the reviewer to set aside?
3. **Batch as the default for the command.** Extraction by `ingest_tenders extract` now goes through the batch API. It took minutes here; the provider allows itself up to an hour, and longer on a bad day. Keep it as the default for Stage 4's corpus runs?
4. **The generic answer schema on shared windows.** It is what makes the cache work, and its answers are checked against the typed model afterwards. If you would rather keep provider-enforced typed output everywhere, `EXTRACT_SHARE_WINDOWS=false` turns sharing off; the cost is the cache saving on short documents.
5. **VM size.** Still 2 cores and 3.9 GB. The resize commands are in the Stage 2 report.
6. **A guard for the Stage 4 dashboard** (`/admin/reliability`) is needed before it is built: an admin token is the smallest change.

## Your step: one real review

A link for NHPC FDRE-II is live. It is not written in this file: a review link is the only key to its review, and this file is in the repository. It is in my message to you, and `docker compose exec -T api python -m scripts.review_token list` prints it on the VM.

It opens NHPC FDRE-II (89 fields, 74 with a value, one 264-page RfS), extracted afresh today. The browser will warn once about the certificate (the app is served on a bare IP; KNOWN-GAPS.md). The link is valid for 30 days and is recorded under the reviewer name `venture@aayuda.energy`, taken from your account; every decision you make carries that name. If you want another name or another tender, make a new link before deciding anything (the old one stops working):

```
cd /work/tender_engine && docker compose exec -T api python -m scripts.review_token create --tender <slug> --reviewer "Your Name"
```

The slugs are in `EXTRACTION-SUMMARY.md`. I have deliberately written no instructions for the screen itself: whether you can complete the review without them is the test.

What I need back, for this report:

1. How long the review took.
2. Which fields you edited (the app has them: once you have completed the review I can list them from the approvals, so "done" is enough).
3. Anything that made you stop and wonder what to do.

Stage 3 stops here. After your review I will add the time and the edited fields to this report; then: `Run Stage 4 of docs/MASTER-PROMPT.md.`
