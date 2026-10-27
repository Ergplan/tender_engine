# Stage 7, Block 4 report: the blind set as an unreviewed check (2026-10-24 to 2026-10-27)

Block 4 of the owner's completion plan asked for eight new tenders from official sites, read
under a frozen commit, reviewed by named reviewers and scored with the Block 1 metrics. On
2026-10-27 the owner turned it into an unreviewed check (DECISIONS 2026-10-27, item 4): four
of the eight tenders (recpdcl-bikaner-v-part-a, msedcl-bess-mt-1000mw, tgredco-rtc-2000mw,
sjvn-wind-4-600mw) are extracted under the frozen commit and reported on what can be measured
without a reviewer: evidence-location rate, confidence distribution, rule-validation pass
rate, type classification, amendment linking and change classes. **No accuracy claim is made
from them**; the only accuracy figure of this build is the in-sample one of Block 1.

## (a) The set

| Slug | Type | Agency | Issued | Documents (pages) | Later versions | Scanned pages | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| recpdcl-bikaner-v-part-a | transmission | RECPDCL | 2026-08-14 | 10 (528) | 5 (2 notices, 3 amendments) | 25 (Amendment-I 20, Amendment-III, NIT, Appendix-A 3) | recpdcl.in |
| recpdcl-sharavathi-psp | transmission | RECPDCL | 2026-03-20 | 8 (633) | 1 amendment | 5 (Amendment-I, Appendix C 3, TSA 1) | recpdcl.in |
| msedcl-bess-mt-1000mw | bess | MSEDCL (state) | 2026-09-24 | 5 (215) | 3 (corrigendum, 2 addenda) | 0 | mahadiscom.in |
| msedcl-bess-2000mw-4000mwh | bess | MSEDCL (state) | 2026-06-30 | 3 (140) | 2 addenda | 0 | mahadiscom.in |
| tgredco-solar-3000mw-ess | solar | TGREDCO (state) | 2026-10-13 | 3 (226) | 0 | 0 | tgredco.telangana.gov.in |
| tgredco-wind-800mw | wind | TGREDCO (state) | 2026-10-13 | 3 (207) | 0 | 0 | tgredco.telangana.gov.in |
| tgredco-rtc-2000mw | re_rtc | TGREDCO (state) | 2026-10-13 | 3 (233) | 0 | 0 | tgredco.telangana.gov.in |
| sjvn-wind-4-600mw | wind | SJVN | 2025-09-05 | 12 (326) | 11 corrigenda | 14 (in the RfS) | sjvn.nic.in |

The plan's mix: transmission covered (two TBCB schemes); at least two state tenders (five);
at least two with scanned pages (four); at least two with amendments (five). **IPP is not
covered.** The only official IPP-class document found is SECI's short-term 80 MW power
procurement RfP of 01.04.2026, on seci.co.in, which refused connections from the VM and
from the fetch proxy all evening (`ECONNREFUSED`, the same host that served the corpus on
2026-10-20); NHPC's RfS documents are behind a login. No news-site copy was used. If the
owner saves that RfP into `/work/tenders/ipp/seci-short-term-80mw/` with a manifest, it
joins the set under the same freeze.

