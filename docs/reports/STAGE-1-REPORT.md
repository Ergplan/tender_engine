# Stage 1 report: shared document intelligence core

Date: 2026-10-04. Diff: `git diff stage-1-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` ("What changed this stage").

## Definition of done (master prompt, row 1)

| Check | Result |
| --- | --- |
| Candidate rows cannot be updated (test) | Yes. Database trigger `candidate_immutable` allows only `status` to change and refuses deletes. `tests/core/test_invariants.py`: `test_candidate_rows_cannot_be_updated` (raw SQL, one case per column tried), `..._through_the_orm_either`, `test_candidate_rows_cannot_be_deleted`, `test_candidate_status_alone_may_change` |
| Every candidate has an evidence_span (test) | Yes for every candidate that carries a value and can reach a reviewer: `ExtractService._add_candidate` refuses a `raw` candidate without spans; `tests/core/services/test_extract.py::test_every_reviewable_candidate_has_at_least_one_evidence_span` and `::test_a_value_without_evidence_is_rejected_and_never_reviewable` cover it. Two statuses carry no span by design: `not_found` (the model returned no value) and `rejected` (a value came without a quote; never shown, cannot be approved) |
| ApprovalService is the only writer to canonical_fact (grep + test) | Yes. `CanonicalFact(` is constructed in one place, `core/services/approve.py`. `test_approval_service_is_the_only_writer_of_canonical_fact` greps the source tree and fails on any other writer |
| e2e on one FDRE tender prints per-field value, confidence, page | Yes, on two: SECI FDRE-IX RfS (140 pages) and NHPC FDRE-II RfS (264 pages). Output below |
| Evidence located for >= 80% of the 12 test fields | **Partly.** NHPC FDRE-II: 9 of 12 fields have a value, all 9 with located evidence (75% of 12). SECI FDRE-IX: 8 of 12 have a value, all 8 located (67% of 12). Every value the model returned was located (100%). The remaining fields are not stated in the documents as single values (see "Fields without a value"), so the model returned null as the prompt requires. Measured against fields the document states, the rate is 100%; measured against all 12, it is below the 80% line on both tenders |
| `make test` green | 209 Python tests and 3 web tests pass; the watcher's eight checks are green |
| `docker compose up` serves the API on the VM | Yes, see "Deployment" |

## What was built

- **Data model, migration 0002.** `document`, `page`, `section`, `extraction_run`, `candidate`, `evidence_span`, `validation_result`, `approval`, `canonical_fact`, `feedback`, `audit_log`, `job`, and `llm_call_log.extraction_run_id`. Three database triggers: candidates are immutable except for status; evidence spans and the audit log are append-only.
- **Schemas as data (`core/schemas/`).** `ExtractionSchema`, `FieldGroup` with routing hints, `FieldDef` with value type, unit, range and regex, a `SchemaRegistry` with cross-field rules, and eight value types (text, long_text, int, decimal, date, bool, enum, list_text). Core names no tender field; a test fails if `core/` imports `tender/`.
- **Services (`core/services/`).** `IngestService.upload` (sha256 dedupe, enqueues parse); `ParseService.parse` (pdfplumber text and one box per character, pymupdf renders at 150 dpi, pages under 50 characters flagged as having no text layer); `SectionMapper.map` (one model call over a digest of every page); `ExtractService` (pages chosen from routing hints, native PDF windows of at most 40 pages, structured output that requires value, confidence, rationale and evidence, quote resolution, confidence capped at 0.3 when unlocated); `ValidationService.validate` (type, required, range, regex, cross-field, evidence located; no model call); `ApprovalService.approve` (the only writer of `canonical_fact`; writes approval, fact, feedback and audit rows; idempotent on an identical repeat; a later decision supersedes the earlier one); `ReviewStateService.for_object` (the one read model).
- **Evidence resolution (`core/services/evidence.py`).** Exact match after normalising case, whitespace, quotes and dashes; then rapidfuzz at threshold 85; then the quote's words in any order over consecutive page words with every number unchanged. Tried on the stated page, the adjacent pages, then the rest of the window.
- **Prompts.** `core/llm/prompts/section_map/v1.md` and `core/llm/prompts/extract/v1.md`, each with the header block. The registry refuses an unregistered version before any network use.
- **API (`api/v1/core/`).** `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/pages/{n}/render`, `GET /documents/{id}/sections`, `POST /documents/{id}/extract`, `GET /extraction-runs/{id}`, `GET /review-state`, `POST /approvals`, `GET /canonical`, all under `/api/v1` and all filtered by tenant. The reviewer comes from the `X-Reviewer` header.
- **Worker (`worker/`).** One process polling `job` every 2 seconds; parse → section_map and extract → validate; traceback in `job.last_error`; three attempts with backoff; non-retryable failures fail at once.
- **Independent review script.** `scripts/independent_review.py` (operating rule 15).

