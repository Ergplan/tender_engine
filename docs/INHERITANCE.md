# INHERITANCE.md: what the Tender Intelligence Engine takes from the two reference repos

Written in Stage 0A (2026-10-04) from a read-only pass over `/work/ref/tariff-oder` (91 commits, ~20k lines of Python, Next.js UI, Terraform) and `/work/ref/FDRE` (2 commits; an FDRE optimiser/EYA toolkit with a tender RAG script and enterprise design documents). Both repos are inputs only. Code marked **keep** is copied into this repo with its origin noted in a comment; nothing is imported from `/work/ref/` at runtime and neither repo becomes a submodule.

Paths are relative to each repo's root. Ratings: **keep** (copy with renames), **adapt** (take the idea, rewrite), **discard**.

---

## Part 1: `tariff-oder` (Tariff Order Intelligence)

### Stack and pinned dependencies

| Layer | What the repo uses | Where |
| --- | --- | --- |
| Python | `requires-python = ">=3.11,<3.13"`, built and tested on `python:3.11-slim-bookworm`; ruff/mypy target `py311` | `pyproject.toml:5,26,45`, `infra/local/Dockerfile.python:3` |
| API | `fastapi>=0.115,<1`, `sqlalchemy>=2.0.36,<3` (DeclarativeBase/Mapped), `alembic>=1.14,<2` (14 migrations), `pydantic>=2.10,<3`, `pydantic-settings>=2.7,<3`, `psycopg[binary,pool]>=3.2` | `services/api/pyproject.toml:6-24`, `services/api/migrations/versions/0001..0014` |
| Database | PostgreSQL 16 (`pgvector/pgvector:pg16` locally and in CI; Cloud SQL `POSTGRES_16`); pgvector extension created but no vector column exists | `infra/local/docker-compose.yml:9`, `.github/workflows/ci.yml:18`, `infra/gcp/sql.tf:12` |
| PDF | `pymupdf>=1.25`, `pdfplumber>=0.11`, `pypdf>=5.1` (declared, unused), optional `docling>=2.100`, tesseract via apt | `services/api/pyproject.toml`, `infra/local/Dockerfile.python` |
| LLM | Raw `httpx.post` to the Anthropic Messages API, `anthropic-version: 2023-06-01`, default model `claude-sonnet-5`; no SDK | `services/api/src/tariff_api/providers.py:418-427`, `config.py:94` |
| Retrieval | `haystack-ai>=2.10,<3` for BM25 passage retrieval only | `services/api/pyproject.toml:23`, `assessment.py:64-119` |
| Web | **Next.js 16.3.5 / React 19.3.0**, TypeScript 5.9.3, `output: "standalone"`, server-side proxy routes under `apps/web/app/api/**`; no test framework | `apps/web/package.json:14-16`, `apps/web/next.config.ts:4`, `apps/web/lib/api.ts:52-72` |
| Tooling | `uv` workspace (`services/api`, `services/worker`), `pnpm@10.20.0`, `openapi-typescript 7.13.0` with a CI drift check, Terraform 1.13.4 | `pyproject.toml:8-9`, `package.json:4`, `packages/contracts/scripts/check-drift.mjs`, `ci.yml:66-67` |

### Data model (one line per table)

Single models file `services/api/src/tariff_api/models.py` (988 lines); `audit_events` is append-only by DB trigger (`migrations/versions/0001_foundation.py:228-234`).

