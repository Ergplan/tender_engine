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

## Part 2: `FDRE` (FDRE bid optimiser with a tender-extraction side path)

### Stack and dependencies

Two commits. Primarily an FDRE bid-sizing optimiser (hourly dispatch, project finance, capacity search) for the NHPC FDRE Tranche-II tender, with a bolted-on regex tender extractor and a browser-side review screen. Not a document-intelligence product.

- `requirements.txt`: streamlit, numpy, pandas, scipy, plotly, `fastapi>=0.115`, uvicorn, `pydantic>=2.8`, `pymupdf>=1.24`, `pypdf>=4.2`, python-docx, pytest, windpowerlib. `requirements-docling.txt`: `docling==2.130.0`. `react_demo/package.json`: React 19, Vite 6, echarts. No database, no ORM, no auth library; `anthropic` is imported only by `Enterprise_Build/claude_doc_reader.py:29` and is not in requirements.
- Code: `fdre_enterprise_engine.py` (101 KB dispatch/finance/optimiser), `fdre_tender_rag.py` (regex and lexical-retrieval extractor), `fdre_tender_review.py` (review-field flattening, CfD guard), `app.py` (89 KB Streamlit UI, no tender upload), `react_demo/backend/api.py` (FastAPI wrapper), `react_demo/src/main.jsx` (189 KB single file) and `TenderReview.jsx`, `Enterprise_Build/claude_doc_reader.py` (standalone Claude script, wired to nothing).
- Documents: `docs/enterprise/*.md` (target design), `ENTERPRISE_SOLUTION_WIREFRAME_BRIEF.md`, `MODEL_NOTES.md`, `QA_TEST_REPORT.md`, `USER_MANUAL.md`.

### Data model (no database; in-memory dataclasses and dicts)

| Structure | Purpose | Path |
| --- | --- | --- |
| `NodeSpec`, `GeneratorSpec`, `BessSpec`, `TenderRules`, `FinanceAssumptions`, `SimulationAssumptions`, `ProjectConfig`, `DispatchResult`, `CapexResult`, `FinanceResult` | optimiser input and output dataclasses, serialised by `project_to_dict/from_dict` | `fdre_enterprise_engine.py:62-370` |
| `project_config_fdre2.json` | `{name, nodes[], generators[], bess[], tender{}, finance{}, simulation{}, metadata{}}` | repo root |
| `TenderChunk(content, meta{file_name, page_number, split_idx_start, clause_id, clause_title, split_id}, score)` | retrieval chunk | `fdre_tender_rag.py:56` |
| `parse_tender_document` result | `tender_schema{title, issuer, rfs_no, rfs_date, procurement_mw, peak_supply_mwh, peak_hours, ppa_years, location, storage_required, procurement_type}`, `security[]`, `eligibility[]`, `risk_flags[]`, `settings{}`, `timeline[]`, `commercial[]`, `financial[]`, `amendments[]`, `rag_status{}` | `fdre_tender_rag.py:376-406` |
| review attachment | `document_id` (sha256), `source_pages[]`, `compatibility{can_apply}`, `cfd_terms[]`, `review_fields[{id, section, label, original, source, page, evidence_status, setting_key}]` | `fdre_tender_review.py:15-60` |
| API request models | `TenderUploadFile{name, content_base64}`, `TenderUploadRequest{file, parser: auto/standard/docling}` and optimiser requests | `react_demo/backend/api.py:36-71` |
| browser review doc | `{parsed, decisions{fieldId: {value, status, note, reviewer, timestamp}}, audit[], reviewer, baseDocumentId}` in `localStorage["fdre-tender-reviews-v1"]` | `react_demo/src/TenderReview.jsx:5-15, 60-75` |
| Claude tool schema `TENDER_SCHEMA` | `fields[]{name enum, value, unit, source_page, verbatim_quote, confidence}` | `Enterprise_Build/claude_doc_reader.py:149-180` |
| design-only rule draft | `rules[]{rule_id, rule_type, quantity, unit, aggregation, evidence[{document_id, physical_page, clause}], review_status}`, `source_documents[]{sha256, issue_date, physical_pages, base_document_id}` | `docs/enterprise/examples/cfd-review-draft.json`, entity table `docs/enterprise/02-architecture-and-api.md:62-89` |

### Document ingestion and parsing path

