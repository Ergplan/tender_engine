# Stage 3 report: reviewer UI and review tokens

Date: 2026-10-05. Diff: `git diff stage-3-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` ("Cost of extraction", "Review tokens and what a request may reach", "The reviewer's view of a tender", "Reviewer screen", "What changed this stage"). Artifacts: `docs/reports/stage-3-artifacts/`.

**The stage is built and deployed. One check of the definition of done is yours: completing one real review from a link, unaided.** How to get the link and what I need back from you are in the last section.

## Definition of done (master prompt, row 3)

| Check | Result |
| --- | --- |
| Playwright suite green | Yes. `make test-ui`: 10 of 10 pass (5 when this report was first written) (`web/e2e/review.spec.ts`), in Chromium at 1366x768 against a seeded stack behind the same proxy routes as the deployed app. Output: `stage-3-artifacts/playwright.txt` |
| User completes one real review from a token URL unaided | **Open: this is your step** |
| First PDF page under 3 s on the VM | Yes, on a quiet VM. `web/e2e/real-load.spec.ts` on the deployed app, Chromium on the VM, nothing cached in the browser: SECI Ramagiri (91 fields, 10 documents, first document 266 pages) first meaningful paint 1.0 s, first PDF page 1.3 s (`stage-3-artifacts/real-tender-load.txt`). Earlier runs of the same test, whose output I did not keep, gave 1.4 s and 1.7 s for SECI Gaya (first document 305 pages), and, while the test watcher was running the full suite on the two cores, up to 4.8 s and 6.2 s. The selectable text layer of the first page arrives later, 3.7 s after the start on the quiet VM. The largest document of the set has 373 pages; none has 400. Not measured from a reviewer's own connection |
| No bulk-approve exists | Yes. The screen has Approve, Edit, Not in document and Flag per field and nothing else; the API has no route that decides more than one field (`POST /approvals` takes one candidate). Both the unit test and the browser test assert that no "approve all" exists |
| `make trace` is clean and every schema field has a complete FIELD-TRACE row | Yes (`stage-3-artifacts/trace.txt`). `docs/FIELD-TRACE.md` has 183 rows (163 before the structured fields, which add 20 paths because a field of a type counts once per type), one per field path of the nine tender types; the watcher's `field_trace` check regenerates it and fails on a difference or on a field without a UI component, route or column |
| `make test` green | 487 Python tests and 68 web unit tests pass; the nine checks are green (`stage-3-artifacts/checks.txt`). The Tests section below gives the counts of the first report, 404 and 37 |
| `make deploy` serves the app | Yes, see "Deployment" |

## Before the UI: cost of extraction

### What was built

- **Shared page windows as a cached prefix.** Sections of one run are read from one shared window when that is cheaper by arithmetic on page counts (`core/services/extract_plan.py`). The window's PDF is sent with a cache mark, the system prompt is the text all section prompts inherit, and the section's own prompt text follows the PDF. The caching changes no prompt file.
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
- **The watcher was stopped** for most of the build and during the load measurements (the VM still has 2 cores); commits made while it was stopped were preceded by a full `make check`. It was started again at the end of the stage.

## Tests

- **Python: 404 pass.** New: the window plan (10), the LLM client's cost, cache layout, replay and batch (4), extraction with shared windows and batches (9), tokens, scoping, the reviewer's view, completion, viewer endpoints, request audit and the link command through HTTP (12), flag and stale decisions, the fact guard under a flag, FIELD-TRACE (5), the cost plan.
- **Web unit: 37 pass** (formatting, keys, the screen with a fake API, the summary, the link).
- **Browser: 5 pass**: a replaced link and a wrong link; the layout at 1366x768 without sideways scroll and the load times; an evidence chip scrolling the PDF and highlighting, the amendment's document, search; approve with Enter, edit a date, not in document, flag, and the same after a reload; complete by keyboard and the snapshot endpoint returning the final values, then read-only.
- **End-to-end with the real model** (`tests/e2e/test_review_flow.py`, run once, `stage-3-artifacts/e2e-real-model.txt`): the 3-page NTPC notice extracted through the batch API (waves of 1 and 9 calls, 77% of input read from the cache, USD 0.57, 299 s in that first run; the artifact now holds the rerun made after review run 7: USD 0.65, 334 s), 31 of 31 values with located evidence, then reviewed and completed through a review link, with the snapshot holding the tender number and its evidence. The Stage 1 and Stage 2 real-model tests were not rerun.
- **Evidence resolver corpus: 218 of 220** (`make evidence-corpus`, `stage-3-artifacts/evidence-corpus.txt`), unchanged. The two known failures are `real-0080` (a watermark through a heading) and `real-0142` (a wrapped table cell without a number).

Two defects the browser tests found that the unit tests had not: the browser cached a 410 answer and showed it for the next link (every API answer is now `no-store`), and an effect returned the promise Chrome gives from `scrollIntoView`, which blanked the page when the edit form opened (fixed; the screen now also has an error boundary that says to reload).

## The two numbers

From `EXTRACTION-SUMMARY.md` as regenerated after the last re-run (schema `v2`, prompts `v3` for commercial and penalties; 13 tenders, 25 versions, 51 documents): **evidence-location rate 99.8%** (875 of 877 values; the two misses are the same two as in Stage 2, in SECI FDRE-RTC-V Amendment-01); **answer rate 70%** (877 of 1248 fields). 12 fields are flagged for review by validation. Before the structured fields the same file gave 804 of 806 located, 806 of 1146 fields with a value and 7 flagged; with the structured fields and before the prompts were tightened, 874 of 876, 876 of 1248 and 18 flagged. These are candidates; no accuracy number exists until reviews are completed.

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

**Run 3** (after those fixes): (a) 1, (b) none, (c) 1, (d) none, (e) 9. No new code defect.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | Invariants and audit of the unchanged write paths cannot be certified from the diff | As in runs 1 and 2: not resolvable by code |
| e8 | The deployment artifact showed migration 0008 while the report says 0009 | Artifact regenerated after the last change: `deployment.txt` now shows 0009, the review links by tender and reviewer, and the count of located spans without a box (e5) |
| e1 to e7, e9 | That no other API route decides several fields, the load times not kept, the count of shared calls, the earlier PDF bytes, the record-list parser in unchanged code, the watcher's history, the live link | Statements of this report that a diff cannot prove; they do not block the stage under rule 15 |

I stopped after three runs: the last found no code defect.

## Open questions

