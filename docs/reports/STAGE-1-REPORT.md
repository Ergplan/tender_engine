# Stage 1 report: shared document intelligence core

Date: 2026-10-04. Diff: `git diff stage-1-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` ("What changed this stage").

## Definition of done (master prompt, row 1)

| Check | Result |
| --- | --- |
| Candidate rows cannot be updated (test) | Yes. Database trigger `candidate_immutable` allows only `status` to change and refuses deletes. `tests/core/test_invariants.py`: `test_candidate_rows_cannot_be_updated` (raw SQL, one case per column tried), `..._through_the_orm_either`, `test_candidate_rows_cannot_be_deleted`, `test_candidate_status_alone_may_change` |
| Every candidate has an evidence_span (test) | Yes for every candidate that carries a value and can reach a reviewer: `ExtractService._add_candidate` refuses a `raw` candidate without spans; `tests/core/services/test_extract.py::test_every_reviewable_candidate_has_at_least_one_evidence_span` and `::test_a_value_without_evidence_is_rejected_and_never_reviewable` cover it. Two statuses carry no span by design: `not_found` (the model returned no value) and `rejected` (a value came without a quote; never shown, cannot be approved) |
| ApprovalService is the only writer to canonical_fact (grep + test) | Yes. `CanonicalFact(` is constructed in one place, `core/services/approve.py`. `test_approval_service_is_the_only_writer_of_canonical_fact` greps the source tree for any other construction of `CanonicalFact` or bulk insert, update or delete on it. It would not catch an ORM attribute write in another module; there is no database-level guard (KNOWN-GAPS.md) |
| e2e on one FDRE tender prints per-field value, confidence, page | Yes, on two: SECI FDRE-IX RfS (140 pages) and NHPC FDRE-II RfS (264 pages). Output below |
| Evidence located for >= 80% of the 12 test fields | **Not met as written.** NHPC FDRE-II: 9 of 12 fields have a value, all 9 with located evidence (75% of 12). SECI FDRE-IX: 8 of 12 have a value, all 8 located (67% of 12). Every value the model returned was located (100%). The remaining fields are not stated in the documents as single values (see "Fields without a value"), so the model returned null as the prompt requires. Measured against fields the document states, the rate is 100%; measured against all 12, it is below the 80% line on both tenders |
| `make test` green | 222 Python tests and 3 web tests pass; the watcher's eight checks are green |
| `docker compose up` serves the API on the VM | Yes, see "Deployment" |

## What was built

- **Migration 0003.** Unique indexes: one active approval and one current canonical fact per field of an object version.
- **Data model, migration 0002.** `document`, `page`, `section`, `extraction_run`, `candidate`, `evidence_span`, `validation_result`, `approval`, `canonical_fact`, `feedback`, `audit_log`, `job`, and `llm_call_log.extraction_run_id`. Three database triggers: candidates are immutable except for status; evidence spans and the audit log are append-only.
- **Schemas as data (`core/schemas/`).** `ExtractionSchema`, `FieldGroup` with routing hints, `FieldDef` with value type, unit, range and regex, a `SchemaRegistry` with cross-field rules, and eight value types (text, long_text, int, decimal, date, bool, enum, list_text). Core names no tender field; a test fails if `core/` imports `tender/`.
- **Services (`core/services/`).** `IngestService.upload` (sha256 dedupe, enqueues parse); `ParseService.parse` (pdfplumber text and one box per character, pymupdf renders at 150 dpi, pages under 50 characters flagged as having no text layer); `SectionMapper.map` (one model call over a digest of every page); `ExtractService` (pages chosen from routing hints, native PDF windows of at most 40 pages, structured output that requires value, confidence, rationale and evidence, quote resolution, confidence capped at 0.3 when unlocated); `ValidationService.validate` (type, required, range, regex, cross-field, evidence located; no model call); `ApprovalService.approve` (the only writer of `canonical_fact`; writes approval, fact, feedback and audit rows; idempotent on an identical repeat; a later decision supersedes the earlier one); `ReviewStateService.for_object` (the one read model).
- **Evidence resolution (`core/services/evidence.py`).** Exact match after normalising case, whitespace, quotes and dashes; on word boundaries; then rapidfuzz at threshold 85 for quotes of 12 characters or more; then, for quotes that hold a number, the quote's words in any order over consecutive page words with every number unchanged. Tried on the stated page, the adjacent pages, then the rest of the window.
- **Prompts.** `core/llm/prompts/section_map/v1.md` and `core/llm/prompts/extract/v1.md`, each with the header block. The registry refuses an unregistered version before any network use.
- **API (`api/v1/core/`).** `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/pages/{n}/render`, `GET /documents/{id}/sections`, `POST /documents/{id}/extract`, `GET /extraction-runs/{id}`, `GET /review-state`, `POST /approvals`, `GET /canonical`, all under `/api/v1`. Every route and service query filters by tenant; the job queue alone is shared across tenants (KNOWN-GAPS.md). The reviewer comes from the `X-Reviewer` header.
- **Worker (`worker/`).** One process polling `job` every 2 seconds; parse → section_map and extract → validate; traceback in `job.last_error`; three retries with backoff (30, 60, 120 seconds); non-retryable failures fail at once; jobs left running by a dead worker are re-queued at start.
- **Independent review script.** `scripts/independent_review.py` (operating rule 15).