| Table | Purpose and key columns | Writer |
| --- | --- | --- |
| `datasets` | `kind` real/fixture isolation | `services/sources.py:get_or_create_dataset` |
| `users` | email, role analyst/reviewer/administrator, active | `cli.py:cmd_users`, registry router |
| `jurisdictions`, `commissions`, `utilities` | registry; `utilities.active_reading_profile` | `seed.py`, `routers/registry.py` |
| `source_documents` | immutable upload: unique `sha256`, `object_key`, 16-state `state` enum with explicit transitions (`models.py:79-146`), per-stage versions and summaries as JSONB, `assigned_to`, optimistic `version` | upload service and every worker stage |
| `source_pages` | 1-based `page_index`, printed/declared/observed labels, `text_chars`, `has_text_layer`, `page_class`, `page_role`, `quality_flags`, OCR provenance (`ocr_used`, `ocr_engine`, `ocr_confidence`, `ocr_agreement`) | inventory, triage, parse stages |
| `table_grids` | per-reader (pymupdf/pdfplumber) grid per page: `bbox`, row/col counts, `agreement_class`, `is_primary` | `stages/parse.py:_store_grids` |
| `document_headings` | heading inventory, `code_canonical`, `text_source`, `rules_version` | parse stage |
| `stage_artefacts` | index of immutable JSON artefacts keyed `<sha>/<stage>/<tool_version>/...`, `content_sha256` | every stage |
| `jobs`, `job_events` | Postgres queue: idempotency key, lease owner/expiry, run-id fencing, checkpoint/progress JSONB, cancel flag | `queue.py` |
| `audit_events` | actor, action, entity, before/after JSONB, request_id; DB-enforced append-only | transitions, review, publication |
| `idempotency_records` | (key, actor) PK, request fingerprint, stored response | upload and decision routers |
| `localisation_records`, `localisation_regions` | where the binding schedule is; `status` proposed/ambiguous/confirmed/corrected; `extraction_allowed` gate; reviewer `excluded`/`reviewer_note` | localise stage, reviewer endpoints |
| `structure_cells` | every numeric cell: (page, grid, row, col), `header_path`, `row_path`, `normalised`, unit binding with `unit_source`, flags, footnotes | `stages/grid.py` |
| `clause_values` | clause-outline value lines with `clause_path`, role, `line_text` | grid stage |
| `extraction_runs` | one row per provider call: provider, model, `prompt_version`, `schema_version`, `is_fixture`, `input_hash`, tokens, `cost_usd`, status/error | `stages/extract.py:556-581` |
| `candidates` | the proposal: denormalised value columns plus full `record` JSONB, `image_record`, `channel_agreement`, `confidence`, `risk_tags`, `routing`, `review_status`, `reviewed_record`, `first_reviewer`, `second_review`, `version`, `published_release_id` | extract (insert), validate (routing), review service (status) |
| `validator_findings` | VAL-xx id, severity, candidate ids | `stages/validate.py` |
| `family_dispositions` | reviewer declares a charge family absent/out of scope | `routers/candidates.py:set_disposition` |
| `category_summaries` | generated prose with provider/model/prompt_version/`grounded`/`unsupported_numbers` | extract stage |
| `condition_records` | verbatim provisions and footnotes, `scope_codes`, `interpretation_status` | extract stage |
| `evidence_views` | proof that page N of candidate X was rendered to viewer Y at dpi D | `services/review.py:render_evidence` |
| `review_decisions` | append-only decisions: sequence, round, outcome, reviewer, `candidate_version`, rationale, `cause_tag`, `corrected_record`, `evidence_view_ids`, before/after snapshots, undo fields | `services/review.py:decide/undo` |
| `data_releases` | publication transaction: scope, completeness, gaps, `preview_token`, `is_current` | `services/publication.py:publish` |
| `published_facts`, `published_evidence` | canonical facts copied from the effective record, with evidence rows (page, printed label, grid/row/col/line, excerpt) | `services/publication.py:289-333` |

### Document ingestion and parsing path

- Upload `POST /sources` (`routers/sources.py:198-280`) → `services/sources.py:register_upload` (:176-274): PDF header check, pymupdf probe, size and page limits, SHA-256 dedup, `storage.put(SOURCES, f"{sha}.pdf")`, enqueue `inventory_source`.
- Storage: `adapters/storage.py`, `FilesystemObjectStore` / `GcsObjectStore` behind an `ObjectStore` ABC.
- Worker chain over a Postgres queue: `inventory → triage → parse → localise → (reviewer confirms localisation) → grid → extract → validate → awaiting_review` (`services/sources.py:277-285`, `services/worker/src/tariff_worker/main.py:23-31`).
- Inventory (`inventory.py:63-126`): per-page `text_chars`, labels, rotation, image/drawing counts. Triage (`triage.py`): page class, quality flags, printed-label inference, `ocr_recommended`. Parse (`stages/parse.py:98-333`): tesseract TSV OCR with word-level confidence and boxes (`ocr.py:88-176`), two table readers with agreement scoring (`readers.py:111,139,339`), headings. Grids are never built from OCR pages (`parse.py:206-207`).
- Granularity stored: page-level text stats and table-level bbox only. **No cell-level bboxes and no char offsets** (consequence recorded in `docs/decisions/ADR-0013-review-workflow.md:66-68`). Evidence is (page, grid, row, col, excerpt) or (page, line).
- Chunking: none for text. Image channel sends 2 pages per call (`config.py:101`, `stages/extract.py:326-351`), with a one-page re-read on truncation. Assessment uses ~500-char Haystack passages with BM25 top-4.

