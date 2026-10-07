# Stage 6 prompt: results import as a reviewed object type

Written 2026-10-07 from `docs/reports/RE-TENDER-RESULTS-ASSESSMENT.md`, at the owner's
request. Runs after Stage 4's reliability report and the amendment diff view, and only when
the owner says so. Not before. CLAUDE.md's operating rules, invariants and locked decisions
apply unchanged; where this prompt and an invariant seem to conflict, the invariant wins and
the conflict goes in the stage report.

The point of the stage: nothing from the dataset reaches the application unreviewed. An
imported record is a candidate like any other. A reviewer opens the source publication,
checks the table against the PDF page, and approves. 122 review sittings, and only approved
rows become canonical or reachable through the API.

```markdown
# STAGE 6: award results from Ergplan/RE-tender-results, imported as candidates, reviewed, canonical only on approval

## Source

- `/work/ref/RE-tender-results` (read-only, commit f6d1d33 of 2026-10-07): 623 records in
  `tender-results-viewer/public/data.json`, 122 archived sources with sha256 in
  `tender-results-viewer/public/sources/`, RfS numbers in `seci-data/records.json`
  (`tender_reference`). Nothing is imported from it at runtime; the importer reads it once.
- Before importing, list the hosts of every source URL in the dataset and confirm they are
  all on the allowlist. At the time of writing they are seci.co.in, cercind.gov.in,
  sjvn.nic.in and ireda.in, all of which qualify. Anything else stops the import until the
  owner decides.

## Source admissibility (DECISIONS.md, 2026-10-07)

- Only original sources are admissible. A source publication must be issued by the
  procuring agency or the regulator on its own domain: seci.co.in, ntpc.co.in, nhpc.nic.in,
  sjvn.nic.in, ireda.in, cercind.gov.in and equivalents. Trade press, aggregators,
  consultancy reports, LinkedIn posts and secondary databases are never a source for a
  value, whatever they report, and are not stored as sources.
- The importer enforces this: a source whose host is not on the allowlist is rejected, not
  imported with a lower verification tier. The allowlist is a committed file under
  `infra/` (`infra/source-domains.yaml`), so adding a legitimate agency domain is an edit
  and a rerun. Subdomains of a listed domain qualify; nothing else does.
- Secondary sources may be used to find a document, never to supply a figure. If a trade
  report says a tender cleared at a price and no official publication states it, the field
  stays null with a note, not populated from the report.

## Object type `award`

- One object per source publication (122), not per record (623): a result sheet or a CERC
  adoption order is one object. Winners are a `record_list` keyed by (bidder, allocation);
  the row carries capacity, capacity unit, price, price unit, adopted capacity, adopted
  price, status, notes. Scalar fields: procurer, reference (RfS number or petition number),
  result kind (auction result, CERC adoption order, allocation, register), order or auction
  date, status, verification tier, source hash (the document's sha256).
- Optional `tender_id` foreign key, set only on an exact string match of the RfS number
  against `tender.external_ref`, never fuzzy. At the time of writing that is 3 tenders
  (22 rows); the two CERC orders that cite our NHPC FDRE-II and NTPC Hybrid-03 tender
  numbers in their text are linked only if the importer finds the exact tender number in
  the order's page text, and the link is recorded with the page it was found on.
- Schema YAML in a new namespace `result.*` (a `result` pack beside `core` and `power`,
  loaded by the same catalog), a model table `award` under `tender/models/` with the
  tenant and audit columns, a migration, routes under `/api/v1/awards/` (list, get, review
  state, approvals through the existing core review routes), and review tokens widened
  from `review_token.tender_id` to (`object_type`, `object_id`): a migration and a
  middleware change, with the tender routes unchanged for the reviewer.

## Documents

- Through the normal ingest: `IngestService.upload`, deduplicated on sha256, with
  `source_url` = the dataset's `url` and `retrieved_on` = its `checked` date. The importer
  asserts that our sha256 equals the dataset's `sha256` for every file and stops on the
  first mismatch. Parsed by the worker as any document, so evidence highlights work.
- The 6 HTML registers (sjvn.nic.in award pages, 15 rows): leave them out rather than
  converting. They are the least verified rows in the set and not worth a conversion path.
  Record the omission in the stage report with the row count.

## Importer

- A management command, `scripts/import_results.py`, run once per dataset commit and safe to
  repeat (a document already imported from the same sha256 is skipped). It produces one
  `ExtractionRun` per document in a new run mode `import` (`RUN_MODES` gains it;
  `ExtractService.start_run` does not offer it), `model = "RE-tender-results@<commit>"`,
  `prompt_name = "import/re-tender-results"`, `prompt_version = "v1"`, no `llm_call_log`.
- Candidates carry the record values; `rationale` is the dataset's verification tier plus
  its notes; confidence is capped (0.8) so that no imported row ranks above a located,
  validated reading. Status flows through validation like any candidate.
- Evidence is resolved against the cited page with `core.evidence.resolver.resolve()`: the
  bidder name and the price (or the capacity when there is no price) must be located on
  `page`. Where they cannot be located, the candidate stays unlocated, is shown at capped
  confidence with the reason, and cannot be approved without reviewer evidence. That
  invariant already handles it; the importer does not work around it. A page range
  ("13–14") is tried page by page.
- Deterministic validators in `tender/domain_packs/result/validation/`: unit consistency
  (price unit matches the result kind), capacity > 0, adopted capacity <= awarded capacity,
  price within the band for its unit, every winner row has a status.
- No LLM call anywhere in the import. `core/llm/` is not touched.

## Producer tag IMPORT

- A fifth producer tag `IMPORT` in FIELD-TRACE (`scripts/gen_field_trace.py`), in
  ARCHITECTURE.md's truth pipeline, and in the master prompt's column definition
  (`docs/MASTER-PROMPT.md`, section 5, FIELD-TRACE columns). The tag names the dataset and
  commit, as `LLM` names the prompt and version.

## Review

- An object-agnostic review page under `web/src/review/`, driven by
  `/api/v1/core/review/{object_type}/{object_id}` and the existing approval route, so the
  trace CI passes for every `result.*` field. The tender review screen is unchanged.
- A review token per award object; the owner receives the 122 links in a message, never
  in the repo. `make gold` is not extended to awards in this stage.

## Tests

- Unit tests for every validator and for the allowlist check (a listed domain, a subdomain
  of one, an unlisted host, an http URL of a listed domain). Importer tests on a fixture
  dataset of three records and two PDFs: hash equality enforced, a rejected host imports
  nothing, evidence located and not located, repeat run imports nothing twice, no
  `canonical_fact` row exists after the import. Integration tests for every `/api/v1/awards`
  route and for the widened token. One end-to-end test on a real one-page SECI result sheet
  from the dataset: import, review, approve one row, read it back as canonical.

## Report

- STAGE-6-REPORT.md: documents imported and skipped (with the hash check result), rows
  imported and the 15 left out, evidence located vs unlocated per source kind, the 5 linked
  tenders, hosts seen, independent review under operating rule 15, and the note that
  linkage coverage (34 of 623 records on 5 of 13 tenders at the time of writing) makes the
  outcome dataset a demonstration until the tender corpus grows.

## Done when

- Every imported row is a candidate with its source document, page and (where located)
  evidence; no canonical fact exists that a reviewer did not approve; the allowlist is
  committed and enforced; the trace regenerates without diff; all tests green; `make
  deploy` serving the award review pages; the 122 links delivered. STOP.
```
