# Stage 2 report: tender domain layer

Date: 2026-10-04. Diff: `git diff stage-2-start..HEAD`. Architecture changes: `docs/ARCHITECTURE.md` ("Tender domain layer" and "What changed this stage"). Extraction results: `docs/reports/EXTRACTION-SUMMARY.md`.

## Definition of done (master prompt, row 2)

| Check | Result |
| --- | --- |
| All 9 schema YAMLs load | Yes. `tests/tender/test_packs.py::test_every_tender_type_has_a_yaml_that_loads` and `::test_every_field_has_a_section_a_value_type_a_label_and_help`; 80 to 89 fields per type |
| Every validator has pass and fail tests | Yes. `tests/tender/test_core_pack_rules.py` (date order, EMD and PBG within 10x), `tender/domain_packs/power/tests/test_rules.py` (bid capacity order, transmission elements, ranges), `tests/tender/test_value_types.py`, and the corrigendum rule in `tests/tender/test_tenders.py` (passing and failing case) |
| Corrigendum carry-forward test green | Yes. `tests/tender/test_tenders.py::test_corrigendum_carry_forward_leaves_untouched_facts_and_their_evidence_unchanged`, and through HTTP in `tests/api/test_tenders.py::test_full_tender_flow_with_an_amendment_through_the_http_api` |
| All tenders extracted | Yes: 13 tenders, 25 versions, 42 PDFs, 3,455 pages; 38 extraction runs, all validated |
| EXTRACTION-SUMMARY.md written with cost | Yes |
| Evidence-location rate >= 95%, per tender | Yes. 709 of 711 values returned have located evidence (99.7%). Twelve tenders are at 100%; SECI FDRE-RTC-V is at 97% (61 of 63) |
| Answer rate reported, per tender | Yes: 65% overall (711 of 1,098 fields), from 32% (a 14-page NTPC notice) to 80% (NHPC FDRE-II) |
| `make test` green | 339 Python tests and 3 web tests pass; the watcher's eight checks are green |
| `make deploy` serves the app | Yes, see "Deployment" |

## The two numbers

| Type | Tender | Versions | Fields | With a value | Located | Evidence-location rate | Answer rate | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bess | seci-ess-iv | 1 | 89 | 55 | 55 | 100% | 62% | 10.53 |
| epc | seci-gaya-60mw | 1 | 89 | 56 | 56 | 100% | 63% | 18.05 |
| epc | seci-ramagiri-70mw-bess | 3 | 89 | 58 | 58 | 100% | 65% | 24.71 |
| fdre | nhpc-fdre-ii | 1 | 85 | 68 | 68 | 100% | 80% | 13.34 |
| fdre | seci-cfd-i | 4 | 85 | 66 | 66 | 100% | 78% | 25.26 |
| fdre | seci-fdre-ix | 2 | 85 | 64 | 64 | 100% | 75% | 26.90 |
| fdre | seci-fdre-rtc-v | 5 | 85 | 63 | 61 | 97% | 74% | 23.90 |
| generation | ntpc-phes-2000mw | 1 | 82 | 31 | 31 | 100% | 38% | 1.84 |
| hybrid | ntpc-hybrid-03 | 1 | 81 | 59 | 59 | 100% | 73% | 8.52 |
| solar | seci-cni-1-700mw | 2 | 83 | 59 | 59 | 100% | 71% | 11.32 |
| transmission | recpdcl-beed-tbcb | 1 | 85 | 50 | 50 | 100% | 59% | 10.94 |
| wind | ntpc-rel-600mw-anantapur-wtg | 1 | 80 | 26 | 26 | 100% | 32% | 2.78 |
| wind | seci-wind-tranche-xx | 2 | 80 | 56 | 56 | 100% | 70% | 12.55 |
| **all** | 13 tenders | 25 | 1,098 | 711 | 709 | 99.7% | 65% | 190.65 |

