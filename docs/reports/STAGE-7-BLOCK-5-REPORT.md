# Stage 7, Block 5 report: full-tender query (2026-10-25 to 2026-10-27)

Block 5 of the owner's completion plan: a question about a whole tender, answered from the
approved record when it names a field and from the tender's own pages otherwise, every
claim tied to a page and a quote the evidence resolver located; cross-tender questions as
a structured search over approved facts; a fifty-question eval over the gold tenders. Built
without OpenAI (the owner's word of 2026-10-25), so the embeddings are a local model and the
rule-15 reviewer is Claude Opus 5.5 (DECISIONS 2026-10-25 and 2026-10-27).

## Definition of done

| Item | State | Evidence |
| --- | --- | --- |
| (a) Haystack pipeline, hybrid retrieval (BM25 + embeddings) in the existing Postgres via pgvector, no new database; embeddings with a config switch for a local model; chunks carry page, clause number and document version | Done; the switch is `EMBEDDINGS_PROVIDER=local\|none` (OpenAI is out) | `core/retrieval/` (chunks, store, embeddings, indexer, query), migration 0023 `retrieval_chunk`, `tests/core/retrieval/` (11) |
| (b) `ask_tender`: field questions from approved facts first; otherwise retrieve and answer from the retrieved pages only; every claim cites page and quote resolved by the resolver, unresolved shown as such; version-aware with an amendment note; marked machine or approved; never a fact | Done | `tender/services/ask.py`, `ask_fields.py`, prompt `ask_tender/v1`, `POST /tenders/{id}/ask`, MCP `ask_tender`; `tests/tender/test_ask.py` (4), `test_ask_fields.py` (10), `tests/api/test_ask.py` (3) |
| (c) Cross-tender questions by structured search over canonical facts, not retrieval | Done | `tender/services/ask_across.py`, `POST /tenders/ask`; `tests/tender/test_ask_across.py` (3) |
| (d) Eval set of 50 questions over the gold tenders with reviewer-written answers; answer accuracy and citation-resolution rate | Done; the expected answers are the reviewers' decided values in the gold records (no reviewer wrote prose answers: the owner's 2026-10-27 decision allows no more reviews) | `evals/questions/gold-questions.yaml` (50 + 3 cross), `evals/ask_eval.py`, `make ask-eval`; results below |

## (a) Retrieval

One table, `retrieval_chunk` (migration 0023), in the app database under the same row-level
security as every other table: the `pgvector` extension, Haystack's columns, `tenant_id`
with the four tenant policies. The compose `db` image is `pgvector/pgvector:pg16` (same
major, same data directory; the owner's deploy of 27 October swapped it and applied 0023).

A chunk is a clause or part of one (`core/retrieval/chunks.py`): the page text cut at
numbered clause lines, short clauses merged, long ones split at sentence ends, offsets into
the page text kept so a chunk is a slice of the page a reader can open. Each chunk carries
the document, filename, page, clause number, section kind and heading, parser layer, and
from the tender layer (`tender/services/retrieval_meta.py`) the tender, version number,
version kind and document role. Indexing is the `index_document` job the worker runs after
every section map, and again when a document is attached to a tender; `embed_pending`
embeds chunks written while the embedder was unavailable; `scripts.ingest_tenders index
[--now]` rebuilds, `POST /tenders/{id}/index` queues one tender.

Embeddings: `fastembed` with `BAAI/bge-small-en-v1.5` (384 dimensions, ONNX, two threads)
on the VM, the model files under `/data/models/fastembed`; no document leaves the machine
and an embedding run costs nothing but time (about three minutes for a 400-chunk document
on the e2-medium). Every embedding run is logged in `llm_call_log` (`embed_chunks`, cost 0)
so the ledger says what was embedded. `EMBEDDINGS_PROVIDER=none` leaves full text alone.

Query (`core/retrieval/query.py`): Haystack's keyword retriever (`ts_rank_cd` over the GIN
index) and embedding retriever (cosine) joined by reciprocal rank fusion, top 8 passages,
filters on the tender and the documents of the version asked about; when the embedding leg
fails at query time the keyword leg answers alone and the answer's `retrieval` field says
so. One rule of this block's close (DECISIONS 2026-10-27): Haystack's keyword query wants
every word of the question on the chunk, so the store asks for every word first and then
for any word, keeping a chunk only when it holds at least two of them; a question none of
whose words are on any page still answers "no passage" without a model call.

## (b) `ask_tender`

`AskService.ask` (`tender/services/ask.py`):

1. **Field route.** `ask_fields.map_question` maps the question to a field of the record by
   label-word coverage with a few domain aliases, deterministic; a tie, or a question whose
   own words fit another field's label as well ("deadline" alone), answers None and the pages
   are asked instead. A matched field is answered from the record without a model call: the
   approved fact when one exists (`source: approved`), else the engine's reading marked
   `machine` with its confidence; every quote behind it is located on its page again by the
   evidence resolver before it is shown.
2. **Retrieval route.** The passages come from the current version's documents (versions in
   date order, Block 3); the model (prompt `ask_tender/v1`) answers from the passages alone,
   each claim naming its passage and a quote copied letter for letter; each quote is resolved
   on the page and an unresolved one is returned as `resolved: false` with the reason, never
   dropped. `answered: false` with "No passage of this tender answers the question" when the
   passages do not answer or none is found.
