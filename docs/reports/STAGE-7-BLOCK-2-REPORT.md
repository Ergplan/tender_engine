# Stage 7, Block 2 report: any input works (2026-10-24)

Block 2 of the owner's completion plan (`docs/COMPLETION-PLAN.md`), built on the e2-medium:
the resize hand-over was written at the block's start (`STAGE-7-BLOCK-2-RESIZE.md`) and the
owner said to keep building, so every timing below is the small machine's and is the
evidence the resize decision asked for.

## Definition of done

| Item | State | Evidence |
| --- | --- | --- |
| (a) pdfplumber primary text layer | Unchanged | `core/services/parse.py` |
| (a) Docling on the VM as layout, table and OCR layer; its boxes into the evidence resolver | Done for pages without a text layer; table pages wait for the benchmark's verdict (below) | `core/parsing/docling.py`, `core/parsing/layers.py`, compose service `docling`, `tests/core/parsing/test_layers.py`, `tests/core/services/test_ingest_parse.py` |
| (a) LlamaParse optional, off by default, per tender, document leaves the VM only then, tender record says so | Adapter and flag done; not exercised live (no key) | `core/parsing/llamaparse.py`, `tender.parser_llamaparse`, KNOWN-GAPS |
| (a) Record per page which layer was used | Done | `page.parser_layer`, `page.layer_detail` (migration 0021) |
| (b) Parser benchmark on a hard set: evidence location, table cells, time, cost | Done, below | `scripts/parser_benchmark.py`, `evals/parser_bench/hard_set.yaml`, `stage-7-artifacts/block-2-parser-benchmark.*` |
| (c) PDF, DOCX, XLSX, ZIP bundles, protected PDFs without a password; everything else refused with a reason | Done | `core/services/inputs.py`, `IngestService.upload_bundle`, `POST /documents/bundle`, `tests/core/services/test_inputs.py` (13 tests) |
| (d) Tender type classification with confidence; unsure asks, unknown reads core only, never forced | Done | `tender/services/classify.py`, prompt `classify_type/v1`, `POST /documents/{id}/classify`, `POST /tenders/{id}/type`, `tests/tender/test_classify.py` |
| (e) Windowing covers 400+ page tenders without dropping sections; coverage reported | Done, below | `scripts/window_coverage.py`, `stage-7-artifacts/block-2-window-coverage.*` |

## (a) Parsing layers

**Shape.** Every layer returns a page as text items with boxes (`core.parsing.layers`).
pdfplumber gives a box per character; Docling and LlamaParse give a box per item (line,
paragraph, table cell), so an item's characters share its box, divided evenly along the
item's width line by line. The page text is the items joined by newlines, with one box per
character aligned to it: exactly what `core.evidence.resolver` reads, so a quote on a
Docling page resolves with the same call as on any page and is highlighted on the block
that holds it (word-exact boxes are a KNOWN-GAP).

**Docling on the VM.** `docker-compose.yml` service `docling`
(`quay.io/docling-project/docling-serve:v1.38.1`, 15.2 GB on disk, profile `parsing`,
`mem_limit: 3g`). The worker, when `DOCLING_URL` is set, sends the pages pdfplumber found
no text layer on as one sub-PDF (nothing more than those pages), OCR forced, and stores
Docling's text and boxes on those pages with `parser_layer = docling`. With the service
down or unconfigured the pages stay as they were, the reason on each page's
`layer_detail` (`not configured`, `unavailable: …`, `no text found`, `blank page`), and the
parse never fails for it. Idle memory 1.3 GiB; under load see the benchmark.

**The text-layer rule, corrected.** The old rule (fewer than 50 characters) called 45 pages
of the corpus scanned. Looking at them: 26 are the NDMC package's rotated scanned
specification pages and 3 the Gaya CAD drawings, which are scans; 15 are divider pages
("NOT USED", "Part II The Supply Contract", "Guidelines.") with a few native characters
and no image, whose words the resolver refused because the page was "scanned". The rule is
now: fewer than 50 characters *and* a raster image over at least half the page. A short
native page keeps its text layer; a blank page gets neither OCR nor a text layer.

**LlamaParse.** `core/parsing/llamaparse.py` (upload, poll, JSON result, items with
`bBox` to LayerPages) behind `LLAMAPARSE_API_KEY` and the per-tender flag
`tender.parser_llamaparse` (default false, migration 0021). No key in this build: the
mapping is tested on the documented response shape only, and the first live run is the
owner's call. A document leaves the VM only for a tender whose record says so; the pages it
read say `llamaparse`.

## (b) Parser benchmark

Hard set (`evals/parser_bench/hard_set.yaml`), quotes transcribed by hand from the page
renders: 5 scanned pages (NDMC specification pages 305, 310, 320; Gaya drawing 272 and
divider 1) with 17 quotes; 4 divider pages with 6 quotes; 2 table pages of the ESS-IV RfS
(pages 3 and 43) with 13 cell and paragraph quotes. A layer locates a quote when the
resolver finds it on the page text the layer produced. Machine: e2-medium, 2 vCPU, 4 GB,
with the whole stack running.