## Tests

- 209 Python tests (33 at the end of Stage 0B). Unit: value types, schema registry, every validation rule, evidence resolution on a synthetic page, delta classification. Service tests against Postgres: ingest and parse, section map, extract (including resume after a failed call, evidence found on an adjacent page, unlocated evidence capped at 0.3), validate, approve, review state, jobs, the runner.
- Invariants (`tests/core/test_invariants.py`): candidate immutability by SQL and ORM, evidence and audit log append-only, one writer of `canonical_fact`, nothing reads `feedback` at runtime, validation makes no model call, core does not import tender.
- Integration through HTTP only (`tests/api/test_review.py::test_full_pipeline_through_the_http_api`): upload → parse → extract (scripted model) → validate → approve → canonical, including an edit that leaves the candidate unchanged. Tenant isolation: `tests/api/test_documents.py::test_another_tenants_document_is_invisible`.
- End to end with the real model (`tests/e2e/test_fdre_core_pipeline.py`, marked slow, `make test-e2e`): two FDRE tenders, the 12-field test schema in `tests/fixtures/fdre_schema.py`.

## End-to-end run on real tenders (real model, `make test-e2e`)

**SECI FDRE-IX RfS**

```text
document: RfS_for_4800_MWh_Peak_Supply_(FDRE-IX)-_final_upload.pdf (140 pages, 41 sections)
run: model=claude-fable-5-1 tokens_in=171757 tokens_out=3359 cost_usd=1.8855
field | value | confidence | status | evidence page (resolution, score) | failed rules
identity.tender_number | 'SECI/C&P/IPP/13/0006/26-27' | 0.98 | validated | p1 (stated_page, 100.0), p3 (stated_page, 100.0) | -
identity.issuing_agency | 'Solar Energy Corporation of India Limited' | 0.97 | validated | p1 (stated_page, 100.0), p8 (stated_page, 100.0) | -
identity.capacity_mw | 1200.0 | 0.93 | validated | p1 (stated_page, 98.5), p6 (stated_page, 100.0) | -
identity.connectivity_type | 'ists' | 0.95 | validated | p3 (stated_page, 100.0), p6 (stated_page, 99.0) | -
key_dates.pre_bid_date | None | 0.00 | not_found | - | -
key_dates.bid_deadline | None | 0.00 | not_found | - | -
security.emd_per_mw | 968000.0 | 0.50 | validated | p24 (stated_page, 100.0), p24 (stated_page, 100.0) | -
security.pbg_per_mw | 2420000.0 | 0.50 | validated | p26 (stated_page, 100.0), p26 (stated_page, 100.0) | -
commercial.scod_months | 18 | 0.95 | validated | p19 (stated_page, 100.0) | -
commercial.ppa_tenure_years | 25 | 0.95 | validated | p31 (stated_page, 100.0) | -
commercial.tariff_ceiling | None | 0.00 | not_found | - | -
commercial.min_cuf_percent | None | 0.00 | not_found | - | -
approved identity.tender_number -> canonical value 'SECI/C&P/IPP/13/0006/26-27'
```

**NHPC FDRE-II RfS**

```text
document: RfS_FDRE_1200MW_NHPC_Tranche-II.pdf (264 pages, 66 sections)
run: model=claude-fable-5-1 tokens_in=200014 tokens_out=2308 cost_usd=2.1155
field | value | confidence | status | evidence page (resolution, score) | failed rules
identity.tender_number | '2024_NHPC_800202_1' | 0.95 | validated | p1 (stated_page, 100.0) | -
identity.issuing_agency | 'NHPC Limited' | 0.97 | validated | p1 (stated_page, 100.0), p9 (stated_page, 100.0) | -
identity.capacity_mw | 1200.0 | 0.97 | validated | p8 (stated_page, 100.0), p8 (stated_page, 100.0) | -
identity.connectivity_type | 'ists' | 0.95 | validated | p8 (stated_page, 100.0), p8 (stated_page, 100.0) | -
key_dates.pre_bid_date | '2024-03-28' | 0.95 | validated | p22 (stated_page, 100.0) | -
key_dates.bid_deadline | '2024-04-12' | 0.85 | validated | p22 (stated_page, 100.0) | -
security.emd_per_mw | None | 0.00 | not_found | - | -
security.pbg_per_mw | None | 0.00 | not_found | - | -
commercial.scod_months | 24 | 0.95 | validated | p66 (stated_page, 100.0), p169 (stated_page, 100.0) | -
commercial.ppa_tenure_years | 25 | 0.95 | validated | p65 (stated_page, 100.0), p163 (stated_page, 100.0) | -
commercial.tariff_ceiling | None | 0.00 | not_found | - | -
commercial.min_cuf_percent | 40.0 | 0.95 | validated | p61 (stated_page, 100.0) | -
approved identity.tender_number -> canonical value '2024_NHPC_800202_1'
```