By tender type, the evidence-location rate is 100% for every type except fdre (99%, 259 of 261). **Fields under 95% by tender type:** `sector.power.common.min_bid_mw` and `sector.power.common.max_bid_mw` for fdre (3 of 4 located each). Both misses are in Amendment-01 of SECI FDRE-RTC-V (version 2, page 1): the quote was not found by any of the four matchers. They are shown as `needs_review` at confidence 0.3 with "evidence not located on p.1".

These are candidates. Nothing has been reviewed, so no accuracy number exists yet; that is Stage 4. "Located" means at least one of the candidate's quotes was found on a page. Ten candidates have some quotes found and some not, or none; they are `needs_review`.

**The SECI FDRE-IX cost includes a repeat.** It was the pilot (USD 13.40), and was extracted again (USD 13.50) after the evidence matcher changed, because candidates and their evidence are immutable.

## What was built

- **Migration 0005.** `tender`, `tender_version`, `tender_version_document`, `tender_field_def` (with namespace, domain, subdomain), and `extraction_run.groups`.
- **Domain packs (`tender/domain_packs/`).** Core pack: `common.yaml` (46 fields, `core.<section>.<field>`), shared validators, eight section prompts. Power pack: `pack.yaml` (29 common power fields, `sector.power.common.<field>`), nine type YAMLs (`sector.power.<type>.<field>`), ten section prompts, sector validators, pack tests. Fields are seeded from the field catalogue; three were added under the Stage 2 schema rules: `core.guarantees.emd_formula`, `core.guarantees.pbg_formula`, `core.key_dates.dates_deferred_note`.
- **Loader (`tender/services/packs.py`).** Compiles each type into the core schema `tender.<type>` `v1` at start-up and registers schemas, value types and rules with core. Combined types by `inherits`, with a conflict raised as an error. Malformed files are refused.
- **Value types.** `money_inr`, `percent`, `duration_months`, `mw`, `mwh`, `kv`, `km`, `record_list` (transmission elements, EPC scope matrix).
- **Prompts.** One per section, each extending core's `extract/v1` with domain guidance: agency vocabulary, lakh and crore, amendments override the base, deferred dates, formulas versus per-MW figures, the three SCOD references. The summary is a section with its own prompt.
- **Validators.** `date_order`, `emd_pbg_within_10x`, `bid_capacity_order`, `elements_have_kv`, ranges in the YAML, type rules as required fields, and the corrigendum rule `later_version_evidence`.
- **Services.** `TenderService` (create, `add_version`, `attach_document`, `start_extraction`, `refresh_status`), `versioning.plan_groups`, `current_view`, `sync_field_defs`, `extraction_summary`.
- **API (`api/v1/tenders/`).** `POST /tenders`, `GET /tenders`, `GET /tenders/{id}`, `POST /tenders/{id}/versions`, `GET /tenders/{id}/versions`, `GET /tenders/{id}/view`, `POST /tenders/{id}/extract`, `GET /tenders/{id}/review-state`, `GET /schemas/tender/{type}`, `GET /reports/extraction-summary`.
- **Management command (`scripts/ingest_tenders.py`).** `ingest`, `extract`, `resume`, `wait`, `summary`.
- **Core extension points**, each with a test and a line in DECISIONS.md: a run limited to named groups; supersession per field and per document; review state across the runs of a version; run rules; prompt inheritance; `item_keys`; and a fourth evidence matcher.

## How versions and amendments came out

The command grouped the 42 PDFs into 25 versions: 13 originals and 12 later versions (10 amendments, 2 clarifications, including the Revised RfS of SECI CfD-I as version 2).

| Tender | Version | Kind | Sections read | Fields with a value |
| --- | --- | --- | --- | --- |
| seci-cfd-i | 2 | revised RfS (amendment) | all 10 | 62 |
| seci-cfd-i | 3 | amendment | 2 | 8 |
| seci-cfd-i | 4 | amendment | 6 | 14 |
| seci-cni-1-700mw | 2 | clarification | 2 | 4 |
| seci-fdre-ix | 2 | amendment | 4 | 11 |
| seci-fdre-rtc-v | 2 | amendment | 9 | 30 |
| seci-fdre-rtc-v | 3 | amendment | 7 | 16 |
| seci-fdre-rtc-v | 4 | clarification | 7 | 10 |
| seci-fdre-rtc-v | 5 | amendment | 8 | 23 |
| seci-ramagiri-70mw-bess | 2 | amendment | 9 | 23 |
| seci-ramagiri-70mw-bess | 3 | amendment | 7 | 20 |
| seci-wind-tranche-xx | 2 | amendment | 3 | 9 |