- `extract_tender_document(name, payload, parser)` (`fdre_tender_rag.py:107`) tries Docling (`_extract_docling` :75; OCR and table structure on, remote services off, 180 s timeout, per-page markdown joined by form feeds, PyMuPDF `native_text` sidecar :117-122) and falls back on any exception to `_extract_pdf_text` (:136, PyMuPDF then pypdf) or `_extract_docx_text` (:157, one logical page). Empty text raises; blank pages add a warning.
- Chunking `split_tender_chunks` (:187): pages, then `CLAUSE_RE` clause headings (:39), then 420-word windows with 70 overlap. Retrieval `retrieve_chunks` (:258) is a hand-rolled lexical scorer with a synonym table `QUERY_EXPANSIONS` (:46). No embeddings.
- Field extraction is regex windows around keywords (`_parse_percent_context` :494, `_parse_mw_context` :519, `_security_formulas` :678, `_eligibility_rows` :753, `_critical_date_map` :851, `_amendment_rows` :892), many falling back to `defaults.tender.*`.
- `react_demo/backend/api.py:235-360` holds an older duplicate parser with no callers.

### LLM calls

The production path makes **zero** LLM calls; `rag_status.notes` says a chat model "can be layered later" (`fdre_tender_rag.py:404`). The only LLM code is `Enterprise_Build/claude_doc_reader.py`: module-level `anthropic.Anthropic()` (:63), model `claude-fable-5` (:31), Files API beta (:33), `ask_document` (:118) with ephemeral cache control on the document block, `extract_tender` (:183) with forced tool use against `TENDER_SCHEMA`, PDFs over 90 pages split with pypdf and `source_page` offset, highest-confidence duplicate kept. Prompts inline and unversioned (:125-130, :209-213). Synchronous, no retries, no logging, no token accounting. Not imported by any app code or test.

### Where extracted values go; is there a human step?

`/api/tender/parse` (`api.py:857`) is stateless; nothing is persisted server-side. `attach_review` labels every field "Related source; verify value" or "No field-level citation" (`fdre_tender_review.py:46-57`) and `compatibility.can_apply` is false for CfD and amendments. The React `apply()` (`TenderReview.jsx:58-70`) pushes only approved fields with a `setting_key` into the project config, so a click is required. But the reviewer is a typed string (:44), decisions and audit live in `localStorage`, and the values themselves are regex-or-default (`declaredCuf` defaults to 40% when not found, `fdre_tender_rag.py:309`), so observed-versus-defaulted provenance is lost; `docs/enterprise/README.md:60-63` admits this. `_confidence` (:951) returns "High" for any positive number.

### Review UI

`react_demo/src/TenderReview.jsx`: field list by section and status, original versus reviewed value, note, approve/reject, per-page source text (extracted, native, or iframe of the blob), page search, amendment-to-base association and compare, JSON export, "Apply approved model inputs". `app.py` has no tender upload. A Playwright script `tools/check_tender_review.cjs` drives it against files in a developer's Downloads folder.

### Tests (`tests/`, 8 files, 63 tests)

Mostly optimiser: `test_engine_smoke.py` (21), `test_optimizer_bounds_matrix.py` (9), `test_eya.py` (11, two depend on `/Users/.../Downloads/NHPC Bikaner*.pdf`), `test_wind_eya.py` (5, CSV in Downloads), `test_enterprise_fdre_engine.py` (3, EMD/PBG formula `0.0928*solar + 0.1264*wind + 0.1464*ess` capped at 10 cr). Extraction: `test_tender_extraction.py` (9: docling fallback disclosure, page boundaries reach chunks, empty text rejected, clause id, CfD guard, amendment yields empty settings, `document_id` bound to content) and `test_react_demo_api.py` (4, one parse of a four-sentence string asserting `declaredCuf == 40.0`). All synthetic strings; no real RfS fixture; nothing asserts that a wrong extraction is flagged.

### Auth, tenancy, audit; deployment

None implemented. CORS allowlist for localhost (`api.py:74-80`). Design docs specify roles, `tenant_id` and append-only decisions (`docs/enterprise/02-architecture-and-api.md:62-66, 202-216`) but nothing exists. No Dockerfile, compose, CI, `.env.example` or migrations; FastAPI serves the Vite `dist/` as an SPA (`api.py:32, 933`).

### Tender domain concepts, rated

