# Handover: the Tender Intelligence Engine as it stands (2026-10-28)

The one page to read first when taking the engine over. It says what runs where, how to
operate it day to day, what the figures mean, and what is still open. The detail behind
each line is in `docs/ARCHITECTURE.md` (how it is built), `docs/DECISIONS.md` (why),
`docs/KNOWN-GAPS.md` (what is missing and what closes it), `docs/CONNECTOR.md` (how to call
it) and the stage and block reports under `docs/reports/`. `docs/CONTEXT.md` is the
build session's own hand-off note and keeps the history.

## What it is

One engine that reads an Indian power tender (the RfS or NIT, its annexures, its
amendments, corrigenda and clarifications) into a versioned record of typed fields, each
value tied to a page and a quote the evidence resolver located on that page; a split-screen
review in which a human approves, edits or rejects every value; a published view of the
approved facts; a full-tender question route; and a REST v1, an MCP server and an OpenAPI
contract that serve all of it to products and to Claude and OpenAI clients.

The truth pipeline is fixed (CLAUDE.md, "Non-negotiable invariants"): the model writes
candidates only; a canonical fact exists only through a human approval; every value carries
located evidence; the tender is a versioned object; validation is deterministic; everything
is audited and tenant-scoped; feedback is stored and never auto-applied; every operation is
an API.

## Where it runs

| What | Where |
| --- | --- |
| The VM | GCE `e2-medium` (2 vCPU, 3.9 GB, 4 GB swap, 200 GB disk), static IP `34.131.65.108`, never changed |
| The app | `https://34.131.65.108/` (Caddy, internal CA: one certificate warning), `/health` |
| The services | `docker compose` in `/work/tender_engine`: `api`, `worker`, `agent`, `web`, `db` (`pgvector/pgvector:pg16`), `caddy`, `docling` (profile `parsing`); `tests` is the check runner, stopped by default |
| The code | `/work/tender_engine`, GitHub `Ergplan/tender_engine`, branch `main`, one tag per stage start (`stage-N-start`, `stage-7-block-N-start`) |
| The data | Postgres volume; files under `/data/` on the VM (`DATA_DIR`); the embedding model under `/data/models/fastembed` |
| The tenders | `/work/tenders/<type>/<slug>/` with a `manifest.yaml` each (source URL and retrieval date per file); the award results dataset read-only at `/work/ref/RE-tender-results` |
| Secrets | `/work/tender_engine/.env` (gitignored; `.env.example` lists every variable with its meaning); review links in `/work/stage*-links.txt` (mode 600). Nothing of either is in the repository |
| Backups | nightly 02:30 UTC by cron (`infra/backup.sh`): `pg_dump` and a tar of `/data` under `/work/backups` (14 days), a `.env`-stripped Drive bundle under `/work/backups/drive`; the bucket copy fails until the bucket exists (below) |
| The MCP server | `https://34.131.65.108/mcp`, streamable HTTP, OAuth 2.1 with dynamic registration, or an API key as a bearer token |
| The tender workspace | `https://34.131.65.108/workspace`: drop a tender or paste its official URL, follow the reading, read every term with its page, the amendments with their impact, ask questions, send for review. Opened with an access key (an API key minted for a person) |
| The admin screens | `/admin` (users, API keys, review tokens, holds) for a signed-in admin; `/admin/reliability` behind `ADMIN_TOKEN` |

## Operating it

Every command runs on the VM in `/work/tender_engine`. `make` with no target lists them.

