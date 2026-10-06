# Context for a new session (written 2026-10-05, last updated about 22:30 UTC)

Read this first, then `CLAUDE.md`, then the last two sections of `docs/reports/STAGE-3-REPORT.md`.

## Where the build stands

- **Stage 3 (reviewer UI) is built, deployed and checked; it closes when the owner has done one timed review.** Stages 0, 1, 2 are closed. Tags: `stage-0-start` to `stage-3-start`.
- App: `https://34.131.65.108/` (static IP, never changed). One GCE VM, 2 vCPU, 3.9 GB RAM, 200 GB disk. Six compose services; the test watcher is stopped on the owner's instruction, so run `make check` before every commit (the pre-commit hook needs a fresh `.ci/status.json`).
- 13 tenders are ingested and extracted under schema `v2`. The owner has started deciding fields of NHPC FDRE-II; no other tender has a decision.
- GCP changes (firewall, addresses) cannot be made by the agent; the owner runs them with the `!` prefix.

## What is open right now (session cut off at its usage limit on 2026-10-05, about 23:50 UTC)

**Uncommitted work in the tree, built at the owner's request before the timed review. Finish it first:**

1. **Clear decision** (`cleared`): a decision kind that supersedes the active approval and leaves the field undecided; audited; no canonical fact, no feedback row. Built in `core/services/approve.py`, `core/services/review_state.py`, `api/v1/schemas/core.py`, the screen (`FieldCard.tsx` button "Clear decision", key `U`, `ReviewScreen.tsx`, `lib/keyboard.ts`, guide text in `guide.ts` and `docs/REVIEWER-GUIDE.md`). Tests written and passing: core, API (`test_a_decision_can_be_cleared_through_the_link...`), web unit (67 pass), and the browser test `approve with Enter, edit a date...` extended (not yet run).
2. **Second readings shown.** `FieldState.alternatives` lists the other reviewable candidates of a field whose coerced value differs from the shown one; the reading a reviewer decided on becomes the field's reading. The card shows each with value, confidence, evidence chips and "Use this reading" (`data-testid` `alternative`, `use-reading`). Tests: `tests/core/services/test_review_state.py` (three new), web unit. The API client was regenerated (`make client`).
3. **The owner's two mis-click decisions on NHPC FDRE-II are cleared** (one `cleared` approval at about 23:40 UTC through their link; review stands at 0 of 97; no canonical fact current). Do not touch the `approval` table.
4. **Not yet done:** `make check` and `make test-ui` on this code (tsc and vitest pass; the Python suite was not run in full); commit; independent review (rule 15, run 13); report section "Clear decision and second readings" with these numbers; `docs/DECISIONS.md`, `docs/ARCHITECTURE.md` (review state: alternatives, decided reading), `docs/KNOWN-GAPS.md` (remove the "second answer not shown" row; add: feedback rows of superseded approvals must be ignored by the Stage 4 feedback report); push. Then tell the owner the timed review can start.

**Numbers for the report (app database, 2026-10-05 23:45 UTC):** of 877 fields with a value, 80 (9.1%) have a second reading that differs after typing; by tender: NHPC FDRE-II 12, SECI Gaya 12, SECI FDRE-IX 11, SECI CnI-1 9, Wind Tranche-XX 7, RECPDCL Beed 5, PHES 4, RTC-V 4, ESS-IV 4, Ramagiri 4, Hybrid-03 3, Anantapur 3, CfD-I 2. By field, the three `core.documents` lists lead (9, 8, 7), then `dates_deferred_note` 4 and six fields at 3. In SQL on the versions shown: 869 fields with a value, 114 with two or more live readings, 79 differ in raw text, 35 are identical. A second reading can come from another page window of the section or from another pass over it.

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

- **The timed review of NHPC FDRE-II**, unaided, from the review link (97 fields, 82 with a value, 8 structured cards). The link is not in the repository: `docker compose exec -T api python -m scripts.review_token list`. Wanted back: the time taken, and anything that made them stop. This closes Stage 3. The build side is ready for it.

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