1. **Your review.** See below.
2. **Published notices on a fresh extraction.** A full extraction reads a notice page for every section its role allows, and where the notice is attached to a later version its short wording becomes the current entry of identity fields (seen on seci-cni-1-700mw). Restricting the role `nit` to key dates would be a schema change, and the `v1` schemas are frozen. Do you want a `v2` that reads notices for key dates only, or leave it for the reviewer to set aside?
3. **Batch as the default for the command.** Extraction by `ingest_tenders extract` now goes through the batch API. It took minutes here; the provider allows itself up to an hour, and longer on a bad day. Keep it as the default for Stage 4's corpus runs?
4. **The generic answer schema on shared windows.** It is what makes the cache work, and its answers are checked against the typed model afterwards. If you would rather keep provider-enforced typed output everywhere, `EXTRACT_SHARE_WINDOWS=false` turns sharing off; the cost is the cache saving on short documents.
5. **VM size.** Still 2 cores and 3.9 GB. The resize commands are in the Stage 2 report.
6. **A guard for the Stage 4 dashboard** (`/admin/reliability`) is needed before it is built: an admin token is the smallest change.

## After the first look at the screens (2026-10-05)

You looked at the screens before reviewing and asked for eight changes, plus a ninth on the confidence figure. All are built, tested and live. No decision had been made in the database, so nothing reviewed was touched.

| # | Asked | Done |
| --- | --- | --- |
| 1 | Dark text on a dark surface in the edit panel; a browser test of the contrast | Cause: pdf.js's viewer stylesheet, imported for the text layer, declared `color-scheme: light dark` for the whole page, so a dark system theme gave inputs a dark surface under the screen's dark text. The screen now declares one light design, gives inputs their own surface and text colour, and includes only the text-layer rules. Two browser tests (light and dark system theme) compute the contrast of the edit textarea, the evidence boxes, the note, a date input, the flag note, the search box, the document selector and a field value, and require 7:1. I ran the dark-theme test once against the old stylesheet to see that it catches the fault: it failed at 1.59:1 (that run is not kept) |
| 2 | Orientation panel, collapsible, open on first visit and remembered; `docs/REVIEWER-GUIDE.md` | `GuidePanel` under the header: what the review is for, how to decide, what the confidence figure means, the keys. `docs/REVIEWER-GUIDE.md` has the same text, with three more paragraphs on numbered evidence, amended fields and completing; a unit test fails if the guide lacks a sentence of the panel |
| 3 | Wider summary, a short paragraph per topic with evidence per sentence, re-run for all 13 | Prompt `summary/v2` asks for eight paragraphs under fixed headings, each sentence ending in the number of its quote; a sentence that only says a topic is not on the pages carries none. Nothing checks the markers by rule (KNOWN-GAPS.md). 15 summaries written (13 tenders; SECI CfD-I has a revised RfS, NTPC PHES two notice documents), each with eight paragraphs; 453 of 454 quotes located (`stage-3-artifacts/summaries.txt`). The one unlocated quote is in NTPC Hybrid-03, whose summary is therefore marked for review. See below for the cost and the limit |
| 4 | Label the confidence figure; hover text | Caption "model confidence" beside the figure. Hover: it is the model's own confidence, not a measure of correctness; a low figure often means an ambiguous or partial statement; the tender-number example; read the rationale first. The same four sentences are in the panel and the guide |
| 5 | Numbered chips tied to sentences; only the active passage highlighted | Chips of a field with several quotes are numbered. In the summary each sentence ends in a small numbered button that opens its quote. In other fields the focused card lists the words each chip quotes. In the PDF the passage being shown is highlighted and the field's other passages are drawn faintly |
| 6 | Rationale cut off with no way to expand | Shown in full for the focused field; a "more" link on every other card |
| 7 | Section headers show where attention is needed | "3 need a closer look": undecided fields that a validation rule flagged or whose confidence is under 0.5. Your own flags are counted beside it |
| 8 | Fields left or time left in the header | "89 to go" under the progress; after five decisions in a sitting, "about N min left" at your own pace (the median gap between decisions, so a pause does not stretch it) |

**The summary, as written for NHPC FDRE-II** (the tender your link opens): eight paragraphs, 38 quotes, all located. It reads at most 40 pages in one call. Where a topic sits outside those pages it says so: for NHPC it reports that the qualifying thresholds and the EMD formula are in clauses "not on these pages", and gives what the pages do state. The eligibility and guarantee fields themselves are extracted from their own pages and are not affected. If the summary proves too thin in review, the next step is to write it from the extracted fields and their quotes (KNOWN-GAPS.md).

**Changes this needed below the screen** (DECISIONS.md): a section can pin its own prompt version and page cap; `evidence_span.ordinal` (migration 0010) keeps each quote's place; the summary is written from the base documents and not from a notice attached beside or after them; the output limit of a call is 20,000 tokens (one summary hit 16,000 in its batch and succeeded on the direct retry). The summary section's keywords, help text and page cap were edited in the `v1` schema file: the one edit to a frozen file, made on your instruction before any review exists.

**Cost of the summary re-run:** USD 10.44 for 16 calls (15 summaries and the one that was cut off), through the batch API. It is more than "one cheap call per tender" suggests: each call reads 25 to 40 pages and writes a long answer with its quotes. Stage 3 is now at about USD 30 and the running total at about USD 290.

**Independent review, run 4** (on these changes): (a) 1, (b) none, (c) 1, (d) none, (e) 14; no code defect. (a) and (c) are the same as in runs 1 to 3 (unchanged write paths cannot be certified from a diff). Of (e): the deployment artifact was stale and is regenerated (`deployment.txt`: migration 0010, no decision in the database); the test totals in the table at the top are now the current ones; "the prompt files are unchanged" now says what it meant; the results of the summary re-run are an artifact (`summaries.txt`). The rest are statements of this report that a diff cannot prove. Output: `stage-3-artifacts/review-gpt-6.1-sol-run4.txt`.

**Checks after these changes:** 410 Python tests and 53 web unit tests pass; the browser suite has 9 tests, all passing (`stage-3-artifacts/playwright.txt`); the nine checks are green (`checks.txt`).

## The summary written from the record (2026-10-05, second change)

After the eight changes you asked for the summary to be written from the extracted fields instead of from a 40-page window. That is built, tested, deployed and has run on all 13 tenders.

**Result** (`stage-3-artifacts/summaries.txt`): 13 summaries, one per tender, each with eight paragraphs, all validated. Each carries between 34 and 128 passages inherited from its fields (1,179 in all), every one located, since they are copies of passages that were located when the fields were extracted. No summary named a source that does not exist. For the amended tenders the summary belongs to the latest version its fields come from and draws on up to seven documents. Cost: USD 3.56 for 14 calls (NHPC was written twice), under 10,000 input tokens per call and no pages; a call takes about 40 seconds. The first two attempts were refused because the model account had run out of credit; they stored nothing, and the summaries were written after you refilled it.