## Tests

- 222 Python tests (33 at the end of Stage 0B). Unit: value types, schema registry, every validation rule, evidence resolution on a synthetic page, delta classification. Service tests against Postgres: ingest and parse, section map, extract (including resume after a failed call, evidence found on an adjacent page, unlocated evidence capped at 0.3), validate, approve, review state, jobs, the runner.
- Invariants (`tests/core/test_invariants.py`): candidate immutability by SQL and ORM, evidence and audit log append-only, one writer of `canonical_fact`, nothing reads `feedback` at runtime, validation makes no model call, core does not import tender.
- Integration through HTTP only (`tests/api/test_review.py::test_full_pipeline_through_the_http_api`): upload → parse → extract (scripted model) → validate → approve → canonical, including an edit that leaves the candidate unchanged. Tenant isolation: `tests/api/test_documents.py::test_another_tenants_document_is_invisible`.
- End to end with the real model (`tests/e2e/test_fdre_core_pipeline.py`, marked slow, `make test-e2e`): two FDRE tenders, the 12-field test schema in `tests/fixtures/fdre_schema.py`.

## End-to-end run on real tenders (real model, `make test-e2e`)

Final run of `make test-e2e` on the committed code (3 passed in 6 min 40 s: the two tenders below and the Stage 0 one-page smoke test). Each tender goes through the HTTP API and the worker: upload, parse, section map, extract, validate, review state, then one approval and the canonical read.

**SECI FDRE-IX RfS**

