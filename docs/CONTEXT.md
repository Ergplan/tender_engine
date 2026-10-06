# Context for a new session (written 2026-10-05, last updated 2026-10-06 about 13:30 UTC)

Read this first, then `CLAUDE.md`, then `docs/reports/STAGE-4-REPORT.md`.

## Where the build stands

- **Stage 4 (human reliability program) is built, checked and deployed; independent review runs 1 and 2 are fixed and committed, run 3 is still owed before the stage closes; it then stays open as reviews complete.** Stages 0 to 3 are closed; the owner's timed review of NHPC FDRE-II (Stage 3's last check) was completed on 2026-10-06 12:48 UTC and is the first gold record. Tags: `stage-0-start` … `stage-4-start` (04751a6).
- App: `https://34.131.65.108/` (static IP, never changed); the reliability dashboard at `https://34.131.65.108/admin/reliability` behind `ADMIN_TOKEN` (in `.env`, gitignored). One GCE VM, 2 vCPU, 3.9 GB RAM, 200 GB disk. Six compose services; the test watcher is stopped on the owner's request, so run `make check` before every commit (the pre-commit hook refuses a stale or red status).
- 13 tenders ingested and extracted under schema `v2`. NHPC FDRE-II is `reviewed` (97 of 97 decided). Review links exist for the other 12 (reviewer `venture@aayuda.energy`, created 2026-10-06; `python -m scripts.review_token list` prints them; never commit or paste them into the repo).
- GCP changes (firewall, addresses) cannot be made by the agent; the owner runs them with the `!` prefix.

## What is open right now (2026-10-06, about 13:30 UTC)

