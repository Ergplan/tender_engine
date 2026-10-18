# Stage 5A report: the independent agent pass

Date: 2026-10-18. Diff: `git diff stage-5a-start..HEAD` (tag at 09b3354). Architecture changes: `docs/ARCHITECTURE.md` (the `agent` container in the component diagram and the services table; layout rows for `agent/`, `core/llm/agent_calls.py`, `tests/agent/`; data-model rows `agent_run`, `agent_finding`, `llm_call_log.agent_run_id`; the section "Independent agent pass (Stage 5A)"; job chain by kind; "What changed this stage", Stage 5A).

**Opened on your word of 2026-10-18 ("use whatever is completed and please move ahead with build") with the Stage 4 stability bar not met: `epc` and `wind` have one reviewed tender each of two, and one required field is below 75% (`docs/reports/RELIABILITY-REPORT.md`, "Stability bar for Stage 5"). Eleven of fourteen reviews are completed and gold. The stage is built and checked (the commits of this stage each passed the full check suite); it is deployed by the `make deploy` reported in the delivery message; the agent has read one real document end to end (USD 0.46); the passes over the eleven gold tenders are the step after this report.**

## Definition of done (master prompt, Stage 5A)

| Check | Result |
| --- | --- |
| `agent/` as a separate container on the OpenAI Agents SDK, the current GPT model | Yes: compose service `agent` (`agent/main.py`), `openai-agents` 0.24.0 (`uv.lock`), model `gpt-6.1-sol` (setting `OPENAI_MODEL`; the model the key reaches, used by the independent reviewer since Stage 4), in `make deploy` |
| It receives the tender type, the compiled field schema, the raw page renders plus page text for the sections the section map names | Yes: `agent/inputs.py` builds the brief from the catalog's compiled schema and the engine's own page selection (`core.services.extract.select_pages` on each document's section map); `read_pages` returns text, and the 150 dpi render when asked for or when a page has no text layer |
| It does NOT receive the engine's candidates, the gold values, or the reviewer's decisions | Yes: `build_inputs` reads `tender_version`, `document`, `page`, `section` and the catalog, nothing else; no import of candidate, approval, canonical_fact or `evals/` in `agent/` |
| Three tools: `read_pages`, `search_text`, `submit_finding` | Yes: `agent/harness.py`, `Harness.read_pages / search_text / submit_finding`, wrapped for the SDK by `sdk_tools` with strict JSON schemas |
| It must call `read_pages` before any `submit_finding` for a field | Yes: a finding of any kind before the first `read_pages` is refused ("no page has been read yet"), and a finding citing a page not read is refused ("was not read: call read_pages before citing a page"); both kept as `rejected` |
| The harness rejects findings whose quotes are not found on the cited page, same rule as core | Yes: `core.evidence.locate` on the cited page at `evidence_match_threshold`; the cited page only (core also tries adjacent pages, the brief says "on the cited page") |
| Results land in `agent_finding`, never in candidate or canonical_fact | Yes: migration 0016; the harness writes `agent_finding`, `agent_run` and their `audit_log` rows, and its model calls `llm_call_log`; nothing in `agent/` imports or writes candidate, approval or canonical_fact, and the guards of Stages 1–3 are untouched |
| `POST /tenders/{id}/agent-pass` runs it; `GET /tenders/{id}/agent-pass/{run_id}` returns findings | Yes, plus `GET /tenders/{id}/agent-pass` (the runs of a tender); `api/v1/tenders/agent_pass.py`; each with a test |
| All tests green, `make deploy` serving the app | See "Tests" and "Deployment" |

## What was built

- **Tables** (`agent/models.py`, migration 0016): `agent_run` (object, schema and prompt version, model, status `queued / running / done / stopped / failed`, turns, tokens in / cached / out, cost, the documents by number, `pages_offered`, `pages_read`) and `agent_finding` (one row per attempt: ordinal, field, value, type, confidence, rationale, status `accepted / not_found / withdrawn / rejected / superseded`, the refusal reason, the evidence as cited and as located). `llm_call_log.agent_run_id` ties the agent's turns to the run.
- **The model call** (`core/llm/agent_calls.py`): the SDK asks `LoggedProvider` for its model and gets the OpenAI Responses-API model wrapped in `LoggedModel`, which writes one `llm_call_log` row per turn — prompt `agent_pass/v1`, model, input hash, the output items, tokens with the cached part told apart, cost at the configured list prices, latency, outcome. Operating rule 8 holds: OpenAI is reached from this module and nowhere else; tracing is disabled, so nothing leaves to the SDK's trace endpoint.
- **The brief** (`agent/inputs.py`): documents of every version up to the one passed, numbered in version order, each with its section headings and the pages the section map names for the schema's groups; the fields by section with type, unit, required, help text, enum values and record keys; the group guidance. The summary field and the derived tables are not asked for (the summary is written from the record, the tables from decisions).
- **The harness** (`agent/harness.py`): `read_pages` (at most `agent_max_pages_per_read` pages a call; marks pages read; images on request or for a scanned page), `search_text` (every page of every document, twenty hits with a snippet), `submit_finding` (unknown field, confidence outside 0–1, empty rationale, an unread page, an unlocated quote, a value without evidence, a value of the wrong type: each refused with the reason the agent is told and a `rejected` row; `null` without evidence is an explicit `not_found`, `null` with located evidence `withdrawn`; a later finding for a field supersedes the earlier). Every finding and every change of a run's status is audited; `pages_read` is progress state on the run row itself, committed as pages are read, not audited per read. `finish` sums the run's logged turns.
- **The pass** (`agent/service.py`): `start` checks the inputs and queues the run; `run` is the job; a model error or the turn limit ends the run as `stopped` with the findings so far; a pass that ends with fields unsubmitted, `done` or `stopped`, names them in `error`. `agent/main.py` polls for `agent_pass` jobs only; `core.services.jobs.claim_next` and `requeue_orphans` now take `kinds`, and the worker claims only the kinds it handles: the first time two processes share the job table.
- **The prompt** (`core/llm/prompts/agent_pass/v1.md`): the engine's extraction rules restated for a tool-using reader — verbatim quotes from read pages, document and page positions as the tools report them, explicit not-found, the later document governs, withdrawals as null with the removing words.
- **The API** (`api/v1/tenders/agent_pass.py`, `api/v1/schemas/agent.py`): the three routes, operator-only (a review token is refused with `not_allowed`); the TypeScript client regenerated by `make client` (`web/src/api/schema.d.ts`, `openapi.json`; generated files, left out of the reviewer's diff by `scripts/independent_review.py`).
- **FIELD-TRACE**: the producer tag `AGENT agent_pass v1 → agent_finding (never canonical)` on the 209 fields the agent is asked for, read from the prompt file by `scripts/gen_field_trace.py`.

## The first real pass

`tests/e2e/test_agent_pass.py` (slow, `make test-e2e`) on the SECI CnI-1 pre-bid notice (one page), 2026-10-18, output kept in `stage-5a-artifacts/e2e-agent-pass-2026-10-18.txt`: status `done`, 118 turns, 1,419,692 input tokens of which 1,402,646 cached, 7,073 output tokens, **USD 0.464** at the configured prices; 11 findings accepted with located evidence, 94 explicit not-founds, nothing rejected. The accepted readings (tender number, agency, title, portal, 700 MW, ISTS-anywhere, NIT date, pre-bid date, bid deadline 2026-10-05, the solar source rule) are each backed by a quote the resolver located on the page, and the values follow from their quotes; nobody has yet compared them with a reviewer's reading — that is Stage 5B's job. Two settings changed on that evidence, in the same diff: `agent_max_turns` 120 → 200 (a full RfS has ~105 fields and a pass that submits one finding per turn needs room for its reads and searches), and parallel tool calls allowed (several findings from one page cost one model call; the harness lock serialises them). The cost of a full tender is not known from a one-page run; it is measured on the eleven gold tenders after this report and reported with them.

## Tests

- `tests/agent/test_harness.py` (5): the tools; each refusal of `submit_finding` (nothing read yet, unknown field, confidence, rationale, a page or document that does not exist, an unread page, an unlocated quote, a value without evidence, a value of the wrong type); supersession, not-found and withdrawn; `finish`.
- `tests/agent/test_inputs.py` (4), `test_service.py` (8), `test_main.py` (5), `test_sdk_driver.py` (2: the real SDK loop with a scripted model — read, submit, final; the turn limit), `tests/core/llm/test_agent_calls.py` (5), `tests/core/services/test_jobs.py` (+2: claims and orphans by kind), `tests/api/test_agent_pass.py` (3: the three routes, the refusals, a review token refused).
- `tests/e2e/test_agent_pass.py` (1, slow): the real parse, section map and agent pass on a real tender PDF.
- The full suite (`make check`, nine checks: ruff, format, mypy over `core tender api worker agent evals`, alembic check, field trace, OpenAPI client drift, pytest, tsc, vitest): green before each commit of this stage; the pre-commit hook refuses a commit over a red or stale `.ci/status.json`, and the hook is what certifies it, not this sentence.

## Deployment

`make deploy` after the last commit of this stage: images rebuilt with `openai-agents`, migration 0016 applied, the `agent` service started beside the worker, health ok, the test watcher stopped afterwards as you asked; the deploy's output is in the message that delivers this report, as before.

## What was skipped and why

- No screen for the findings: the brief gives Stage 5A two endpoints and no UI; Stage 5B's three-way report is their first reader (KNOWN-GAPS).
- No image for every page by default: the agent asks for images when a table's layout matters or the text looks garbled, and always gets one for a scanned page; images in every turn would multiply the cost for little (KNOWN-GAPS).
- OpenAI prices are settings, not fetched: `agent_run.cost_usd` is the figure at the configured list price; the invoice is the truth (KNOWN-GAPS, DECISIONS).
- The eleven passes over the gold tenders are not in this diff: they are runs, started after this report through the API, and their cost is reported with them.

## Independent review (operating rule 15)

Reviewer `gpt-6.1-sol` (OpenAI, a different family from the builder), fresh context, three inputs: CLAUDE.md, `stage-5a-artifacts/stage-5a-prompt.md` (the Stage 5A block of the master prompt and your instruction of 2026-10-18), and the stage diff against the tag `stage-5a-start` (generated files left out: `uv.lock`, the OpenAPI client, gold, results, released packs). Both runs are kept verbatim as `stage-5a-artifacts/review-gpt-6.1-sol-run1.txt` and `-run2.txt`. The diff reviewed was the staged working tree before the stage's commit (the review and the check suite ran together to save an hour), so the commit holds exactly what run 2 saw plus the wording changes listed below.

**Run 1** — one invariant defect, one enforcement gap, two audit and reporting gaps, and ten report claims. Fixed in code:

- (a) `Harness._stand` looked the earlier finding up by primary key without a tenant filter → a tenant-scoped select.
- (e)3 The brief says `read_pages` must precede any `submit_finding`; the harness checked it only for findings with evidence, so an abstention could be submitted before any page was read → any finding before the first read is refused ("no page has been read yet"), kept as `rejected`; test added.
- (e)4 The run's `queued → running` and `→ failed` transitions committed without an audit row → audited (`status_change`); the report no longer says "every write" but names what is audited.
- (e)5 A `stopped` run did not name the fields left without a finding → both `done` and `stopped` do; three tests tightened.
- (e)9 Two refusal branches (empty rationale, a page or document that does not exist) had no test → tests added.
- (e)2, 6, 10 Report wording: the SDK version is the locked one (`uv.lock`), the model is the one the key reaches; the generated client is left out of the reviewer's diff by design; the claim that `make report` recomputes costs was wrong and is gone.

**Run 2** — (a), (b), (c): no finding. Code defects: none. Report wording fixed after it: the harness also writes audit rows and its calls `llm_call_log` ((e)4); `pages_read` is on the run row, not in the closing audit ((e)5); the readings of the first pass are backed by located quotes, not "checked by me" ((e)6); the Anthropic cost of the e2e's section map is not kept ((e)7).

**Not resolvable by code, listed with a rationale (does not block the stage):**

- (d) `make trace` regenerating without diff: the `field_trace` check of the suite is the proof (`scripts/gen_field_trace.py --check` fails the build on a stale file); a diff cannot show an execution result. Run before the commit: "docs/FIELD-TRACE.md is current (212 fields)".
- (e)1, 2 Green checks before each commit, the deploy, the migration applied, the watcher stopped: operational facts the pre-commit hook and the delivery message certify, not a diff.
- (e)3 `openai-agents` 0.24.0 is the version in `uv.lock`, left out of the reviewer's diff for size; "current GPT model" is the master prompt's phrase, and `gpt-6.1-sol` is the model the key reaches today (the reviewer itself runs on it).

## Open questions

- The bar: the stage opened on your word with the bar not met. Stage 5B's three-way comparison is meant for gold tenders; eleven exist. Say whether 5B should wait for Ramagiri, Wind-XX and RECPDCL or run on the eleven.
- The OpenAI prices in `.env` (`OPENAI_PRICE_IN_PER_MTOK`, `OPENAI_PRICE_OUT_PER_MTOK`): set them from the provider's price list for `gpt-6.1-sol` if the defaults are not it. A run's stored cost is the figure at the prices of its time; the tokens are stored too, so a figure at other prices can be worked out from `llm_call_log`.
- Whether the agent should read page images on every page (more cost, perhaps more table readings): decide after the eleven passes show where it missed.

## Costs

This stage's model spend so far: USD 0.464 (OpenAI, the one real pass, from `agent_run.cost_usd`) plus the Anthropic parse and section map of the one-page notice in the same test (one section-map call; its log row went with the test schema, which the suite drops, so the figure is not kept), plus the two independent review runs (91,288 + 93,056 input tokens, 3,230 + 2,141 output, on `gpt-6.1-sol`; the review script does not price them). The eleven passes follow and are reported with their own figures.