An amendment often restates a field without changing it (the tender number, the issuing agency), so "fields with a value" is more than "fields changed". I did not compare amendment values with the base values; the reviewer sees both versions.

## Validation failures (21 fields shown as `needs_review`, 39 flags over all versions)

| Rule | Flags | What they are |
| --- | --- | --- |
| `required_present` | 23 | Bid submission deadline missing on 9 tenders (SECI defers it to the NIT, which is not in the folders), 13 of the 23 on later versions that do not mention the field; the Beed RFP prints no reference number; FDRE profile fields on two RTC-V amendments |
| `evidence_not_located` | 10 | Two values with no quote found (above); eight with one of several quotes not found |
| `date_order` | 2 | NHPC FDRE-II: queries close on 26.03.2024, before the pre-bid meeting on 28.03.2024. The rule's chain is the one the stage prompt gives; the dates may well be right |
| `range` | 2 | Both EPC tenders: `ppa_tenure_years` = 5, which is the O&M period, not a PPA |
| `type` | 2 | An empty list returned for `named_states_or_sites` |

## What extraction did not return, and why

- **Bid dates.** 9 of 13 tenders have no bid deadline. `dates_deferred_note` is filled on them and names the NIT.
- **Formulas.** On the FDRE tenders EMD and PBG came back in the formula fields with the per-MW fields empty, as the schema rule intends.
- **Units.** Bid validity in months, financial closure counted back from SCSD, turnover and liquidity per MW: left empty by instruction, with the figures in the rationale (KNOWN-GAPS.md).
- **Short notices.** The two NTPC tenders are notices of 3 and 14 pages; answer rates of 38% and 32% reflect the documents.

## Things that went differently from the stage prompt

- **A section is the extraction group and the review block.** There is no separate summary service; the summary is a section extracted like the others.
- **Which sections an amendment touches is decided by keywords** in its text, not by matching its section map against the base.
- **Extraction of a version is started explicitly** (API or command) once its documents are parsed, not by `add_version`.
- **Migration number** is 0005 (0003 and 0004 were used by Stage 1).
- **13 tenders, not 11**, as decided in Stage 0.
- **PSA documents are stored but not read**; no catalogue field belongs to them.
- **The test watcher was stopped twice** while parsing and extraction ran, because the VM has two cores. Each commit in those windows was preceded by a full `make check`. It is running again.

## The interruption

The model account ran out of credit at 15:44 UTC during the full run: 30 of 38 runs failed at once. I added `resume` to the command; after you refilled the account, the 30 runs were put back in the queue and continued at the first section each had not finished. No section was paid for twice because of the interruption.

## End-to-end test (real model, `tests/e2e/test_tender_pipeline.py`)

Run once on the NTPC pumped-hydro notice (3 pages) through the tender API and the worker: create, upload as the original version, parse, section map, extract ten sections, validate, approve the tender number, read the current view. 30 of 82 fields returned a value, 30 of 30 with located evidence; USD 1.79; passed in 4 min 36 s. This ran before the fourth evidence matcher was added and was not rerun.

## Cost

| Item | USD |
| --- | --- |
| Extraction runs, 13 tenders (table above) | 190.65 |
| Section maps, 42 documents | 12.66 |
| End-to-end test | 1.79 |
| **Stage 2** | **about 205** |
| Stage 1 | about 22 |
| **Running total** | **about 227** |

Figures are tokens from `llm_call_log` at the configured prices (USD 10 per million in, USD 50 per million out), not the provider's invoice. The independent reviewer's OpenAI calls are not included.

## Deployment

