# RE-tender-results: import assessment

Assessment of `Ergplan/RE-tender-results` (clone at `/work/ref/RE-tender-results`, read-only,
commit `f6d1d33` of 2026-10-07, 435 MB) as a source of reviewed award results for the Tender
Intelligence Engine. Written 2026-10-07 after Stage 4 closed. Assessment only; nothing built.

## 1. Shape of `tender-results-viewer/public/data.json`

Top level: `asOf` ("7 October 2026"), `records` (623), `sources` (122), `coverage` (6 agency
notes). The viewer's `build_data.py` emits it from three research datasets (`seci-data/`,
`ntpc-nhpc-data/`, `sjvn-ireda-nlc-data/`). `id` is positional (`r1`...) and changes on
rebuild; it is not a stable key. A stable key is (source sha256, page, bidder, allocation).

### Fields per record (25)

| Always populated | Partially populated |
| --- | --- |
| `agency` (SECI 365, NTPC 111, NHPC 75, SJVN 67, IREDA 5), `bidder`, `project` (title), `reference`, `technology` (15 values), `allocation` (Published result 365 / Base 227 / Greenshoe 31), `status` (12 values), `dateType`, `page`, `source` (-> `sources.id`), `verification` (5 fixed strings), `dataset`, `flag`, `nlc`, `id` | `capacity` 504, `capacityUnit` 594 (7 units: MW 446, kW 84, MW/year, MT/year, MT, MW manufacturing), `price` 551, `priceUnit` 551 (10 units: INR/kWh 491, INR/kg, INR/MW VGF, INR/MW/month, months (PPA term), INR contract value), `adopted` 237, `adoptedPrice` 51, `date` 448 (dd.mm.yyyy; 22 are multi-date strings), `notes` 241, `related` 422 (agency tender page URL) |

### Where the qualifications live

