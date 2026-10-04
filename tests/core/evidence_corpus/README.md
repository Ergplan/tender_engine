# Evidence corpus

Quotes with the page they should, or should not, be found on. `core.evidence.corpus` loads
it; `python -m scripts.evidence_corpus run --failures` (or `make evidence-corpus`) prints
the resolver's pass rate, which every stage report gives separately from extraction results.

- `pages/<document sha256 prefix>-p<page>.json.gz`: text and character boxes of real pages.
- `real_cases.json`: from the Stage 2 extraction of the 13-tender set, added by
  `python -m scripts.evidence_corpus export`: every quote that was not located at
  extraction (`real_unlocated_at_extraction`), every quote located with a score under 100
  (`real_near_miss`) and every quote the exact matcher does not find (`real_not_exact`).
  All of them were checked to be on their page, so each expects `located: true`.
- `synthetic_cases.json`: deliberate cases on small made-up pages: hyphenation across a
  line break, ligatures, non-breaking and thin spaces, smart quotes and dashes,
  reformatted numbers, two-column tables, table cells that wrap, a quote across a page
  boundary, a quote that occurs twice, and quotes that are not on the page.
- `known_failures.json`: cases the resolver does not pass today. The test fails when a
  case outside this list fails, and when a case inside it starts passing (remove it then).

A case passes when the resolver's answer matches `expect.located` and, for a located
quote, every number of the quote is inside the located text and the case's own
`contains`, `not_contains`, `method`, `line` and `page_no` hold.

Known failures:

- `real-0080`: a watermark is printed through the heading, so the text layer reads
  "SOLAR ENERGY CORPORA SCT-ResItricOted#N OF INDIA LIMITED".
- `real-0142`: a wrapped table cell read out of order ("Start of e-" ... "Reverse Auction"
  after the neighbouring cell) in a quote without a number; words alone are never matched
  out of order, because that can reverse a sentence.
