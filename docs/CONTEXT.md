# Context for a new session (written 2026-10-05, last updated about 22:30 UTC)

Read this first, then `CLAUDE.md`, then the last two sections of `docs/reports/STAGE-3-REPORT.md`.

## Where the build stands

- **Stage 3 (reviewer UI) is built, deployed and checked; it closes when the owner has done one timed review.** Stages 0, 1, 2 are closed. Tags: `stage-0-start` to `stage-3-start`.
- App: `https://34.131.65.108/` (static IP, never changed). One GCE VM, 2 vCPU, 3.9 GB RAM, 200 GB disk. Six compose services; the test watcher is stopped on the owner's instruction, so run `make check` before every commit (the pre-commit hook needs a fresh `.ci/status.json`).
- 13 tenders are ingested and extracted under schema `v2`. The owner has started deciding fields of NHPC FDRE-II; no other tender has a decision.
- GCP changes (firewall, addresses) cannot be made by the agent; the owner runs them with the `!` prefix.

## What is open right now

1. **The owner's timed review of NHPC FDRE-II.** Everything on the build side of Stage 3 is done; this is the last check of the definition of done. When it is complete: add the time taken and the edited fields to `docs/reports/STAGE-3-REPORT.md` (the fields can be listed from the `approval` table), then Stage 3 is closed.
2. **Do not disturb the owner's decisions.** The app database holds decisions made through the review link (the first on 2026-10-05 17:33 UTC, on `sector.power.fdre.excess_energy_structured`). Never truncate, re-seed or force a re-extraction of NHPC FDRE-II without asking. A re-extraction of a section supersedes its candidates; a field already decided keeps its approval.
3. Nothing else is in progress. The working tree is clean and pushed.

## What was fixed late on 2026-10-05 (so you do not look for it again)

- A browser test failed after the schema version check went in. Cause one: the check parsed the released schema files once per tender type, which tripled the pack load time (fixed, parsed once). Cause two, exposed by the delay: the summary was reported as current while its new text was stored but not yet validated, so the screen stopped looking for it (fixed in `SummaryWriter.state`).
- In that same moment a review could have been completed without a decided summary (found by independent review run 10; fixed, completion is refused while a summary is being written).
- FIELD-TRACE did not name run rules (review run 9; fixed).
- Independent reviews 8 to 11 are recorded in the Stage 3 report; outputs in `docs/reports/stage-3-artifacts/`.

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