### LLM calls: built, prompted, retried, validated, logged

- `AnthropicProvider` (`providers.py:383-581`) forces `tool_choice` to a single tool whose `input_schema` is `ExtractionOutput.model_json_schema()` (`tariff_schema.py:231-233`). `FixtureProvider` is the default (`config.py:93`). The "structure channel" is deterministic rules, never the model (`stages/extract.py:306-310`).
- Prompts are inline Python strings with hand-bumped integer version constants: `SYSTEM_PROMPT` (`providers.py:76-86`, `PROMPT_VERSION="1"` in `extraction.py:20`), `image_prompt()` (`providers.py:587-631`, `IMAGE_PROMPT_VERSION="4"` at :584, never persisted), `ASSESSMENT_SYSTEM_PROMPT` (`assessment.py:36-51`), `SUMMARY_SYSTEM_PROMPT` (`summaries.py:38-47`). No prompt files, no registry, no prompt text hash.
- Validation: `normalise_tool_output → recover_truncated → coerce_candidates` (per-candidate `model_validate`, bad rows dropped) → `ExtractionOutput.model_validate` (`providers.py:436-441`); schema failure raises non-retryable `ProviderUnavailable`. `value` is a `Decimal` string; `evidence` has `min_length=1` (`tariff_schema.py:169,183-194`).
- Retries: none at HTTP level (single `httpx.post`, 120 s timeout). Failures become `JobFailure(retry=...)` and the queue retries the whole job up to 3 times (`queue.py:205-253`); `extract_source` saves a per-region checkpoint (`stages/extract.py:363`) but never reads it, so a retry re-spends every region.
- Logging: no log line per provider call; instead every call persists an `extraction_runs` row plus request-hash/output/raw-response artefacts in the object store (`stages/extract.py:293-298, 311-320, 352-357, 466-477`). Prompt text is not stored, only `input_hash`. Cost from configured per-Mtok prices with a hard budget stop at $5 / 2M tokens per order (`config.py:95-96,102-103`, `extract.py:226-237`).
- Synchronous, blocking, and always inside the worker process; never in a FastAPI handler. The only other path is the CLI `provider-smoke` (`cli.py:102-198`).

### Where extracted values land; is model output ever treated as truth?

Write path: `stages/extract.py:extract_source → candidate_rows (:480-522)` deletes pending candidates and inserts `CandidateRecord(review_status="pending")` (:601-616). `validate_source` can only lower confidence or route to individual review (`stages/validate.py:148-154`). The human gate `services/review.py:decide` (:635-755) is the only writer of approved/corrected/rejected; it requires `EvidenceView` rows for the actor (:565-601), an `expected_version`, a rationale for anything but approve, and a different second reviewer where policy demands. `services/publication.py:publish` (:188-371) copies only approved/corrected candidates into `published_facts`; explorer routes read published tables only, with a test that the explorer module never reads candidates (`tests/integration/test_publication_and_explorer.py:94`).

Three places where model output mutates stored state before a human sees it:

1. `assessment.apply` writes the model's sub-category into `applicability.rate_block` when rules left it empty (`assessment.py:275-277`), which feeds `Candidate.key()` (`tariff_schema.py:214`) and therefore dedupe and pairing.
2. `Compared.primary` returns the image (model) candidate when the rules channel found nothing (`extraction.py:779-780`), and `candidate_rows` denormalises that value into `candidates.value` (`stages/extract.py:504-512`). Still gated, but the headline value shown to the reviewer can be an unverified model reading.
3. `category_summaries.text` is model prose shown to reviewers (labelled generated, grounding-checked, never published).

Verdict: candidate → human → canonical separation holds for everything published. The two leaks are pre-review enrichments; the new engine avoids them by having no "primary" selection step at all (every model value is a candidate, nothing else).

### Review and approval UI

