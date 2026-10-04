# Stage 0B report: scaffold

Date: 2026-10-04. The stack is running on the VM at `https://34.131.65.108/`.

## Acceptance checks (section 14, row 0B)

| Check | Result |
| --- | --- |
| Static IP recorded | `34.131.65.108` in `infra/STATIC-IP.txt` and `docs/DECISIONS.md`; address `tender-engine-ip` is `IN_USE` |
| Firewall shows only allowlisted ranges on 22 and 443 | 22: `35.235.240.0/20` (IAP) only. 443: `0.0.0.0/0` plus the IAP range. **443 is open to the world by user decision**, which departs from the locked decision; recorded in DECISIONS.md and KNOWN-GAPS.md |
| `make deploy` answers `https://<static-ip>/health` | Yes, from the VM: `{"status":"ok","tenant_id":"ergplan","database":"ok"}`. Confirmed from the user's browser outside the VM on 2026-10-04: the page showed "API and database are up. Tenant: ergplan" |
| `make test` green | 33 Python tests and 3 web tests pass |
| 11 tenders in `/work/tenders` with manifests | 12 tenders, 41 PDFs, 3191 pages, 12 manifests (done in Stage 0A) |
| One mocked LLM call writes an `llm_call_log` row | `tests/core/llm/test_client.py`, 14 cases: success, refusal, truncation, schema failure, four API error classes, unregistered prompt |
| Tests watcher running and writing `.ci/status.json` | `tests` service is up; eight checks green; the pre-commit hook was shown to refuse a commit over a deliberately failing test |
| `ARCHITECTURE.md` committed | Yes, written before any application code |

## What was built

- **Layout.** `core/`, `tender/`, `api/`, `worker/`, `web/`, `infra/`, `tests/`, `scripts/`, `migrations/`, `docs/`. Additions to the fixed layout are listed in `docs/ARCHITECTURE.md` under "Repository layout".
- **Compose stack.** `db` (postgres:16), `api` (FastAPI, uvicorn), `worker` (same image), `web` (Vite dev server), `caddy` (TLS from its internal CA on the static IP; `/health` and `/api/*` to the API, everything else to the web app), `tests` (the watcher). One shared `/data` directory; `/work/tenders` mounted read-only.
- **Database.** Alembic migration 0001 creates `tenant` (seeded with `ergplan`) and `llm_call_log`. Every table carries `tenant_id`, `created_at`, `created_by`; a test fails if a table is added without them, and another checks the migrated schema against the models.
- **API.** `GET /health` and `GET /api/v1/health` report the database and the tenant row; 503 with a typed error when either is missing. Every response carries `X-Request-Id`.
- **LLM boundary.** `core/llm/client.py` has one call path: typed request, Pydantic output schema via `messages.parse`, prompt loaded by name and version from `core/llm/prompts/`, SDK retries with backoff (4), and one `llm_call_log` row for every outcome. A test fails if any file outside `core/llm/` imports the Anthropic SDK.
- **Watcher.** `infra/ci/run_checks.py` runs ruff check, ruff format, mypy (strict), alembic upgrade and check, pytest, OpenAPI client drift, tsc and vitest on every save, and writes `.ci/status.json` and `.ci/latest.log`. A full run takes about one to two minutes on this VM.
- **Pre-commit hook.** `infra/hooks/pre-commit`, enabled by `make up` or `make hooks`. It waits for the watcher to finish checking the staged files and refuses the commit if any check is red.
- **Makefile.** `up`, `down`, `test`, `test-e2e`, `check`, `watch`, `migrate`, `deploy`, `logs`, `smoke`, `client`, `hooks`.
- **CI.** `.github/workflows/ci.yml` runs the same `run_checks.py --once` on every push.
- **Web.** React 18, TypeScript, Vite 6, Tailwind. One page that shows API status through the generated client in `web/src/api/`.

## Real LLM calls made (both logged)

| Call | Input | Result | Tokens in / out | Latency |
| --- | --- | --- | --- | --- |
| `make smoke` | text only | "The connection works…", `saw_document=false` | 462 / 45 | 3.4 s |
| `make test-e2e` | 1-page SECI pre-bid notification as native PDF | "The document was issued by Solar Energy Corporation of India Limited (SECI).", quote copied verbatim from the page | 2696 / 69 | 4.0 s |

Model returned: `claude-fable-5-1`. The key works and native PDF input works.

## Skipped or deferred, and why

- **`make trace`, `make report`.** They need schemas, routes, UI and gold data. Stages 3 and 4.
- **PDF libraries.** `pdfplumber` and `pymupdf` are installed in Stage 1 with the parse service.
- **Playwright nightly job.** No UI flows exist to test until Stage 3.
- **Refusal fallback model.** Not enabled, so all results come from one model (DECISIONS.md).
- **`pytest-watcher`.** Replaced by one watcher script on `watchfiles`, because all checks must land in one status file (DECISIONS.md).
- **Part B step 5 (tenders).** Already done in Stage 0A.

## Deviations to be aware of

- 443 open to 0.0.0.0/0 (your decision). The Stage 4 admin dashboard will need its own guard.
- GCP changes cannot be made from the agent session; you run `infra/firewall.sh` with the `!` prefix.
- The VM has 2 vCPU, 3.9 GB RAM and a 10 GB disk with 2.2 GB free. Stage 1 renders pages at 150 dpi and Stage 2 processes 3191 pages. **Update, same day:** the disk was grown to 200 GB and the filesystem extended online; 182 GB free. CPU and memory are unchanged.

## Open questions

1. Add the NHPC FDRE Tranche-II RfS (264 pages, in the FDRE reference repo) as a 13th tender?
2. Ingest the standard PPA/PSA/CfDA documents as extraction inputs, or keep them as attachments? Needed by Stage 2.
3. Guard for the admin dashboard now that 443 is public. Needed by Stage 4.
4. Disk resized to 200 GB (done). The machine type is still 2 vCPU and 3.9 GB RAM; change it only if Stage 1 runs short of memory.

## Closed after the report

- External reachability confirmed by the user in a browser on 2026-10-04.
- Disk grown to 200 GB; NHPC FDRE-II added as the 13th tender; tender documents-with-roles decision and operating rule 15 recorded (see DECISIONS.md).

Stage 0 is complete. Next: `Run Stage 1 of docs/MASTER-PROMPT.md.`