```text
document: RfS_for_4800_MWh_Peak_Supply_(FDRE-IX)-_final_upload.pdf (140 pages, 38 sections)
run: model=claude-fable-5-1 tokens_in=233057 tokens_out=3287 cost_usd=2.4949
field | value | confidence | status | evidence page (resolution, score) | failed rules
identity.tender_number | 'SECI/C&P/IPP/13/0006/26-27' | 0.98 | validated | p1 (stated_page, 100.0), p3 (stated_page, 100.0) | -
    rationale: The cover page and Bid Information Sheet state the RfS number directly; the same number appears in the footer of every page.
identity.issuing_agency | 'Solar Energy Corporation of India Limited' | 0.97 | validated | p1 (stated_page, 100.0), p8 (stated_page, 100.0) | -
    rationale: The cover page names Solar Energy Corporation of India Limited as the issuer, and Clause 1.3 states SECI invites the proposals; Clause 2.7 confirms SECI issued the RfS as Intermediary Procurer.
identity.capacity_mw | 1200.0 | 0.90 | validated | p1 (stated_page, 89.8), p6 (stated_page, 92.5) | -
    rationale: The tender is for assured peak supply of 4800 MWh expressed as 1200 MW x 4 Hrs, so the capacity in MW is 1200; the document frames the capacity as 1200 MW of peak supply rather than installed capacity.
identity.connectivity_type | 'ists' | 0.95 | validated | p1 (window_page, 89.8), p6 (stated_page, 92.5) | -
    rationale: The title and Clause 1.3 require ISTS-connected RE projects; no intra-state connectivity option is mentioned in the attached pages.
key_dates.pre_bid_date | None | 0.00 | not_found | - | -
    rationale: Looked for a pre-bid meeting date in the Bid Information Sheet (item J) and Clause 30; the document only says the meeting is 'Scheduled as per NIT on ISN-ETS portal and/or SECI website' and prints no date.
key_dates.bid_deadline | None | 0.00 | not_found | - | -
    rationale: Looked for the bid submission deadline in Bid Information Sheet item K and Clauses 2.3 and 26.1; the document only states 'As per NIT on ISN-ETS portal'. The '10.08.2026' on attached page 11 is an explicit illustrative example ('For e.g.'), not the actual dead
security.emd_per_mw | 968000.0 | 0.40 | validated | p24 (stated_page, 100.0) | -
    rationale: Clause 16 does not state a single EMD per MW; it gives a component-based formula: INR 9,68,000 per MW of Solar PV, INR 13,68,000 per MW of Wind/other RE, and INR 2,40,000 per MWh of ESS. The Solar PV component rate (INR 9,68,000 = 968000) is reported as the ca
security.pbg_per_mw | 2420000.0 | 0.40 | validated | p26 (stated_page, 100.0) | -
    rationale: Clause 17.1 does not state a single PBG per MW; it gives a component-based formula: INR 24,20,000 per MW of Solar, INR 34,20,000 per MW of Wind/other RE, and INR 6,00,000 per MWh of ESS. The Solar component rate (INR 24,20,000 = 2420000) is reported as the can
commercial.scod_months | 18 | 0.95 | validated | p19 (stated_page, 100.0) | -
    rationale: Clause 9.2.a states SCSD for the full Project capacity is the date as on 18 months from the Effective Date of the PPA, with a worked example (07.11.2026 to 07.05.2028) confirming 18 months.
commercial.ppa_tenure_years | 25 | 0.95 | validated | p31 (stated_page, 100.0) | -
    rationale: Clause 20.2 states the PPAs are valid for 25 years from the SCSD; clause 20.8 consistently refers to the 25-year PPA period.
commercial.tariff_ceiling | None | 0.00 | not_found | - | -
    rationale: Searched the attached pages (scope, energy supply, commencement, PPA signing, financial closure, definitions, technical annexures) for a ceiling or maximum tariff in INR/kWh; none is stated. Only penalty multipliers of PPA Tariff and a 7 paise/unit trading mar
commercial.min_cuf_percent | None | 0.00 | not_found | - | -
    rationale: Looked for a minimum capacity utilisation factor or annual CUF requirement; the attached pages only specify a daily peak-hour supply obligation of 4000 kWh per MW with a 10% monthly shortfall allowance, not a CUF percentage.
approved identity.tender_number -> canonical value 'SECI/C&P/IPP/13/0006/26-27'
```

**NHPC FDRE-II RfS**