- `notes`: free text. Greenshoe awarded vs adopted quantities, disqualified bidders, PPA
  terminations, tariff discrepancies, page references ("Greenshoe award 730 MW, adopted
  470 MW; pp.18,27"). SECI 174 rows, NTPC/NHPC 30, SJVN/IREDA 37.
- `status`: only 257 rows are plain "Awarded". Others: "Tariff adopted" 169, "L1 ranked; award
  not confirmed" 80, "Tariff adoption recorded" 52, "Empanelled" 27, "Company register
  disclosure" 15, "Partially adopted" 8, "Historical award; not adopted in this order" 5,
  "Published allocation" 5, "Award reported; not adopted in this order" 3, "Selected" 1,
  "Award in LoA; adoption quantity ambiguous" 1.
- `adopted` / `adoptedPrice`: kept separate from the award (CERC orders adopt less than was
  awarded in several greenshoe cases).
- `verification`: the source tier ("Official SECI result publication", "Official CERC order;
  historical award and adoption recorded separately", "Official primary source; row checked
  against published table", "Official company register checked; missing fields left blank",
  "Official sources checked; tariff discrepancy flagged").
- `flag`: derived, not editorial. `bool(notes) or status != <primary status of the dataset>`
  (SJVN/IREDA also flag a missing capacity or price). 256 rows flagged.
- Missing values are left `null`: 109 SECI rows without capacity, 60 without price, 175
  without a date. Units must be read before any comparison; IREDA prices are viability-gap
  funding in INR/MW, not tariffs.

### What `data.json` drops

The RfS number. `reference` is the SECI catalog id (`SECI000001`) for SECI rows and the CERC
petition number (`721/AT/2020`) for NTPC/NHPC/SJVN rows; 15 SJVN rows carry a tender name
("Wind-2 (1200 MW tender)"); only the 5 IREDA rows carry an RfS number, inside `project`.
The RfS number survives in `seci-data/records.json` (`tender_reference`, populated 365/365,
joined on `tender_id`) and in `seci-data/catalog.json` (`reference`, 217 of 284 entries), and
for CERC rows only inside the order PDF text.

## 2. `tender-results-viewer/public/sources/`

128 files: 116 PDFs, 6 HTML pages, 6 `.txt` extractions of those pages. Each of the 122
`sources` entries carries `id`, `url`, `file`, `name`, `sha256`, `kind` (PDF 116, Web page 6),
`checked` (all 2026-10-07); the web pages also carry `text` (path of the extraction). Hosts:
seci.co.in 73, cercind.gov.in 42, sjvn.nic.in 6, ireda.in 1. Every record's `source`
resolves and every source is referenced.

- The PDFs are complete documents, not extracts. 1,171 pages in all; 70 are one-page SECI
  result sheets (xlsx-to-PDF website uploads, complete as published); the 42 CERC orders run
  15 to 54 pages, from "Page 1 of N" to the signature page ("Petition ... is disposed of.
  Sd/-"). All 116 have a text layer on page 1.
- Page citations are per record (`page`): an integer for 607 rows, a range (`13–14`) for 1,
  `"HTML award register"` for the 15 SJVN register rows (the least verified rows).
- The repo holds 352 PDFs in all; the other 230 sit in the research `sources/` folders and
  in `outputs/*.zip` (deliberate duplicates per the README). Verification screenshots
  (`check_*.png`) sit beside the research datasets.

## 3. Matches against our corpus (13 tenders)

| Basis | Records | Our tenders |
| --- | --- | --- |
| `data.json` alone (RfS number in the file) | 0 | none |
| With `seci-data/records.json` (`tender_reference` == `tender.external_ref`) | 22 | `seci-fdre-ix` (SECI000258, 3 awards), `seci-fdre-rtc-v` (SECI000240, 7), `seci-wind-tranche-xx` (SECI000250, 12) |
| By citation inside the CERC order text (no JSON carries it) | 12 | `NHPC_235_AT_2025` cites "Tender No. 2024_NHPC_800202_1" -> `nhpc-fdre-ii` (8 rows: 5 base adopted, 3 greenshoe of which 2 partially adopted); `NTPC_774_AT_2025` cites "NTPC/RE-CS/2024-25/HYBRID-03" -> `ntpc-hybrid-03` (4 rows adopted) |
| Total | 34 of 623 | 5 of 13 |

Five more of ours are in the SECI catalog with "no successful-bidder PDF linked"
(`seci-ess-iv`, `seci-gaya-60mw`, `seci-ramagiri-70mw-bess`, `seci-cfd-i`,
`seci-cni-1-700mw`). Three are outside the dataset's agencies (`ntpc-phes-2000mw`,
`ntpc-rel-600mw-anantapur-wtg`, `recpdcl-beed-tbcb`). The catalog's `detail_url` entries
are a ready list for watching those results later.

## 4. Importing as a reviewed object type, no re-extraction

The core is already object-agnostic: `ExtractionRun`, `Approval` and `CanonicalFact` carry a
free `object_type`; `ApprovalService`, `ReviewStateService` and
`/api/v1/core/review/{object_type}/{object_id}` work for any type. The tender layer is what
hardcodes `OBJECT_TYPE = "tender"`, review tokens per tender (`review_token.tender_id`) and
the UI routes. The import fits the truth pipeline: the research rows become candidates with
evidence against the archived PDF; a reviewer approves them; approval writes canonical.

1. **Object: `award` per source publication (122), not per record (623).** One object per
   result sheet or CERC order, winners as a `record_list` field keyed (bidder, allocation),
   plus scalar fields: procurer, reference (RfS or petition number), result kind, order or
   auction date, status, verification. 122 review sittings instead of 623; the reviewer sees
   one table against one PDF. Optional `tender_id` FK for the 5 matched. Needs a schema YAML
   (new namespace, e.g. `result.*`), a model table, a migration, routes, and a token scheme:
   widening review tokens to (object_type, object_id) is a middleware change.
2. **Documents through the normal ingest.** `IngestService.upload` dedups by sha256; the
   importer asserts our hash equals the dataset's `sha256`, so the link to the archived
   version is preserved by construction. `ParseService.parse` gives pages with char boxes so
   evidence highlights work. Ingest refuses non-PDF input, so the 6 HTML registers are either
   printed to PDF or their 15 rows are left out.
3. **Provenance needs a home.** `Document` has no `source_url` or `retrieved_on`; the manifests
   carry those for tenders, documents do not. Two columns (or a `document_source` table) is a
   migration, i.e. a data-model decision for the owner.
4. **Importer as a management command** (`scripts/import_results.py`). One `ExtractionRun` per
   document in a new run mode (`RUN_MODES` are sync and batch, plus the internal `record`;
   an `import` mode with `model = "RE-tender-results@f6d1d33"`,
   `prompt_name = "import/re-tender-results"`), candidates holding the record values,
   `rationale` = `verification` + `notes`, confidence capped. Evidence:
   `core.evidence.resolver.resolve()` locates the bidder name and tariff on the cited page;
   where it cannot (reordered table cells, page ranges, HTML rows) the candidate stays
   unlocated and cannot be approved without reviewer evidence, as the invariant requires.
   Deterministic validators: unit consistency, adopted <= awarded, price band per unit.
5. **A fifth producer tag.** FIELD-TRACE knows LLM, RULE, HUMAN and AGENT; an `IMPORT`
   producer touches `scripts/gen_field_trace.py`, ARCHITECTURE.md and the master prompt's
   column definition. That, with the migration, is why this stops at assessment under the
   operating rules.
6. **UI and trace.** The trace check fails any schema field without a UI component and route,
   so the reviewer page must exist before the import can merge: an object-agnostic review
   page (the `/core/review` endpoints already serve it) or an award page under
   `web/src/review/`.

Rough size: a stage's worth. Schema, models, migration, routes and tests about 1.5 days;
importer, evidence resolution and tests about 1 day; UI 1 to 1.5 days; docs, trace and
independent review about 0.5 day. Nothing is dropped: notes, status, adopted vs awarded,
verification tier and hash all land in the record value, the rationale, the document and
the run.

## Decisions for the owner

- Per-publication `award` objects (all 623 rows) versus attaching the 34 matched rows as a
  `result` document on the 5 tenders (needs a new version kind; covers 5% of the dataset).
- Whether the 15 HTML-register rows are worth converting the archived pages to PDF.
- Where document provenance (URL, retrieved date, dataset commit) is stored.
