# Stage 7, Block 3 report: complete amendment pipeline (2026-10-24/25)

Block 3 of the owner's completion plan. Most of the pipeline stood from Stages 3 to 5; this
block adds the auto-link, date-ordered projection, the registered change classes, and
proves each kind on the corpus's real amendments.

## Definition of done

| Item | State | Evidence |
| --- | --- | --- |
| (a) Auto-link an amendment, corrigendum or clarification to its base tender by number, reference and issuer; below a threshold ask | Done | `tender/services/amendment_link.py`, `POST /documents/{id}/link-amendment`, `tests/tender/test_amendment_link.py` (5) |
| (b) Out-of-order arrival: insert at its date position and re-project, no reseed; the Ramagiri case as a test | Done | `TenderService.versions` (date order), `ordered_versions`, `tests/tender/test_version_order.py` |
| (c) Every change kind registers (value changed, clause withdrawn, annexure or format replaced, date moved, new requirement); section-map diff as the fallback; each kind tested on a real amendment | Done | `amendments.change_class`, `AmendmentVersion.by_class`, `tests/tender/test_change_class.py`; `scripts/amendment_report.py` over the corpus (below); the fallback is `amendment_map.py` since Stage 3 |
| (d) Every new version opens a review round scoped to the changed fields, approvals carry forward with provenance; impact cues | Stood since Stage 4/5; shown below | `rounds.RoundOpener`, `review._current`, `AmendmentChange.changes_decided` / `impacts` |
| (e) Weekly report-only freshness check; never auto-ingests | Stood since 2026-10-13; shown below | `tender/services/freshness.py`, `freshness_interval_days = 7` |

## (a) Auto-link

Two steps, from the document's first three pages. A reference the document prints that
equals exactly one tender's `external_ref` (case, spaces and an `/Amendment-N` suffix set
aside) links it at confidence 0.98; the corpus's own amendments all print one ("RfS No.
SECI/C&P/IPP/13/0002/26-27 dated 15.07.2026", "Ref No. …/Amendment-02", "Tender Reference
No.: SECI/C&P/IPP/15/0009/26-27", CPPP ids like `2026_SECI_850226_1`). Otherwise the share
of each tender's own title words that the document's opening words carry decides, capped
at 0.5 when a number of the title is missing (FDRE-IX is not FDRE-X) or the issuer named
is another, and links only at 0.85 or above with a 0.10 margin over the next tender.
Anything less is `ask` with up to three candidates and what tells them apart; a reference
two tenders share is `ask` too. Nothing is written: the caller adds the version to the
tender a person confirms. Block 6's `submit_amendment` uses it.

## (b) Out-of-order arrival

A version keeps its arrival number for ever (candidates, facts, approvals and rounds name
it), and `TenderService.versions` now returns the versions in **date order**: the original
first, the later ones by `issued_on`, an undated one after the dated ones, ties by number.
Every projection reads that list (the review, the amendments view, the current view, the
changelog, the summary), so an amendment that arrives late slots in where its date puts it
and the readings re-project from the same list with no reseed; the current version is the
latest dated, not the latest arrived. The Ramagiri case is the test: the original, then
Amendment-02 (3 Aug), then Amendment-01 (17 Jul) arriving third; the order becomes 1, 3, 2,
Amendment-02 stays current, Amendment-03 (8 Oct) then follows. The live corpus shows the
rule at work on `seci-cni-1-700mw`: the dated amendment of 12 Oct (v3) now projects after
the undated pre-bid clarification (v2) was listed first before; with the rule, the
undated clarification is last.

## (c) Change classes on the corpus's real amendments

`scripts/amendment_report.py` runs the amendments projection over every tender and counts
each version's changes by class (`stage-7-artifacts/block-3-amendment-report.txt`):

| Class | Changes | Example (real amendment) |
| --- | --- | --- |
| value_changed | 174 | seci-fdre-rtc-v v5: 17 values |
| restated | 155 | the amendment repeats the clause unchanged |
| requirement_added | 34 | seci-cfd-i v2 (the revised RfS): 4 |
| annexure_replaced | 24 | seci-cni-1-700mw v3: Annexure-G/H formats |
| date_moved | 4 | seci-cfd-i v2 and v4, seci-fdre-rtc-v v2 and v4 |
| clause_withdrawn | 1 | seci-cfd-i v5: clause 40.3 (the `withdrawn` reading) |

Sixteen later versions over six tenders; every registered class occurs at least once on a
real amendment, and the unit test builds each from its inputs. The keyword routing with
the section-map diff fallback is unchanged (`amendment_map.py`; every disagreement in the
audit log, `python -m scripts.ingest_tenders amendment-routing`).

## (d) Rounds and impact cues

Unchanged. `RoundOpener.after_validation` opens a round from a version a completed review
did not see, scoped to the fields that version touched plus the derived tables their rules
read and the summary; `_current` carries an earlier decision forward until a later
reading is decided; each change carries `changes_decided` (replaces a decided value),
`required`, `impacts` (derived tables) and the delta (`before` against the entry). On the
corpus today: the cfd-i v5 corrigendum has 14 changes that replace decided values (its
round 1 link is live, issued by hand in Block 0, not by version); `seci-cni-1-700mw` v3
has the open round opened by `scripts.review_token round` in Block 0 (the version was
read before rounds existed, so no automatic round had been opened for it).

## (e) Freshness

Unchanged: `source_freshness` ran on 2026-10-13 and 2026-10-20 (both `done`) and the next
is queued; it reports and never ingests.

## Tests

`make check` green (`stage-7-artifacts/check-run8.log`; run 6 was red on the OpenAPI client alone and run 7 on the web fixtures lacking the new `change_class` and `by_class` fields, both fixed). New: `tests/tender/test_amendment_link.py` (5), `tests/tender/test_version_order.py` (2), `tests/tender/test_change_class.py` (8); `tests/tender/test_rounds.py` and the tender API tests pass with the date order.

## Deployment

Not deployed by the build agent (classifier). The API reloads the mounted source; the
worker restarts at the owner's `! make -C /work/tender_engine deploy`, together with
migration 0022 from Block 2.

## Independent review (operating rule 15)

Pending with Blocks 0 to 2 on the OpenAI key.

## Costs

No model call in this block.