```text
document: RfS_FDRE_1200MW_NHPC_Tranche-II.pdf (264 pages, 78 sections)
run: model=claude-fable-5-1 tokens_in=327221 tokens_out=3937 cost_usd=3.4691
field | value | confidence | status | evidence page (resolution, score) | failed rules
identity.tender_number | '2024_NHPC_800202_1' | 0.95 | validated | p1 (stated_page, 100.0), p17 (stated_page, 100.0) | -
    rationale: The cover page states the Tender ID and the definitions section (attached page 9) identifies the RfS No. as 2024_NHPC_800202_1 dated 15.03.2024; both agree.
identity.issuing_agency | 'NHPC Limited' | 0.95 | validated | p1 (stated_page, 100.0), p9 (stated_page, 100.0) | -
    rationale: The cover page states the document is issued by NHPC Limited, and clause 1.11 confirms NHPC Limited issued this RfS as Intermediary Procurer/REIA.
identity.capacity_mw | 1200.0 | 0.95 | validated | p8 (stated_page, 100.0), p8 (stated_page, 100.0) | -
    rationale: NIT clause 1.0/1.1 and the title state an aggregate capacity of 1200 MW of Firm and Dispatchable RE power with ESS; the 600 MW figure is only a per-bidder cap, not the total.
identity.connectivity_type | 'ists' | 0.90 | validated | p1 (stated_page, 100.0), p8 (stated_page, 100.0) | -
    rationale: The RfS title and NIT clause 1.4 require ISTS-connected RE Power Projects; pooling definition also refers to connection to the ISTS substation. No intra-state option is mentioned in the attached pages.
key_dates.pre_bid_date | '2024-03-28' | 0.95 | validated | p22 (stated_page, 100.0) | -
    rationale: The critical date sheet (clause 3.4 B) lists the pre bid meeting date and time as 28.03.2024 (15:00 Hrs.), day-first, which converts to 2024-03-28.
key_dates.bid_deadline | '2024-04-12' | 0.85 | validated | p22 (stated_page, 100.0), p22 (stated_page, 100.0) | -
    rationale: The critical date sheet gives the Online Bid Submission Closing Date & Time as 12.04.2024 (17:30 Hrs.), taken as the bid submission deadline; a separate later date of 15.04.2024 is given for offline submission of physical documents (processing fee, EMD origina
security.emd_per_mw | None | 0.00 | not_found | - | -
    rationale: The RfS does not state a single EMD per MW; Clause 3.24(i) (attached pages 3 and 8) defines EMD by formula as INR 9,28,000 per MW of Solar component + INR 12,64,000 per MW of Wind component + INR 14,64,000 per MW of ESS component, capped at Rs. 10 Crores per P
security.pbg_per_mw | None | 0.00 | not_found | - | -
    rationale: The RfS does not state a single PBG per MW; Clause 3.24(ii) (attached page 9) defines PBG by formula as INR 23,20,000 per MW of Solar component + INR 31,60,000 per MW of Wind component + INR 36,60,000 per MW of ESS component, and the PPA Article 3.3.1 (attache
commercial.scod_months | 24 | 0.95 | validated | p48 (stated_page, 100.0), p66 (stated_page, 100.0) | -
    rationale: Clause 3.28 (attached page 7) and SCC Clause 7.2(a) (attached page 22) both state SCSD for full contracted capacity is 24 months from the Effective Date / date of execution of the PPA; no disagreement found.
commercial.ppa_tenure_years | 25 | 0.95 | validated | p35 (stated_page, 100.0), p47 (stated_page, 100.0) | -
    rationale: Clause 3.14 and Clause 3.28 state the PPA is for 25 years from the Scheduled Commissioning Date / SCSD; SCC Clause 7.1 also says 25 years from SCSD or commencement of full contracted capacity, whichever is later.
commercial.tariff_ceiling | None | 0.00 | not_found | - | -
    rationale: Searched the attached pages (RfS clauses 3.10-3.30, SCC Clauses 1-11, PPA Articles 2, 3, 4, 11, 13 and annexures) for a ceiling/maximum tariff in INR per kWh; none is stated. Only PSM charges (Rs 0.02/kWh) and trading margin (7 paise/unit) appear, which are no
commercial.min_cuf_percent | 40.0 | 0.95 | validated | p29 (stated_page, 100.0), p61 (stated_page, 100.0) | -
    rationale: Clause 3.10 and SCC Clause 6.1(b) both state the declared annual CUF shall in no case be less than 40%; the PPA template leaves the declared CUF blank and ties the lower limit to 85% of the declared value, but the tender floor is 40%.
approved identity.tender_number -> canonical value '2024_NHPC_800202_1'
```

