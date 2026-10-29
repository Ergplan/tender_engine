# Stage 7, Block 7 report: done (2026-10-28)

Block 7 of the owner's completion plan closes the build: the definition-of-done checklist
over the master prompt's stages and the plan's seven blocks, each item marked with its
evidence; the reliability report that joins the Block 1, Block 4 and Block 5 d figures and
is served through `reliability_report`; the independent review of the whole diff; and the
living documents brought current, with `docs/HANDOVER.md` new. Built under the owner's
decisions of 2026-10-27 and the subscription-only rule of 2026-10-28, under which no model
call was made from this build: the items that need one are listed at the end with what
each costs and the command that runs it.

## Definition of done (Block 7 of the plan)

| Item | State | Evidence |
| --- | --- | --- |
| (a) The definition-of-done checklist from the master prompt plus Blocks 0–6, each item done or not done with evidence | Done | the two tables below |
| (b) The reliability report (Block 1 + Block 4 + query eval), published through `reliability_report`; no accuracy claim anywhere this report does not support | Done; the query-eval figure is absent because that eval has not run, and the report says so in its place | `evals/reliability.py`, `docs/reports/RELIABILITY-REPORT.md` ("Headline"), the MCP tool `reliability_report` (`composite` and its `statements`); `tests/evals/test_reliability.py` (4), `tests/mcpserver/test_tools.py` |
| (c) Independent review on the whole diff until no new code defect | **Not run**: a model call through the app's key, forbidden from this build (DECISIONS 2026-10-28) | the command and the estimate under "Waiting on the owner" |
| (c) ARCHITECTURE, FIELD-TRACE, HANDOVER current | Done | `docs/ARCHITECTURE.md` ("Stage 7, Block 7"), `docs/FIELD-TRACE.md` (regenerated; `field_trace` green), `docs/HANDOVER.md` (new) |
| The owner's item 5 of 2026-10-27: `procurement_mode` split, gold eval run again, reported as in-sample | Split done (schema v5); the re-read of the eleven tenders and the eval after it wait on the owner (a model call) | below, "The procurement_mode split" |

## The checklist: the master prompt's stages

Each row is the master prompt's "Checks before STOP" line for the stage, as the stage report
verified it; the report named is where the evidence is laid out.

