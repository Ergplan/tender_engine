## Operating rules for Claude Code (goes in CLAUDE.md)

You are building the Tender Intelligence Engine on a single GCP VM that you control directly. You have shell, Docker, git and the project API keys. Act, do not ask for permission for routine steps; stop only at the stage boundaries named in each prompt or when a decision would change the data model or the truth pipeline.

1. Work stage by stage. Never start the next stage's work early, even if it looks obvious.
2. Every stage ends with: all tests green, `make deploy` serving the app on the static IP, a `STAGE-N-REPORT.md` listing what was built, what was skipped and why, and the open questions. Then stop.
3. Write tests before or with the code, never after as an afterthought. Unit tests for every validator and state transition, integration tests for every API endpoint, one end-to-end test per stage that runs on a real tender PDF.
4. The continuous test pipeline (section 5) runs the whole time you work. Before every commit, read `.ci/status.json`; if anything is red, fix it first. Never commit over a red watcher, never skip or mark tests as expected-failure to get green.
5. Small commits with plain messages. Commit after each working increment, not at the end of the stage.
6. The two reference repos (`tariff-oder`, `FDRE`) are read-only inputs in `/work/ref/`. Copy ideas and, where `INHERITANCE.md` says keep, copy code into the new repo with its origin noted in a comment. Never import from them at runtime, never submodule them.
7. One language for services: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, pytest. One language for the UI: TypeScript, React, Vite. No framework hopping mid-build.
8. Every LLM call goes through one module, `core/llm/`, with a typed request, a typed response, a stored prompt version, retries, and a full log of input hash, output, model, tokens and latency. No inline `anthropic.messages.create` anywhere else.
9. Keep the folder layout in section 5 exactly. New code goes in the folder the layout names; if nothing fits, add the folder to the layout in `docs/ARCHITECTURE.md` first, then the code. No `utils/`, `misc/`, `helpers/`, `temp/` or `old/` folders, no scripts at the repo root, no dead files left behind after a refactor.
10. Configuration by environment variables with a checked-in `.env.example`. Secrets never committed.
11. Phase 1 security is deliberately minimal: a GCP firewall allowlist on the VM and unguessable review tokens. Do not add auth, roles or login screens until Stage 5. Do build the tenant and audit columns from day one, so adding auth later is a middleware change.
12. Reviewer accuracy beats everything else. When a choice trades speed of extraction against traceability of evidence, pick traceability.
13. When uncertain about the tender domain, read the sample tenders in `/work/tenders/` before guessing. When uncertain about the architecture, re-read the invariants below. Do not invent fields that no tender in the sample set contains.
14. Four living documents are kept current in the same commit as the code that changes them: `docs/ARCHITECTURE.md`, `docs/FIELD-TRACE.md` (generated, see section 5), `docs/DECISIONS.md` (one dated line per decision) and `docs/KNOWN-GAPS.md`. A stage is not done if any of them is stale; the CI job for FIELD-TRACE fails the build when it is.
15. Independent review before each stage report, from Stage 1 onward. Run a reviewer with a model from a different family than the builder (OpenAI via OPENAI_API_KEY, or the reviewer the user names), in a fresh context with no access to this session. It receives only three things: the stage diff (git diff <stage-start-tag>..HEAD), CLAUDE.md, and the stage prompt. It answers a fixed checklist and nothing else: (a) every invariant in section 3 upheld, citing file and line, or the violation; (b) every API endpoint added has a test; (c) every write to candidate, approval, canonical_fact, tender_version and feedback goes through the audit log; (d) make trace regenerates FIELD-TRACE.md without diff; (e) any claim in the draft stage report that the code does not support. Fix every finding, rerun the reviewer until it reports none, then put the findings and the fixes in the stage report under "Independent review". Tag the commit at each stage start (stage-N-start) so the diff is well defined.

## Non-negotiable invariants (goes in CLAUDE.md)

These hold in every stage and override anything else in this document. If a prompt below ever seems to conflict with them, the invariant wins and you flag the conflict in the stage report.