Reading the tables: SECI has 8 of 12 fields with a value and NHPC 9 of 12; every one of those 17 values has evidence located on the page the model named. The EMD and PBG values on the SECI tender (confidence 0.40) are the Solar PV component of a component-wise formula, which the model says in its rationale; they are not a single per-MW figure.

### Run-to-run variation

The section map differs between runs (38 to 41 sections on the SECI RfS, 57 to 78 on the NHPC RfS), and with it the pages each field group receives. Before the page-selection change, a run returned no EMD, PBG or PPA tenure on the SECI tender because only the bank-guarantee formats were sent; another returned no minimum CUF on the NHPC tender. `select_pages` now adds, to the sections the routing hints name, up to 12 pages that mention each of the group's keywords, taken keyword by keyword. The final run above was made after that change. One run is not proof that the variation is gone; Stage 2 runs all tenders and will show the rate per field group. Tokens per run rose with the wider windows: about 233,000 in for SECI (USD 2.49) and 327,000 in for NHPC (USD 3.47) at the configured prices.

### Fields without a value

Checked against the page text of each document:

| Tender | Field | What the document says |
| --- | --- | --- |
| SECI FDRE-IX | pre-bid date, bid deadline | Bid Information Sheet, page 4: "Scheduled as per NIT on ISN-ETS portal" and "As per NIT on ISN-ETS portal". No date is printed |
| SECI FDRE-IX | tariff ceiling, minimum CUF | Neither "ceiling" nor "CUF" occurs in the RfS text |
| SECI FDRE-IX | EMD per MW, PBG per MW (a value was returned at confidence 0.40) | Clause 16 gives a formula by component: INR 9,68,000 per MW of solar, INR 13,68,000 per MW of wind or other RE, INR 2,40,000 per MWh of storage. The candidate holds the solar rate |
| NHPC FDRE-II | EMD per MW, PBG per MW | Formulas by component (pages 21, 40, 41): INR 9,28,000, 12,64,000 and 14,64,000 per MW for EMD; INR 23,20,000, 31,60,000 and 36,60,000 for PBG. The model returned no value and listed the components in its rationale |
| NHPC FDRE-II | tariff ceiling | No ceiling tariff is stated |

These are schema questions for Stage 2, listed in `docs/KNOWN-GAPS.md`. No field had a value with evidence that could not be located in the final runs.

### One evidence failure found and fixed during the stage

On the first NHPC run the bid deadline (12.04.2024, page 22) came back with unlocated evidence and confidence capped at 0.30. The model quoted a wrapped table cell in reading order; the text layer interleaves the label and the value. `core/services/evidence.py` now also matches a quote's words in any order over consecutive page words, with every number unchanged, at the same threshold. Two unit tests cover it, and the rerun located the quote with score 100.

## Deployment

`make deploy` was run after the last code change: images rebuilt, migrations applied (`alembic current` is `0003 (head)`), containers recreated, and the health probe answered `{"status":"ok","tenant_id":"ergplan","database":"ok"}` on `https://34.131.65.108/health`.

Checked against the deployed API from the VM with a real file (SECI FDRE-IX Amendment-01, 4 pages): `POST /api/v1/documents` 201; the worker parsed it and mapped one section of kind `amendment` in about 10 seconds; `GET .../pages/1/render` returned a PNG; `GET /api/v1/review-state` 200 with no run. That document (`85d1bb37...`, created_by `stage1-check`) is now in the app database. It was not checked from a browser outside the VM.

No extraction schema is registered in the deployed API and worker: core is schema-agnostic and the tender schemas are Stage 2. On the deployed app, upload, parse, section map, renders and sections work; `POST /documents/{id}/extract` answers `validation_failed` for any schema name until Stage 2.

## Independent review (operating rule 15)

Two reviews were run, both with only the three inputs rule 15 names (stage diff, CLAUDE.md, stage prompt).

**1. OpenAI reviewer** (`scripts/independent_review.py`, model `gpt-4-turbo-2024-04-09`, the only chat model the key on the VM can call besides `gpt-4`). First run, on the draft report: (a) to (e) all "FINDINGS: none"; (d) not applicable. Its answer cited files but no line numbers and attributed `GET /extraction-runs/{id}` to the wrong test, so it was not treated as sufficient.