### Fields without a value

Checked against the page text of each document:

| Tender | Field | What the document says |
| --- | --- | --- |
| SECI FDRE-IX | pre-bid date, bid deadline | Bid Information Sheet, page 4: "Scheduled as per NIT on ISN-ETS portal" and "As per NIT on ISN-ETS portal". No date is printed |
| SECI FDRE-IX | tariff ceiling, minimum CUF | Neither "ceiling" nor "CUF" occurs in the RfS text |
| NHPC FDRE-II | EMD per MW, PBG per MW | Given as formulas: "Earnest Money Deposit = [INR 9,28,000 x Rated cumulative Installed Capacity of Solar component (MW) + ...]" (pages 21 and 40) and "Performance Bank Guarantee = [INR 23,20,000 x ...]" (page 41). There is no single per-MW figure |
| NHPC FDRE-II | tariff ceiling | No ceiling tariff is stated |

These are schema questions for Stage 2, listed in `docs/KNOWN-GAPS.md`. No field had a value with evidence that could not be located in the final runs.

### One evidence failure found and fixed during the stage

On the first NHPC run the bid deadline (12.04.2024, page 22) came back with unlocated evidence and confidence capped at 0.30. The model quoted a wrapped table cell in reading order; the text layer interleaves the label and the value. `core/services/evidence.py` now also matches a quote's words in any order over consecutive page words, with every number unchanged, at the same threshold. Two unit tests cover it, and the rerun located the quote with score 100.

## Deployment

(Draft: `make deploy` is run after the independent review and its output is recorded here.)

No extraction schema is registered in the deployed API and worker: core is schema-agnostic and the tender schemas are Stage 2. On the deployed app, upload, parse, section map, renders and sections work; `POST /documents/{id}/extract` answers `validation_failed` for any schema name until Stage 2.

## Independent review (operating rule 15)

(Draft: findings and fixes are recorded here after the reviewer has run.)

## Skipped or changed, and why

- **`delta_kind = exact` is never written.** When the final value equals the candidate, no feedback row is created.
- **Two extra candidate statuses**, `not_found` and `rejected` (DECISIONS.md).
- **Objects instead of documents.** Candidates, approvals and facts hang on `(object_type, object_id, object_version)`; in Stage 1 the object is the document.
- **`make trace`.** Still Stage 3; checklist item (d) of the independent review is not applicable.
- **Scanned pages.** A page with fewer than 50 characters is flagged `has_text_layer = false`. The model still sees it, because extraction sends native PDF pages, but evidence cannot be located on it. No such page occurred in the two test tenders, so this path is covered by unit tests only.
- **The e2e ran on two tenders, not one**, and has a 30-minute timeout.

## Things to know

- The stack was found with the API container unhealthy at the start of this session (`pymupdf` missing from an image built before the dependency was added). The images were rebuilt and migration 0002 was applied to the app database.
- `git push` over SSH fails in a new session because the key is passphrase-protected; pushes went over HTTPS with the `gh` login.
- The master prompt was amended on 2026-10-04 (Stage 2 field namespace and domain packs; Stage 5D public library and widgets). Nothing from it was built. Two points need your decision before Stage 2 (see "Open questions").
- Real-model cost of this stage's e2e runs: about USD 2 per tender per run.

## Open questions

1. **Stage 2 layout.** The amendment puts schemas, prompts and sector validators under `tender/domain_packs/`. CLAUDE.md's fixed layout names `tender/schemas/`, `tender/prompts/` and `tender/validation/`. Confirm that `domain_packs/` replaces all three and that CLAUDE.md should be updated.
2. **Field paths.** Confirm that the field catalogue's paths are to be renamed into the `core.*` and `sector.power.*` namespaces in Stage 2, including the FIELD-TRACE examples in CLAUDE.md.
3. **Stage 5D base text.** The file had no Stage 5D; the two sub-sections were added as a new block. The MCP server and the base tools (search_tenders, get_tender, get_field, get_document_page, list_changes, compare_tenders, reliability_report) are not specified anywhere yet.
4. **The 80% line.** It is not met when counted over all 12 fields because the documents do not state some of them. Is "located evidence for every value returned, and null for what the document does not state" the bar you want, or should the test schema be changed to fields every FDRE RfS states?
5. **EMD and PBG as formulas** (NHPC) and **dates deferred to the NIT** (SECI): how should the Stage 2 schema hold them?
6. **Reviewer model.** The OpenAI key exposes only `gpt-4-turbo` and `gpt-4`. Enable a current model if you want a stronger independent review.

Stage 1 stops here. Next: `Run Stage 2 of docs/MASTER-PROMPT.md.`
