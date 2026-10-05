# Context for a new session (written 2026-10-05, about 18:40 UTC)

Read this first, then `CLAUDE.md`, then the last two sections of `docs/reports/STAGE-3-REPORT.md`.

## Where the build stands

- **Stage 3 (reviewer UI) is built and deployed but not closed.** Stages 0, 1, 2 are closed. Tags: `stage-0-start` to `stage-3-start`.
- App: `https://34.131.65.108/` (static IP, never changed). One GCE VM, 2 vCPU, 3.9 GB RAM, 200 GB disk. Six compose services; the test watcher is stopped on the owner's instruction, so run `make check` before every commit (the pre-commit hook needs a fresh `.ci/status.json`).
- 13 tenders are ingested and extracted under schema `v2`. No reviewer decision exists in the database (0 approvals, 0 canonical facts).
- GCP changes (firewall, addresses) cannot be made by the agent; the owner runs them with the `!` prefix.

## What is open right now (do these first)

1. **One browser test fails and must be understood before the timed review.** `make test-ui`: 9 pass, 1 fails: "complete the review by keyboard; the snapshot holds the final values" (`web/e2e/review.spec.ts:305`). After every other field is decided, the summary card's Approve stays disabled with "The summary is being written again from your decisions". It passed before the last change. Facts so far: reproducible on an idle machine; in the test database no `tender_summary` job is queued after the decisions and no record run is under way; computed fresh with the real services (`SummaryWriter.state`) the summary is `current=True`, `waiting_for=0`. So the API process and a fresh process disagree, or the screen's polling does. Not yet bisected. Suspects, all from the last change: the new key `compensation_basis`, prompt `v3` of commercial and penalties, `verify_versions` and field exclusion in `core/services/review_state.py`, `released/v2.yaml`. Next step: `git stash`, run `make test-ui`, then reapply piece by piece. **This is the summary approval a reviewer reaches at the end of a real review, so the owner should not start the timed review until it is resolved.**
2. **The last report section has placeholders.** In `STAGE-3-REPORT.md`, section "The quote rule and the version check", fill the test counts (478 Python, 65 web unit, browser count once fixed) and the independent review.
3. **Independent review run 9** (rule 15) has not been run on the last change: `set -a; . ./.env; set +a; .venv/bin/python -m scripts.independent_review --stage 3 > docs/reports/stage-3-artifacts/review-gpt-6.1-sol-run9.txt`.
4. Refresh the artifacts `checks.txt`, `playwright.txt`, `trace.txt`, `deployment.txt` after the fix, then commit and push.

## Decisions made today (details in `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`)

- **Structured fields.** Prose fields that hold numbers have typed siblings (15 fields, 20 paths, one retyped list) for a financial model. Extracted in the same call as the prose, with their own quotes; never derived by a model. The model writes `key: value` lines and code types them. The model input profile that will read them is designed, not built; a value the tender states can never be overridden by an assumption.
- **Schema v2.** Reads `v1` runs (`reads_versions`). Compatibility is now checked at load time against `tender/domain_packs/power/released/<version>.yaml` (`verify_versions` in `tender/services/packs.py`): a removed field, or a changed field not listed under `read_again`, fails the load; released versions are frozen. `v1` and `v2` are released. A change to a `v2` field needs a `v3`.
- **Quote rule (owner's decision).** A structured number must be printed in a quote of its own field; nothing is computed; wording that is not a number ("at the tariff") takes an enum key or stays empty. Prompts `extract/commercial` and `extract/penalties` are `v3`; both were read again on all 13 tenders (USD 27.04). Result: `structured_numbers_quoted` fails 0 of 116 (was 9 of 117). Three scalar-agreement failures stay for the reviewer by the owner's decision. Evidence: `docs/reports/stage-3-artifacts/structured-fields.txt`.
- **Review state** reads runs of all versions registered with the same content; a `v2` run had hidden every field read only under `v1` (fixed, tested).
- **Public tier and MCP are Stage 5D** (after 5C): reserved `public` tenant, free read-only access, MCP widgets, one deterministic financial engine. Text is in `docs/MASTER-PROMPT.md`; the base MCP tools are still unspecified and nothing is to be built now.
- **Amendment diff view for the first buyer.** Named by the owner as a decision of today. It is not yet written in DECISIONS.md or the master prompt; ask the owner for its scope and stage before building.
- Port 443 is open to the world (access by review token); an admin guard is needed before the Stage 4 dashboard.

## What the owner owes

- **The timed review of NHPC FDRE-II**, unaided, from the review link (97 fields, 82 with a value, 8 structured cards). The link is not in the repository: `docker compose exec -T api python -m scripts.review_token list`. Wanted back: the time taken, and anything that made them stop. This closes Stage 3. Not before item 1 above is resolved.

## Open questions for the owner

1. Do numbers written out in words ("one and a half times") count as printed, and may a printed percentage be given as a multiple? Both are allowed now.
2. Scope and stage of the amendment diff view.
3. Guard for `/admin/reliability` before Stage 4 (an admin token is the smallest change).
4. Published notices on a fresh extraction: read them for key dates only (a schema change), or leave to the reviewer?
5. Batch API as the default for extraction commands in Stage 4?
6. VM size: still 2 cores, 3.9 GB.

## Costs

Model calls in the app database: about USD 356. Report convention: Stage 3 about USD 121, running total about USD 381.