**2. Second review in a fresh context** by a Claude agent, read-only. It is the same model family as the builder, so it does not satisfy rule 15 by itself; it was added for depth. It reported 20 findings (6 medium, 14 low, none high) and confirmed that the invariants hold, that every endpoint has a test, and that every truth-table write has an audit row in the same transaction.

| # | Finding | Severity | Outcome |
| --- | --- | --- | --- |
| 1 | Exact evidence match could land inside a longer number or word ("50 MW" inside "250 MW") | medium | Fixed: exact and fuzzy matches must sit on word boundaries; test added |
| 2 | Word-order-free matching accepted a quote with reversed meaning when it held no number | medium | Fixed: used only for quotes that hold a number; test added |
| 3 | Two concurrent first decisions on one field could leave two active approvals and two current facts | medium | Fixed: unique indexes in migration 0003; `approve` answers a plain error to the loser; test added |
| 4 | An older run finishing after a newer one superseded it, and could leave fields with no live candidate | medium | Fixed: the newest finished run keeps the live candidates; test added |
| 5 | Review state followed the latest run even when it was queued or failed, hiding validated candidates | medium | Fixed: latest validated run; test added |
| 6 | A failed cross-field rule was written only on the best candidate, so an alternative could be shown without it | medium | Fixed: written on every typed candidate of the fields; test added |
| 7 | Jobs left `running` by a dead worker were never recovered | medium | Fixed: re-queued when the worker starts; tests added |
| 8 | A candidate with one located and one unlocated quote was validated silently | low | Fixed: sent to review with "n of m quotes were not found"; test added |
| 9 | `approved` compared the raw final value with the coerced candidate value | low | Fixed; test added |
| 10 | Index map misaligned for characters that lower-case to two | low | Fixed; test added |
| 11 | "Retries 3 times" was implemented as three attempts | low | Fixed: four attempts, backoff 30, 60, 120 s |
| 12 | A section map that failed for good left no trace on the document | low | Fixed: `document.error`; test added |
| 13 | Storage read failure in parse left the document `uploaded`; concurrent upload of one file could answer 500 | low | Fixed (no test for the upload race) |
| 14 | Service queries scoped only through an id from a tenant-filtered row | low | Fixed: tenant filter added to each listed query; the job queue stays shared (KNOWN-GAPS.md) |
| 15 | `not_found` candidates reach the reviewer without evidence; a fact made by editing one has only the reviewer's decision as evidence | low | Not changed; KNOWN-GAPS.md, for the Stage 3 UI |
| 16 | A field with only `rejected` candidates cannot be decided; an identical approval repeated after re-extraction answers 422 | low | Not changed; KNOWN-GAPS.md |
| 17 | 80-page cap per group and page-selection fallbacks were not disclosed; an out-of-range page position is stored as the window's first page | low | Disclosed in this report and KNOWN-GAPS.md |
| 18 | The reviewer script calls OpenAI outside `core/llm/` | low | Kept: build tooling, recorded in DECISIONS.md |
| 19 | Report and ARCHITECTURE.md wording: grep test described too broadly, "all filtered by tenant", e2e on one tender, matcher description | low | Corrected |

(Twenty findings as counted by the reviewer; some rows above merge two.)

**3. OpenAI reviewer rerun** on the final diff and this report: run twice.

- Rerun 1: (a), (b), (c) "FINDINGS: none"; (d) not applicable; (e) one finding: "Full implementation details for handling tender versions are not provided." The report made no such claim, but a line was added under "Skipped or changed" saying plainly that tender versions are Stage 2.
- Rerun 2, after that change: (a), (b), (c) none; (d) not applicable; (e) the same finding again: "Tender versioning and linking canonical facts to versions are claimed but not supported in this stage."