| Class | Pages | Quotes | pdfplumber located | Docling located | Docling s/page |
| --- | --- | --- | --- | --- | --- |
| Scanned (NDMC rotated specs, Gaya drawing, a bordered divider) | 5 | 17 | 1 (6%), the native divider | **16 (94%)** | 40.1 |
| Divider pages (few native characters, no image) | 4 | 6 | 6 (100%) with the new rule; 0 under the old one | 6 (100%) | 13.1 |
| Table pages (ESS-IV RfS bid information sheet, envelope sticker) | 2 | 13 | 11 (85%) | **13 (100%)** | 19.1 |

The one Docling miss is a 15-word sentence on a rotated page (best score 53: a line of the
OCR'd paragraph came back with words run together). The two pdfplumber misses are table
cells whose text wraps inside the cell ("TWO BID SYSTEM", "BID PROCESSING FEE"): pdfplumber's
layout interleaves the wrapped lines with the neighbouring cells, so the cell's words are
not contiguous on the page text; Docling returns the cell whole. Raw rows:
`stage-7-artifacts/block-2-parser-benchmark.txt`; the first Docling answer in full
(`block-2-docling-probe.json`) shows the response shape the client maps (texts and table
cells with `BOTTOMLEFT` boxes, page size 792 x 612 for the rotated page).

**Machine under load** (`block-2-docling-memory.log`, sampled every 20 s): Docling's
container rose from 1.0 GiB idle to **1.93 GiB** at 190 to 220% CPU; system swap in use went
from 0.65 GB to **2.1 GB** while it ran, with the stack beside it. The owner's resize rule
asked for these numbers: memory pressure is real on the e2-medium, and at 40 s a scanned
page a 400-page scanned tender would take about 4.5 hours here, about 2.2 on e2-standard-4
and about 1.1 on e2-standard-8 if the time scales with cores (Docling runs pages one after
another on CPU; docling-serve can run several in parallel on more cores). No e2 size meets
the 30-minute mark for 400 scanned pages on CPU alone; the corpus's largest scanned stretch
is 26 pages (18 minutes here), and a 400-page *native* tender is parsed by pdfplumber in
under a minute with Docling touching only its table pages.

Docling wins both classes it was measured on, so per the plan it is kept for both: scanned
pages (the only layer that reads them at all) and **table pages of native documents**,
wired in this block after the benchmark as an augmentation, not a replacement: pdfplumber's
page text and character-exact boxes stay, and Docling's table cells are appended to the
page text with their cell boxes, so a wrapped cell resolves as one piece and everything
else keeps its precision. On by default when `DOCLING_URL` is set (`docling_tables`), off
without it. The cost is Docling's time on table pages only (about 19 s each here), paid once
per document at parse time. LlamaParse was not measured (no key): it stays optional and off.

Cost: pdfplumber and Docling run on the VM at no per-page price; Docling's cost is the
machine (see the resize hand-over). LlamaParse's list price is per page and is not
measured here.

## (c) Inputs

`core/services/inputs.py`: `classify` (by signature first, suffix second), `normalise`
(the PDF to store), `bundle_members` (a .zip opened member by member), `render_docx_pdf`
(paragraphs in order, tables cell by cell as `R2C3: …`, deterministic bytes). What is
stored is always a PDF; the upload's media type is kept on the document. A PDF protected
with an owner password alone is saved plain; one that needs a password is refused with
that reason. Legacy .doc and .xls, images, web pages, empty files and anything else are
refused with a reason that says what to do instead. `POST /documents/bundle` returns the
documents made from a bundle and the members left out with their reasons.

## (d) Tender type classification

One text-only model call (`classify_type/v1`) over the first eight pages. Bands, the
reviewer screen's: at or above 0.8 `set`; between 0.5 and 0.8 the best guess with state
`unsure` and a reviewer asked; below 0.5, or `unknown`, state `unknown`: the guess (or
`ipp`, the generic schema) names the schema and only its core groups would be read
(`classify.core_groups`). Never forced: `POST /tenders/{id}/type` settles it (audited,
source `reviewer`), refused once the tender has been read. Kept on the document
(`document.classification`) and on a tender created from it (`type_source`,
`type_state`, `type_confidence`); every existing tender is `manifest`/`set`. No live call
was made in this block (the test scripts the model); the first live classifications are
Block 4's eight blind tenders, where the accuracy of the classifier is reported with
them.

## (e) Window coverage

`scripts/window_coverage.py` plans every group's window for every document of every
current tender version exactly as an extraction would (`ExtractService.plan_windows`, no
model call) and reports the pages no window covers and the section-map sections no window
touches. Corpus: 29 documents, 1,624 pages; 1,181 pages (72.7%) inside some window. Full
table: `stage-7-artifacts/block-2-window-coverage.txt` and `.json`.

| Document | Role | Pages | Groups | Pages covered | Untouched substantive sections |
| --- | --- | --- | --- | --- | --- |
| seci-gaya-60mw, Technical tender document | technical | 340 | 1 | 80 (24%) | 8 (earthing, SCADA, transformers, civil works, foundations) |
| seci-gaya-60mw, Contractual tender document | contractual | 305 | 11 | 228 (75%) | 2 (labour laws, applicable laws) |
| nhpc-fdre-ii, RfS Tranche-II | rfs | 264 | 11 | 224 (85%) | 7 (draft PPA articles and schedules) |
| recpdcl-beed-tbcb, RFP | rfs | 166 | 11 | 151 (91%) | 0 |
| ntpc-hybrid-03, RfS | rfs | 138 | 11 | 119 (86%) | 0 |
| seci-ess-iv, RfS | rfs | 137 | 11 | 128 (93%) | 0 |

**What the numbers mean.** Coverage of pages is not the requirement: the engine reads
fields, and a group's window is the sections whose kind or heading its routing names plus
the pages its keywords hit, capped at 80 pages a group. The pages outside every window are
annexure formats (34 untouched sections of kind `formats_and_annexures`), draft-agreement
articles (7), EPC technical-specification chapters (8) and two legal boilerplate chapters:
sections no field is read from. The script's last check is the one that matters: of the
untouched substantive sections, how many are of a kind some group of that document's role
routes to. **Ten**, all in the Gaya EPC tender: eight technical-specification chapters of the 340-page
technical volume (earthing, SCADA, transformers, weather station and CCTV, civil
specifications, grading and roads, design loads, foundations and module mounting) and two
chapters of the contractual volume (labour laws; applicable laws and settlement of
disputes). All eight technical ones are of kind `technical_requirements`, which the sector
technology group routes to; that group's 80-page window took the keyword-ranked pages
(module, ALMM, degradation, CUF, land) and left these, which is right for the fields the
group reads and is the honest statement of what the window drops. Every other document of
the corpus: zero. No section of kind `dates_and_schedule`, `eligibility`,
`financial_security`, `penalties_and_remedies` or `bidding_process` is outside its window
anywhere.

**The 400-page question.** The corpus's largest document is 373 pages (NDMC package, a
`technical` document of a superseded version, outside the current set) and the largest in
the current set 340. A 400-page RfS is handled the same way: windows are per group and
capped, so size adds sections, not risk, as long as the section map labels them; the
cap is the one lever. The Gaya technical document shows the lever's other side: one
group routes to a `technical` document and reads 80 of 340 pages, the keyword-ranked ones;
the technical-specification chapters it leaves are not field sources (the gold eval on this
tender stands at 97.7%), but a tender whose technical volume *does* carry fields (a BESS
specification with the cycle and degradation terms) would want a larger cap for that
role. Recorded in KNOWN-GAPS with the setting to turn (`extract_max_pages_per_group`,
or `max_pages` on the group).