**NHPC FDRE-II**, the tender your link opens: the summary now gives the bid dates, the net worth, turnover and liquidity thresholds, and the EMD and PBG amounts, each with the number of the field it comes from. This morning's page-read summary said those were "not on these pages".

Two things I adjusted after reading the first real summary:

- Amounts are also given to the model the way tenders write them, so the text reads "INR 13000000 (INR 1.3 crore) per MW".
- A summary with more than twelve passages kept its chips behind a toggle. (Replaced later the same day: the summary card has no chips at all, see "Three changes to the summary card".)

One thing you will notice: a sentence that rests on a field with several quotes carries all of them, so some sentences end in six or eight numbers. That is what inheriting the field's evidence means, and I have kept it. If it is too heavy to read, the alternative is one number per field (its first quote); say so.

How it works (ARCHITECTURE.md, "The summary: a second pass over the record"):

- When the last extraction run of a tender is validated, the worker queues the summary. It is also available on request (`POST /tenders/{id}/summarize`, `ingest_tenders summarize`).
- The model gets the record as a list of sources: every field that has a value with located evidence (the current value: an amendment's where it changes the field, the reviewer's where they have decided), each with an id. It returns eight paragraphs and, for every sentence, the ids it rests on. No document is attached.
- Code, not the model, writes the numbers after the sentences and copies the fields' evidence onto the summary. A number in the summary opens the same passage as the chip of the field it comes from. Nothing is located anew.
- A topic the record does not hold says so, in a sentence without a number.
- The page-read summary (`summary/v2`) is still made during extraction and feeds only the first three topics (what is procured, buyer and offtaker, location), which no single field holds.
- The summary is stored as a candidate like any other, in a run marked `record`, and replaces the earlier summaries of the tender in review. If the call fails nothing is stored and the earlier summary stays.

Tested on the synthetic tender with a scripted model (`tests/tender/test_summary.py`, 10 tests; the API and browser suites): the summary's evidence spans are copies of the fields' spans; after an amendment the summary is written again and the deadline's number opens the amendment; a record that has not changed is not summarised twice; a reviewer's edit is what the summary reads.

Three things to know:

1. **The summary was not rewritten when you decided a field.** (Changed later the same day: it is now decided after the fields and written again from your decisions, see "Three changes to the summary card".)
2. **A field without located evidence is left out of the summary** (it has no evidence to pass on). It is still flagged as a field.
3. **Whether a sentence says what its field says is not checked by code**, only that its number is a real field's evidence. That check is the review of the summary card.

Checks after this change: 422 Python tests, 54 web unit tests and 9 browser tests pass; the nine checks are green (`checks.txt`, `playwright.txt`). Stage 3 is now at about USD 34 and the running total at about USD 294.

**Independent review, run 5** (on this change): (a) 2, (b) none, (c) 1, (d) none, (e) 15. One code defect, fixed: where a reviewer had edited a field and given their own evidence, the summary took the corrected value but the model's original quote; it now inherits the reviewer's evidence, and a field the model could not evidence joins the summary once a reviewer has (`test_a_field_the_reviewer_corrected_brings_the_reviewers_evidence_to_the_summary`). Three report statements corrected against the artifacts (fields failing validation, input tokens per call, which version a summary belongs to). The rest are the unchanged write paths a diff cannot certify and statements of this report. Output: `stage-3-artifacts/review-gpt-6.1-sol-run5.txt`.

**Run 6** (after that fix): (a) 1, (b) none, (c) 1, (d) none, (e) 14. No code defect: (a) and (c) are again the unchanged write paths, (e) statements a diff cannot prove. I stopped here. Output: `stage-3-artifacts/review-gpt-6.1-sol-run6.txt`.

## Three changes to the summary card (2026-10-05, third change)

1. **The note is on top.** What the summary leaves out is shown above the text ("Note on this summary: Change in law, GNA details, the ISTS waiver cut-off of 30 June 2028 and capacity addition flexibility were left out for brevity...", for NHPC FDRE-II).
2. **No citation list on the card.** The list of which number is which field is gone from the card and kept in the stored record. Pointing at a number shows the field it comes from and the words it quotes; clicking it opens the passage and spells the same out under the text ("71 · Consortium allowed · p. 23: ..."). The chips of the summary are gone too: the numbers are the way in. For this each inherited passage now stores the label of its field, so the 13 summaries were written once more (USD 3.15); all 13 are validated, with every passage located and labelled.
3. **The summary cannot be approved before its fields.** I built both of the ways you offered, as one rule:
   - The summary's Approve, Edit and Not in document stay off until every other field has a decision; the card says how many are left. It can be flagged at any time. The API refuses the same decisions, so the rule does not depend on the screen.
   - If your decisions changed the record (an edit, a field marked not in document), the summary is written again from them as soon as the last other field is decided. That takes about a minute; the card says so, looks for the new text by itself and then offers it. The old text cannot be approved in the meantime.
   - If you change a field after approving the summary, that approval is withdrawn (the summary is flagged in your name with the reason) and it is written again.
   - Approving fields as they stand changes nothing in the record, so a review without corrections has no rewrite and no wait.

**One consequence you should know before the timed review:** the summary is a required field, so Complete review now needs every field that has a candidate to be decided, not only the required ones. A field left flagged keeps the summary locked. For NHPC FDRE-II that is 88 fields and then the summary.

Also changed: values reach the summary model as an approval would store them, with dates in words ("12 April 2024") and amounts also in lakh and crore.

**Independent review, run 7** (on this change): (a) 1, (b) none, (c) 1, (d) none, (e) 18. One code defect, in a test: the real-model end-to-end test still decided the summary before the other fields, which the new rule refuses. It now runs the worker as deployed (with the second pass), checks that the summary is refused early, decides every other field and then the summary; it was run again with the real model (`e2e-real-model.txt`). Two earlier paragraphs of this report that the third change had made untrue are marked as replaced. The rest are the unchanged write paths and statements a diff cannot prove. Output: `stage-3-artifacts/review-gpt-6.1-sol-run7.txt`.

Checks: 427 Python tests, 57 web unit tests and 9 browser tests pass (`checks.txt`, `playwright.txt`). The browser suite now runs a whole review in which a corrected deadline makes the summary be written again before it is approved. Stage 3 is at about USD 37 and the running total at about USD 297. The test watcher is stopped, as you asked, so that your timing is not disturbed.

## Structured fields for the financial model (2026-10-05, fourth change)