| Concept | What the repo has | Rating | Reasoning and path |
| --- | --- | --- | --- |
| Lifecycle states | document uploaded/scanning/extracting/extracted/partial/failed/superseded; fact unreviewed/corrected/accepted/rejected/conflicted/superseded; rule-set draft/in_review/approved/superseded/withdrawn | **keep** (design only) | Clean vocabulary that maps onto candidate/approval/tender_version; `docs/enterprise/01-tender-rules.md:40-45` |
| Header fields | `issuer` (SECI/NHPC only), `rfs_no`, `rfs_date`, `search_code`, `title` | **adapt** | Fields match the catalogue's identity section; issuer must become an open agency field, not a two-value regex; `fdre_tender_rag.py:459-473` |
| Procurement quantum | `procurement_mw`, `peak_supply_mwh`, `peak_hours`, `procurement_type`, `location`, `storage_required` | **keep** | Maps to scope and fdre_profile sections; `fdre_tender_rag.py:423, 545, 556` |
| Bid capacity rules | `min_project_mw`, `project_mw_multiple`, `max_bidder_capacity_mw` | **keep** | Universal to SECI/NTPC RfS; `fdre_enterprise_engine.py:166-168` |
| PPA | `ppa_years`, `contract.start_basis` COD/SCD | **keep** | Matches `ppa_tenure_years` and `scod_reference`; `docs/enterprise/06-input-dictionary.md:11-12` |
| FDRE technical | declared annual CUF, relative lower tolerance, upper multiplier 1.10, 8766 h, peak availability floor 0.90, morning and evening windows, peak schedule mode, external green limit 5%, first-year relief | **keep** as fdre_profile fact types; **adapt** tolerance to an explicit relative-versus-percentage-point operator | `fdre_enterprise_engine.py:165-192`, `06-input-dictionary.md:21` |
| Commercial constants | penalty multiplier 1.5x, PSM charge, trading margin, success charge 1 lakh/MW plus GST | **keep** the fact types, **discard** the hard-coded defaults | `fdre_enterprise_engine.py:172-176` |
| Securities | EMD and PBG as per-technology per-MW rates with a cap; processing fee slab; document fee | **keep** the composite-formula shape | Recurs in SECI/NHPC hybrid and FDRE RfS; `fdre_tender_rag.py:678`, engine `:981-995` |
| Eligibility | turnover INR/MW, PBDIT INR/MW, line of credit INR/MW, MSE exemption | **keep** | Matches catalogue eligibility fields; `fdre_tender_rag.py:753` |
| Timeline milestones | RfS issue, pre-bid, clarification deadline, bid start/close, offline submission, technical opening, e-RA, PPA execution, financial closure, SCOD | **keep** the enum, **discard** the regex | `fdre_tender_rag.py:826-851` |
| Risk flags | no-deviation, GNA/connectivity, buying entity/PSM, BG format, merchant outside peak | **adapt** into a clause-tag taxonomy for the connectivity and commercial sections | `fdre_tender_rag.py:792` |
| Amendments | role by filename and first-700-chars regex; rows of clause refs plus snippet; UI links amendment to base; design: operation {source/target clause, action add/replace/delete/clarify, effective date, conflict state} | **keep** the design, **discard** the implementation | `fdre_tender_review.py:8`, `fdre_tender_rag.py:892`, `01-tender-rules.md:153-163` |
| CfD terms | daily kWh/MW minimum, buyer-selected 2-hour blocks, weekly shortfall 10%, 25% external green, market-price sharing above Rs 10 | **adapt** as fdre_profile fields for SECI CfD tenders | `fdre_tender_rag.py:63` |
| Canonical rule contract | `rule_id, version, rule_type, scope, quantity/unit/basis, calendar, aggregation, schedule, denominator, tolerance, treatment, dependencies, evidence, review, implementation` | **keep** as the long-term shape for machine-readable facts | Strongest reusable idea in the repo; `01-tender-rules.md:48-72` |
| Vocabulary | `QUERY_EXPANSIONS` synonyms (EMD, PBG, PSM, e-RA, SCOD, GNA) | **keep** | Seed for the tender extract prompts; `fdre_tender_rag.py:46-52` |
| Clause-to-parameter QA matrix | NHPC clauses 6.1/6.2/3.3/3.11 mapped to parameters | **keep** | Golden expectations for an FDRE fixture; `QA_TEST_REPORT.md:22-36` |
| Other tender types | solar/wind/hybrid/BESS exist only as asset specs; transmission, EPC, IPP absent | **discard** | FDRE defaults must not bleed into other types, as the design itself says (`docs/enterprise/03-ui.md:179`) |

### Critique of the enterprise design documents

