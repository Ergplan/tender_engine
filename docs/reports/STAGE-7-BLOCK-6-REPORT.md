# Stage 7, Block 6 report: serve it to every caller (2026-10-27 to 2026-10-28)

Block 6 of the owner's completion plan: a REST v1 behind API keys (submit a tender or an
amendment, status, the snapshot as contract v1, changes with impacts, ask, a review link for
a named reviewer), webhooks signed and retried, the MCP server with write tools for Claude
and OpenAI clients, an OpenAPI 3.1 document usable as function definitions with a thin
Python client, and `docs/CONNECTOR.md`. Built under the owner's decisions of 2026-10-27 (no
OpenAI account; the MCP server must still serve OpenAI clients) and, from 2026-10-28, the
owner's rule that the build session uses the subscription only: no call through the app's
API key, so nothing in this block cost a model call.

## Definition of done

| Item | State | Evidence |
| --- | --- | --- |
| (a) REST v1 with API keys: submit a tender (file or official URL) and an amendment; status; the snapshot with value, unit, page, quote, version, state, approved or machine, confidence; changes with impacts; ask; a review link for a named reviewer; the snapshot JSON Schema as contract v1, additive only, with a contract test | Done | `api/v1/tenders/contract.py`; `tender/services/submit.py`, `status.py`, `snapshot.py`; `docs/contracts/snapshot.v1.schema.json`; `tests/api/test_contract.py` (4), `tests/tender/test_submit.py` (5), `test_snapshot_status.py` (4), `tests/scripts/test_export_contract.py` (3: the additive rule, the drift check, the routes covered) |
| (b) Webhooks: extraction done, review complete, new version or amendment detected; signed and retried | Done | `core/services/webhooks.py`, `core/models/webhook.py`, migration 0025; `tests/core/services/test_webhooks.py` (5) |
| (c) MCP over streamable HTTP with the existing OAuth, for Claude.ai, Claude Code and OpenAI; the ten named tools; read tools kept; write tools need the write scope | Done in code; the live connection from each client is the owner's check (below) | `mcpserver/server.py`, `tools.py`, `auth.py` (`own:write`); `tests/mcpserver/test_tools.py::test_the_write_tools_need_the_write_scope_and_file_a_tender_from_its_official_url`, the server tests (tool count, a call through a client session) |
| (d) OpenAPI 3.1 for REST v1 usable as OpenAI function definitions; a thin Python client | Done | `scripts/export_contract.py`, `docs/contracts/openapi.v1.json`, `functions.v1.json`; `client/tender_engine_client.py`; `contract_drift` in `make check` |
| (e) `docs/CONNECTOR.md` for Claude Code, Claude.ai, ChatGPT, the Responses API and a Python product; each tested end to end against the live engine | The guide is written; **the live tests are not run from this build** (below) | `docs/CONNECTOR.md`; KNOWN-GAPS |

## (a) REST v1

`POST /tenders/submit` takes a multipart form: `file` or `source_url`, and `tender_type`,
`agency`, `title`, `external_ref`, `issued_on`, `priority`. A URL is fetched only from a
domain on `infra/source-domains.yaml` (the agency's own site, the 2026-10-07 rule applied to
callers); anything else is refused with the reason, as is an unknown tender type. The same
file again (by its sha256) is the same tender, answered `created: false`, and nothing is
read twice. The document goes down the chain the worker always runs (parse, section map,
index); a `tender_extract` job waits until the version's documents are parsed and, when the
caller named no type, until the classifier has answered, then starts the reading, through
the batch API (half price) unless `priority` asked for direct calls. The answer is 202 with
the tender id, the version number and `status_path`.

`POST /tenders/{id}/submit-amendment` (`kind` corrigendum, amendment or clarification;
`file` or `source_url`; `issued_on`, `summary_of_change`, `force`) runs Block 3's link check
first: a document that names another tender is refused with the candidates unless `force`;
then `add_version`, the amendment plan and the reading as for any later version.

`GET /tenders/{id}/status` reports, per version, its documents and where each stands, its
runs, the jobs still pending, and the stage (`submitted`, `parsing`, `mapping`,
`extracting`, `validated`, `failed`); for the tender, `extraction_done`, the review state
and the publication state.