The record is to feed a financial model, and a model computes with numbers. Prose fields that hold numbers therefore got typed siblings, before any review, so that the gold set covers them. The database held no decision when this was done and holds none now (`stage-3-artifacts/deployment.txt`). The design of the projection that will turn approved facts into model inputs is in ARCHITECTURE.md ("Model input profile"); it is designed, not built.

**Built** (ARCHITECTURE.md, "Structured siblings"; DECISIONS.md):

- 15 structured fields and one retyped list, in schema `v2`. Six are in every tender type (EMD, PBG, payment security, delay LD, shortfall rules, deemed generation); the rest belong to a type (FDRE demand profile and excess energy; CUF terms and excess energy for solar, wind and hybrid; two each for BESS, EPC and transmission, whose `elements` now carry kV and route km as numbers).
- A structured field is extracted in the same call as its prose parent, with its own quotes. Nothing is derived from the prose by a model.
- The model writes a record as `key: value` lines and code types them, so the answer schema is the same for every field and the cached prefix of a shared window survives.
- `v2` adds fields and retypes one list (transmission `elements`, whose kV and route km became numbers). It is registered as also reading `v1`, so sections that did not gain a field were not read again. The section that holds the retyped list was read again on the one transmission tender, and its `v1` candidates are superseded (`stage-3-artifacts/structured-fields.txt`, table 8). Nothing checks that a version declared as readable is compatible with the earlier one; the declaration in the pack is trusted (KNOWN-GAPS.md).
- On the screen a record is a card of labelled values with units, every key shown, "not stated" where the document is silent. A list of records shows, per item, the keys that item states. An edit of a record has one input per key; a list is edited as text lines.
- Two checks that call no model, and `ingest_tenders revalidate` to run them again on finished runs.

### Cost of the v2 pass

Only the ten sections that gained a field were read again, on all 13 tenders: 44 extraction runs (NHPC FDRE-II directly, the other 43 through the batch API), 133 model calls, 6.02 million uncached input tokens plus 0.44 million read from the cache, and 0.54 million output tokens.

| Section read again (prompt `v2`) | Calls | USD |
| --- | --- | --- |
| commercial | 39 | 13.84 |
| guarantees | 31 | 9.88 |
| penalties | 29 | 8.08 |
| epc_scope | 13 | 7.21 |
| fdre_profile | 12 | 5.55 |
| tbcb_elements | 2 | 1.01 |
| bess_performance | 2 | 0.71 |
| wind_tech | 3 | 0.61 |
| hybrid_mix | 1 | 0.43 |
| solar_tech | 1 | 0.33 |
| **Reading the sections again** | **133** | **47.65** |
| Summaries written again after the pass (26 calls; written from an incomplete record, see "A defect found while finishing") | 26 | 5.78 |
| Summaries written once more from the complete record | 13 | 3.47 |
| **The v2 pass in all** | **172** | **56.90** |

From `llm_call_log.cost_usd` at the configured prices, not the provider's invoice; the query results behind this table and the ones below are kept in `stage-3-artifacts/structured-fields.txt`. USD 5.78 of it bought nothing: those summaries were replaced. Stage 3 is now at about USD 94 and the running total at about USD 354.

### What came back

The 13 tenders have 102 structured fields between them: 73 have a value and 29 are not stated in the documents read. A section can be read in more than one window, and an amended tender in more than one document, so those fields have 246 candidates (counting the two for the transmission `elements` list that was retyped): 117 with a value, every one with located evidence, and 129 that say not stated. The two checks below run per candidate. NHPC FDRE-II, the tender your link opens, has 8 structured fields, all with a value.

### Violation counts of the two checks

These are the counts of the first v2 pass. The quote check's nine failures were then removed at the source; the counts as they stand now are in "The quote rule and the version check" below.

Both run on every structured value, cost nothing, and never drop a value: a failure marks the candidate `needs_review` with the key named, and the reviewer decides.

| Check | What it requires | Candidates checked | Failed |
| --- | --- | --- | --- |
| `structured_numbers_quoted` | Every number of a structured value is printed in that candidate's own quotes | 117 | **9** |
| `structured_agrees_with_scalar` (all types) and `power_structured_agrees_with_scalar` | A key and the scalar field holding the same fact are equal; one stated without the other fails too | 50 (15 and 35) | **3** (1 and 2) |

The 12 failures are 12 different candidates in 8 tenders.

Numbers not printed in the quotes (9):

- **5 times `compensation_pct_of_tariff: 100`** in deemed generation (NHPC FDRE-II, SECI CnI-1, SECI FDRE-IX, SECI FDRE-RTC-V, SECI Wind Tranche-XX). The documents say compensation is at the tariff; none prints "100". The value is an inference, and the check is right to hold it for a person.
- **3 times `threshold_pct: 90`** in the first shortfall rule (SECI CfD-I once, SECI FDRE-IX twice, once for each of the two candidates of that field). The 90 is not in the passages quoted for the rule.
- **Once `penalty_multiple_of_tariff: 1.5`** (NTPC Hybrid-03).

A key and its scalar disagree (3), all of the kind "the scalar is stated, the key is not":

- SECI CfD-I and SECI FDRE-IX: `assured_availability_percent` is 90, but `peak_availability_pct` of the demand profile is not stated.
- SECI Ramagiri: `delay_ld_per_mw_per_day_inr` is 20250, but `rate_inr_per_mw_per_day` of the delay LD record is not stated.

What the first check cannot see is in KNOWN-GAPS.md: it compares numbers, not meaning, so "10 Crores" satisfies a 10 anywhere in the quotes.