`make deploy` was run after the extraction finished: images rebuilt, `alembic current` is `0005 (head)`, containers recreated (one worker), health probe `{"status":"ok","tenant_id":"ergplan","database":"ok"}` on `https://34.131.65.108/health`.

Checked against the deployed API from the VM: `GET /api/v1/tenders` returns 13 tenders, all `extracted`; `GET /api/v1/schemas/tender/fdre` 200; `GET /api/v1/reports/extraction-summary` returns 13 tenders with 711 values, 709 located; `GET /api/v1/tenders/{id}/review-state` for SECI FDRE-IX returns version 2 (amendment) with 11 changed fields of 85; `GET /api/v1/tenders/{id}/view` returns 0 of 85 decided, as nothing is approved yet. `tender_field_def` holds 759 rows. Not checked from a browser outside the VM. The web front end is still the Stage 0 placeholder; the reviewer UI is Stage 3.

The three workers used for the run were scaled back to one. The extracted candidates are in the app database, ready for review in Stage 3.

## Independent review (operating rule 15)

Reviewer: `scripts/independent_review.py` on `gpt-6.1-sol`, given only the stage diff, CLAUDE.md and the stage prompt. Outputs are in `docs/reports/stage-2-artifacts/`.

**Run 1** (on the code, before the full extraction and before this report existed): (b), (c) none; (d) not applicable; (a) 2 findings; (e) 1.

| # | Finding | Outcome |
| --- | --- | --- |
| a1 | A document of role amendment or clarification could be added to an existing version instead of creating a new one | Fixed: `TenderService.attach_document` refuses those roles; tests added |
| a2 | The extraction summary was only a management command, not an API operation | Fixed: `GET /api/v1/reports/extraction-summary`; test added |
| e1 | No stage report in the diff | The report did not exist yet |

**Run 2** (on the draft report): (b), (c) none; (d) not applicable; (a) 2; (e) 10.

| # | Finding | Outcome |
| --- | --- | --- |
| a1 | With `version_no`, the request's `kind` was ignored: a document declared as an amendment could still be filed in an existing version under another role | Fixed: `kind`, when sent with `version_no`, must be that version's own kind; `kind` is required for a new version; tests added |
| a2 | Write routes take the actor from the `X-Reviewer` header, not from a review token | Not resolvable by code in this stage: the token middleware is Stage 3 by the master prompt. Until then the header is the phase-1 identity (ARCHITECTURE.md, API surface) |
| e1 to e4, e6 to e10 | Run results, rates, counts, test results, costs, the interruption and the deployment are not provable from a diff | Statements of this report. To support them, three listings from the app database are now committed: `extraction-runs.txt` (every run with tokens and cost), `validation-failures.txt`, `model-calls.txt`; and `EXTRACTION-SUMMARY.md` is generated from the database |
| e5 | "Seeded from the field catalogue" cannot be checked because the catalogue is not in the reviewer's input | The catalogue is in `docs/MASTER-PROMPT.md`, outside the stage prompt section the reviewer receives |

RUN3_PLACEHOLDER

## Open questions

1. **Cost per tender.** About USD 10 for one RfS and USD 18 to 27 for a tender with agreements or amendments, on 80 pages per section at most. Is that acceptable for the review phase, or should Stage 4 look for cheaper routing once accuracy per section is known?
2. **NITs.** Nine tenders have no bid dates because the NIT is not in the folder. Do you want to add the NITs before the reviewers start?
3. **Required fields on amendments.** An amendment that does not mention the bid deadline is flagged for it. I propose the Stage 3 UI shows only the fields a later version changes (`changed_fields`); confirm, or say if you would rather have the flag removed in core.
4. **EPC type.** Should the PPA and tariff fields be dropped from the `epc` type? They do not apply to an EPC contract and one of them was filled wrongly on both EPC tenders.
5. **Periods in other units** (validity in months, closure counted back from SCSD, turnover per MW): change the schema now, or after the first reviews show how often it matters?
6. **Date-order rule.** Keep "pre-bid before queries close", or drop that pair?

Stage 2 stops here. Next: `Run Stage 3 of docs/MASTER-PROMPT.md.`