- `apps/web/app/sources/[id]/review/review-workspace.tsx`: one candidate at a time; keyboard a/c/r/u/Enter/n/p/z; approve and change are disabled until the evidence image has loaded and returned an `x-evidence-view-id` header (:228-247); decisions carry an `Idempotency-Key` (:286-293); shows channel disagreement, validator findings and the generated summary with a grounding badge.
- `review/table/tariff-table.tsx` (589 lines): grid view per category with per-cell approve/reject/note, "approve all agreeing" (:291), undo own decision (:269-284). Localisation checkpoint UI, publish form, review queue.
- Candidate state machine (`services/review.py:48-49, 665-711`): `pending → approved|corrected` or `awaiting_second_review → approved|corrected`; `rejected`; `unresolved`. `undo` restores the before snapshot, only for the latest decision by its own reviewer, never after publication.

### What the tests actually assert

240 test functions: 181 unit (`tests/unit/`, 24 files) and 59 integration (`tests/integration/`, 17 files). No browser tests, no web unit tests. Harness `tests/conftest.py`: real Postgres via `TARIFF_TEST_DATABASE_URL`, schema dropped and migrated per session, filesystem store, `X-Local-User` identity, in-process worker.

- Negative paths are well covered: evidence-not-rendered 422, stale version 409, same-reviewer second review 422, correction without cause tag 422, undo 403, idempotency conflict 409 (`test_review_workflow.py:85-212, 254-263`); adversarial instruction text in a PDF (`test_extract_stage.py:240-253`); queue fencing and lease expiry (`test_queue.py`); worker kill mid-job and resume (`test_worker_recovery.py`).
- The real `AnthropicProvider` HTTP path is never exercised (no httpx mock; stubs subclass `FixtureProvider` at `test_extract_stage.py:277,313`). Thin: publication (2 tests), ARR (1), commissions/export (2); nothing for `budget_exceeded`, `GcsObjectStore`, or IAP signature verification.
- No accuracy eval exists: `tests/evals/README.md` is a placeholder and `tests/golden/manifest.json` has `reviewed_reference_facts: []`.

### Auth, tenancy, audit

- Identity adapters (`adapters/identity.py`): `LocalIdentityProvider` trusts `X-Local-User` for an allow-list and refuses under the gcp profile; `IapIdentityProvider` verifies IAP JWTs; `GoogleIdTokenIdentityProvider` verifies OIDC tokens. Roles analyst < reviewer < administrator from the `users` table (`auth.py:17-23`).
- Single tenant. No tenant column anywhere; isolation only by `datasets.kind` and the registry; reviewer assignment is advisory ("Not an access control", `models.py:288-290`).
- `audit_events` with actor/action/entity/before/after/request_id, UPDATE/DELETE forbidden by trigger and tested (`test_migrations.py:46`); request-id middleware (`main.py:67-92`).

### Deployment

`infra/local/docker-compose.yml`: pg16, optional minio, one-shot `migrate`, `api`, `worker --poll-seconds 1`, `web`, shared object-store volume. CI (`.github/workflows/ci.yml`): ruff, pytest with tesseract and pg16, OpenAPI drift check, tsc, next build, terraform validate, image build without push. GCP via Terraform (`infra/gcp/*.tf`): Cloud Run api/web, worker and migrate as Cloud Run Jobs, Cloud SQL pg16 with PITR, Secret Manager, IAP. Config by `pydantic-settings` with `validate_profile()` forbidding local adapters under gcp (`config.py:40-156`).

### Reliability patterns, rated