One thing you will notice on NHPC FDRE-II: the FDRE section is read in two windows, and the two answers for excess energy differ (above the maximum CUF at the PPA tariff, against above contracted capacity and not purchased). The card shows the better-evidenced one. (Corrected after review run 9: I had written that the card says there is an alternative. It does not; the count of other answers is in the API's answer and is not drawn on the card. See the open question at the end of the next section.) Which of the two is right is a question for the review, not something a check decides.

### A defect found while finishing

The session that built this stopped before its checks were green. Finishing it, I found three things. The first is the one that matters.

1. **After the v2 pass the review showed only the fields that had been read again.** `v2` is registered as also reading `v1`, but the review state still kept only runs whose schema version equalled the newest run's. With a `v2` run as the newest, every field of a section that was not read again (identity, key dates, eligibility, connectivity, documents) lost its candidate: NHPC FDRE-II showed 37 values instead of 82, and the regenerated summary file 365 values instead of 876. Nothing was lost in the database; the candidates were there and validated. It was live on your review link for about eighty minutes, from about 15:36 UTC, when NHPC's `v2` run was validated, until the correction at 16:55 UTC (the times are in `structured-fields.txt`, table 10). No decision was made in that time. The counts of 37 and 365 are from the summary file as I first regenerated it; that version of the file was replaced and is not kept.
   - Fixed in `core/services/review_state.py`: runs of every version registered with the same content are read together (`SchemaRegistry.versions_read_as`). A version that changes or removes a field has other content and is still read on its own.
   - Two tests, the first of which failed before the fix: `test_runs_of_an_earlier_schema_version_are_read_under_a_later_one_that_only_adds` and `test_runs_of_a_schema_version_with_other_fields_are_not_mixed_in`.
   - The summary is written from the record through the same code, so the 13 summaries written after the pass had lost those fields too (NHPC's no longer mentioned net worth, turnover or the pre-bid date). All 13 are written again from the complete record, validated, every passage located (`stage-3-artifacts/summaries.txt`).
2. **A record a reviewer had edited was not shown.** A scalar edit is told in the decision line ("Edited to ..."); a record cannot be, and the card went on drawing the extracted record. The new browser test caught it. The card now draws the reviewer's record once a record field is edited (`shownValue` in `web/src/review/FieldCard.tsx`, two unit tests).
3. **One stale assertion**: the extraction-summary test expected 9 values in the markdown row where the fixture now gives 10 (its data assertion had already been updated). The over-length line in `scripts/ingest_tenders.py` was already fixed in the working tree.

### Checks

458 Python tests, 65 web unit tests and 10 browser tests pass; the nine checks are green (`checks.txt`, `playwright.txt`). The browser suite has one new test: a structured field shows every key, says what is not stated, is edited key by key, and holds the edit after a reload. The layout test prints a load time: in the two runs made for this change the first meaningful paint was 5.7 s and 6.0 s and the first PDF page 6.3 s and 6.5 s against 2.2 s and 2.8 s in the run kept before (`playwright.txt` holds the last run of the stage: 4.8 s and 5.0 s); it is printed, not asserted, on a seeded stack that had just been started on the two cores, and the real-tender load test was not run again.

Deployment: no migration (`alembic_version` is still `0011`); the API reloads from the mounted source and the worker was restarted after the fix (`stage-3-artifacts/deployment.txt`). The test watcher is still stopped.

### What this changes for your review

- The link for NHPC FDRE-II is the same and still valid. The tender now has 97 fields (89 before): 82 with a value, 2 flagged by validation (1 after the re-run described in the next section).
- 8 of them are structured cards. Read them as you would any field: each has its own quotes. A key shown as "not stated" is a claim that the document is silent, and worth a glance at the prose field beside it.
- The summary is the one written from the complete record (at 17:00 UTC, and once more after the re-run described in the next section).

**Independent review, run 8** (on this change): (a) 1, (b) none, (c) 1, (d) none, (e) 20. No code defect. Output: `stage-3-artifacts/review-gpt-6.1-sol-run8.txt`.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | Invariants and audit of the unchanged write paths cannot be certified from the diff | As in runs 1 to 7: not resolvable by code |
| e17 | "`v2` only adds fields" is not exact: the transmission `elements` list is retyped, and the `v1` registration is replaced by the `v2` content without a check that the two are compatible | Report, DECISIONS.md and ARCHITECTURE.md corrected to what was done. In the data no harm follows: the two `v1` candidates of that list are superseded and the live ones come from the `v2` run (`structured-fields.txt`, table 8). That no check exists is in KNOWN-GAPS.md; whether to build one is a decision for you (see below) |
| e18 | The totals of the v2 pass and the populations of the two checks had no retained query result | `structured-fields.txt` now holds the queries: runs, calls and cost by prompt, fields and candidates, the results of both checks and every failure |
| e19 | The chronology of the defect is not provable: the 37 and 365 values, the length of the exposure, the failing run of the new test, that the browser test found the record defect | The times are now in the artifact and the report says which numbers are not kept. The rest are statements of this report |
| e20 | The two load measurements did not match the artifact | Report corrected: it had mixed the paint and the PDF times |
| e1 to e16 | Earlier statements of this report: historical test totals, deployments, load times not kept, costs outside the call log, your instructions, the first page-read summaries, what a prompt asks for but no rule enforces | As in earlier runs: statements a diff cannot prove, or limits already listed in KNOWN-GAPS.md. They do not block the stage under rule 15 |

I stopped after this run: it found no code defect, and the changes after it are to the report, two documents and one artifact.

**One decision for you** (decided the same day: you asked for the check, and it is built, see the next section). `reads_versions` lets a new schema version read the runs of an earlier one. It is safe only when the new version leaves every earlier field as it was, or when a changed field's section is read again, as was done here. Today that is a rule people follow, not one the code checks. A check is possible (keep each released version's field definitions, and refuse `reads_versions` when a field differs unless it is named as read again). Say if you want it built before Stage 4.

## The quote rule and the version check (2026-10-05, fifth change; Stage 3 close)

You asked for two things before the timed review: the compatibility check on schema versions, and the quote-check failures fixed at the source instead of being left to reviewers. Both are done. The three cases where a scalar is stated and its structured key is not remain for the reviewer, as you decided.

### A structured number must be printed in the field's own quotes

**New violation count: 0 of 116** for `structured_numbers_quoted`, on the candidates now in review (`stage-3-artifacts/structured-fields.txt`, tables 12 to 14). It was 9 of 117. The agreement checks stand at 3 of 42, the same three as before.

| Check | Before (prompts `v2`) | Now (prompts `v3` for commercial and penalties) |
| --- | --- | --- |
| `structured_numbers_quoted` | 9 failed of 117 | **0 failed of 116** |
| `structured_agrees_with_scalar` and `power_structured_agrees_with_scalar` | 3 failed of 50 | 3 failed of 42, the same three, kept for the reviewer |

The counts are per candidate. The denominators moved because the two sections were read again and windows returned a slightly different number of candidates; at field level nothing moved: 73 of the 102 structured fields have a value, as before.

What caused the nine, read from their quotes:

- **Five times 100 for deemed generation.** The documents give a formula ("Tariff x RE power (MW) offered but not scheduled by Procurer x 1000 x hours"). None prints 100. The `v2` prompt itself told the model to write 100 "when compensation is at the full tariff". That instruction was mine and it was wrong.
- **Three times a threshold of 90.** The documents print the permitted shortfall ("permissible up to 10% below the energy requirement"). The model subtracted it from 100.
- **Once 1.5** at NTPC Hybrid-03, where the document says "one and half times of the PPA tariff". That is a number the document states, in words; the check read "one and a half" but not "one and half".

What changed:

- **Prompts `extract/commercial` and `extract/penalties`, version `v3`.** A number is given only if the document prints it in a passage quoted for that same field, in figures or written out as a number. Nothing is computed: no subtracting from 100, no turning one figure into another. Wording that is not a number ("at the tariff", "in full", "the entire amount") never becomes one: the key that takes a fixed choice is used, or the numeric key is left out, and the prose field keeps the wording. Before answering, the model checks every number against the quotes of that field. Two older lines that broke this rule are gone: 100 for "at the tariff", and a letter of credit of 1 month for "average monthly billing" with no number printed.
- **One key added** to `deemed_generation_structured`: `compensation_basis`, a fixed choice of `full_tariff`, `percent_of_tariff`, `fixed_rate` or `other`. `compensation_pct_of_tariff` is now given only where a percentage is printed. This was the last change to `v2`, made before any review; `v2` is released and frozen since (below).
- **The check** now also reads "one and half times" as 1.5 (`tender/domain_packs/core/structured.py`, one test case).
- **Unit conversions stay**, and the prompt names them: lakh and crore to rupees, paise to rupees, a printed percentage of the tariff to a multiple (50% is 0.5). The number is the document's; only its unit changes.

How the same fields read now (`structured-fields.txt`, tables 16 and 17):

- Deemed generation on NHPC FDRE-II, SECI CnI-1, SECI FDRE-IX, SECI FDRE-RTC-V and SECI Wind Tranche-XX: `compensation_basis: full_tariff`, no percentage. On SECI ESS-IV the percentage 100 is given, with `percent_of_tariff`, and passes the check: there the document prints it.
- SECI FDRE-IX shortfall rules: `tolerance_pct: 10`, no threshold. SECI CfD-I keeps a threshold of 90 in two rules and passes: the quotes now given print it.
- NTPC Hybrid-03: 1.5, read from "one and half times".
- NHPC FDRE-II: `lc_months_of_billing` is no longer given. The PPA says "average monthly billing" and prints no number of months; the prose field says so.

One judgement of mine to confirm: a number written out in words ("one and a half times", "24 (twenty-four) months") counts as printed, and a printed percentage may be given as a multiple. If you want figures only, or no conversion of a percentage, say so; it is one sentence in each prompt and one branch in the check.

**The re-run.** Both sections were read again on all 13 tenders: 34 extraction runs (one for NHPC FDRE-II directly first, to see the prompts work, then 33 for the other twelve through the batch API), 68 model calls, followed by 13 summary runs (`structured-fields.txt`, table 21).

| Item | Calls | USD |
| --- | --- | --- |
| commercial, prompt `v3` | 39 | 14.51 |
| penalties, prompt `v3` | 29 | 8.88 |
| Summaries written again by the worker, since the records changed | 13 | 3.67 |
| **The re-run in all** | **81** | **27.04** |

From `llm_call_log.cost_usd` (`structured-fields.txt`, table 11). Unlike the v2 pass, no input was read from the cache in the batch: the two sections' calls did not share a cached prefix this time, and I have not found out why. It cost roughly what the same two sections cost in the v2 pass (USD 21.92), so the cache had saved little there either. Stage 3 is now at about USD 121 and the running total at about USD 381.

Only these two sections were read again. The other eight `v2` prompts carry the older wording of the rule ("never compute a number the document does not print"). They had no failure of the quote check, so I left them and did not pay to read them again. If a later tender fails the check in one of those sections, the same paragraph goes into that prompt.

### Compatibility of schema versions is checked when the packs load

Built as you specified (`verify_versions` in `tender/services/packs.py`; ARCHITECTURE.md, "Compatibility of versions"). The API, the worker, every command and the test suite load the packs, so a fault stops all of them.

- Each released version has a file, `tender/domain_packs/power/released/<version>.yaml`: per tender type, every field with its type, unit, allowed values and record keys. `scripts/release_schema.py` writes it. `v1` was written from the pack files of the last `v1` commit (`fbbd991`), `v2` from the current ones.
- A version that says it reads an earlier one is compared with that file, field by field, for all nine types. **A field of the earlier version that is missing fails the load**, naming the field: its candidates would be orphaned. A field defined differently also fails, unless the pack lists it under `read_again`.
- A field under `read_again` is not read from runs of the earlier version at all: the review state leaves those candidates out. `v2` lists the one field it changed, `sector.power.transmission.elements`. Before this, that the old candidates of that list were not read depended on their having been superseded; now it does not.
- A released version is frozen: the loader refuses it if a field has been added, removed or changed since its file was written.
- Also refused: reading a version that has no released file, listing a field that did not change, listing a version that is not read.

Tests (`tests/tender/test_pack_versions.py`, 18, and one in `tests/core/services/test_review_state.py`): a removed field fails the load; each kind of change (type, unit, allowed values, item keys, record keys) fails unless declared; every field at fault is named in one message; a label or help text may change; a released version is frozen; the real power pack reads `v1` with exactly one declared change and would not load without the declaration; every `v1` field of every type is still present; a field the later version changed is not read from the earlier version's run.

What it cannot see is in KNOWN-GAPS.md: it compares definitions, not meaning. A field whose help text gives it another meaning while its type stays the same passes.

### A defect the browser suite caught after this change

After the version check went in, the last browser test failed: at the end of a full review the summary's Approve stayed disabled. Two things were stacked.

1. **The version check made loading the packs slow.** It parsed the two released files again for every tender type. Loading took 5.6 s on an idle machine, the Python suite took 498 s where it had taken 279 s, and in the browser-test stack the worker's first validation after a start took 17 s. Fixed: each released file is parsed once (`_parse_released` in `tender/services/packs.py`). Loading now takes 1.9 s and the suite, with 22 more tests, 301 s in its last run; I did not measure the load time before the version check existed.
2. **That delay exposed a race that was there before.** The worker writes a new summary in one job and validates it in the next. Between the two, the state reported the summary as current although the new text was not yet in review. The screen then stopped looking for it and the card stayed locked. With the scripted model the gap had always been shorter than the screen's first look, so the test had passed; with the real model, where a rewrite takes about 40 seconds, a reviewer who corrected a field could have been left unable to approve the summary without reloading the page. Fixed: the summary is current only once the text written from the record is validated (`SummaryWriter.state`, `_already_written(..., in_review=True)`). `test_a_correction_to_a_field_has_the_summary_written_again_before_it_can_be_approved` now stops between the two jobs and checks the state there; it fails without the fix.

I found the second one only because the first slowed things down. It is the reason I asked you to hold the timed review.

### Checks, deployment, review

481 Python tests, 65 web unit tests and 10 browser tests pass; the nine checks are green (`checks.txt`, `playwright.txt`, both from the last code of the stage); `make trace` regenerates `FIELD-TRACE.md` without a difference (`trace.txt`). No migration; the API and the worker were restarted to load the prompts, the schema and the two fixes (`deployment.txt`). The test watcher is still stopped.

**Decisions in the database: yours, on one field.** At 17:33 and 17:35 UTC, through the review link, `sector.power.fdre.excess_energy_structured` of NHPC FDRE-II was first marked not in document and then edited (above contracted capacity, not purchased). That is the field I had pointed out as having two differing answers. I have not touched those rows. The sections read again afterwards (commercial, penalties) do not hold that field. The summary does not read structured fields, so your edit does not change it; the summary of 17:49 UTC was written because the two sections had been read again. Every earlier statement in this report that the database holds no decision was true when written and is not true now.

**Independent review, run 9** (on this change): (a) 1, (b) none, (c) 1, (d) none, (e) 24. One code defect, in the trace generator. Output: `stage-3-artifacts/review-gpt-6.1-sol-run9.txt`.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | Invariants and audit of the unchanged write paths cannot be certified from the diff | As in every run: not resolvable by code |
| e2 | FIELD-TRACE lists cross-field rules but no run rules, so `structured_numbers_quoted` was missing from the rows of the structured fields | Fixed in code: each pack declares which fields a run rule concerns (`RUN_RULE_FIELDS`), the generator lists them and refuses a run rule that does not say (two tests). All 183 rows now also name `later_version_evidence`; the 20 structured rows name `structured_numbers_quoted` |
| e19 | The card does not say that a field has another answer | Report corrected. The gap is real and is in KNOWN-GAPS.md and the open question below |
| e22 | 47 extraction runs was wrong | Corrected: 34 extraction runs and 13 summary runs (`structured-fields.txt`, table 21) |
| e18 | "Every key shown" does not hold for a list of records | Report corrected |
| e8 | The real-model figures no longer matched their artifact | Report says which run each figure is from |
| e24 | Your two decisions and the time of the summary had no retained evidence | `structured-fields.txt`, tables 20 and 21 |
| e21, e23, e20 | Load times of runs not kept, the timings of the slow load, the failing run of the regression test | The report says which run the artifact holds; the rest are statements of this report |
| e1, e3 to e7, e9 to e17 | Earlier statements of this report | As in earlier runs: statements a diff cannot prove, or limits already in KNOWN-GAPS.md |

**Run 10** (after those fixes): (a) 1, (b) none, (c) 1, (d) none, (e) 19. One code defect. Output: `stage-3-artifacts/review-gpt-6.1-sol-run10.txt`.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | The unchanged write paths | As in every run |
| e19 | In the moment between a rewritten summary being stored and being validated, the summary field has no entry in review, a required field without an entry does not count as undecided, and so the review could be completed without a decided summary | Fixed in code: completion is refused while a summary is being written, and the screen is told it cannot complete (`complete_review(..., summary_being_written=...)`, `get_tender_review`). The test that stops between the two jobs now also tries to complete there and is refused. The moment lasts as long as the worker takes to pick up the validation, a second or two in normal running |
| e1 | Besides the historical point, one approval request can also flag the summary (when a field is decided again after the summary was approved) | True and by design: the request decides one field, and the summary's approval is withdrawn as a consequence, in the reviewer's name, audited. The table at the top says "no route decides more than one field"; read it with this exception |
| e2 to e18 | Earlier statements of this report | As in earlier runs |

**Run 11** (after that fix): (a) 1, (b) none, (c) 1, (d) none, (e) 20. One code defect, small, in code from earlier in the stage. Output: `stage-3-artifacts/review-gpt-6.1-sol-run11.txt`.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | The unchanged write paths | As in every run |
| e20 | A request made with a valid link and then refused (a route the link may not use, another tender, a change after completion) was audited under "api", not under the reviewer's name | Fixed in code: the middleware keeps who asked for the request audit also when it refuses; access is still granted only on admission (`review_identity` in `api/middleware/review_token.py`, one test) |
| e19 | I wrote that the summary of 17:49 was written with your edit in the record; the summary does not read structured fields | Report corrected |
| e1 to e18 | Earlier statements of this report, and by-design behaviour already answered in run 10 | As in earlier runs |

**Run 12** (after that fix): (a) 1, (b) none, (c) 1, (d) none, (e) 20. No code defect. Output: `stage-3-artifacts/review-gpt-6.1-sol-run12.txt`. Two points were new: the token total of the v2 pass had counted cached input as part of the uncached figure (report corrected); and an edit that keeps a field's value and changes only its evidence does not have the summary written again, because the summary's input is the record's values, so the summary keeps the model's passage for that field (a limit, now in KNOWN-GAPS.md; the value the summary states is still right). The rest are as in earlier runs.

I stopped after run 12: it found no code defect. Runs 8 to 12 found four, all fixed: the trace generator's missing run rules, completion across the summary's rewrite gap, the summary counted as current before it was validated, and the request audit of a refused request.

**An open question from this review.** On NHPC FDRE-II, 17 fields have two reviewable answers, one from each of two page windows of the same section (`structured-fields.txt`, table 22). The card draws the better-evidenced one and gives no sign of the other. For 16 of them I have not compared the two answers. For the seventeenth, excess energy, they differ, and you have already decided it. Options: leave it; show "1 other answer" on the card; or show both values side by side. I have not changed the screen before your timed review.

### For the timed review

- The link for NHPC FDRE-II is unchanged. 97 fields, 82 with a value, 1 flagged by validation.
- Its deemed-generation card now reads "Compensation computed at: Full tariff" and shows the percentage as not stated. Its payment-security card shows the size of the letter of credit as not stated; the prose field beside it says "average monthly billing".
- The summary was written again at 17:49 UTC, after the two sections were read again.

## Clear decision, and both readings when they differ (2026-10-06, sixth change)

You asked for two things before the timed review, after a mis-click on NHPC FDRE-II could only be escaped by an edit, which wrote a false correction into the feedback table.

### Clear decision

A decided or flagged card has "Clear decision" (key `U`). It records a decision of kind `cleared`: an approval row like any other, audited (one insert, one supersede of the earlier decision, one supersede of its canonical fact), with no canonical fact and no feedback row. The field is undecided again, counts as such in the progress and in completion, and can be decided afresh. Nothing is deleted: the earlier decision and its feedback row stay as history, which is why KNOWN-GAPS.md now says that the Stage 4 feedback report must count only feedback of active approvals. A stale clear (the field decided again meanwhile) is refused like any other write. Tests: two in `tests/core/services/test_approve.py` (the audit rows, idempotence, nothing to clear, no value taken), one through the link in `tests/api/test_review_tokens.py`, one on the screen, and the browser test of decisions now also clears one.

**Your two decisions of 2026-10-05 are cleared.** I did it through your own review link, with the reason in the note ("cleared at the owner's request before the timed review: the decisions of 17:33 and 17:35 UTC were a mis-click and the edit made to escape it"), so the audit reads like any other decision. NHPC FDRE-II stands at 0 of 97 decided, with no canonical fact current. The two earlier rows and the edit's feedback row remain, superseded.

### Both readings when they differ

The review state now returns, per field, the reading it shows and every other reviewable reading whose value differs from it, typed as it would be stored, so "12.03.2026" and "2026-03-12" count as one reading. Where readings agree nothing is listed and the card is as before. A second reading comes from another page window of the section, or from a later pass over it.

On the card a differing reading is drawn below the value in an amber panel: "The model also read this field differently", its value, its confidence, its evidence chips (which open the passage like any other) and "Use this reading", which approves that candidate. The reading you decide on becomes the field's reading, and the other moves to the panel; clearing the decision puts the best-evidenced one back on top. Tests: three in `tests/core/services/test_review_state.py` (a differing reading is listed with its evidence; an agreeing one is not; the decided reading becomes the field's), one on the screen.