1. **The review phase is the owner's.** As each review is completed and the owner confirms it is trustworthy: `make gold TENDER=<slug>` (writes `evals/gold/<type>/<slug>.yaml`, regenerates `RELIABILITY-REPORT.md` and `REVIEW-LOG.md`), `make eval`, `make feedback-report`, commit. The stability bar for Stage 5 needs two reviewed tenders for each of `epc`, `fdre`, `wind` and 90% on required fields across two prompt versions; it is not met with one record.
2. **Stage 5 waits for the bar.** Do not start it.
3. **Corpus gaps found 2026-10-06 (owner's audit request, see the Stage 4 report "Corpus audit")**: SECI Ramagiri 70 MW BESS is missing Amendment-01 and Clarification-01 (xlsx, 28/07/2026, on the SECI page); SECI CnI-1's bid deadline moved on the portal with no document; SECI CfD-I lacks four pre-bid notices. Ingesting any of these changes a tender that holds candidates: wait for the owner's word.
4. **Owner's feedback from the NHPC review, not built** (KNOWN-GAPS): GST captured separately wherever a value carries it; Annexure-1A worked examples captured or linked for penalties; a note on an approved value; multi-valued fields.
5. A judgement for the owner to confirm (Stage 3 report, review run 14): the summary written from the approved record sends reviewer-edited values to the model.

## Stage 4, what exists (2026-10-06)

- `evals/gold.py` (gold record from the latest completed-review snapshot plus the active approvals and the candidates they judged), `evals/runner.py` (match rules by value type; `--prompt <section>/vN` reads that section again on every gold tender through `extraction_run.prompt_overrides`, migration 0012), `evals/feedback_report.py` (only corrections of standing decisions), `evals/report.py` (reliability report, review log, stability bar), `scripts/make_gold.py`; Makefile `gold`, `eval`, `feedback-report`, `report`.
- `GET /api/v1/admin/reliability` behind `X-Admin-Token` (middleware `api/middleware/review_token.py`; empty `ADMIN_TOKEN` closes it); `web/src/admin/ReliabilityPage.tsx` at `/admin/reliability`.
- First results: value accuracy 98.7% on 79 scored fields of NHPC FDRE-II, evidence accuracy 100% on 64, 18 long-text fields unscored, one miss (`sector.power.common.metering_point`, a wording edit).
- An incident to remember: a model column saved while the API was up broke the live API until `make migrate` ran (the owner's "Complete review" click got a 500). Migrate the app database before saving a model change.

## Built on 2026-10-06 before the timed review (owner's request)

- **Clear decision** (`cleared`): supersedes the active decision, the field is undecided again, audited, no canonical fact, no feedback row. Key `U` or the card's "Clear decision".
- **Both readings when they differ**: `FieldState.alternatives` lists other reviewable readings whose typed value differs; the card shows each with evidence and "Use this reading"; the reading decided on becomes the field's. 80 of 877 fields with a value have one (9%); figures in `stage-3-artifacts/second-readings.txt`.
- Completion waits for every field the summary is written from, optional ones too; a second reading's chips highlight; the summary card offers "Check again" and the screen keeps polling while a rewrite is reported. Independent reviews 13 and 14 recorded; 14 found no code defect.

## What was fixed late on 2026-10-05 (so you do not look for it again)

- A browser test failed after the schema version check went in. Cause one: the check parsed the released schema files once per tender type, which tripled the pack load time (fixed, parsed once). Cause two, exposed by the delay: the summary was reported as current while its new text was stored but not yet validated, so the screen stopped looking for it (fixed in `SummaryWriter.state`).
- In that same moment a review could have been completed without a decided summary (found by independent review run 10; fixed, completion is refused while a summary is being written).
- A request refused to a valid review link was audited under "api" instead of the reviewer (run 11; fixed).
- FIELD-TRACE did not name run rules (review run 9; fixed).
- Independent reviews 8 to 12 are recorded in the Stage 3 report (four code defects found and fixed, run 12 found none); outputs in `docs/reports/stage-3-artifacts/`.

## Decisions made today (details in `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`)

- **Structured fields.** Prose fields that hold numbers have typed siblings (15 fields, 20 paths, one retyped list) for a financial model. Extracted in the same call as the prose, with their own quotes; never derived by a model. The model writes `key: value` lines and code types them. The model input profile that will read them is designed, not built; a value the tender states can never be overridden by an assumption.
- **Schema v2.** Reads `v1` runs (`reads_versions`). Compatibility is now checked at load time against `tender/domain_packs/power/released/<version>.yaml` (`verify_versions` in `tender/services/packs.py`): a removed field, or a changed field not listed under `read_again`, fails the load; released versions are frozen. `v1` and `v2` are released. A change to a `v2` field needs a `v3`.
- **Quote rule (owner's decision).** A structured number must be printed in a quote of its own field; nothing is computed; wording that is not a number ("at the tariff") takes an enum key or stays empty. Prompts `extract/commercial` and `extract/penalties` are `v3`; both were read again on all 13 tenders (USD 27.04). Result: `structured_numbers_quoted` fails 0 of 116 (was 9 of 117). Three scalar-agreement failures stay for the reviewer by the owner's decision. Evidence: `docs/reports/stage-3-artifacts/structured-fields.txt`.
- **Review state** reads runs of all versions registered with the same content; a `v2` run had hidden every field read only under `v1` (fixed, tested).
- **Public tier and MCP are Stage 5D** (after 5C): reserved `public` tenant, free read-only access, MCP widgets, one deterministic financial engine. Text is in `docs/MASTER-PROMPT.md`; the base MCP tools are still unspecified and nothing is to be built now.
- **Amendment diff view for the first buyer.** Named by the owner as a decision of today. It is not yet written in DECISIONS.md or the master prompt; ask the owner for its scope and stage before building.
- Port 443 is open to the world (access by review token); an admin guard is needed before the Stage 4 dashboard.

## What the owner owes

- Reviews of the other twelve tenders from their links, one at a time, pressing "Complete review" at the end; then say which completed reviews are trustworthy so `make gold` can be run.
- A word on the corpus gaps (Ramagiri Amendment-01 and Clarification-01 above all).

## Open questions for the owner

1. Do numbers written out in words ("one and a half times") count as printed, and may a printed percentage be given as a multiple? Both are allowed now.
2. Scope and stage of the amendment diff view.
3. Guard for `/admin/reliability` before Stage 4 (an admin token is the smallest change).
3a. A second answer for a field is not shown on its card (17 fields on NHPC FDRE-II have two reviewable answers from two page windows). Leave it, show a count, or show both values?
4. Published notices on a fresh extraction: read them for key dates only (a schema change), or leave to the reviewer?
5. Batch API as the default for extraction commands in Stage 4?
6. VM size: still 2 cores, 3.9 GB.

## Costs

Model calls in the app database: about USD 356 (the independent reviewer's OpenAI calls are not in it). Report convention: Stage 3 about USD 121, running total about USD 381.