&#91;embedded content: truth pipeline · 6 stages, 1 feedback store\]

Model output stops at the candidate; a reviewer's decision is the only step that produces a canonical fact, and every correction they make is kept for prompt work rather than fed back into the model.

**The LLM never writes truth.** Model output lands only in the `candidate` table. The `canonical_fact` table is written by exactly one code path: the approval handler, acting on a human decision. There is no admin override, no bulk-accept, no "auto-approve above 0.95 confidence" in phase 1.

**Every value carries its evidence.** A candidate without at least one `evidence_span` (document id, page, bounding box or character range, quoted text) is rejected by validation before a reviewer ever sees it. Canonical facts inherit the evidence of the candidate they were approved from, plus the reviewer's edit if any.

**The tender is a versioned object.** A corrigendum, amendment or clarification creates a new `tender_version`, never an in-place edit. Canonical facts are attached to a version. The current view of a tender is a projection over its versions, with each field showing which version last changed it.

**Candidates are immutable.** A reviewer's edit does not change the candidate; it creates an `approval` row holding the final value, a link to the candidate it was based on, and the reviewer's identity. The diff between candidate and approved value is the feedback signal.

**Validation is deterministic.** Type checks, range checks, cross-field rules (bid deadline after pre-bid date, SCOD after PPA signing, EMD within the stated per-MW band) run in plain Python. No LLM in the validation step. A failed validation marks the candidate `needs_review` with the rule name; it does not hide it.

**Everything is audited and tenant-scoped.** Every table has `tenant_id`, `created_at`, `created_by`. Every write to candidate, approval, canonical\_fact and tender\_version also appends to `audit_log`. In phase 1 there is one tenant and `created_by` is the reviewer name from the token; the columns still exist and every query filters by `tenant_id`.

**Feedback is stored, never auto-applied.** Corrections go into `feedback`. Humans use that table to revise prompts and eval sets. No code path reads `feedback` to change a prompt, a threshold or a model at runtime.

**API first.** Every intelligence operation (parse, extract, validate, compare, report) is a versioned endpoint under `/api/v1/`. The reviewer UI calls those endpoints and nothing else. If a feature cannot be driven through the API, it is not finished.

## Locked decisions (goes in CLAUDE.md)

These are decided. Do not reopen them in a stage report unless `INHERITANCE.md` shows the tariff repo already does something materially better.