| Stage | Check | State | Evidence |
| --- | --- | --- | --- |
| 0A | INHERITANCE.md names a file path for every keep/adapt; at least five concrete flaws; stack recommendation stated | Done | `docs/INHERITANCE.md`; `STAGE-0A-REPORT.md` |
| 0B | Static IP recorded; firewall allowlisted on 22 and 443; `/health` from an allowed IP; `make test` green; 11 tenders with manifests; one mocked LLM call writes an `llm_call_log` row; tests watcher writing `.ci/status.json`; ARCHITECTURE committed | Done; the watcher is stopped by the owner's request since Stage 4 and `make check` replaces it (`.ci/status.json` is still what the hook reads) | `infra/STATIC-IP.txt`, `infra/allowlist.yaml` (gitignored), `tests/core/llm/`; `STAGE-0B-REPORT.md` |
| 1 | Candidates cannot be updated (test); every candidate has an evidence span (test); `ApprovalService` is the only writer to `canonical_fact` (grep and test); e2e on one FDRE tender; evidence location ≥ 95% on the 12 test fields; answer rate reported | Done | `tests/core/test_invariants.py`, `tests/e2e/`; `STAGE-1-REPORT.md` |
| 2 | All 9 schema YAMLs load; every validator has pass and fail tests; corrigendum carry-forward test; all 11 tenders extracted; EXTRACTION-SUMMARY.md with cost; evidence location ≥ 95% and answer rate per tender | Done (fourteen tenders by Stage 4, eleven of them reviewed) | `tests/tender/test_packs.py`, `tender/domain_packs/power/tests/`, `docs/reports/EXTRACTION-SUMMARY.md`; `STAGE-2-REPORT.md` |
| 3 | Playwright suite green; one real review completed from a token URL unaided; first PDF page under 3 s; no bulk-approve exists; `make trace` clean, every schema field has a complete FIELD-TRACE row | Done (the owner's timed review of NHPC FDRE-II, 2026-10-06) | `web/e2e/`, `docs/FIELD-TRACE.md`, `scripts/gen_field_trace.py --check`; `STAGE-3-REPORT.md` |
| 4 | `make gold`, `make eval`, `make report` end to end on two completed reviews; dashboard reachable; URL list for all 11 tenders delivered; FEEDBACK-REPORT.md lists top corrected fields | Done (eleven gold records by 2026-10-15) | `evals/`, `/admin/reliability`, `docs/reports/FEEDBACK-REPORT.md`; `STAGE-4-REPORT.md` |
| 5A | Agent findings exist for every gold tender; no agent code path can write candidate or `canonical_fact` (test) | Done | `agent/`, `tests/agent/`; `STAGE-5A-REPORT.md`. The agent is OpenAI-based and is off since the owner's 2026-10-27 decision (no OpenAI account) |
| 5B | THREEWAY-REPORT.md classifies every gold field into the six agreement classes | Done on 2026-10-18 (1,075 fields); not re-run since (needs the agent) | `docs/reports/THREEWAY-REPORT.md`; `STAGE-5B-REPORT.md`; KNOWN-GAPS |
| 5C | Cross-tenant read under RLS returns zero rows; Cloud Run deploy green; published view exposes canonical facts only | RLS and the published view done; **Cloud Run not deployed** (the owner's GCP steps, `infra/cloudrun/README.md`); sign-in waits for the Google OIDC client | `tests/core/test_rls.py`, `tests/tender/test_published.py`; `STAGE-5C-REPORT.md` |
| 5D | Widgets render from fixtures with a `not_reviewed` field; no outbound request but the bridge; text fallback complete; widget and server finance agree; `find_matching_tender` resolves informal phrasings and refuses near-misses; no end-user write to `public` (database-level test); usage attributed to the calling tenant; publication state machine with holds; corrections never change a value; takedown recorded; every public answer names the authority | Done | `tests/mcp/`, `tests/mcpserver/`, `tests/tender/test_library.py`, `test_corrections.py`; `STAGE-5D-REPORT.md` |
| 6 | Every imported award row a candidate with its evidence; no canonical fact without approval; allowlist committed and enforced; hash equality; no double import; validator tests; route tests; one end-to-end on a real result sheet; trace regenerates; 116 links delivered | Done; the 116 award reviews are the owner's and none is completed | `tests/tender/test_results_import.py`, `tests/api/test_awards.py`; `STAGE-6-REPORT.md` |

The two measurements every stage report carries since Stage 1: evidence-location rate 100%
on the gold set (634 of 634 scored fields) and on the three complete unseen tenders (238 of
238); answer rate 72.8% on the unseen tenders (reported, not targeted). The evidence
resolver's corpus (`make evidence-corpus`) stands as the Stage 6 report left it.

## The checklist: the completion plan's blocks

| Block | Item | State | Evidence |
| --- | --- | --- | --- |
| 0 a | Resize commands with cost; wait for approval | Written; the resize was declined by the owner (2026-10-24, 2026-10-27): the VM stays e2-medium | `STAGE-7-BLOCK-0-REPORT.md`, `STAGE-7-BLOCK-2-RESIZE.md` |
| 0 b | Nightly `pg_dump` + `/data` to the VM, a versioned GCS bucket with 30-day retention, a `.env`-stripped Drive copy; one run, a test restore, row counts | VM copy and Drive bundle done and running nightly (02:30 UTC; the 2026-10-28 run: 164 MB dump, 1.9 GB files); restore done; **the bucket copy fails: the bucket does not exist** (the owner's Cloud Shell block in the Block 0 report) | `infra/backup.sh`, `/work/backups/backup.log`; KNOWN-GAPS |
| 0 c | 4 GB swap; `restart: always`; the cause of the 20 Oct reboot | Done (a clean power-off on 2026-10-18 22:07 UTC and a start on 2026-10-20 07:49 UTC, from the journal; who, from the GCP operations list, is the owner's command) | Block 0 report |
| 0 d | Worker model-call logging fixed, with a test that fails if any process can call a model without a committed log row; Stage 6 report corrected; the UTC window | Done | `tests/worker/test_registry.py` (13 entry points); `STAGE-6-REPORT.md` "Corrected 2026-10-24" |
| 1 a | Review links for the nine open fields | Issued (`/work/stage7-links.txt`); the decisions are the owner's and not in (no more reviews, 2026-10-27) | Block 1 report |
| 1 b | Eval on the 11 gold tenders: per field, per type, critical fields, calibration | Done: 97.5% on 942 fields, 98.8% on 249 critical, 100% evidence; by band 98.1 / 93.3 / 91.7%; run again 2026-10-28 with the same result | `evals/results/20261028T193144Z-ergplan-latest.json`, `evals.runner.is_critical`, `confidence_band`; `tests/evals/test_runner.py` |
| 2 a | pdfplumber primary; Docling for layout, tables, OCR with boxes into the resolver; LlamaParse optional and off; per-page layer recorded | Done; LlamaParse's adapter is not exercised live (no key) | `core/parsing/`, migration 0021; Block 2 report |
| 2 b | Parser benchmark on a hard set before wiring a default | Done: Docling on scanned pages (located rate 0 → 100% on the transcribed quotes), off on table pages where pdfplumber held | `scripts/parser_benchmark.py`, `stage-7-artifacts/block-2-parser-benchmark.*` |
| 2 c | PDF, DOCX, XLSX, ZIP, protected PDFs; everything else refused with a reason | Done | `core/services/inputs.py`, `tests/core/services/test_inputs.py` (13) |
| 2 d | Type classification with confidence; unsure asks; unknown reads core only; never forced | Done; on the eight blind documents six `set` in agreement, two `unsure`, none forced | `tender/services/classify.py`; Block 4 report |
| 2 e | Windowing covers 400+ page tenders; coverage reported | Done | `scripts/window_coverage.py`, `stage-7-artifacts/block-2-window-coverage.*` |
| 3 a | Auto-link amendments by number, reference, issuer; ask below a threshold | Done; on the blind set 15 linked to their own tender, 4 asked, 0 wrong | `tender/services/amendment_link.py`; Block 4 report |
| 3 b | Out-of-order arrival at its date position, no reseed; the Ramagiri case as a test | Done | `tests/tender/test_version_order.py` |
| 3 c | Every change kind registers; section-map diff as fallback; each kind tested on a real amendment | Done; all six classes found on the corpus and on the blind set | `tender/services/amendments.py`, `scripts/amendment_report.py`; Block 3 report |
| 3 d | A review round per new version scoped to the changed fields; approvals carried with provenance; impact cues | Done (since Stages 4 and 5) | `tender/services/rounds.py`; Block 3 report |
| 3 e | Weekly report-only freshness check; never auto-ingests | Done; since Block 6 it also emits `amendment_detected` | `tender/services/freshness.py` |
| 4 a | Eight new tenders from official sites: transmission and IPP, two state, two scanned, two with amendments | Eight fetched (two transmission, five state, four scanned, five with amendments); **IPP not covered** (the only official IPP RfP found was unreachable from the VM) | Block 4 report, "The set" |
| 4 b | Freeze at a tagged commit before reading; extract; review links for the named reviewers | Frozen (`stage-7-block-4-freeze` = cbd191c) and four of eight extracted; no reviewers (the owner's 2026-10-27 decision); Bikaner's six runs unfinished (credit ran out) | Block 4 report |
| 4 c | Score against the reviews; fix systematic errors; before and after | **Not scored**: no reviews. The one systematic error Block 1 found (`procurement_mode`) is fixed in this block as schema v5; the "after" waits on the re-read | this report |
| 4 d | Evidence location ≥ 95%; accuracy ≥ 95% and ≥ 99% critical; every wrong reading below the high band | Evidence location 100% on the three complete tenders; **the accuracy targets are not claimed** (no reviewed values) | Block 4 report, "Targets" |
| 5 a | Hybrid retrieval in Postgres via pgvector; embeddings with a local switch; chunks carry page, clause, version | Done, local embeddings only (no OpenAI) | `core/retrieval/`, migrations 0023 and 0024 |
| 5 b | `ask_tender`: field questions from approved facts; otherwise from retrieved pages; every claim cited and resolved; version-aware; marked machine or approved; never a fact | Done | `tender/services/ask.py`, `POST /tenders/{id}/ask`, MCP `ask_tender` |
| 5 c | Cross-tender questions by structured search over canonical facts | Done | `tender/services/ask_across.py`, `POST /tenders/ask` |
| 5 d | Fifty-question eval with reviewer answers; answer accuracy and citation resolution | The set and the runner are built (the expected answers are the gold records' decided values: no reviewer wrote prose); **the eval has not run** (a model call) | `evals/questions/gold-questions.yaml`, `evals/ask_eval.py`, `make ask-eval` |
| 6 a | REST v1 with API keys: submit tender and amendment, status, snapshot, changes, ask, review link; snapshot JSON Schema as contract v1 with a contract test | Done | `api/v1/tenders/contract.py`, `docs/contracts/snapshot.v1.schema.json`, `tests/api/test_contract.py` |
| 6 b | Webhooks for extraction done, review complete, new version or amendment; signed and retried | Done | `core/services/webhooks.py`, migration 0025, `tests/core/services/test_webhooks.py` |
| 6 c | MCP over streamable HTTP with the existing OAuth; the ten tools; read tools kept; write tools need write scope | Done in code and tested with an MCP client; the connection from Claude.ai, Claude Code and OpenAI clients is the owner's check | `mcpserver/`, `tests/mcpserver/` |
| 6 d | OpenAPI 3.1 usable as OpenAI function definitions; a thin Python client | Done | `docs/contracts/openapi.v1.json`, `functions.v1.json`, `client/tender_engine_client.py` |
| 6 e | `docs/CONNECTOR.md`; each client tested end to end against the live engine | The guide is written; **the live tests are not run** (no API key on the live engine, the worker not restarted, a submission is a model call; the ChatGPT and Responses-API tests dropped by the owner) | Block 6 report, "(e)" |
| 7 a–c | This checklist; the reliability report through `reliability_report`; the review of the whole diff; ARCHITECTURE, FIELD-TRACE, HANDOVER | Done but for the review (a model call) | this report |

## (b) The reliability report

`evals/reliability.py` reads three files under `evals/results/` and builds the figures and
the sentences every caller prints: the latest plain `make eval` of the tenant (in-sample), the
latest `<stamp>-blind-check.json` (the unseen tenders; `scripts/blind_check.py` now writes
one beside its artifact), and the latest `ask-eval-<stamp>.json` when one exists. The
sentences are the two the owner allows (DECISIONS 2026-10-27, item 6), formed from the
numbers rather than typed, with the question-eval line added when that eval has run and a
plain "has not run" until then:

- 97.5% field accuracy on 11 human-reviewed tenders (in-sample)
- 100.0% evidence location on 3 unseen tenders (238 of 238 values located on the page they cite; no accuracy claim)
- The question eval (Block 5 d, `make ask-eval`) has not run: the retrieval route calls the model, and no run was allowed yet.

`make report` opens `docs/reports/RELIABILITY-REPORT.md` with this block (regenerated
2026-10-28 19:31 UTC from the live database, no model call); the MCP tool
`reliability_report` returns it as `composite` with the per-type figures it already gave,
and its text begins with the sentences and the caveat (the in-sample figure is not a forecast
for a new tender; a located quote is not a right value). Tests: `tests/evals/test_reliability.py`
(no files: every statement says what is missing; the latest plain eval of the tenant wins
over older runs, other tenants and prompt experiments; the unseen rate counts complete
tenders only and its sentence claims no accuracy; the question eval appears when it has
run).

## The procurement_mode split (the owner's item 5)

Block 1 found that five of the ten high-confidence misses on the gold set were
`core.identity.procurement_mode`: the enum mixed the stage structure
(`single_stage_two_envelope`) with the price discovery (`e_reverse_auction`), both true of
most SECI tenders, and the reviewers themselves split (seven chose the stage structure, four
approved the auction). Schema v5 separates them:

- `core.identity.procurement_mode` keeps its path and its allowed values and now means the
  stage and envelope structure alone. The value `e_reverse_auction` stays allowed so that
  every reading made under v1 to v4 still loads and the eleven reviewed tenders keep their
  decided value on screen (a narrowed enum would have set every earlier candidate aside,
  `verify_versions`); the v3 identity prompt never returns it.
- `core.identity.price_discovery` is new: `e_reverse_auction`, `sealed_bid`, `other`.
- `tender/domain_packs/core/prompts/extract/identity_and_scope/v3.md`; `common.yaml` and
  `pack.yaml` at v5 reading v1–v4 with nothing under `read_again` (no signature changed);
  `power/released/v5.yaml` written by `scripts.release_schema`; FIELD-TRACE regenerated
  (the new field's row, the prompt version on the identity rows).

**What waits:** the re-read of `identity_and_scope` on the eleven gold tenders under v5 and
`make eval` after it, about USD 6 to 12 through the batch API (one section, two or three
page windows a tender). The expected outcome, stated before the run: the seven gold records
that hold `single_stage_two_envelope` match; the four that hold `e_reverse_auction`
(nhpc-fdre-ii, ntpc-phes-2000mw, seci-cfd-i, ntpc-hybrid-03) become misses of the field,
because the reviewers approved the auction under the old enum and the no-more-reviews rule
leaves the gold as it is. The in-sample figure would move from 24 to about 23 misses
(97.5% to about 97.6%); the honest gain of the split is the end of the ambiguity for every
tender read from now on, not the gold number.

## Tests

All tests were written with the code: `tests/evals/test_reliability.py` (4); the pack tests
moved to v5 (`tests/tender/test_packs.py`, `test_pack_versions.py`); one Block 6 test
corrected (`tests/core/services/test_identity.py` used `write` as its example of an unknown
scope, which Block 6 made a real one; it now uses `delete`), and one API test that pinned the
schema version (`tests/api/test_tenders.py`, `v4` to `v5`). Check run 13 (the Block 6 tree,
`stage-7-artifacts/check-run13.log`, 2,486 s) was red on the scope test and nothing else;
run 14 (the Block 7 tree, `check-run14.log`, 2,370 s) red on the version pin and nothing
else; run 15 (`check-run15.log`) is the green run both the Block 6 and the Block 7 commits
stand on:

Run 15, 2026-10-28 20:12 UTC, 2,365 s, every check green (`ci-status-block-7.json`):

| Check | Result | Seconds |
| --- | --- | --- |
| ruff_check | pass | 0.4 |
| ruff_format | pass | 0.3 |
| mypy | pass | 83.7 |
| alembic_check | pass | 13.0 |
| pytest | pass | 2082.7 |
| openapi_drift | pass | 37.5 |
| contract_drift | pass | 27.0 |
| field_trace | pass | 39.7 |
| tsc | pass | 19.5 |
| vitest | pass | 62.2 |

## Independent review (operating rule 15), 2026-10-29

Run outside the build session by the owner's assistant (Claude Opus 5.5, a fresh session
with the repository only; same vendor as the builder, per DECISIONS 2026-10-25), over
`stage-7-start..69e6d07` with CLAUDE.md and `docs/COMPLETION-PLAN.md`, on the fixed
checklist. It made no call through the app's key.

| Check | Finding |
| --- | --- |
| (a) Invariants | Upheld. `canonical_fact` is written only in `core/services/approve.py:292`; the Stage 7 services that answer (`ask`, `ask_fields`, `ask_across`, `snapshot`, `status`) write nothing; the version order change keeps versions immutable and re-projects. No LLM in validation. |
| (b) Endpoint tests | **Defect, fixed**: `POST /documents/bundle`, `POST /documents/{id}/classify`, `POST /documents/{id}/link-amendment` and `POST /tenders/{id}/type` had no API test. Now `tests/api/test_stage7_routes.py`. |
| (c) Audit | Upheld for the five audited tables; webhook registration is audited too. |
| (d) Trace | `scripts.gen_field_trace --check`: current, 218 fields. |
| (e) Report claims | No claim found that the code does not support. |
| Security (beyond the checklist) | **Three defects, fixed.** Webhook receivers could be private or in-network addresses (the worker would post into the deployment, where an unmarked request is trusted): now refused at registration and, after resolving, at delivery; `WEBHOOK_ALLOW_PRIVATE` for a receiver on the same network. The official-URL fetch checked only the final redirect target and read the whole body before its size check: every hop is now checked before it is requested and the body is streamed under the cap. A bundle had no total cap and a member with a lying size header raised a 500: now a 600 MB declared total and a named rejection. |

Tests added: `tests/api/test_stage7_routes.py` (5), `tests/core/services/test_webhooks.py`
(11 new cases), `tests/core/services/test_inputs.py` (2), `tests/api/test_contract.py` (2).
The full suite was run on the fixed tree outside the VM (Postgres 16 with pgvector).

Not resolvable by code, listed and not blocking: the reviewer is the builder's vendor (the
owner's decisions of 2026-10-25 and 2026-10-27); the unauthenticated trust of requests made
inside the deployment is by design (Stage 5C) and is what the webhook fix protects.

## Deployment

The api runs the mounted tree and reloads on Python changes; the pack files are read at
process start, so the live api serves schema v5 at its next restart, and the live worker
runs Block 6's handlers and v5 after `docker compose restart worker` (both refused to the
build session on 2026-10-28, the owner's `! make -C /work/tender_engine deploy` does both).
No migration and no new dependency in this block.

## Waiting on the owner (each a model call through the app's key, or a GCP step)

| Step | Command | Estimate |
| --- | --- | --- |
| Rule-15 review of the whole Stage 7 diff (Block 7 c): **done 2026-10-29 outside the build session, see above**; a further run is optional | `git add -A && make review STAGE=7 RANGE=stage-7-start..HEAD PROMPT=docs/COMPLETION-PLAN.md > docs/reports/stage-7-artifacts/review-stage-7-run1.txt`; if the diff is too long for one call, per block: `stage-7-block-5-start..stage-7-block-6-start`, `stage-7-block-6-start..stage-7-block-7-start`, `stage-7-block-7-start..HEAD` | under USD 5 a run (Opus 5.5); two or three runs |
| Re-read `identity_and_scope` under v5, then the eval | `docker compose exec -T api python -m scripts.ingest_tenders extract --groups identity_and_scope --force --only <eleven gold slugs>` then `make eval`, `make report` | USD 6 to 12 (batch API) |
| Bikaner's six unfinished Block 4 runs | `docker compose exec -T api python -m scripts.ingest_tenders resume --only recpdcl-bikaner-v-part-a`, then `python -m scripts.blind_check` | about USD 15 |
| The question eval (Block 5 d) | `make ask-eval` | about USD 3 |
| Block 6 e live checks | mint a key on `/admin` (scopes read, write, review:mint); `docker compose restart worker`; the `docs/CONNECTOR.md` examples | no model call but one submission (about USD 0.045 a page) |
| GCP | the backup bucket and key (Block 0 report), a snapshot schedule, the OIDC client, Cloud Run if wanted | none |

## Costs

No model call in this block. Ledger (`llm_call_log`): USD 502.76 over 1,882 calls, unchanged
since 2026-10-27 11:00 UTC.

## Open questions

- Whether the four gold records holding `e_reverse_auction` for `procurement_mode` should be
  revisited by a reviewer once reviews resume (one field each; the re-read's misses would
  then close).
- Whether the public library tenant should carry a reliability file of its own
  (`reliability_report` falls back to the `public` tenant's eval when the caller's tenant has
  none; today only `ergplan` has one).