- `docs/enterprise/02-architecture-and-api.md` is close to the target (Postgres plus object store, job queue, append-only decisions, rule-set versions, idempotency keys, 202 jobs). It never decides the extractor (Docling versus LLM), has no schema for how LLM candidates with evidence enter the fact table, and says "retrieval indexes" without a design.
- `01-tender-rules.md` wants a typed rule compiler and adapter registry. Right instinct, but it couples "approved" to "compilable by the dispatch engine"; the fact layer must stand on its own.
- `ENTERPRISE_SOLUTION_WIREFRAME_BRIEF.md` is 23 optimiser screens; its tender-upload screen (:129-181) still applies regex-driven confidence and an "Apply to Project Configuration" button; its data model (:980-1006) is a flat list with no document, version or fact entity. UX inspiration only.

---

## Part 3: flaws not carried forward (both repos)

**tariff-oder**

1. Model-only candidates become the displayed value: `Compared.primary` returns the image candidate when rules found nothing (`extraction.py:779-780`) and `candidate_rows` denormalises it into `candidates.value` (`stages/extract.py:504-512`).
2. Model output mutates candidate identity before review: `assessment.apply` writes `applicability.rate_block` (`assessment.py:275-277`), which feeds `Candidate.key()` (`tariff_schema.py:214`).
3. Prompts inline with weak versioning: four prompt strings (`providers.py:76-86, 587-631`; `assessment.py:36-51`; `summaries.py:38-47`); `IMAGE_PROMPT_VERSION` (`providers.py:584`) is never written to `extraction_runs`; no prompt text hash.
4. No HTTP retry or backoff and whole-order re-run on failure: single `httpx.post` (`providers.py:417-431`); `extract_source` saves a checkpoint (`stages/extract.py:363`) but never reads it.
5. Hand-rolled Anthropic client duplicated three times (`providers.py:418, 488, 540`), API version string hard-coded, model name in two places (`config.py:94`, `infra/gcp/variables.tf:114`).
6. No evidence bbox or char offsets: `EvidenceRef` has no coordinates (`tariff_schema.py:98-111`); image-channel row/col are "as you count them" (`providers.py:617-619`) and not reconciled to reader grids.
7. Real provider path untested; no eval harness (`tests/integration/test_extract_stage.py:262-277, 300-313`; `tests/evals/README.md`).
8. Module-level global DB state (`db.py:14-15, 28, 36`) and an `lru_cache` settings singleton tests must clear (`config.py:152-156`, `tests/conftest.py:63,104`).
9. Dead code: `main.py:131`, `summaries.numbers_in`, `telemetry.get_logger`, `publication.now`, unused `pypdf` dependency, unused pgvector extension (`db.py:68`).
10. Denormalised candidate columns are not updated on correction (`models.py:700-711`; `test_review_workflow.py:221-224`), a trap for anyone querying columns.
11. Synchronous full-PDF rendering inside request handlers (`services/review.py:395-423`).

**FDRE**

12. Defaults masquerade as extractions: `_parse_percent_context(..., default=0.4*100)` (`fdre_tender_rag.py:309-313`); `_confidence` returns "High" for any number (:951).
13. Issuer and type detection by keyword: only SECI/NHPC known (:470-473); "FDRE" anywhere sets the type (:556).
14. Clause numbers hard-coded to one RfS: `"Clause": "16"`, `"17.1"`, `"36.2"` (:629-650, :693-704, :759).
15. Page references recovered by regex from a label string (`fdre_tender_review.py:46`); no bbox or char offsets; DOCX collapses to page 1.
16. Synchronous 180 s Docling conversion inside a FastAPI handler with the whole PDF base64 in the request body (`api.py:857-887`, `fdre_tender_rag.py:82`); the 129-page RfS timed out in the repo's own test (`01-tender-rules.md:170-173`).
17. Review state in `localStorage`, reviewer identity a typed string, audit generated client-side (`TenderReview.jsx:5-15, 44-50`).
18. Developer-machine paths in code and tests (`api.py:31`, `app.py:26-31`, `tests/test_eya.py:150,168`, `tests/test_wind_eya.py:11`, `tests/test_react_demo_api.py:23`).
19. Global state: `anthropic.Anthropic()` at import (`claude_doc_reader.py:63`), module global `sessionReviews` (`TenderReview.jsx:3`), Streamlit session-state sprawl.
20. Dead duplicate parser (`api.py:235-360`), alias module `enterprise_fdre_engine.py`, a 189 KB `main.jsx`, an 89 KB `app.py`; large binaries committed.
21. Tests are happy-path on four-sentence strings with machine-dependent skips; no negative extraction tests.

---

## Part 4: shared-core versus tender-domain modules, with what is copied