`GET /tenders/{id}/fields` is **the snapshot, contract v1**: every field of the record with
`value`, `unit`, `state` (`value`, `withdrawn`, `not_stated`), `source` (`approved`,
`machine`, `none`), `confidence` for machine readings, `version_no` and `version_kind`, and
`evidence` (document, page, quote, whether the resolver located it on the page again).
Approved values come from the current view (canonical facts over the versions), machine
readings from each version's review state, the latest valued version winning, the way the
summary picks them. The contract is additive only: a property, once published, keeps its
name and type and never becomes required (`scripts.export_contract.additive_change`;
`--check` in `make check` as `contract_drift`, and the unit test).

`GET /tenders/{id}/changes` and `POST /tenders/{id}/ask` stand where Blocks 3 and 5 put
them. `POST /tenders/{id}/review-link` (`reviewer_name`) mints a review token the way the
admin route does and answers the link; it needs the `review:mint` scope. The API-key scopes
are now `read` (always), `model` (the ask routes), `write` (submissions, webhook changes)
and `review:mint`; the middleware's `_SCOPED` table refuses a route the key's scopes do not
cover (`tests/api/test_contract.py::test_an_api_key_needs_the_scopes_the_routes_want`).

## (b) Webhooks

`POST /webhooks` registers a URL with the events wanted and a secret of sixteen characters
at least (shown to nobody afterwards); `GET /webhooks`, `DELETE /webhooks/{id}` (deactivate),
`GET /webhooks/{id}/deliveries`. Events: `extraction_done` (emitted when `after_validation`
reports the tender's runs settled and the summary queued), `review_complete`
(`complete_review`), `new_version` (`add_version`, in the same transaction as the version),
`amendment_detected` (the weekly freshness check found a new or changed document on the
source page; nothing is ingested). `emit` writes one pending delivery per subscribed active
endpoint and queues a `webhook_deliver` job; the deliverer POSTs the JSON payload with
`X-Tender-Event`, `X-Tender-Delivery` and `X-Tender-Signature: t=<unix seconds>,v1=<hex
HMAC-SHA256 over "<t>.<raw body>">`, six attempts with backoff (30 s, 60 s, 120 s, …), then
`failed`. `client/tender_engine_client.py` has `verify_webhook` with a tolerance on `t`.
Tests: the signature round trip and its tolerance, the registration checks, one delivery
per subscribed endpoint, a failing receiver retried and given up, the payload of the review
and amendment events (`tests/core/services/test_webhooks.py`, 5; the runner's deliveries
land in `WebhookSink`, a mock transport in `tests/conftest.py`).

## (c) MCP

The server at `/mcp` (stateless streamable HTTP, the OAuth 2.1 server of Stage 5D) gains
`get_status`, `get_changes` (the changelog under the contract's name; `list_changes` stays),
`submit_tender` (official URL only through a tool call), `submit_amendment` and
`get_review_link`; `search_tenders`, `get_tender`, `get_field`, `ask_tender` and
`reliability_report` were already there, so the plan's ten names all answer. The OAuth
scope `own:write` is added to `SCOPES`: a client asks for it, the consent grants it to an
enterprise plan, and an API key with `write` acts the same; `get_review_link` needs
`review:mint` or `own:write`. Without the scope the write tools refuse in plain words
(`tests/mcpserver/test_tools.py`, the write-tools test); the server tests count the tools
and call one through an MCP client session over HTTP.

## (d) The contract and the client

`python -m scripts.export_contract --write` regenerates `docs/contracts/`: the snapshot's
JSON Schema, an OpenAPI 3.1 document of the caller's routes (contract, ask, published)
with the `ApiKey` security scheme and the server URL, and `functions.v1.json`, one
`{"type": "function", "name", "description", "parameters"}` per operation with `x-method`
and `x-path`, the shape a model's `tools` list takes; the path and query parameters and the
body are one flat parameters object, an optional upload becomes a string (or `source_url`
instead), and the identity headers are left out (they are the caller's transport, not an
argument). A fix of 2026-10-28: FastAPI writes an optional upload as `anyOf` with
`contentMediaType` under OpenAPI 3.1, which the exporter had looked for as `format: binary`
at the top level; the contract test caught it. `client/tender_engine_client.py` is a
standard-library client (`submit_tender`, `submit_amendment`, `status`, `fields`,
`changes`, `published`, `ask`, `ask_across`, `review_link`, webhooks, `wait_until_done`,
`verify_webhook`); `client/` is a folder added to the layout (ARCHITECTURE).

## (e) The connector guide and the live checks

`docs/CONNECTOR.md` says how to connect from Claude Code (`claude mcp add --transport http`,
OAuth in the browser or an API key header), Claude.ai (custom connector), ChatGPT
(connector) and the OpenAI Responses API remote MCP tool (same URL, untested here: no
OpenAI account, the owner's decision of 2026-10-27), any MCP client in Python, and a
Python product through the client.

**The end-to-end tests against the live engine are not run from this build.** The live
engine serves the Block 6 routes (the api runs the mounted tree and reloaded; its OpenAPI
lists `submit`, `status`, `fields`, `review-link` and the webhook routes; every one answers
401 without identity). Three things stood in the way on 2026-10-28, all the owner's to lift:

1. No API key exists on the live engine, and minting one from the build session was
   refused by the permission classifier (it adds access). The owner mints one on `/admin`
   or with `POST /api/v1/admin/api-keys` (scopes `read`, `write`, `review:mint`).
2. The live worker still runs with Block 5's handlers; the restart that loads
   `tender_extract` and `webhook_deliver` was refused to the build session the same way.
   The owner's `docker compose restart worker` (or `make deploy`) lifts it; a submission or
   a delivery queued before that waits as `queued` and is not lost.
3. A live submission reads the tender through the model (about USD 0.045 a page through
   the batch API), which the owner's subscription-only rule forbids from here.

What the owner can run, in `docs/CONNECTOR.md`'s words, once a key exists: `status`,
`fields` and `changes` on a gold tender (no model call), the webhook registry, the Python
MCP client's `get_status`, `claude mcp add` from Claude Code, the Claude.ai connector; and,
when they allow the spend, one submission by official URL with a webhook registered for
`extraction_done`. The outcome goes into this section.

## Tests

The block's tests were written with the code (CLAUDE.md rule 3): 22 new tests in the five
new test files (`tests/api/test_contract.py` 4, `tests/tender/test_submit.py` 5,
`tests/tender/test_snapshot_status.py` 4, `tests/core/services/test_webhooks.py` 5,
`tests/scripts/test_export_contract.py` 3) and one in `tests/mcpserver/test_tools.py`; the
MCP server test's tool count and fixture were extended. The job chain's test fixtures gained
the `WebhookSink` and the MCP fixture a submit transport, so no test reaches a real site.
The full `make check` run this commit stands on is recorded below.

Run 13 (`stage-7-artifacts/check-run13.log`, 2026-10-28 18:38 UTC, 2,486 s) was red on one
test and nothing else: `tests/core/services/test_identity.py` used `write` as its example of
an unknown scope, which this block made a real one (the test now uses `delete`; Block 7's
commit holds the change). Run 15 (`check-run15.log`, 2026-10-28 20:12 UTC, 2,365 s, every
check green, `ci-status-block-7.json`) is the run this commit and the Block 7 commit stand on:

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

## Deployment

The api serves the block already (the mounted tree, uvicorn reloads); migration 0025 is
applied on the live database (`alembic current` says 0025). The worker needs the owner's
restart (above). No new dependency was added, so no image rebuild is needed.

## Independent review (operating rule 15)

**Waits on the owner** (the reviewer is a model call through the app's key, forbidden by
the subscription-only rule of 2026-10-28): `make review STAGE=7
RANGE=stage-7-block-6-start..stage-7-block-7-start PROMPT=docs/COMPLETION-PLAN.md`,
about the cost of one long Opus 5.5 call over the block's diff (Block 5's estimate: under
USD 5 a run). Block 5's review is in the same state. When the owner allows them, both run,
their code defects are fixed in Block 7's tree, and the findings are listed here and in
the Block 5 report with the outputs under `stage-7-artifacts/`.

## Costs

No model call in this block (the one-token probe of 2026-10-28 that the owner saw was
outside the app, about USD 0.0001, and is the reason for the subscription-only rule).
Ledger total unchanged at USD 502.76.

## Open questions

- The ChatGPT connector and the Responses API remote MCP tool are untested (no OpenAI
  account; KNOWN-GAPS). The server speaks the transport and OAuth they document.
- The snapshot carries machine readings marked `machine` with their confidence; a caller
  that wants only reviewed values filters on `source == "approved"` or reads the published
  view. Whether the contract should offer that filter as a query parameter is a v1.1
  addition when a product asks for it.