## Tests

`make check` green (`stage-7-artifacts/check-run5.log`). Four earlier runs today went red
on a pytest timeout (2,700 s) and only the fifth showed why: the Block 0 deploy's `up -d
… tests` had restarted the continuous test watcher (`tender-engine-tests-1`), stopped on
the owner's request weeks ago, so every check since 15:41 UTC shared the 2 vCPUs with a
second full suite (`check-run2.log` to `check-run4.log`). The watcher is stopped again and
the deploy target no longer starts it (`Makefile`); the modules this block added or
touched were run in the tests container first: `tests/core/services/test_inputs.py` (13),
`tests/core/parsing/test_layers.py` (4), `tests/core/services/test_ingest_parse.py` (+6,
including a scanned page through a fake Docling, a service that is down, the text-layer
rule, Docling's cells on a ruled table), `tests/tender/test_classify.py` (4),
`tests/api/test_documents.py` and `tests/api/test_tenders.py` (updated for the new media
type, the refusal text and the type provenance). The tests image was rebuilt for
python-docx. No live Docling call runs in the suite: the benchmark is the live test.

## Deployment

Not deployed by the build agent (the session's permission classifier refuses `make
deploy`, as in Block 0). The live stack runs the mounted source with the API reloading, so
the code is live for the API already; the worker process still needs the restart and the
app image needs rebuilding for httpx (now a runtime dependency) before the worker can
reach Docling. Migration 0021 was applied by the owner at 17:0x UTC; **migration 0022**
(`document.classification`) is new and waits for the owner's `! make -C /work/tender_engine
migrate`; until then the document routes read the column through a savepoint and answer
`classification: null`. The `docling` service is stopped after the benchmark and stays off
on the e2-medium (profile `parsing`); `DOCLING_URL=http://docling:5001` and
`COMPOSE_PROFILES=parsing` go into `.env` after the resize.

Owner's steps, in order: `! make -C /work/tender_engine migrate`, then
`! make -C /work/tender_engine deploy`.

## Independent review (operating rule 15)

Pending with Blocks 0 and 1: the OpenAI key in `.env` is invalid. The three reviews run
over `stage-7-start..HEAD` once the owner replaces it.

## Costs

No model call in this block.