**How often the two differ, across the 13 tenders** (app database, 2026-10-05 23:45 UTC, queries kept in `stage-3-artifacts/second-readings.txt`):

| | Fields |
| --- | --- |
| Fields with a value, in the entries shown for review | 877 |
| of which with a second reading that differs (what the card now shows) | **80 (9.1%)** |

By tender: NHPC FDRE-II 12 of 82, SECI Gaya 12 of 63, SECI FDRE-IX 11 of 84, SECI CnI-1 9 of 76, SECI Wind Tranche-XX 7 of 74, RECPDCL Beed 5 of 54, NTPC PHES 4 of 32, SECI FDRE-RTC-V 4 of 83, SECI ESS-IV 4 of 73, SECI Ramagiri 4 of 65, NTPC Hybrid-03 3 of 73, NTPC Anantapur 3 of 33, SECI CfD-I 2 of 85.

By field: the three lists of the documents section lead (required documents 9, annexure formats 8, draft agreements referenced 7), then the deferred-dates note (4), and six fields at 3 (offtaker, payment security in prose and structured, PBG encashment triggers, shortfall penalty basis and shortfall rules). Lists and long prose differ most often; the two windows see different parts of a long enumeration. A date differs twice (bid submission deadline), an agency once.

Counted in SQL rather than through the review state, by raw text rather than typed value, and taking for each field the latest version with a live valued reading (a close but not identical choice of entries: 869 fields with a value against the review's 877): 114 fields have two or more live readings; 79 differ in their text and 35 are identical. So where a field was read more than once and both readings gave a value, they agreed in roughly one case in three; the card shows the others.

### The screen while a summary is on its way

The browser test of a whole review failed once in five runs since yesterday's fix, each time the same way: the summary's Approve stayed disabled after the rewrite had finished. The server's state was right each time (the kept database shows the new text validated seconds after it was queued); the screen had stopped reading the review. I could not make it fail on demand. Two changes so that a reviewer is never left waiting on a timer: the screen now reads the review again every four seconds for as long as the server reports a text being written, not only while the summary is not current; and the summary card's lock message carries a "Check again" link that reads the review at once (one screen test). Since then the browser suite has passed four times in four runs (`playwright.txt` holds the last).

### Checks and review

487 Python tests, 68 web unit tests and 10 browser tests pass; the nine checks are green (`checks.txt`, `playwright.txt`); `make trace` regenerates `FIELD-TRACE.md` without a difference (`trace.txt`). No migration: `cleared` is a value of an existing column. The API reloads from the mounted source; the worker needs nothing of this. The test watcher is still stopped.

**Independent review, run 13** (on this change): (a) 1, (b) none, (c) 1, (d) none, (e) 23. Two code points, both fixed. Output: `stage-3-artifacts/review-gpt-6.1-sol-run13.txt`.

| # | Finding | Outcome |
| --- | --- | --- |
| a1, c1 | The unchanged write paths | As in every run |
| e20 | After the summary is approved, clearing an optional field that had been approved as it stood leaves the record unchanged, so the summary stays approved, and completion checked only the required fields: the review could be completed with that field undecided, against what this report says of completion | Fixed in code: completion is refused while the summary's count of undecided fields is above zero, and the screen is told it cannot complete (`complete_review(..., summary_waiting_for=...)`); the completion test now clears an optional field after the summary was approved and is refused until it is decided again |
| e21 | A chip of a second reading scrolled and pulsed but did not draw the lasting highlight, which was built from the shown reading's passages only | Fixed: the highlights include the second readings' passages |
| e22 | The SQL count was described as being on the same entries as the review's count; the populations differ slightly (869 and 877) | Report corrected |
| e23 | The failure history of the browser test and the runs since the polling change are not retained | Statements of this report; `playwright.txt` holds one run |
| e19, e1 to e18 | As in earlier runs | Statements of this report, by-design behaviour, or limits in KNOWN-GAPS.md |

{REVIEW14}

## Your step: one real review

A link for NHPC FDRE-II is live. It is not written in this file: a review link is the only key to its review, and this file is in the repository. It is in my message to you, and `docker compose exec -T api python -m scripts.review_token list` prints it on the VM.

It opens NHPC FDRE-II (97 fields since the structured fields were added, 82 with a value, one 264-page RfS), extracted afresh today, with the summary written from its fields. You said this run will be the timed one. The browser will warn once about the certificate (the app is served on a bare IP; KNOWN-GAPS.md). The link is valid for 30 days and is recorded under the reviewer name `venture@aayuda.energy`, taken from your account; every decision you make carries that name. If you want another name or another tender, make a new link before deciding anything (the old one stops working):

```
cd /work/tender_engine && docker compose exec -T api python -m scripts.review_token create --tender <slug> --reviewer "Your Name"
```

The slugs are in `EXTRACTION-SUMMARY.md`. I have deliberately written no instructions for the screen itself: whether you can complete the review without them is the test.

What I need back, for this report:

1. How long the review took.
2. Which fields you edited (the app has them: once you have completed the review I can list them from the approvals, so "done" is enough).
3. Anything that made you stop and wonder what to do.

Stage 3 stops here. After your review I will add the time and the edited fields to this report; then: `Run Stage 4 of docs/MASTER-PROMPT.md.`
