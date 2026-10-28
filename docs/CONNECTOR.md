# Connecting to the Tender Intelligence Engine

The engine serves every caller the same way (Stage 7, Block 6): a REST v1 behind API keys,
an MCP server over streamable HTTP behind OAuth 2.1 (or an API key), an OpenAPI 3.1 document
and function definitions a model can be handed, and a thin Python client. Whatever the
caller, the rule is the same: **the tender document is the authoritative source**; a value
is a reviewer's decision only where `source` says `approved`, and nothing the engine
answers is a fact on its own.

The live engine is at `https://34.131.65.108` (the VM's static address, a certificate from
Caddy's internal CA: clients must accept it or pin it). On Cloud Run it is the service URL
of `tender-api` (`infra/cloudrun/README.md`).

## Keys and scopes

An administrator mints an API key on the admin page (`/admin`) or with
`POST /api/v1/admin/api-keys` (`{"name": "…", "scopes": [...]}`); the secret
(`tie_live_…`) is shown once. Every request carries it as `Authorization: Bearer tie_live_…`
and the header `X-Public-Request: 1` (the mark of a request from outside the deployment).

| Scope | Lets the key |
| --- | --- |
| `read` (always) | read tenders, the published view, changes, `status`, `fields`, the webhook registry |
| `model` | call the model for the caller: `ask` and the cross-tender question |
| `write` | submit tenders and amendments, register and deactivate webhooks |
| `review:mint` | mint a review link for a named reviewer |

Every key has a rate limit per minute and a daily cap; every call is metered to the
key's tenant.

## REST v1 (`docs/contracts/openapi.v1.json`)

| Operation | Route | Scope |
| --- | --- | --- |
| Submit a tender (file or official URL) | `POST /api/v1/tenders/submit` (multipart: `file` or `source_url`; `tender_type`, `agency`, `title`, `external_ref`, `issued_on`, `priority`) | `write` |
| Submit an amendment | `POST /api/v1/tenders/{id}/submit-amendment` (`kind` corrigendum/amendment/clarification; `file` or `source_url`; `issued_on`, `summary_of_change`, `force`) | `write` |
| Extraction status | `GET /api/v1/tenders/{id}/status` | `read` |
| The snapshot, contract v1 | `GET /api/v1/tenders/{id}/fields` | `read` |
| Changes with impacts | `GET /api/v1/tenders/{id}/changes` | `read` |
| Ask one tender | `POST /api/v1/tenders/{id}/ask` `{"question": "…"}` | `model` |
| Ask across tenders | `POST /api/v1/tenders/ask` | `model` |
| A review link for a named reviewer | `POST /api/v1/tenders/{id}/review-link` `{"reviewer_name": "…"}` | `review:mint` |
| Webhooks | `POST`/`GET /api/v1/webhooks`, `DELETE /api/v1/webhooks/{id}`, `GET /api/v1/webhooks/{id}/deliveries` | `write` to change, `read` to list |

A submission by URL is fetched only from a domain on `infra/source-domains.yaml` (the
agency's own site); anything else is refused with the reason. A submitted document is
parsed, mapped, indexed and read without another call; `status` reports each version's
stage (`parsing`, `mapping`, `extracting`, `validated`, `failed`) and `extraction_done`.

**The snapshot** (`docs/contracts/snapshot.v1.schema.json`) lists every field of the
record with `value`, `unit`, `state` (`value`, `withdrawn`, `not_stated`), `source`
(`approved`, `machine`, `none`), `confidence` (machine readings only), `version_no` and
`version_kind`, and `evidence` (document, page, quote, whether the resolver located it).
The contract is additive only: a property, once published, keeps its name and type and
never becomes required; `make check` refuses a change that is not (`contract_drift`).

**Webhooks.** Register a URL with the events wanted: `extraction_done` (a tender's runs
all validated), `review_complete`, `new_version` (a version added), `amendment_detected`
(the weekly freshness check found a new document on the source page; nothing is
ingested). Every delivery is a JSON POST with `X-Tender-Event`, `X-Tender-Delivery` and
`X-Tender-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 over "<t>.<raw body>">` using the
endpoint's secret; answer 2xx. A failed delivery is retried six times with backoff (30 s,
60 s, …) and then marked `failed`; `GET /api/v1/webhooks/{id}/deliveries` shows each one.
`client/tender_engine_client.py` has `verify_webhook`.

## MCP (`/mcp`, streamable HTTP)

Tools: `search_tenders`, `get_tender`, `get_field`, `get_document_page`,
`find_matching_tender`, `list_changes`, `compare_tenders`, `reliability_report` (free tier,
the public library); `ask_tender`, `get_status`, `get_changes`, `submit_tender`,
`submit_amendment`, `get_review_link`, `model_tender`, `save_model_assumptions`,
`my_watchlist` (paid tier). `submit_*` need the write scope on the token (`own:write`
from the OAuth consent, or `write` on an API key); `get_review_link` needs `review:mint`
(or `own:write`). Submissions through MCP take the official URL of the document.

Authentication: OAuth 2.1 with dynamic client registration and PKCE (`/.well-known/
oauth-authorization-server`, `/register`, `/authorize`, `/token`; the consent page needs a
signed-in user, so the Google sign-in must be configured), or an API key as the bearer
token for a client that cannot run the OAuth flow.

**Claude Code**

```
claude mcp add --transport http tender https://34.131.65.108/mcp
```

Claude Code runs the OAuth flow in the browser on first use (`/mcp` in the session shows
the state); with an API key instead: `claude mcp add --transport http tender
https://34.131.65.108/mcp --header "Authorization: Bearer tie_live_…"`.

**Claude.ai**: Settings → Connectors → Add custom connector → URL
`https://34.131.65.108/mcp`; sign in on the consent page when asked. The widgets (tender
card, changes view, comparison table, financial model) render in the chat where the host
supports MCP Apps; every tool answers in text as well.

**ChatGPT (connectors)**: Settings → Connectors → Create → the same URL. The server speaks
the streamable-HTTP transport and OAuth 2.1 the connector expects; **this path is not tested
from this build** (no OpenAI account: the owner's decision of 2026-10-27), and the first
connection is the owner's check. **The OpenAI Responses API remote MCP tool**
(`tools=[{"type": "mcp", "server_url": "https://…/mcp", "authorization": "tie_live_…"}]`)
takes the same server; the same note applies.

**Any other MCP client** (the Python `mcp` package, for instance):

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    "https://34.131.65.108/mcp", headers={"Authorization": "Bearer tie_live_…"}
) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        print(await session.call_tool("get_status", {"tender": "seci-ess-iv"}))
```

## A Python product (`client/tender_engine_client.py`)

Standard library only; copy the file or install it as a module.

```python
from tender_engine_client import TenderEngine, verify_webhook

engine = TenderEngine("https://34.131.65.108", api_key="tie_live_…", verify_tls=False)
made = engine.submit_tender(source_url="https://www.seci.co.in/…/RfS.pdf", tender_type="solar")
status = engine.wait_until_done(made["tender_id"])
snapshot = engine.fields(made["tender_id"])
deadline = next(
    f for f in snapshot["fields"] if f["path"] == "core.key_dates.bid_submission_deadline"
)
print(deadline["value"], deadline["source"], deadline["evidence"])
```

`verify_tls=False` is for the VM's internal certificate only; on Cloud Run keep the default.

## Function definitions for a model (`docs/contracts/functions.v1.json`)

One entry per REST operation in the shape `{"type": "function", "name", "description",
"parameters"}` with `x-method` and `x-path` to call it: hand the list to a model as its
tools and route each call to the REST route. A multipart file is sent as `source_url`
(the official URL) from a model; the OpenAPI document serves the same purpose for a client
that reads OpenAPI (ChatGPT Actions, code generators).

## Regenerating the contract

`python -m scripts.export_contract --write` after a change to the routes or the snapshot;
`--check` (in `make check`) refuses a stale file and a non-additive change of the snapshot.
`python -m scripts.export_openapi --write` keeps the web client's types in step.