| Pattern | Rating | Reasoning | Path |
| --- | --- | --- | --- |
| Schema validation: Pydantic model doubles as the tool `input_schema`; per-candidate validate-and-drop; schema failure is non-retryable | **keep** | Exactly the "candidate must validate or be rejected" discipline; the unwrap/unstringify/truncation salvage is tested against real model quirks | `tariff_schema.py:146-233`, `providers.py:160-281, 436-446` |
| Confidence scoring: categorical from channel agreement plus risk tags; model confidence can only lower trust | **adapt** | Principle is right (model doubt never raises trust); tag vocabulary is tariff-specific; the new engine uses a 0-1 confidence capped by evidence resolution | `extraction.py:935-977`, `stages/extract.py:489-497` |
| Evidence linkage: (page, grid, row, col or line) plus exact excerpt, `min_length=1`; server-recorded evidence views | **adapt** | Strong provenance and the evidence-view idea is excellent; lacks char offsets and bboxes, which the new engine requires on every candidate | `tariff_schema.py:98-111`, `models.py:833-850`, `services/review.py:377-450` |
| Chunking: region → 2-page image chunks, truncation → per-page re-read; BM25 passages for assessment | **adapt** | Page-window plus truncation fallback is reusable for 20-40 page windows; no text chunking exists | `stages/extract.py:326-351, 692-731`, `assessment.py:64-119` |
| Retry and fallback: Postgres queue with `SKIP LOCKED`, lease fencing, heartbeats, bounded retries, typed `JobFailure(retry=...)`, per-order budget | **keep** (queue) / **adapt** (provider: add HTTP backoff and resume from checkpoint) | Durable queue is production-grade and matches the locked "Postgres-backed job table" decision | `queue.py`, `services/worker/src/tariff_worker/runner.py`, `providers.py:50-57, 417-431` |
| Eval harness | **absent** | Placeholder only; the new engine's `evals/` is built from scratch | `tests/evals/README.md`, `tests/golden/manifest.json` |
| Grounding check: a verbatim quote must exist in page text; numbers in a summary must exist in candidates or pages | **keep** | Cheap deterministic hallucination guard for the summary field and every evidence quote | `assessment.py:146-157`, `summaries.py:103-122` |
| `is_fixture` on every run and row | **keep** | Keeps test data out of accuracy metrics | `models.py:675,720,926,962` |
| Immutable per-stage artefacts keyed by tool version | **keep** | Reproducibility and re-run diffing | `stages/parse.py:72-95`, `stages/extract.py:582-599` |
| Prompt versioning | **adapt** | Integer constants only; one version is never persisted; the new engine uses `prompts/<name>/vN.md` files and stores the version on every candidate | `extraction.py:20`, `providers.py:584` |

---

## Part 3: stack comparison against the locked decisions

The locked decisions table said "Matches the likely tariff-repo stack; confirm in Stage 0". Confirmed, with four differences:

| Area | Locked decision | tariff-oder | Recommendation |
| --- | --- | --- | --- |
| Python | 3.12 | allows 3.11-3.12, builds and tests on 3.11 | **Follow the table.** 3.12 is inside the repo's own range; nothing copied depends on 3.11 behaviour. |
| Backend | FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 | same, plus `pydantic-settings`, `psycopg` 3 | **Matches.** Adopt `pydantic-settings` for config and `psycopg[binary,pool]` as the driver; both are within the locked stack. |
| Database | PostgreSQL 16, jsonb payloads | PostgreSQL 16 via the pgvector image; extension unused | **Matches.** Use plain `postgres:16`; no pgvector. |
| Queue | Postgres-backed job table polled by `worker/` | Postgres queue with `SKIP LOCKED`, lease fencing, checkpoints | **Matches and is materially better than a naive poller.** Copy `queue.py` and `runner.py` (keep). |
| LLM client | one module `core/llm/`, typed request/response, stored prompt version, retries, full call log | raw `httpx.post`, no SDK, no HTTP retry, inline prompts, `extraction_runs` row per call | **Follow the table.** Use the `anthropic` SDK with native PDF input; keep the tariff repo's per-call run row and output-salvage helpers. |
| Frontend | React 18 + TypeScript + Vite, pdf.js, Tailwind | **Next.js 16 / React 19**, server-side API proxy routes, no tests | **Follow the table.** The tariff UI's data path (browser → Next route → API with forwarded identity) exists only because it has login; phase 1 has none. Port the review-workspace flow and keyboard model as ideas, not files. |
| Layout and coordinates | pdfplumber char boxes, pymupdf renders | pymupdf, pdfplumber (tables only), tesseract OCR; no char boxes or cell bboxes stored | **Follow the table**; the tariff repo's evidence granularity is the one thing it does worse than the design. Keep its OCR word-box code for scanned pages. |
| Deployment | single VM, docker compose, Caddy | compose locally; Cloud Run + Cloud SQL + IAP via Terraform | **Follow the table for phase 1.** The Terraform is the Stage 5C starting point. |
| Auth | none until Stage 5; tenant and audit columns from day one | IAP/OIDC identity adapters and roles; **no tenant column**; append-only audit trigger | **Follow the table.** Copy the identity adapters into Stage 5C; copy the audit trigger now. |

Net: the tariff repo does not do anything materially better in an area the table locks, except the queue, which the table already allows. No locked decision is reopened.