Each manifest records the source URL and the retrieval date of every file; the notes name
what was not available (MSEDCL's revised RfS v2 of 31.07.2026 and addenda 1 to 6 and 8 of
the 2000 MW tender were not linked on the site's listing).

## (b) The freeze and the extraction

**Freeze:** tag `stage-7-block-4-freeze` = commit `cbd191c` (the Block 3 commit, pushed),
before any model call on the set. The reading of the four tenders on 2026-10-27 ran on that
code and those prompts: `git diff cbd191c -- core/services core/llm core/parsing
core/validation core/evidence tender/domain_packs tender/services/{amendment_map,amendments,
worker_jobs,classify,rounds,derive,summary}.py` is empty, and the released schema v4 and the
section prompts are frozen files. The two exceptions are on record: the worker's `runner.py`
and `main.py` carry the Block 5 indexing hook (no bearing on a reading), and the amendment
mapper's routing was changed on 2026-10-27 after the set itself found a defect (below).

**Docling was not wired into the live stack** when the set was first parsed (2026-10-24,
21:25 to 22:40 UTC): no `DOCLING_URL` in the worker's environment, the `docling` service
down, so the 44 scanned pages had no text and no table page was augmented. The set was parsed
again under the production condition (`DOCLING_URL=http://docling:5001`, the service up, the
worker recreated; 47 `parse` jobs, `created_by = stage7-block4-reparse`), finishing 2026-10-25
03:58 UTC (94 section-map calls, USD 18.10). In the four tenders of the check Docling read 38
scanned pages as the whole layer (`parser_layer = docling`: Bikaner Amendment-I 20, the SJVN
combined RfS 14, Bikaner Appendix-A 3, Amendment-III 1) and augmented the table cells of 145
native pages (`pdfplumber+docling`).

**Ingestion** (`scripts.ingest_tenders ingest --root /work/tenders --only …`, 2026-10-24):
47 documents, 2,508 pages, 30 versions over the eight tenders; the four of the check hold 30
documents, 1,302 pages and 23 versions.

**Extraction** (2026-10-27, batch API, `scripts.ingest_tenders extract --only …`): batch 1
(tgredco-rtc-2000mw, msedcl-bess-mt-1000mw, sjvn-wind-4-600mw) queued 00:20 UTC, every run
validated by 00:55 UTC, USD 39.5 (the owner's rule: under USD 50 in one go); batch 2
(recpdcl-bikaner-v-part-a, 4 runs on v1 and the five amending documents) queued 01:05 UTC.
**At 00:56 UTC the Anthropic account's credit balance ran out** ("Your credit balance is too
low to access the Anthropic API", nine calls refused, batch requests errored): Bikaner's v3
run failed and its v1, v4, v5 and v6 runs wait on batches that will not complete. After the
owner's refill: `docker compose exec -T api python -m scripts.ingest_tenders resume --only
recpdcl-bikaner-v-part-a`, then `python -m scripts.blind_check --only …` again; the tables
below are the three complete tenders' and Bikaner's partial ones, marked.

**A pipeline defect the set found, fixed under the freeze.** The first amending document of
MSEDCL's medium-term tender had its change routed by the amendment map to the pack's `derived`
section (a section written from decisions, never read from pages), and the run was refused:
"schema tender.bess has no group(s) ['derived'] that read from pages". The version would never
have been read. `amendment_map._readable` now keeps derived and imported sections out of the
prompt's section list and out of the routing (DECISIONS 2026-10-27); the worker was restarted
and the job retried. This changes what is routed, not what is read or how.

**Classification** was run on the main document of all eight blind tenders (`classify_type`,
eight calls, USD 0.73), writing on the document only; the tenders keep their manifest type.

## (c) The check (`scripts/blind_check.py`, `stage-7-artifacts/block-4-check.{md,json}`)

Candidates only, from the live reading of the latest valued version of each field, the way
the extraction summary picks them. "Located" means the resolver found the quote on its page.

### Readings

| Tender | Type (manifest) | Complete | Versions | Docs | Pages | Fields | With a value | Located | Evidence-location rate | Answer rate | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | bess | yes | 4 | 5 | 215 | 112 | 81 | 81 | 100.0% | 72.3% | 13.02 |
| tgredco-rtc-2000mw | re_rtc | yes | 1 | 3 | 233 | 112 | 78 | 78 | 100.0% | 69.6% | 10.50 |
| sjvn-wind-4-600mw | wind | yes | 12 | 12 | 326 | 103 | 79 | 79 | 100.0% | 76.7% | 12.38 |
| recpdcl-bikaner-v-part-a | transmission | **no** (6 of 9 runs unfinished, credit) | 6 | 10 | 528 | 108 | 56 | 56 | 100.0% | 51.9% | 10.76 |
| **three complete** | | | 17 | 20 | 774 | 327 | 238 | 238 | **100.0%** | 72.8% | 35.90 |

The evidence-location rate on the unseen tenders is the one figure of this block the
reliability report may quote (the owner's item 6): **100% on the three complete tenders (238
of 238 values located)**, to be restated with Bikaner once its runs finish. The answer rate
(values / fields) is reported, not targeted: a field the documents do not state returning
nothing is a correct answer, and a transmission RfP states fewer of the catalogue's fields.

### Confidence distribution

| Tender | High (≥ 0.8) | Medium (≥ 0.5) | Low | Unlocated at high confidence |
| --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | 48 (100% located) | 28 (100% located) | 5 (100% located) | none |
| tgredco-rtc-2000mw | 68 (100% located) | 9 (100% located) | 1 (100% located) | none |
| sjvn-wind-4-600mw | 69 (100% located) | 9 (100% located) | 1 (100% located) | none |
| recpdcl-bikaner-v-part-a (partial) | 36 (100% located) | 18 (100% located) | 2 (100% located) | none |

What this says and does not say: every reading at high confidence has its quote on the page.
Whether the value is right is not known; Block 1 found that on the gold set 10 of 24 misses sat
in the high band (five of them `procurement_mode`), so a located quote at high confidence is
not accuracy, and these counts are the shape of the reading, nothing more.

### Rule validation

| Tender | Rules run | Passed | Pass rate | Failed (error) | Failed (warning) | Fields in needs_review | Failing rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | 260 | 258 | 99.2% | 2 | 0 | 2 | range ×1, type ×1 |
| tgredco-rtc-2000mw | 181 | 181 | 100.0% | 0 | 0 | 0 | none |
| sjvn-wind-4-600mw | 214 | 213 | 99.5% | 1 | 0 | 1 | evidence_not_located ×1 |
| recpdcl-bikaner-v-part-a (partial) | 141 | 136 | 96.5% | 3 | 2 | 3 | evidence_not_located ×2, type ×1; date_order (warning) ×2 |

The deterministic rules (type, range, cross-field order, evidence located, the structured
quote rule) pass on 99.5% of the readings of the three complete tenders (652 of 655); the four
failures mark their fields `needs_review`, as the invariant wants, and hide nothing.

### Type classification (one model call over the first eight pages, against the manifest)

| Tender | Manifest | Classifier | Confidence | Band | Outcome |
| --- | --- | --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | bess | bess | 0.98 | set | agree |
| tgredco-rtc-2000mw | re_rtc | fdre | 0.70 | unsure | differ, unsure: the reviewer would be asked |
| sjvn-wind-4-600mw | wind | wind | 0.98 | set | agree |
| recpdcl-bikaner-v-part-a | transmission | transmission | 0.98 | set | agree |

Over all eight blind documents: six `set` and in agreement with the manifest (both MSEDCL,
both RECPDCL, SJVN, TGREDCO wind), two `unsure` at 0.70 (TGREDCO solar+ESS read as `solar`, in
agreement; TGREDCO RTC read as `fdre` where the manifest says `re_rtc`, the two schemas being
the FDRE and RE-RTC readings of the same kind of tender). No forced type; the unsure ones are
exactly the ones a reviewer should settle, which is what the bands were for.

### Amendment linking (each later document from its own first pages, against the tender it was ingested under)

| Outcome | Count | Where |
| --- | --- | --- |
| linked to its own tender | 15 | MSEDCL 3 of 3 (title ×2, reference ×1); SJVN 11 of 11 (reference ×10 at 0.98, title ×1 at 0.95); Bikaner Amendment-I (title, 0.87) |
| ask (below the threshold or margin) | 4 | Bikaner: the two pre-bid notices (0.83), Amendment-II (0.65), Amendment-III (0.78) |
| linked elsewhere (wrong) | 0 | |

No document was linked to a wrong tender. The four `ask` cases are RECPDCL's short notices,
which print no tender reference the engine recognises (`references_found` 0 or 1) and share
their title words with the sister Sharavathi scheme; the Block 3 rule asks rather than
guesses, with candidates, which is the designed outcome.

### Change classes (the amendments view, per later version)

| Tender | Later versions | Changes | By class |
| --- | --- | --- | --- |
| msedcl-bess-mt-1000mw | 3 | 96 | value_changed 44, restated 38, requirement_added 6, date_moved 4, annexure_replaced 2, clause_withdrawn 2 |
| sjvn-wind-4-600mw | 11 | 114 | restated 60, value_changed 27, date_moved 25, annexure_replaced 2 |
| recpdcl-bikaner-v-part-a (partial: v2 read, v3 to v6 not yet) | 5 | 3 | restated 1, requirement_added 1, clause_withdrawn 1 |

Every registered class occurs on the set; the eleven SJVN corrigenda are date extensions and
read as such (25 `date_moved` over 11 versions, the rest restatements and the values the
extensions move). Per-version rows are in `block-4-check.md`.

## Reviewer links

None: the owner's decision of 2026-10-27 (no more human reviews). The review links can be
minted later (`scripts.review_token create`) and the plan's scoring run then.

## (d) Targets

| Target | Measured | Result |
| --- | --- | --- |
| Evidence location ≥ 95% | Yes | 100% on the three complete tenders (238 of 238); Bikaner pending |
| Machine-reading accuracy ≥ 95% overall, ≥ 99% on critical fields | No: needs reviewed values | Not claimed |
| Every wrong reading below the high-confidence band | No: needs reviewed values | Not claimed; the in-sample Block 1 figure (10 of 24 misses in the high band) stands as the only evidence |

## Costs

Block 4 model spend to 01:40 UTC 2026-10-27: USD 18.10 (the re-parse's section maps, 25 Oct),
USD 47.30 extraction, USD 4.65 amendment maps, USD 0.90 summaries, USD 0.73 classification:
about USD 71.7, in two batches each under USD 50. Running total of the ledger (`llm_call_log`): USD 502.76.