**The reviewer has therefore not reported "none" on (e), and rule 15 is not fully met.** I could not find the claim it objects to: this report and DECISIONS.md say that no tender version exists in Stage 1. The diff it reads also contains ARCHITECTURE.md's section on Stage 2 tender documents and the master-prompt amendment, which describe versioning as future work and may be what it is reading as a claim. I stopped rerunning rather than reword documents until the reviewer goes quiet. The line numbers it cites in (a) and (c) do not match the files (for example, candidate audit "extract.py lines 180-185"), so its "none" answers there carry little weight either; the second review above is the one that examined the code.

Checklist item (d): not applicable until Stage 3 (`make trace` does not exist yet).

## Skipped or changed, and why

- **`delta_kind = exact` is never written.** When the final value equals the candidate, no feedback row is created.
- **Two extra candidate statuses**, `not_found` and `rejected` (DECISIONS.md).
- **Objects instead of documents.** Candidates, approvals and facts hang on `(object_type, object_id, object_version)`; in Stage 1 the object is the document.
- **Tender versions are not built.** No `tender` or `tender_version` table exists in Stage 1 and nothing here creates or compares versions; that is Stage 2. Core only stores the `object_version` number it is given, which is always 1 in Stage 1.
- **`make trace`.** Still Stage 3; checklist item (d) of the independent review is not applicable.
- **Scanned pages.** A page with fewer than 50 characters is flagged `has_text_layer = false`. The model still sees it, because extraction sends native PDF pages, but evidence cannot be located on it. No such page occurred in the two test tenders, so this path is covered by unit tests only.
- **The e2e ran on two tenders, not one**, and has a 30-minute timeout.
- **Page selection.** At most 80 pages per field group, with a keyword and then first-pages fallback when no section matches (KNOWN-GAPS.md).
- **Migration numbering.** Stage 1 used 0002 and 0003; Stage 2 starts at 0004.

## Things to know

- The stack was found with the API container unhealthy at the start of this session (`pymupdf` missing from an image built before the dependency was added). The images were rebuilt and migration 0002 was applied to the app database.
- `git push` over SSH fails in a new session because the key is passphrase-protected; pushes went over HTTPS with the `gh` login.
- The master prompt was amended on 2026-10-04 (Stage 2 field namespace and domain packs; Stage 5D public library and widgets). Nothing from it was built. Two points need your decision before Stage 2 (see "Open questions").
- Real-model cost of this stage's e2e runs: about USD 22 in total over three full runs and four single-tender runs (one of them cut short by the test timeout).

## Open questions

1. **Stage 2 layout.** The amendment puts schemas, prompts and sector validators under `tender/domain_packs/`. CLAUDE.md's fixed layout names `tender/schemas/`, `tender/prompts/` and `tender/validation/`. Confirm that `domain_packs/` replaces all three and that CLAUDE.md should be updated.
2. **Field paths.** Confirm that the field catalogue's paths are to be renamed into the `core.*` and `sector.power.*` namespaces in Stage 2, including the FIELD-TRACE examples in CLAUDE.md.
3. **Stage 5D base text.** The file had no Stage 5D; the two sub-sections were added as a new block. The MCP server and the base tools (search_tenders, get_tender, get_field, get_document_page, list_changes, compare_tenders, reliability_report) are not specified anywhere yet.
4. **The 80% line.** It is not met when counted over all 12 fields because the documents do not state some of them. Is "located evidence for every value returned, and null for what the document does not state" the bar you want, or should the test schema be changed to fields every FDRE RfS states?
5. **EMD and PBG as formulas** (NHPC) and **dates deferred to the NIT** (SECI): how should the Stage 2 schema hold them?
6. **Independent review.** The OpenAI key exposes only `gpt-4-turbo` and `gpt-4`. Its review was shallow and its one repeated finding is not a claim the report makes (see "Independent review"). Do you accept Stage 1 on that basis, or enable a current model on the OpenAI project so the review can be rerun with `python -m scripts.independent_review --stage 1 --model <name>`?

Stage 1 stops here. Next: `Run Stage 2 of docs/MASTER-PROMPT.md.`