| Task | Command |
| --- | --- |
| Start, stop | `make up` (also starts the test watcher), `make down` (volumes kept) |
| Deploy the checked-out tree | `make deploy` (pull, build, migrate, restart, health check); starts `docling` under `COMPOSE_PROFILES=parsing` |
| Load a code change into the worker without a deploy | `docker compose restart worker` (the api reloads by itself: uvicorn on the mounted tree) |
| Run every check once | `make check` (about 30 minutes on this VM; run nothing heavy beside it). The pre-commit hook refuses a commit over a red or stale `.ci/status.json` |
| Add a tender from the shell | put its files and `manifest.yaml` under `/work/tenders/<type>/<slug>/`, then `docker compose exec -T api python -m scripts.ingest_tenders ingest --only <slug>` and `… extract --only <slug>` |
| Add a tender through the API | `POST /api/v1/tenders/submit` with a file or an official URL (API key with `write`); the status at `GET /tenders/{id}/status`; `docs/CONNECTOR.md` |
| Add an amendment | `POST /api/v1/tenders/{id}/submit-amendment`; or `ingest_tenders ingest` after adding the file to the manifest |
| Give a reviewer a link | `/admin` as an admin, `POST /api/v1/tenders/{id}/review-link` (scope `review:mint`), or `docker compose exec -T api python -m scripts.review_token create --tender <slug> --reviewer <email>`; `… list` prints the live ones. A link is a credential: never into the repository or a chat |
| A later version reached a reviewed tender | the engine opens a review round for the reviewer scoped to what changed; `scripts.review_token round --tender <slug> --from-version N` opens one by hand |
| A completed review becomes a gold record | `make gold TENDER=<slug>`, then `make eval`, `make feedback-report`, `make report` |
| Score the engine against the gold records | `make eval` (no model call); `make eval PROMPT=<section>/vN` reads one section again first (a model call) |
| The question eval | `make ask-eval` (model calls: about fifty short answers) |
| The rule-15 review of a diff | `git add -A`, then `make review STAGE=7 RANGE=<tag>..HEAD PROMPT=docs/COMPLETION-PLAN.md` (one long Claude Opus 5.5 call) |
| The weekly freshness check by hand | `make freshness` (report only; nothing is ingested) |
| The field trace, the OpenAPI document, the contract | `make trace`, `make client`, `python -m scripts.export_contract --write`; each has a drift check in `make check` |
| Backups | `make backup`; a restore is described in the Block 0 report |
| Logs | `make logs`; the model ledger is the `llm_call_log` table (`cost_usd` per call) |

Things to know before changing code:

- A released schema version is frozen (`tender/domain_packs/power/released/vN.yaml`): a
  changed field needs a new version, declared in `pack.yaml` and `common.yaml` and released
  with `python -m scripts.release_schema`. The loader refuses the pack otherwise.
- A model change needs a migration before the API is restarted: `make migrate` (the API
  broke once when a column was saved while it was up).
- Every model call goes through `core/llm`; a call anywhere else fails the registry test.
- Four living documents change in the same commit as the code: ARCHITECTURE, FIELD-TRACE
  (generated), DECISIONS, KNOWN-GAPS.

## What the figures mean

The engine's accuracy is stated in two sentences and no others (the owner's rule of
2026-10-27), both produced from the result files by `evals/reliability.py` and served by
the MCP tool `reliability_report` and the reliability report:

- **97.5% field accuracy on 11 human-reviewed tenders (in-sample)**: `make eval` over the
  gold records, 942 scored fields, 24 misses, 98.8% on the critical fields, 100% of cited
  pages accepted. In-sample means the engine was tuned on these same tenders.
- **100% evidence location on 3 unseen tenders (238 of 238 values located)**: the Block 4
  tenders, read under a frozen commit and never reviewed. A located quote says the value is
  on the page it cites, not that it is right; nothing about their correctness is known.

The question eval (Block 5 d) has not run; its figures join the report the day it does.

## What is live

Twenty-three tenders in the enterprise tenant (eleven reviewed, with gold records; the
Block 4 set of eight, unreviewed; the rest open or superseded), 220 documents, about 7,400
pages, 1,265 canonical facts, 19,400 retrieval chunks; 116 award publications imported as
candidates, none approved. The model ledger stands at USD 502.76 over 1,882 calls.

## Open at the handover (who, what, how)

The owner's items, in the order they unblock the most:

1. **Restart the worker** so it runs the Block 6 handlers (`docker compose restart worker`
   or `make deploy`); until then a submission waits in `tender_extract` and a webhook
   delivery in `webhook_deliver`, both `queued`.
2. **Mint an API key** (`/admin`, scopes `read`, `write`, `review:mint`) and run the
   `docs/CONNECTOR.md` checks against the live engine; record the outcome in the Block 6
   report.
3. **Model calls the build could not make** under the subscription-only rule of
   2026-10-28, each with its estimate: the rule-15 reviews of Blocks 5, 6 and 7 and of the
   whole Stage 7 diff (`make review`, under USD 5 a run); Bikaner's six unfinished Block 4
   runs (`scripts.ingest_tenders resume`, about USD 15); `make ask-eval` (about USD 3); the
   `identity_and_scope` re-read of the eleven gold tenders under schema v5 and the eval
   after it (`scripts.ingest_tenders extract --groups identity_and_scope --force`, about
   USD 6 to 12 through the batch API, then `make eval`).
4. **GCP**: the backup bucket and the `tender-backup` key (Block 0 report, Cloud Shell
   block); a snapshot schedule; the Google OIDC client for sign-in; Cloud Run if wanted
   (`infra/cloudrun/README.md`).
5. **Reviews**, when they resume: the nine open Block 1 fields (links in
   `/work/stage7-links.txt`), the Block 4 tenders, the 116 awards.

Everything else that is missing is a row of `docs/KNOWN-GAPS.md`.