| Area | Decision | Why |
| --- | --- | --- |
| Repo | `Ergplan/tender_engine` (exists, empty), monorepo: `core/`, `tender/`, `api/`, `worker/`, `web/`, `infra/`, `evals/`, `docs/` | Shared core and domain layer live side by side; two products later split by deployment, not by code |
| Build agent | Claude Code running on the VM itself, model Fable 5.1, with shell, Docker, git and gcloud; it codes, tests and deploys in place | No copy-paste between laptop and VM; the agent sees the real environment |
| Extraction model | Claude Fable 5.1 (`claude-fable-5-1`) for all extraction, summarisation and classification calls | Best available accuracy on long structured documents; one model keeps eval results comparable |
| Document input to the model | Native PDF page input to Claude for extraction, 20 to 40 page windows chosen by section map | Tables and layout survive; avoids OCR-text drift |
| Layout and coordinates | `pdfplumber` for text with character boxes; `pymupdf` for page renders and thumbnails | Gives evidence highlights their bounding boxes; both are libraries, not LLM providers |
| Independent agent (Stage 5) | OpenAI Agents SDK on the current GPT model, given raw pages and schema only | Different model family makes the second pass independent rather than confirmatory |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 | Matches the likely tariff-repo stack; confirm in Stage 0 |
| Database | PostgreSQL 16 in a container on the VM; `jsonb` for candidate payloads, proper columns for canonical facts | Cloud SQL migration later is a connection string change |
| Files | Local volume `/data/` on the VM in phase 1, with a `storage` interface so GCS is a config switch | No cloud credentials needed in the review phase |
| Queue | Postgres-backed job table polled by `worker/`; no Redis, no Celery | One fewer moving part; volume is 11 tenders |
| Frontend | React 18 + TypeScript + Vite, `pdf.js` viewer, Tailwind | Fast to build; `pdf.js` supports page jump and overlay highlights |
| Deployment | The existing GCE VM, `docker compose` with `api`, `worker`, `web`, `db`, `caddy`; a reserved static external IP attached on Day 1 and never changed | Reviewer URLs and the firewall rule stay valid for the whole review phase; Cloud Run split is Stage 5 |
| Access | GCP firewall: 443 open only to reviewer IPs, 22 open only to admin IPs; Caddy terminates TLS; no application login | Minimum security, maximum reviewer convenience, per phase 1 brief |
| Credentials | Anthropic key entered at bootstrap; OpenAI key, reviewer IPs and admin IPs asked by Claude Code in Stage 0 Part 0 and written to `.env` and `infra/allowlist.yaml` (gitignored) | Asked once, on Day 1, never pasted again |
| Reviewer identity | Per-tender review token in the URL, mapped to a reviewer name at creation | One reviewer per tender; identity without login; attribution preserved |
| Tenant model | `tenant_id` on every table from day one; single tenant `ergplan` in phase 1 | Isolation is a query filter and later a row-level policy, not a refactor |
| Prompts | Versioned files under `core/llm/prompts/<name>/vN.md`; the version is stored on every candidate | Feedback analysis can be grouped by prompt version |
| Evals | `evals/` holds gold sets as YAML per tender, a runner that scores per field, and a report generator | Accuracy per field per tender type is the phase 1 success metric |

## Repository layout, continuous testing, living documents (goes in CLAUDE.md)

The layout below is fixed from Stage 0B. Every later stage adds files inside it, never beside it.

```text
tender_engine/
├── CLAUDE.md                 # sections 2 to 5 of the master prompt, verbatim
├── Makefile                  # up, down, test, watch, trace, migrate, deploy, logs, report
├── docker-compose.yml        # api, worker, web, db, caddy, tests
├── pyproject.toml            # one Python project; ruff, mypy, pytest config here
├── .env.example
├── .ci/                      # watcher output; status.json is what Claude Code reads
├── core/                     # domain-agnostic document intelligence
│   ├── models/               # SQLAlchemy tables: document, page, section, candidate, evidence_span, approval, canonical_fact, feedback, audit_log, job, llm_call_log
│   ├── services/             # ingest, parse, section_map, extract, validate, approve, review_state
│   ├── llm/                  # client.py, registry.py, prompts/<name>/vN.md
│   ├── storage/              # local and gcs behind one interface
│   └── validation/           # rule engine and generic rules
├── tender/                   # tender domain on top of core
│   ├── models/               # tender, tender_version, tender_field_def, review_token, model_assumption
│   ├── schemas/              # common.yaml + one yaml per tender type
│   ├── prompts/              # per section-group extract prompts, summary prompt
│   ├── services/             # tender, versioning, current_view, tokens
│   └── validation/           # tender-specific rules
├── api/                      # FastAPI app; routes only, no business logic
│   ├── main.py
│   ├── deps.py               # tenant, reviewer, db session
│   ├── middleware/            # review_token, audit, errors
│   └── v1/                   # core/ and tenders/ routers, schemas/ (Pydantic I/O models)
├── worker/                   # job poller and the parse→map→extract→validate chain
├── agent/                    # Stage 5A only; OpenAI Agents SDK; its own container
├── web/                      # React + Vite + TypeScript
│   └── src/
│       ├── api/              # generated client from OpenAPI; the only place fetch() appears
│       ├── review/           # the split-screen reviewer: FieldCard, SectionList, PdfPane, EvidenceChip
│       ├── admin/            # reliability dashboard
│       └── lib/              # formatting by value_type, keyboard handling
├── evals/                    # gold/, runner.py, feedback_report.py, threeway.py, results/
├── infra/                    # bootstrap.sh, firewall.sh, allowlist.example.yaml, Caddyfile, STATIC-IP.txt, cloudrun/ (Stage 5C)
├── tests/                    # mirrors the package tree: tests/core/..., tests/tender/..., tests/api/..., tests/e2e/
├── scripts/                  # management commands only: ingest_tenders.py, make_gold.py, gen_field_trace.py
└── docs/
    ├── MASTER-PROMPT.md      # this document
    ├── ARCHITECTURE.md       # kept current every stage
    ├── FIELD-TRACE.md        # generated by make trace; never hand-edited
    ├── INHERITANCE.md
    ├── DECISIONS.md
    ├── KNOWN-GAPS.md
    └── reports/              # STAGE-N-REPORT.md, EXTRACTION-SUMMARY.md, FEEDBACK-REPORT.md, RELIABILITY-REPORT.md
```