| Target module | Role | Source repo and file | Action |
| --- | --- | --- | --- |
| `core/models/job.py`, `worker/` | Postgres queue with `SKIP LOCKED`, lease fencing, checkpoints, bounded retries | tariff-oder `services/api/src/tariff_api/queue.py`, `services/worker/src/tariff_worker/runner.py`, `models.py:446-493` | copy, rename |
| `core/models/audit_log.py` + migration | append-only audit with DB trigger | tariff-oder `models.py:496`, `migrations/versions/0001_foundation.py:228-234` | copy |
| `core/models/` idempotency | (key, actor) idempotency records for approvals | tariff-oder `models.py:514`, `routers/review.py` | copy |
| `core/storage/` | local and GCS behind one interface | tariff-oder `adapters/storage.py` | copy |
| `api/middleware/errors.py`, `api/main.py` | typed error taxonomy, request-id middleware, exception handlers | tariff-oder `errors.py`, `telemetry.py`, `main.py:67-107` | copy |
| `core/services/parse.py` | page inventory, OCR word boxes for scanned pages, table-reader agreement | tariff-oder `inventory.py`, `ocr.py:88-191`, `readers.py`, `stages/parse.py`; FDRE `fdre_tender_rag.py:75-135` (disclosed fallback, "no text means reject") | adapt |
| `core/services/section_map.py` | clause-aware segmentation baseline before the LLM section map | FDRE `fdre_tender_rag.py:39, 187-245` | adapt |
| `core/llm/client.py` | tool-forced structured output, output salvage, per-call run row, budget stop, truncation re-read | tariff-oder `providers.py:160-289`, `models.py:658-685`, `stages/extract.py:226-237, 326-351`; FDRE `Enterprise_Build/claude_doc_reader.py:149-230` (page batching with offset, verbatim quote plus source page) | adapt |
| `core/validation/grounding.py` | verbatim quote must exist on the cited page; numbers in a summary must exist in evidence | tariff-oder `assessment.py:146-157`, `summaries.py:103-122` | copy |
| `core/services/approve.py`, `core/models/approval.py` | evidence-view enforcement, decide with before/after snapshots and expected version, idempotent | tariff-oder `services/review.py:377-601, 635-796`, `models.py:833-888` | adapt |
| `core/models/` `is_fixture` column | keep fixture runs out of metrics | tariff-oder `models.py:675,720` | copy |
| `tests/conftest.py` | per-session throwaway schema, in-process worker, synthetic PDF fixtures | tariff-oder `tests/conftest.py`, `tests/fixtures/synthetic_pdfs.py` | adapt |
| `web/src/api/` drift check | OpenAPI → TypeScript with CI drift failure | tariff-oder `packages/contracts/scripts/check-drift.mjs` | adapt |
| `web/src/review/` | evidence-first flow, keyboard model, three-pane layout, amendment-versus-base compare | tariff-oder `apps/web/app/sources/[id]/review/review-workspace.tsx`; FDRE `react_demo/src/TenderReview.jsx` | ideas only (Next.js and single-file React do not port) |
| `tender/schemas/*.yaml` | field catalogue seeds for identity, scope, key_dates, eligibility, guarantees, fdre_profile | FDRE `fdre_enterprise_engine.py:162-210`, `docs/enterprise/06-input-dictionary.md:7-28`, `fdre_tender_rag.py:423-556, 678-851` | adapt (section 13 of the master prompt is authoritative) |
| `tender/models/tender_version.py` | amendment operation model and lifecycle states | FDRE `docs/enterprise/01-tender-rules.md:40-45, 153-163` | adapt |
| `tender/prompts/` | Indian RE tender vocabulary and synonyms | FDRE `fdre_tender_rag.py:46-52` | copy into prompt text |
| `tender/validation/` | per-technology EMD/PBG formula with cap, processing-fee slabs | FDRE `fdre_enterprise_engine.py:981-995`, `fdre_tender_rag.py:678` | adapt as validators |
| `evals/gold/` | clause-to-parameter QA matrix as golden expectations for an FDRE fixture | FDRE `QA_TEST_REPORT.md:22-36` | adapt |
| not copied | tariff-specific rules extractor, validators, normalisers, localisation profiles, ARR taxonomy, explorer; FDRE optimiser, EYA, Streamlit app, regex extractor | tariff-oder `extraction.py`, `validators.py`, `normalise.py`, `localisation.py`, `profiles.py`, `arr/*`; FDRE `fdre_enterprise_engine.py` (engine parts), `fdre_eya.py`, `app.py`, `fdre_tender_rag.py` (regex parts) | discard |

## Part 5: stack comparison against the locked decisions

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
