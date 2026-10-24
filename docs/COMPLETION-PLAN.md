# Tender Intelligence — completion plan (the owner's, 2026-10-24, verbatim)

Received 2026-10-24 while Stage 7 was being scoped; it replaces that scope. Each block is
run under CLAUDE.md's rules (tests with the code, independent review before each report,
deploy, stop). Block 0 first; the owner approves the resize before it runs.

```text
TENDER INTELLIGENCE — COMPLETION PLAN

Scope: tender_engine only. Do not touch TenderOS. The goal is that the engine reads any Indian power tender with measured, near-accurate results; answers any question about a full tender; and serves the full tender and amendment pipeline to any jouleWise product, Claude Code, Claude.ai and OpenAI, through the REST API, the MCP connector and an OpenAPI spec.

Unchanged rules: nothing becomes a canonical fact without human approval, and every quote must resolve on its page through the existing evidence resolver. Only Claude or OpenAI models. No Google OIDC and no new login work; leave the existing auth as it is. All sources are official sites only, never news publications.

Record each change of direction below as a new entry in DECISIONS.md with its reason, reversing the earlier entries where they conflict (LlamaParse rejected; no RAG).

Stop and report after each block. Run the independent review before each report as per operating rule 15.

────────────────────────────────
BLOCK 0 — SAFETY AND CAPACITY (first)
a) Resize: give me the exact gcloud commands to snapshot the disk and then resize this VM to e2-standard-8 (8 vCPU, 32 GB), with the expected monthly cost. Wait for my approval before running them.
b) Backups: nightly pg_dump + /data to the VM, to a versioned GCS bucket with 30-day retention, and a .env-stripped copy I can sync to Drive. Run one now, do a test restore into a scratch DB, and report row counts against live. Use the VM service account for GCS; if it lacks storage scope, give me the exact command to grant it.
c) Stability: add 4 GB swap, set compose restart=always, and find the cause of the 20 Oct reboot (journal and GCP operations).
d) Fix the worker model-call logging defect, with a test that fails if any process can call a model without a committed log row. Correct the Stage 6 report's "no model spend" line, and give me the UTC window so I can check the real spend in the Anthropic console.

────────────────────────────────
BLOCK 1 — BASELINE ON THE GOLD SET
a) Give me review links for the 9 open fields: seci-cfd-i v5 (4 fields, including the clause 40.3 withdrawal), seci-cni-1-700mw v3 (4 fields, opened as a review round, not a fresh link) and seci-wind-tranche-xx (1 field).
b) Once I have decided them, run the eval on all 11 gold tenders: per-field evidence-location rate and accuracy, per tender type, critical fields separately (dates, capacity, tariff/ceiling, EMD, PBG, eligibility thresholds, penalties), and confidence calibration (accuracy within each confidence band).

────────────────────────────────
BLOCK 2 — ANY INPUT WORKS
a) Parsing layers:
   - pdfplumber stays the primary text layer for native pages.
   - Docling, running on the VM, is the layout, table and OCR layer: it runs on scanned pages and on pages with tables. Its word boxes go into the evidence resolver, so quotes resolve on scanned pages and in table cells.
   - LlamaParse is an optional parser: off by default, enabled per tender by config. A document only leaves the VM when LlamaParse is enabled for that tender, and the tender record says so. Its output is used only where quotes resolve against page boxes.
   - Record per page which layer was used.
b) Parser benchmark on a hard set (the scanned corrigenda, the tables in the 11 gold tenders and the Block 4 tenders): evidence-location rate, table-cell accuracy, time and cost for pdfplumber, Docling and LlamaParse. Report before wiring any default, then keep whichever wins per document class.
c) Inputs: PDF, DOCX, XLSX (done), ZIP bundles of a tender pack, and protected PDFs that need no password. Anything else is rejected with a clear reason.
d) Tender type classification, with confidence. When the type is unsure, ask the reviewer; when it is unknown, read with the core pack only and say so. Never force a type.
e) Large documents: confirm that windowing covers 400+ page tenders without dropping sections, and report the coverage.

────────────────────────────────
BLOCK 3 — COMPLETE AMENDMENT PIPELINE
a) Auto-link an amendment, corrigendum or clarification to its base tender by tender number, reference and issuer. Below a confidence threshold, ask instead of guessing.
b) Out-of-order arrival: insert the version at its date position and re-project, with no reseed. Make the Ramagiri case a test.
c) Every change kind registers: value changed, clause withdrawn, annexure or format replaced, date moved, new requirement added. Use a section-map diff of the amending document against the base as the fallback when keyword routing misses. Test each kind on a real amendment from the corpus.
d) Every new version opens a review round scoped to the changed fields, with approvals carrying forward with provenance. Impact cues on each change: delta, replaces a decided value, required field, derived sections affected.
e) A weekly, report-only freshness check of the source sites for new amendments to held tenders. It never auto-ingests.

────────────────────────────────
BLOCK 4 — BLIND TEST (the honest "any tender" number)
a) Fetch 8 new tenders from official sites only (seci.co.in, ntpc.co.in, nhpcindia.com, sjvn.nic.in, state discom/utility sites). They must cover transmission and IPP, and include at least 2 state tenders, 2 with scanned pages and 2 with amendments.
b) Freeze prompts and code at a tagged commit before reading them. Extract them and give me review links for the reviewers I name.
c) Score against the reviews with the Block 1 metrics. Only after scoring, fix systematic errors and report before and after.
d) Targets: evidence location ≥95%, machine-reading accuracy ≥95% overall and ≥99% on critical fields, and every wrong reading below the high-confidence band. Report misses honestly; do not tune to the test.

────────────────────────────────
BLOCK 5 — FULL-TENDER QUERY
a) A Haystack pipeline with hybrid retrieval (BM25 + embeddings) in the existing Postgres via pgvector, with no new database. Embeddings use OpenAI, with a config switch for a local model. Chunks carry page, clause number and document version.
b) ask_tender(tender_id, question):
   - When the question maps to a field, answer from approved facts first.
   - Otherwise retrieve, and the model answers from the retrieved pages only.
   - Every claim cites page and quote, resolved by the resolver; an unresolved claim is shown as unresolved.
   - Version-aware: answer against the current version, and note when an amendment changed the answer.
   - Mark every answer as machine or approved. Never write answers as facts.
c) Cross-tender questions (e.g. "which tenders allow thermal with RECs") are answered by structured search over canonical facts, not retrieval.
d) An eval set of 50 questions over the gold tenders, with reviewer-written answers. Report answer accuracy and citation-resolution rate.

────────────────────────────────
BLOCK 6 — SERVE IT TO EVERY CALLER
a) REST v1 with API keys:
   - submit a tender (file or official URL) and submit an amendment
   - get extraction status
   - GET snapshot: every field with value, unit, page, quote, version, state (value / withdrawn / not_stated), approved or machine, and confidence
   - GET changes with impacts
   - ask_tender
   - mint a review link for a named reviewer
   Publish the snapshot JSON Schema as contract v1, additive-only, with a contract test.
b) Webhooks: extraction done, review complete, new version or amendment detected. Signed and retried.
c) MCP over streamable HTTP with the existing OAuth, for Claude.ai, Claude Code (claude mcp add) and OpenAI (ChatGPT connectors and the Responses API remote MCP tool). Tools: search_tenders, get_tender, get_field, ask_tender, submit_tender, submit_amendment, get_status, get_changes, get_review_link, reliability_report. Keep the existing read tools working. Write tools need write scope.
d) An OpenAPI 3.1 spec for REST v1, usable directly as OpenAI function definitions, plus a thin Python client for jouleWise products.
e) docs/CONNECTOR.md: how to connect from Claude Code, Claude.ai, ChatGPT, the OpenAI Responses API and a Python product. Test each end to end against the live engine and record it in the report.

────────────────────────────────
BLOCK 7 — DONE
a) The definition-of-done checklist from the master prompt plus Blocks 0–6, each item marked done or not done, with evidence (test name, commit, metric).
b) The reliability report (Block 1 + Block 4 + query eval numbers), published through reliability_report. No accuracy claim anywhere that this report does not support.
c) Run the independent review on the whole diff until it finds no new code defect. Update ARCHITECTURE.md, FIELD-TRACE.md and HANDOVER.md.

Not now: TenderOS, schema v5, award reviews, public library growth.
```