3. **Version-aware.** The answer carries `version_no` and an `amendment_note` when a later
   version changed the field or the cited passage is an amendment's.
4. **Never a fact.** Every answer is `is_fact: false` with the authority note; nothing on this
   route writes to any table but the call log.

`POST /tenders/{id}/ask` is the one route that calls the model inside the request (a
question wants its answer now; DECISIONS 2026-10-25); the MCP tool `ask_tender` (paid tier)
returns the same answer with a text fallback.

## (c) Cross-tender questions

`POST /tenders/ask` (`tender/services/ask_across.py`): the question is read into one
structured query (field, operator, value) or the caller sends the query itself; the search
runs over approved facts only and returns the query that ran with the matching tenders, and
lists under `unreviewed` the tenders whose field is read but not reviewed. Retrieval is not
used here.

## (d) The question eval

**Not run yet: the Anthropic credit balance ran out at 00:56 UTC on 2026-10-27** (Block 4's
second batch hit it first; nine calls refused with "Your credit balance is too low"). The
retrieval route calls the model, so the eval waits for the owner's refill. The chunks of
the eleven gold tenders are indexed by the worker meanwhile (`index_document` jobs, local
embeddings, no model cost). After the refill:

```
docker compose exec -T api python -m scripts.ingest_tenders resume --only recpdcl-bikaner-v-part-a
make ask-eval
```

`evals/ask_eval.py` asks the live engine the way the API does and reports answer accuracy
(the expected value in the answer under the match rules in its docstring) and the citation
resolution rate (quotes the resolver located / quotes given), overall, for the critical
questions, and per route (field: from the record without a model call; retrieval: from
passages by the model), plus the three cross-tender questions (read into the right query;
the query matching the right gold tenders). Results go to `evals/results/ask-eval-<stamp>.*`
and this section is filled from them. The numbers are **in-sample**: the expected answers are
the gold records' decided values, read from the same tenders the engine was tuned on.

## Tests

The block's first full `make check` (run 9, `stage-7-artifacts/check-run9.log`, 2026-10-27
00:51 UTC) was red on two checks: `alembic_check` (the chunk table's four indexes were not
on the model) and pytest (eight failures: the job chain's expectations without the new
`index_document` step in three tests; four parse tests reading their scanned fixture through
the live Docling because the container's `.env` carries `DOCLING_URL` since Block 4; the
MCP fixture built without the retrieval services; `retrieval_chunk` without the audit
columns; one tool-count assertion). Every one fixed in code or in the test it belonged to
(DECISIONS 2026-10-27), none skipped. Run 10 (`check-run10.log`) was red on one test alone,
`tests/tender/test_corrections.py`, which read the audit rows of a hold without an order
and had so far been lucky with the heap's order; it now orders them. Run 11
(`check-run11.log`) is the green run the commit stands on. New tests, 43: `tests/core/retrieval/` (11: chunking 4, embeddings logged 3,
the index with its tender meta, tenant isolation and the any-word fallback 4),
`tests/tender/test_ask.py` (4), `test_ask_fields.py` (10), `test_ask_across.py` (3),
`tests/api/test_ask.py` (3), `tests/evals/test_ask_eval.py` (5),
`tests/scripts/test_independent_review.py` (3), `tests/scripts/test_blind_check.py` (4).

## Deployment

The owner's `make deploy` of 2026-10-27 00:16 UTC built the images with the Block 5
dependencies, swapped the `db` image, applied migration 0023 and recreated the services;
the api and worker run the mounted tree, so the block's later fixes are live on the api
(uvicorn reloads) and reached the worker with `docker compose restart worker` (00:41 UTC).
`make deploy` now also starts the `docling` service (the owner's decision 2 of 2026-10-27)
and waits up to two minutes for the health endpoint.

## Independent review (operating rule 15)

**Pending the credit refill** (the reviewer is a model call: `make review STAGE=7
RANGE=stage-7-block-5-start..HEAD PROMPT=docs/COMPLETION-PLAN.md`, Claude Opus 5.5 through
`core/llm`, the block's diff with CLAUDE.md and the plan as its only inputs; DECISIONS
2026-10-25 and 2026-10-27 record that it is the builder's vendor). The block is committed
with this report so that Block 6 can start on a clean tree; the review runs on the tag range
as soon as the model answers, its code defects are fixed in Block 6's tree and listed here
with the run's output in `stage-7-artifacts/review-block-5-runN.txt`.

## Costs

No model call of this block has run yet (the embedding runs are local and cost nothing; the
eval and the review are the block's only model calls and wait on the refill). Running total
of the ledger (`llm_call_log`) at the block's commit: USD 502.76, of which Block 4's reading
of the blind set on 2026-10-27 is about USD 54.

## Open questions

- The local embedding model is unmeasured against OpenAI's (KNOWN-GAPS): the eval reports
  retrieval with `bge-small` alone.
- The question set's expected answers are gold values, not prose answers a reviewer wrote
  for the questions; a reviewer-written set is a later addition if reviews resume.
