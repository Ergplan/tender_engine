# Stage 7 prompt: completion, Block 0 (safety and capacity)

The owner's completion plan of 2026-10-24 is the prompt for Stage 7 and the stages after
it: `docs/COMPLETION-PLAN.md`, verbatim. Each block is a stage of its own under CLAUDE.md's
rules: a tag at its start, tests with the code, the independent review (rule 15) before
its report, `make deploy`, the report. Tag `stage-7-start` is `5e84ca6` (the
Stage 6 close); Block 0 runs under it. **Stopping (owner's update, 2026-10-24 afternoon):**
after Block 0 the blocks run on without a stop between them; the build stops only for the
owner's review decisions, reviewer names, spend over USD 50 in one go, the Block 2 resize
(Cloud Shell commands for e2-standard-4 with the storage-rw scope change), or a decision
that cannot be undone. A short report closes each block. "Not now" items of the plan (TenderOS, schema v5,
award reviews, public library growth) are not built.

An earlier Stage 7 scope written the same morning (the financial-model page, a results
page, award results into the public library, schema v5) was withdrawn when the plan
arrived; the code written for it was reverted before any commit. What stays from that
morning is what Block 0 asks for: the worker's model registry and its test, the backup,
the review round for `seci-cni-1-700mw`.

## Block 0, read as a stage

- (a) The resize is the owner's step: the commands and the cost go in the report; nothing
  runs before approval. Decided 2026-10-24 afternoon: not now; e2-standard-4 at the start of
  Block 2.
- (b) `infra/backup.sh`: nightly `pg_dump` and a tar of `/data` on the VM (14 days local),
  copied to a versioned GCS bucket (30-day lifecycle) when `BACKUP_BUCKET` is set and the
  VM's service account may write; a Drive bundle without `.env`. One run now, a restore
  into a scratch database, row counts against live in the report. The bucket and the
  scopes are GCP mutations: the owner's commands, in the report.
- (c) 4 GB swap on the VM; `restart: always` on the app services (the test services stay
  `no`); the cause of the 2026-10-20 start from the journal, and the GCP operations
  command for the owner.
- (d) Every process that opens a session registers every table; a test that fails when any
  entry point's metadata cannot resolve `llm_call_log`'s foreign keys (the exact failure
  of 2026-10-20); the Stage 6 report corrected; the UTC window of the unlogged calls.

## Block 1, read as a stage (2026-10-24)

- (a) The links for the nine open fields were issued in Block 0 (`/work/stage7-links.txt`);
  the decisions are the owner's and the build does not wait for them.
- (b) `make eval` on the eleven gold records with the two cuts the plan names and the runner
  lacked: critical fields (`is_critical`) and confidence calibration (`confidence_band`),
  with tests. Report the baseline as it is; tune nothing (plan 4c decides what to fix, after
  the blind test).

## Block 2, read as a stage (2026-10-24, on the e2-medium: the resize hand-over is written,
`docs/reports/STAGE-7-BLOCK-2-RESIZE.md`, and the owner said to keep building)

- (a) Layers: pdfplumber primary; Docling on the VM for the pages without a text layer
  (compose service `docling`, profile `parsing`), its item boxes turned into character
  boxes so quotes resolve on scanned pages; LlamaParse an adapter behind a per-tender
  flag, off; every page records its layer (migration 0021).
- (b) `scripts/parser_benchmark.py` on `evals/parser_bench/hard_set.yaml`: the scanned
  pages of the corpus (quotes transcribed from the renders), the divider pages the old
  rule mislabelled, and table pages of a gold RfS: located rate, seconds per page, per
  layer. Report before wiring any default; Docling stays off table pages unless it wins.
- (c) Inputs: `core/services/inputs.py`; .docx and .zip accepted, protected PDFs without a
  user password saved plain, everything else refused with a reason; `POST
  /documents/bundle`.
- (d) `classify_type`: one text-only call, calibrated bands (0.8 / 0.5), `unsure` asks a
  reviewer, `unknown` reads the core groups only; `POST /tenders/{id}/type` settles it,
  audited; never forced.
- (e) `scripts/window_coverage.py`: pages and sections no group's window reaches, for
  every document of the corpus, with the two 300-page-plus documents called out.

## Block 3, read as a stage (2026-10-24/25)

What already stands from Stages 3 to 5: change kinds `added`, `changed`, `restated`,
`removed` with the `withdrawn` reading (`tender/services/amendments.py`); the keyword
routing with the section-map diff fallback (`amendment_map.py`, every disagreement in the
audit log); a review round per later version scoped to the changed fields, approvals
carrying forward (`rounds.py`, `review._current`); impact cues (`changes_decided`,
`impacts`); the weekly report-only freshness check (`freshness.py`). Block 3 adds:

- (a) `tender/services/amendment_link.py`: the base tender of an amending document from
  its own first pages (tender number, reference, issuer, title words), scored with the
  library matcher's rules; linked only above the threshold with a clear margin, else the
  candidates are returned and a person chooses. `POST /documents/{id}/link-amendment`.
- (b) Out-of-order arrival: versions keep their arrival number (candidates and facts name
  it) and are projected in **date order** (`issued_on`, then number) everywhere a version
  list is read; the current version is the latest dated. The Ramagiri case (Amendment-01
  arriving after Amendment-02) is a test, with no reseed.
- (c) Each change carries a `change_class`: `value_changed`, `date_moved`, `clause_withdrawn`,
  `annexure_replaced`, `requirement_added`, `restated`, from the kind, the value type and
  the field; `scripts/amendment_report.py` lists every class found on the corpus's real
  amendments, and the unit tests build each class on a synthetic tender.
- (d) Unchanged; the report shows the round opened for a version and the cues on it.
- (e) Unchanged; the report shows the last run and the schedule.