**Continuous test pipeline.** A `tests` service in docker-compose runs beside the app from Stage 0B onward and is started by `make up`. It watches the source tree and re-runs on every save: `ruff check` and `ruff format --check`, `mypy` on `core/ tender/ api/ worker/`, `pytest` in watch mode (`pytest-watcher`) scoped to the packages that changed and then the full suite, `vitest --watch` and `tsc --noEmit` for `web/`, and `alembic check` so a model change without a migration fails immediately. Each run writes `.ci/status.json` (one entry per check: name, pass/fail, duration, first failing message) and `.ci/latest.log`. Claude Code reads `status.json` before every commit; a red entry blocks the commit. A pre-commit hook enforces the same locally, and the GitHub Actions workflow runs the identical checks on every push plus the Playwright suite nightly. The e2e tests that call the real LLM are marked `slow` and run on `make test-e2e`, not in the watcher.

**ARCHITECTURE.md.** Created in Stage 0B from the locked decisions and the layout above, then updated in every stage: the component diagram as a Mermaid block, the data model as a table (table, purpose, who writes it), the truth pipeline with the exact function names that implement each step, the API surface by router, the job chain, the deployment picture, and a short "what changed this stage" list at the end. Claude Code rewrites the sections that changed, not the whole file, and the stage report links to the diff.

**FIELD-TRACE.md.** The end-to-end trace of every field a reviewer sees, generated by `make trace` (`scripts/gen_field_trace.py`) from the schema YAMLs, the route registry and the ORM models, so it cannot drift from the code. One row per field path, in review order, with these columns: UI component and prop (web/src/review/...), API route that serves and that writes it, API middleware it passes (review\_token, audit), service and function in Python that produces the candidate and that approves it, DB table and column for candidate, approval and canonical, the producer tagged `LLM` (prompt name and version), `RULE` (validator name), `HUMAN` (approval decision) or `AGENT` (Stage 5A), and the evidence table. A CI check regenerates the file and fails the build if it differs from the committed one or if any field in a schema YAML has no UI component, no route or no table. Example rows:

| Field | UI (web/src) | API read / write | Middleware | Service (py) | DB candidate → approval → canonical | Producer | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| key\_dates.bid\_submission\_deadline | review/FieldCard value (date) | GET /v1/tenders/{id}/review-state / POST /v1/approvals | review\_token, audit | core.services.extract.extract\_group('key\_dates') / core.services.approve.approve() | candidate.value → approval.final\_value → canonical\_fact.value | LLM extract/key\_dates v1; RULE date\_order | evidence\_span.page\_no, bbox |
| summary.plain\_english\_summary | review/FieldCard value (long\_text) | same | same | tender.services.summary.write\_summary() / approve() | same | LLM summary v1 | evidence\_span (multi-page) |
| ipp\_model.capex\_inr\_per\_mw | review/AssumptionPanel | GET, PUT /v1/tenders/{id}/assumptions | review\_token, audit | tender.services.assumptions.upsert() | model\_assumption.capex\_inr\_per\_mw (no candidate, no canonical) | HUMAN | none |

