# Tender Intelligence Engine — Claude Code Master Prompt (One-Week Build)

Oct 4, 2026 · @Aayuda Energy

## How to use this prompt

Nothing is pasted from this document into the VM except one bootstrap script. This document is committed to the repo as `docs/MASTER-PROMPT.md`, and Claude Code reads every stage from that file.

1. **Push once from your laptop.** Download this doc as Markdown and push it to `Ergplan/tender_engine` as `docs/MASTER-PROMPT.md`. That is the only git action you do by hand all week.
2. **Bootstrap once on the VM.** SSH in and paste the bootstrap script from section 7, Part 0. It installs Docker, Node, GitHub CLI and Claude Code, signs you into GitHub (one device code in your browser), asks for your Anthropic key, clones the repo and opens Claude Code set to Fable 5.1.
3. **Start Stage 0 with one line.** In Claude Code type: `Read docs/MASTER-PROMPT.md. Write sections 2 to 5 into CLAUDE.md verbatim. Run Stage 0 Part 0.` It asks you for the OpenAI key, the reviewer IPs and the admin IPs, sets up the static IP and firewall, then continues into Part A and stops.
4. **Every later stage is one line.** After you have read the previous report: `Run Stage N of docs/MASTER-PROMPT.md.`

Each stage ends with a hard stop: Claude Code writes `STAGE-N-REPORT.md`, runs the acceptance checks in section 14, and waits. You read the report, open the running app, and only then send the next line.

Section 12 (independent agent, three-way comparison, production) is not part of the week. It runs after the 11-tender review phase is complete and the reliability report exists.

Section 13 is the field catalogue. Stage 2 reads it from the master prompt file as the seed for the schema files. Edit it before then if a field is missing or wrong for your tenders.

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
15. Independent review before each stage report, from Stage 1 onward. Run a reviewer with a model from a different family than the builder (OpenAI via OPENAI_API_KEY, or the reviewer the user names), in a fresh context with no access to this session. It receives only three things: the stage diff (git diff <stage-start-tag>..HEAD), CLAUDE.md, and the stage prompt. It answers a fixed checklist and nothing else: (a) every invariant in section 3 upheld, citing file and line, or the violation; (b) every API endpoint added has a test; (c) every write to candidate, approval, canonical_fact, tender_version and feedback goes through the audit log; (d) make trace regenerates FIELD-TRACE.md without diff; (e) any claim in the draft stage report that the code does not support. Fix every code defect it finds. Rerun until the reviewer reports no new code defect. Findings that cannot be resolved by code (by-design behaviour, statements a diff cannot prove, decisions pending from the user) are listed in the stage report with a one-line rationale and do not block the stage. Put the findings, the fixes and that list in the stage report under "Independent review". Tag the commit at each stage start (stage-N-start) so the diff is well defined.

## Non-negotiable invariants (goes in CLAUDE.md)

These hold in every stage and override anything else in this document. If a prompt below ever seems to conflict with them, the invariant wins and you flag the conflict in the stage report.

&#91;embedded content: truth pipeline · 6 stages, 1 feedback store\]

Model output stops at the candidate; a reviewer's decision is the only step that produces a canonical fact, and every correction they make is kept for prompt work rather than fed back into the model.

**The LLM never writes truth.** Model output lands only in the `candidate` table. The `canonical_fact` table is written by exactly one code path: the approval handler, acting on a human decision. There is no admin override, no bulk-accept, no "auto-approve above 0.95 confidence" in phase 1.

**Every value carries its evidence.** A candidate that carries a value but no `evidence_span` (document id, page, bounding box or character range, quoted text) is rejected by validation before a reviewer ever sees it. A candidate without located evidence (its quote could not be found in the document, or the model returned no value) is shown, at capped confidence and marked with the reason, but cannot be approved without the reviewer supplying a page and quote that resolve. No canonical value exists without located evidence. Canonical facts inherit the evidence of the candidate they were approved from, plus the reviewer's edit and evidence if any.

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
│   ├── domain_packs/         # schemas, prompts and validators; one folder per pack
│   │   ├── core/             # common.yaml, shared validators, section-group prompts, summary prompt
│   │   └── power/            # pack.yaml, one yaml per tender type, prompts/, validation/, tests/
│   └── services/             # tender, versioning, current_view, tokens
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
| core.key\_dates.bid\_submission\_deadline | review/FieldCard value (date) | GET /v1/tenders/{id}/review-state / POST /v1/approvals | review\_token, audit | core.services.extract.extract\_group('key\_dates') / core.services.approve.approve() | candidate.value → approval.final\_value → canonical\_fact.value | LLM extract/key\_dates v1; RULE date\_order | evidence\_span.page\_no, bbox |
| core.summary.plain\_english\_summary | review/FieldCard value (long\_text) | same | same | tender.services.summary.write\_summary() / approve() | same | LLM summary v1 | evidence\_span (multi-page) |
| sector.power.ipp.capex\_inr\_per\_mw | review/AssumptionPanel | GET, PUT /v1/tenders/{id}/assumptions | review\_token, audit | tender.services.assumptions.upsert() | model\_assumption.capex\_inr\_per\_mw (no candidate, no canonical) | HUMAN | none |

## Seven-day plan

The week ships a working review system and a first accuracy number; the independent agent comes after the 11 tenders are reviewed. Each stage boundary is a stop where you approve before the next session starts.

&#91;embedded content: seven-day plan · 5 stages, 4 stop points\]

Stage 1 gets two days because the core is where mistakes become permanent; every other stage is one day.

1. **Day 1, Stage 0.** Morning: bootstrap the VM, sign into GitHub, Claude Code collects keys and IPs, reserves the static IP, writes the firewall rules, clones both reference repos and produces `INHERITANCE.md`. Stop. Afternoon: scaffold `tender_engine`, `docker compose` with an empty API and DB served on the static IP, CI running pytest.
2. **Days 2 to 3, Stage 1.** Shared document intelligence core: upload, page store, section map, evidence spans, candidate extraction through Fable 5.1, deterministic validation, approval state machine, audit log. End-to-end test on one FDRE tender PDF. Stop.
3. **Day 4, Stage 2.** Tender domain layer: tender types, schema YAMLs from section 13, corrigendum versioning, type-specific validators, extraction prompts per section. All 11 tenders ingested and extracted. Stop.
4. **Day 5, Stage 3.** Reviewer UI: token URL, split screen, evidence jump and highlight, approve/edit/not-found, keyboard flow, progress and completion. You do a full review of one tender yourself before approving the stage. Stop.
5. **Day 6, Stage 4 part one.** Gold set tooling: the first two completed reviews become gold; eval runner scores candidates per field; feedback table populated from every edit. Reviewer links for all 11 tenders sent out.
6. **Day 7, Stage 4 part two.** Accuracy dashboard per field per tender type, `RELIABILITY-REPORT.md` generator, prompt revision loop using the feedback table. Reviews continue beyond the week; the report regenerates on each completion.

If Stage 1 slips past Day 3, cut from Stage 3 (drop keyboard shortcuts and thumbnails, keep evidence jump) rather than from Stage 1. A core that leaks LLM output into truth cannot be fixed later; a plainer UI can.

## Stage 0 prompt: repo archaeology and scaffold

The bash block is the one thing you paste, into the VM shell over SSH. It ends by opening Claude Code; from there every instruction is a single line. The markdown block is read by Claude Code from `docs/MASTER-PROMPT.md`.

```bash
# One-time VM bootstrap. Ubuntu 22.04/24.04 on the GCE VM. Paste as one block.
set -e
sudo apt-get update -y && sudo apt-get install -y git curl wget ca-certificates gnupg build-essential python3-pip jq
# Docker + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Node 22 (for Claude Code and the Vite build)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
# GitHub CLI
sudo mkdir -p -m 755 /etc/apt/keyrings
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
sudo apt-get update -y && sudo apt-get install -y gh
# Claude Code
sudo npm install -g @anthropic-ai/claude-code
# GitHub sign-in: covers tender_engine, tariff-oder and FDRE in one step (device code in your browser)
gh auth login --hostname github.com --git-protocol ssh --web
# Anthropic key for Claude Code and the app; stored in the shell profile, never in the repo
read -s -p "Anthropic API key: " ANTHROPIC_API_KEY; echo
{ echo "export ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"; echo "export ANTHROPIC_MODEL=claude-fable-5-1"; } >> ~/.bashrc
export ANTHROPIC_API_KEY ANTHROPIC_MODEL=claude-fable-5-1
# Workspace
sudo mkdir -p /work /data && sudo chown -R $USER:$USER /work /data
cd /work && gh repo clone Ergplan/tender_engine && cd tender_engine
echo "Bootstrap done. Run: newgrp docker  then: claude"
```

Then type `newgrp docker`, then `claude`, then the one line from section 1 step 3.

```markdown
# STAGE 0: VM and credentials, repo archaeology, scaffold

You are running on the GCE VM as the project's build agent. Part 0 collects everything you need for the week so the user never pastes anything again. Part A is read-only analysis. Part B scaffolds the repo.

## Part 0: VM, credentials, network

1. Confirm the environment: docker, docker compose, node, python3, gh auth status, gcloud (print versions). If gcloud is missing, install it. If gh is not authenticated, stop and tell the user to run `gh auth login --web`.
2. Ask the user, one question at a time, and wait for each answer: (a) the OpenAI API key, to be stored now for Stage 5; (b) the reviewer IPs or CIDRs that may reach the app on 443; (c) the admin IPs or CIDRs that may SSH on 22; (d) the GCP project id, zone and this VM's instance name if `gcloud config` and the metadata server do not already tell you. Do not proceed with placeholders.
3. Write `.env` at the repo root (gitignored) with ANTHROPIC_API_KEY, ANTHROPIC_MODEL=claude-fable-5-1, OPENAI_API_KEY, DATABASE_URL, DATA_DIR=/data, TENANT_ID=ergplan, and a checked-in `.env.example` with the same keys blank. Write `infra/allowlist.yaml` (gitignored) with the reviewer and admin lists and an `infra/allowlist.example.yaml`.
4. Static IP: check whether this VM already has a reserved static external address. If not: `gcloud compute addresses create tender-engine-ip --region <region>`, then attach it to this VM's NIC (`gcloud compute instances delete-access-config` then `add-access-config --address`). Expect your SSH session to survive; if the VM's service account lacks compute scope, print the exact two commands for the user to run in Cloud Shell, wait for "done", then verify. Record the final IP in `infra/STATIC-IP.txt` (committed) and in DECISIONS.md. This IP is never changed after today.
5. Firewall: tag the instance `tender-engine`. Create or update `tender-engine-https` (tcp:443, source ranges = reviewer list + admin list, target tag tender-engine) and `tender-engine-ssh` (tcp:22, source ranges = admin list). Remove any default rule that opens 22 or 443 to 0.0.0.0/0 for this instance's tags. Print the resulting rules. Write `infra/firewall.sh` that recreates them from `infra/allowlist.yaml`, so adding a reviewer later is: edit the YAML, run the script.
6. Verify from the VM that 443 is reachable from an allowed IP (ask the user to open https://<static-ip>/ once Caddy is up in Part B) and that nothing else is open (`gcloud compute firewall-rules list --filter=targetTags:tender-engine`).
7. Install the Python toolchain you will use for the whole week (uv or pip with a venv under /work/tender_engine/.venv) and pre-pull the postgres:16 and caddy images.
8. Commit everything that is not a secret. Write STAGE-0-PART0-REPORT.md: static IP, firewall rules, what was asked and stored where. Continue straight into Part A without stopping.

## Part A: archaeology

1. Clone git@github.com:Ergplan/tariff-oder.git and git@github.com:Ergplan/FDRE.git into /work/ref/ (gh already holds the credentials). Treat both as reference implementations, never as code to merge.
2. For each repo write a section in docs/INHERITANCE.md covering: stack and pinned dependencies; data model (every table or collection, one line each); document ingestion and parsing path; how LLM calls are built, prompted, retried, validated and logged; where extracted values are stored and whether anything downstream treats model output as truth without a human step; review or approval UI if any; what the tests actually assert; auth, tenancy and audit handling; deployment config.
3. From tariff-oder, list the reliability patterns specifically: schema validation, confidence scoring, evidence linkage, chunking strategy, retry and fallback, eval harness. Rate each keep / adapt / discard with one line of reasoning and a file path.
4. From FDRE, list the tender domain concepts: entity types, field lists, lifecycle states, handling of corrigenda and amendments, bid parameters, anything tender-type specific. Rate each the same way.
5. List the flaws you would not carry forward in either repo, with file references. Be specific. Typical things to look for: LLM output written straight to a primary table, prompts embedded in code without versioning, missing page references on extracted values, tests that only check the happy path, synchronous LLM calls inside request handlers, global state.
6. End with a table: candidate shared-core modules vs tender-domain modules, with the source repo and file for anything you intend to copy.
7. Compare what you found against the locked decisions table in CLAUDE.md. If the tariff repo's stack differs, say so and recommend whether to follow it or the table; do not silently pick one.
8. Commit docs/INHERITANCE.md, write STAGE-0A-REPORT.md and STOP. Wait for the word "proceed".

## Part B: scaffold (after "proceed")

1. Lay out the monorepo in /work/tender_engine: core/, tender/, api/, worker/, web/, infra/, evals/, docs/. CLAUDE.md already holds sections 2 to 5 of docs/MASTER-PROMPT.md; re-read it now. Create docs/ARCHITECTURE.md and the tests watcher service in this step, before any application code.
2. docker-compose.yml with api (FastAPI, uvicorn), worker (same image, different command), web (Vite dev server for now), db (postgres:16), caddy (reverse proxy on 443 to web and /api to api, TLS with Caddy's internal CA on the static IP; note in KNOWN-GAPS.md that reviewers will see a certificate warning once and how to switch to a domain + Let's Encrypt later). One shared volume at /data.
3. Alembic initialised. A base model mixin with tenant_id, created_at, created_by. A health endpoint. A single tenant row seeded as 'ergplan'.
4. pytest with a database fixture that spins a throwaway schema per test session. One passing test for the health endpoint. A Makefile with make up, make down, make test, make migrate, make logs, make deploy (pull, build, migrate, restart, health check). A GitHub Actions workflow that runs make test on push.
5. Ask the user where the 11 tender PDFs are (a GCS bucket, a Drive link, or they will scp them to /work/tenders/). Fetch or wait for them. Arrange them as /work/tenders/<tender_type>/<slug>/ with a manifest.yaml per tender: type, issuing agency, filename, page count, any corrigenda files. If some are missing, continue with what is there and list the gaps.
6. core/llm/client.py: one function to call Claude Fable 5.1 with typed Pydantic input and output, prompt version, retries with backoff, and a row written to llm_call_log for every call. One test that mocks the API and asserts the log row. One real smoke call that proves the key works, logged, not in the test suite.
7. make deploy on the VM; confirm https://<static-ip>/health answers from an allowed IP. Push to Ergplan/tender_engine. Write STAGE-0B-REPORT.md and STOP.
```

## Stage 1 prompt: shared document intelligence core

Two days. Nothing tender-specific lives in `core/`; it must work for a tariff order or a contract with a different schema plugged in.

```markdown
# STAGE 1: shared document intelligence core (core/)

Build core/ as a domain-agnostic library plus its API endpoints. A "schema" is a Pydantic model describing the fields to extract; core/ knows nothing about tenders. Re-read the invariants in CLAUDE.md before starting.

## Data model (Alembic migration 0002)

- document: id, tenant_id, sha256, filename, mime, page_count, storage_path, status (uploaded/parsed/failed), created_by.
- page: document_id, page_no, text, width, height, render_path (PNG at 150 dpi), char_boxes (jsonb list of {char, x0, y0, x1, y1}).
- section: document_id, start_page, end_page, heading, kind (free text), confidence. Produced by the section mapper.
- extraction_run: id, document_id, schema_name, schema_version, prompt_version, model, status, started_at, finished_at, token_in, token_out, cost_usd.
- candidate: id, extraction_run_id, field_path, value (jsonb), value_type, confidence (0-1), rationale (short text), status (raw/validated/needs_review/superseded). Immutable after insert.
- evidence_span: candidate_id, document_id, page_no, bbox (x0,y0,x1,y1 in page units) nullable, char_start, char_end nullable, quote (text). At least one per candidate, enforced in the service layer and by a test.
- validation_result: candidate_id, rule_name, passed, message.
- approval: id, candidate_id, field_path, final_value (jsonb), decision (approved/edited/not_in_document/rejected), reviewer, note, decided_at. One per field per review; a later approval supersedes the earlier one and the earlier is marked superseded.
- canonical_fact: id, tenant_id, object_type, object_id, object_version, field_path, value (jsonb), value_type, approval_id, evidence refs copied from the candidate, effective_at. Written only by ApprovalService.approve().
- feedback: approval_id, field_path, candidate_value, final_value, delta_kind (exact/format/wrong_value/missing/extra), reviewer, prompt_version, created_at.
- audit_log: tenant_id, actor, action, table_name, row_id, before (jsonb), after (jsonb), at.
- llm_call_log from Stage 0, add extraction_run_id.
- job: id, kind, payload, status, attempts, last_error, run_after. The worker polls this table.

## Services (core/services/)

- IngestService.upload(file) -> document. Dedupes on sha256. Enqueues parse.
- ParseService.parse(document): pdfplumber for text and char boxes per page, pymupdf for renders. Stores page rows. Falls back to rendering the page image for Claude when a page has fewer than 50 extractable characters (scanned pages). Marks document parsed.
- SectionMapper.map(document): one Fable 5.1 call over the page texts (first 400 characters of each page plus any detected headings) returning a list of sections with page ranges. Stored as section rows. This is the only full-document LLM pass; everything else works on sections.
- ExtractService.extract(document, schema, prompt_version): for each schema field group, choose the sections the group's routing hints name, build a request with the native PDF pages for those sections (cap 40 pages per call, split if larger), call Fable 5.1 with a structured-output schema that REQUIRES for every field: value, confidence, rationale, and evidence as a list of {page_no, quote}. Resolve each quote to char offsets and a bbox by fuzzy-matching against page.char_boxes (rapidfuzz, threshold 85). A field whose quote cannot be located on the stated page gets a second attempt on adjacent pages; if still unresolved, the candidate is stored with confidence capped at 0.3 and a validation failure "evidence_not_located". Insert candidates and evidence_spans. Never update a candidate.
- ValidationService.validate(extraction_run): runs type coercion, required-field presence, per-field range rules and cross-field rules registered by the schema. Writes validation_result rows and sets candidate.status. Pure Python, no LLM, fully unit-tested.
- ApprovalService.approve(candidate_id, decision, final_value, reviewer, note): the only writer to canonical_fact. Validates final_value against the field type. Writes approval, canonical_fact, feedback (when final_value differs from candidate value, classify delta_kind by simple rules), audit_log. Idempotent on a repeated identical call.
- ReviewStateService.for_object(object_type, object_id): returns every field with its best candidate, its validation results, its approval if any, and its evidence; this is the one read model the UI uses.

## Prompts (core/llm/prompts/)

- section_map/v1.md and extract/v1.md as files, with a short header block: purpose, inputs, output schema name, known failure modes. The extract prompt must instruct the model to quote evidence verbatim from the page, to prefer the specific clause over the summary table when they disagree and flag the disagreement in rationale, and to return null with confidence 0 rather than guess.
- A prompt registry that loads by name and version and refuses to run an unregistered version.

## API (api/v1/core/)

- POST /documents (multipart) ; GET /documents/{id} ; GET /documents/{id}/pages/{n}/render ; GET /documents/{id}/sections
- POST /documents/{id}/extract {schema_name, schema_version, prompt_version} -> extraction_run ; GET /extraction-runs/{id}
- GET /review-state?object_type=&object_id=
- POST /approvals {candidate_id, decision, final_value, note} ; reviewer comes from the X-Reviewer header in phase 1 (set by the token middleware in Stage 3)
- GET /canonical?object_type=&object_id=&version=
- All endpoints filter by tenant_id taken from a request dependency; phase 1 resolves it to 'ergplan'.

## Worker (worker/)

- Polls job every 2 seconds, runs parse, section_map, extract, validate as a chain, records failures with the traceback in job.last_error, retries 3 times with backoff. A single process; no concurrency tricks.

## Tests

- Unit: every validation rule; evidence resolution on a synthetic page; ApprovalService writes exactly one canonical_fact and one audit row; a second identical approve() call writes nothing; candidate rows cannot be updated (DB trigger or ORM guard, tested).
- Integration: upload -> parse -> extract (mocked LLM returning a fixture) -> validate -> approve -> canonical, through the HTTP API.
- End to end (marked slow, run manually): the real FDRE tender in /work/tenders/, a 12-field test schema (tender number, issuing agency, capacity MW, bid deadline, pre-bid date, EMD per MW, PBG per MW, SCOD months, PPA tenure, tariff ceiling, min CUF, connectivity type). Assert every candidate has located evidence; print per-field value, confidence and page for the user to eyeball in the report.

## Done when

- make test is green, the e2e run has been executed once and its output pasted into STAGE-1-REPORT.md, docker compose up serves the API on the VM, and KNOWN-GAPS.md lists any field where evidence could not be located. STOP.
```

## Stage 2 prompt: tender domain layer

One day. Section 13 (the field catalogue) is read from the master prompt file with this prompt.

```markdown
# STAGE 2: tender domain layer (tender/)

Build tender/ on top of core/. Nothing in core/ changes except through a documented extension point; if you need one, add it to core/ with a test and note it in DECISIONS.md.

## Data model (migration 0005; 0003 and 0004 were used by Stage 1)

- tender: id, tenant_id, tender_type (enum: fdre, solar, wind, hybrid, bess, transmission, generation, epc, ipp), issuing_agency, external_ref (RfS number), title, status (ingested/extracted/in_review/reviewed/published), current_version_id.
- tender_version: tender_id, version_no, kind (original/corrigendum/amendment/clarification), document_id, issued_on, summary_of_change (text, human-written or approved), supersedes_version_id.
- tender_field_def: generated from the schema YAML at startup for introspection, not hand-edited: tender_type, field_path, section, label, value_type, required, help_text, review_order.
- Canonical facts for tenders use object_type='tender', object_id=tender.id, object_version=tender_version.version_no.

## Schemas (tender/domain_packs/, see "Field namespace and domain packs" below)

- One YAML per tender type: common.yaml plus fdre.yaml, solar.yaml, wind.yaml, hybrid.yaml, bess.yaml, transmission.yaml, generation.yaml, epc.yaml, ipp.yaml. Each type file lists the common sections it includes and its own additional fields. Seed every file from the field catalogue in the master prompt; do not add fields the catalogue does not name.
- Each field: path, label, section, value_type (text, long_text, int, decimal, money_inr, percent, date, duration_months, enum[...], list_of[text], mw, mwh, kv, km), unit, required, help_text (one line a reviewer sees on hover), routing_hints (list of section kinds and keywords the extractor uses to pick pages), validation (range, regex, cross-field rule names), review_order.
- A loader that compiles YAML into Pydantic models and registers them with core/ as schemas named tender.<type> v1. A test that every YAML loads and every field has a section and a value_type.
- Amounts stated as a formula. Where a tender states EMD or PBG as a formula (per MW by component, or a percentage of project cost) rather than one figure, the schema holds the formula text in a dedicated field (for example core.guarantees.emd_formula) alongside the computed value field (core.guarantees.emd_per_mw_inr). The computed value is filled only where the tender itself states one; it is never derived by the model. Each of the two fields carries its own evidence.
- Dates deferred to another document. Where the RfS defers a date to the NIT or to a later notification ("As per NIT on ISN-ETS portal"), the date field is null with a deferral note naming the document that will set it, with evidence for the deferral. Never a guessed date. The date is filled when that document is ingested as part of the tender version.

## Extraction prompts (tender/domain_packs/<pack>/prompts/)

- One extract prompt per section group, not per field, so related fields share context: identity_and_scope, key_dates, eligibility, guarantees, commercial, penalties, connectivity_and_compliance, documents, and one per type-specific group (fdre_profile, bess_performance, transmission_elements, epc_scope, ipp_model_inputs, and so on). Each inherits the core extract prompt and adds domain guidance: Indian RE tender vocabulary, how SECI/NTPC/NHPC/SJVN/state agencies phrase the same thing differently, that corrigenda override the base RfS, that a per-MW figure may be stated in lakh or crore, that "months from Effective Date" and "months from PPA signing" are different fields.
- A summary prompt that writes the four-line plain-English summary (what, how much, where, by when) with page evidence for each sentence. It is reviewed like any other field.

## Validators (tender/domain_packs/<pack>/validation/)

- Date order: nit_date <= pre_bid_date <= query_deadline <= bid_deadline <= technical_opening; scod_months > 0; ppa_tenure_years in [10, 35].
- Money sanity: emd_per_mw and pbg_per_mw positive and within 10x of each other; tariff_ceiling in INR/kWh between 1 and 15.
- Capacity: min_bid_mw <= max_bid_mw <= total_capacity_mw.
- Type rules: fdre requires demand_profile and availability_penalty; bess requires mwh and cycles_per_day; transmission requires at least one element with kv; hybrid requires min_share_per_resource.
- Corrigendum rule: a field changed by a later version must carry evidence from that version's document, not the original.

## Versioning

- TenderService.add_version(tender, document, kind, issued_on): creates tender_version, runs extraction only for sections the corrigendum touches (section mapper on the corrigendum, matched against the base), produces candidates attached to the new version. Fields the corrigendum does not mention carry forward their canonical facts untouched.
- TenderService.current_view(tender): per field, the canonical value from the latest version that set it, with version_no and kind shown.

## API (api/v1/tenders/)

- POST /tenders {type, agency, external_ref, title} ; POST /tenders/{id}/versions (multipart: file, kind, issued_on) ; GET /tenders ; GET /tenders/{id} ; GET /tenders/{id}/view ; GET /tenders/{id}/versions ; POST /tenders/{id}/extract ; GET /tenders/{id}/review-state (delegates to core)
- GET /schemas/tender/{type} returns the compiled field list for the UI.

## Run

- Ingest all 11 tenders from /work/tenders/ via a management command, including any corrigenda as versions. Run extraction on all of them. Produce EXTRACTION-SUMMARY.md: per tender, fields extracted, evidence-location rate and answer rate (section 14), fields failing validation, total tokens and cost.

## Tests

- Every validator unit-tested with passing and failing cases. Schema loading. Corrigendum carry-forward: a version that changes bid_deadline leaves emd_per_mw's canonical fact and evidence unchanged. API contract tests for every endpoint.

## Done when

- All 11 tenders are ingested and extracted, EXTRACTION-SUMMARY.md is written, tests green, STAGE-2-REPORT.md gives the evidence-location rate and the answer rate by tender type and lists the fields whose evidence-location rate is under 95%. STOP.

## Field namespace and domain packs

Field paths carry their origin. Universal fields are core.<section>.<field>; sector fields are sector.<domain>.<subdomain>.<field>.

- core.identity.tender_number, core.key_dates.bid_submission_deadline, core.eligibility.technical_experience_requirement, core.guarantees.emd_per_mw_inr, core.commercial.payment_security_mechanism, core.penalties.delay_ld_per_mw_per_day_inr, core.documents.required_documents
- sector.power.fdre.demand_profile, sector.power.bess.capacity_mwh, sector.power.transmission.elements, sector.power.epc.scope_matrix, sector.power.ipp.cuf_floor_percent
- A core field keeps its meaning in any sector. Anything whose meaning depends on the industry is a sector field even when its name looks generic: experience thresholds such as min_commissioned_mw are sector.power.*, while the experience clause itself stays core.

Schemas live under tender/domain_packs/:

tender/domain_packs/
├── core/            # common.yaml, shared validators, section-group prompts
└── power/
    ├── pack.yaml    # name, version, sector, subdomains, section groups it adds
    ├── solar.yaml  wind.yaml  hybrid.yaml  fdre.yaml  bess.yaml
    ├── transmission.yaml  generation.yaml  epc.yaml  ipp.yaml
    ├── prompts/     # section-group extract prompts for this pack
    ├── validation/  # rules whose meaning is sector-specific
    └── tests/

Rules:

- One tender resolves to exactly one type, and one type names exactly one pack. Runtime composition of several packs over one tender is out of scope: overlapping fields would make per-field accuracy ambiguous, which is the number this programme exists to produce. Types that genuinely combine (solar paired with BESS under an EPC contract) get their own YAML inheriting from both at load time, resolved and frozen when the schema compiles, with any conflict raised as an error rather than silently resolved.
- A pack is data plus prompts plus tests. Adding a sector must not require a change in core/. If it does, that is a defect in core/, fixed there, with a note in DECISIONS.md.
- tender_field_def carries namespace (core or sector), domain and subdomain alongside the existing columns, so the API and FIELD-TRACE can group by them.
- The financial model takes a model type: model_tender(tender_id, model_type), with power_project_finance the only implementation. Other model types (epc_contract_cashflow, supply_contract_margin, o&m_contract_economics) are named in ARCHITECTURE.md as future work and not built.

Record in ARCHITECTURE.md as the intended path, not built now: a second sector pack, automatic sector classification at ingestion, multi-pack composition, and packs as separately licensed products. The second sector is added when power is at measured reliability and a customer is attached to it, as a test of whether core/ truly generalises.
```

## Stage 3 prompt: reviewer UI

One day. The reviewer is a domain expert, not a software user. Every design choice favours speed of reading and confidence in the evidence over features.

```markdown
# STAGE 3: reviewer UI (web/) and review tokens

## Tokens (api/)

- review_token: token (32 random url-safe chars), tender_id, reviewer_name, created_at, expires_at (30 days), completed_at. One active token per tender; creating a second revokes the first.
- POST /review-tokens {tender_id, reviewer_name} -> {url}. The URL is https://<host>/review/<token>. A management command prints the URL so the user can send it by WhatsApp or email.
- Middleware: any request under /review/<token> or carrying X-Review-Token resolves the token, sets request.reviewer = reviewer_name and request.tender_id, and rejects expired, revoked or completed tokens with a plain-language page. No other identity mechanism exists in phase 1.

## Layout (web/src/review/)

- Full-height two-pane layout. Left pane 44% width: the extracted data. Right pane 56%: the PDF. Divider draggable. Header shows tender title, type, agency, reviewer name, progress "37 of 92 fields decided", and a Complete review button that stays disabled until every required field has a decision.
- Left pane: sections in review_order (Summary, Identity and scope, Key dates, Eligibility, Guarantees, Commercial, Penalties, Connectivity and compliance, Documents, then the type-specific sections). Each section collapsible with a count of decided/total. Each field is a card: label, help text on hover, candidate value formatted by value_type (dates as 12 Mar 2026, money as ₹ 25 lakh/MW, percent with one decimal), confidence as a small coloured pill (green >= 0.8, amber 0.5 to 0.8, red < 0.5), validation failures as a one-line red note under the value, and an Evidence row: "p. 47" chips, one per evidence span.
- Right pane: pdf.js viewer with continuous scroll, page thumbnails in a collapsible strip, text search, a bookmark list built from the section map (so a reviewer can jump to Annexure or Corrigendum), and a highlight overlay layer. Clicking an evidence chip scrolls the PDF to that page, draws a translucent highlight over the bbox (or over the matched line when only char offsets exist), and briefly pulses it. The current field's evidence stays highlighted until another field is focused.
- When a tender has more than one version, a version switcher in the right pane header lists them; selecting a version loads its document. A field whose candidate comes from a corrigendum shows a small "v2 corrigendum" tag.

## Actions

- Three buttons per field: Approve, Edit, Not in document. Edit opens an inline input typed to value_type (date picker for dates, numeric with unit suffix for money and capacity, dropdown for enums, textarea for long text), with Save and Cancel. A fourth, smaller action: Flag with a note, for "unsure, come back", which does not count as decided.
- Keyboard: Enter approves the focused field and moves to the next undecided field; E opens edit; N marks not in document; F flags; J and K move focus down and up; Escape cancels an edit. Keyboard focus always scrolls the PDF to the focused field's first evidence.
- Every action calls POST /approvals immediately; no local draft state that can be lost. The card shows a saved tick or a red retry on failure. Version-checked: the request carries the candidate_id and the previous approval_id if any; the server rejects a stale write and the UI reloads the field.
- Narrative fields (summary sentences, eligibility clauses) are edited as text; their evidence chips may point to several pages.
- No bulk approve, no section approve-all, no auto-advance on a timer. Explicitly out of scope for phase 1.
- Complete review: confirms, writes completed_at on the token, sets tender.status = reviewed, snapshots the current view to tender_review_snapshot (jsonb) for the gold set, and shows a read-only summary page with a Download JSON button.

## Reviewer home

- /review/<token> opens straight into the tender; there is no list page in phase 1. An optional /review/<token>/summary shows the read-only view after completion.

## Quality bar

- First meaningful paint under 2 seconds on the VM over the allowlisted connection; PDF first page visible under 3 seconds for a 400-page tender (lazy page rendering, renders served from /data by Caddy with caching).
- Works in current Chrome and Edge on a 1366x768 laptop without horizontal scrolling. Phone layout is out of scope.

## Tests

- Playwright: open a token URL, approve a field with Enter, edit a date field, mark a field not in document, click an evidence chip and assert the PDF page changed and a highlight element exists, complete the review and assert the snapshot endpoint returns the final values. API tests for token lifecycle and stale-write rejection.

## Done when

- The user opens a token URL for one real tender on the VM and completes a full review without needing instructions from you. Record how long it took and which fields they edited in STAGE-3-REPORT.md. STOP.
```

## Stage 4 prompt: human reliability program

Days 6 and 7, then it keeps running as reviews complete. The output of this stage is a number per field per tender type, and the evidence for whether that number is stable.

```markdown
# STAGE 4: gold set, per-field accuracy, feedback loop, reliability report (evals/)

## Gold set

- A completed review snapshot becomes a gold record: evals/gold/<tender_type>/<tender_slug>.yaml with, per field: final_value, decision, evidence pages, reviewer, decided_at, and the candidate it was judged against (value, confidence, prompt_version). Written by a command `make gold TENDER=<id>` after the user confirms the review is trustworthy; not automatic on completion.
- A gold record is versioned with the tender version it was reviewed against.
- A field the document does not state is recorded with final_value null and decision not_in_document. A candidate that returned null for it is a correct answer and is scored as one.

## Scoring (evals/runner.py)

- Scores an extraction_run against a gold record field by field. Match rules by value_type: exact for enums and ints; date equality; decimals and money within 0.5%; text by normalised exact match, with a secondary fuzzy score (token sort ratio) reported but not counted as correct; long_text scored manually only, listed as "needs human judgement".
- Also scores evidence: did the candidate cite a page the reviewer accepted? Report value accuracy and evidence accuracy separately; a right value from the wrong page is a reliability problem.
- Outputs evals/results/<run_id>.json and a markdown table: per field, per tender type, accuracy, n, and the list of misses with candidate vs gold.
- `make eval` re-scores every gold record against the latest extraction_run for its tender; `make eval PROMPT=extract/v2` runs a fresh extraction with that prompt version on every gold tender and scores it, so a prompt change is measured before it becomes the default.

## Feedback analysis (evals/feedback_report.py)

- Reads the feedback table and groups deltas by field_path, delta_kind, tender_type, issuing_agency and prompt_version. Writes FEEDBACK-REPORT.md: the ten fields with the most corrections, example candidate/final pairs for each, and a suggested prompt or validator change in one line. The suggestions are for the user to act on; nothing is applied automatically.

## Dashboard

- /admin/reliability (behind the same IP allowlist, no login): a table of tender type x field with accuracy and n, colour-banded; a per-tender list with review status, reviewer, duration, fields edited; a prompt-version comparison when more than one has been evaluated. Served from the API, rendered in web/.

## Reliability report

- `make report` writes RELIABILITY-REPORT.md: tenders reviewed by type; overall and per-section accuracy; value vs evidence accuracy; fields below 90% with analysis of why (vocabulary variance across agencies, table vs clause conflict, corrigendum handling, scanned pages); prompt versions tried and their effect; reviewer time per tender; a recommendation per field group: stable / needs prompt work / needs validator / needs schema change. Regenerated on every new gold record.
- Stability definition for the go/no-go into Stage 5: at least 2 reviewed tenders per type for the types with 2 or more tenders in the set, value accuracy >= 90% on required fields across the last two prompt versions, and no required field below 75%.

## Operating the review phase

- Create review tokens for all 11 tenders and print the URL list for the user. As each review completes, run make gold after the user confirms, then make eval and make report. Keep a REVIEW-LOG.md: tender, reviewer, started, completed, fields edited, notable misses.
- Prompt revisions during this phase go in as new versions (extract/v2, v3) and are evaluated with make eval before becoming the default in config. Record each promotion in DECISIONS.md with the before and after accuracy.

## Tests

- Runner unit tests for every match rule, including the 0.5% money tolerance and date parsing of Indian formats (12/03/2026, 12-Mar-2026, 12th March 2026). Feedback report on a fixture table. Report generation on two fixture gold records.

## Done when

- The dashboard and report exist and reflect at least two completed reviews; the user has the URL list for all 11; STAGE-4-REPORT.md states the current accuracy and how far it is from the stability bar. STOP. Stage 5 waits for the bar to be met.
```

## Stage 5 (after the 11-tender review): independent agent, three-way comparison, production

Not part of the week. Starts only when the stability bar in Stage 4 is met. Split into four sessions (5A, 5B, 5C, 5D); each stops.

```markdown
# STAGE 5A: independent agent pass (agent/)

- Build agent/ as a separate container using the OpenAI Agents SDK on the current GPT model. It receives: the tender type, the compiled field schema, and the raw page renders plus page text for the sections the section map names. It does NOT receive the engine's candidates, the gold values, or the reviewer's decisions.
- The agent has three tools: read_pages(page_nos), search_text(query), and submit_finding(field_path, value, confidence, evidence pages and quotes). It must call read_pages before any submit_finding for a field, and the harness rejects findings whose quotes are not found on the cited page, same rule as core.
- Results land in agent_finding, a separate table, never in candidate or canonical_fact.
- POST /tenders/{id}/agent-pass runs it; GET /tenders/{id}/agent-pass/{run_id} returns findings.

# STAGE 5B: three-way comparison (evals/threeway.py)

- For every gold tender: human (gold), engine (candidate), agent (agent_finding) per field. Classify each field into: all agree; engine right agent wrong; agent right engine wrong; both wrong same way; both wrong differently; both abstained. Report by field, tender type and agency.
- Error pattern analysis written to THREEWAY-REPORT.md: where both models fail the same way, the schema or the document is the problem (ambiguous clause, table/clause conflict); where they disagree, the field is a candidate for mandatory second-pass in production; where the agent catches engine misses, promote the agent's evidence strategy into the extract prompt and re-evaluate.
- Production confidence rule, written into config and the report: a field is "auto-surface with low-review" only if human-engine-agent agreement >= 97% over at least 15 gold instances; otherwise it stays full review. Still no auto-approval: this only changes the UI's default emphasis, never the truth pipeline.

# STAGE 5C: production hardening

- Auth: OIDC login (Google Workspace first), roles reviewer/approver/admin/api_client, API keys for the intelligence product. Review tokens stay for external one-off reviewers but now require a logged-in admin to mint them.
- Tenant isolation: Postgres row-level security policies on every table keyed by tenant_id, set from the session; a test that a cross-tenant read returns zero rows even with a bug in the service layer.
- Deployment: split api, worker, agent and web into Cloud Run services; Cloud SQL; GCS via the existing storage interface; Secret Manager; Cloud Armor allowlist replacing the VM firewall. docker compose stays for local dev.
- Client-facing output: a published tender view (GET /tenders/{id}/published) that exposes only canonical facts with their evidence pages, a PDF export with a page-reference appendix, and a changelog across versions. Everything published shows its review date and reviewer role, never the raw candidate.
- Two products from one core: Product A, the enterprise front end, is web/ with auth and multi-tenant admin. Product B, the intelligence API, is the same api/ with API-key auth, rate limits, usage metering per tenant and OpenAPI docs. Neither has code the other lacks; they differ in deployment config and which routes are exposed.

# STAGE 5D: public library tier and MCP widgets

(Added 2026-10-04. This file held no Stage 5D text before that date; the two sub-sections below are the whole of Stage 5D as given so far. The MCP server itself and the base definitions of search_tenders, get_tender, get_field, get_document_page, list_changes, compare_tenders and reliability_report are referred to here but not yet specified in this file.)

## Public library tier (free, read-only)

Build it as an ordinary tenant with a special authorization policy, not as a special case in the code.

### Tenant and principals

- A reserved tenant `public` holds the reviewed central tenders: SECI, NTPC, NHPC, RECPDCL and others as the library grows. Same rows, same truth pipeline, same review requirement.
- A principal carries own_tenant and read_tenants (its own plus public). A free account is a tenant with no tenders of its own and read access to public.
- No end-user principal may write to public under any role. Only reviewer and ingestion service accounts write there, and a test asserts a user principal's write to public is denied at the database, not only in the service layer.
- Sign-up creates a free user and tenant. MCP clients authenticate through OAuth and receive scoped access tokens granting read-only access to public. Server-to-server API credentials are issued separately in the enterprise product, never at free sign-up.
- Usage is attributed to the calling tenant, never the resource tenant, otherwise free-tier limits are unenforceable. Each call records actor_tenant_id, resource_tenant_id, user_id, tool, tier, tokens or compute, and timestamp.

### Tiers

- Free: search_tenders, get_tender, get_field, get_document_page, find_matching_tender, list_changes, compare_tenders, reliability_report, over public only, at a lower rate limit with a daily call cap and no bulk export.
- Paid: their own tenants' tenders, model_tender, save_model_assumptions, my_watchlist, and the enterprise front end.
- Every public response carries the same provenance and reliability block as a paid one.

### Publication state machine

A public tender carries a publication state, independent of review state:

- published — current version reviewed, field groups meet the stability bar, visible to search_tenders.
- update_pending — a later version exists but is not yet reviewed. The tender stays visible, every response carries a banner naming the unreviewed version and its issue date, and fields the amendment may touch are marked possibly superseded.
- publication_suspended — the unreviewed amendment touches critical fields (bid deadline, capacity, EMD or PBG, tariff ceiling, SCOD, eligibility thresholds). The tender leaves search_tenders and direct lookups return the suspension and the amending document, not the stale values.
- On approval of the new version a new snapshot publishes and the state returns to published.
- A corrigendum's arrival is detected at ingestion; which fields it may touch comes from the section map of the amending document matched against the base, the same mechanism Stage 2 uses for versioning.

### Corrections and takedown

- POST /v1/public/corrections accepts a field path, the claimed error and the claimant's reasoning, from any authenticated user or a public form. It creates a correction case, never changes a value.
- A correction case queues the field for re-review. If the reviewer agrees, the new approval supersedes the old one through the normal pipeline and the change is visible in list_changes with its date and reason.
- An agency or rights-holder takedown request suspends publication of that tender within one business day and is recorded in docs/KNOWN-GAPS.md and the audit log.
- Every public response states that the tender document is the authoritative source and jouleWise's record is a reviewed reading of it.

## Widgets (MCP Apps extension)

MCP Apps is a ratified MCP extension (standardized 2026-01-26): a tool declares a ui:// HTML resource through _meta.ui.resourceUri, the host renders it in a sandboxed iframe, and the iframe talks back over postMessage. Build four widgets in mcp/widgets/, bundled to single self-contained HTML files.

### Implementation requirements

- Resources served with mimeType: text/html;profile=mcp-app.
- The server declares the extension capability io.modelcontextprotocol/ui.
- Hosts without MCP Apps support fall back to the structured text result, so every tool must remain complete and readable with no widget at all. A test asserts this.
- Widgets are self-contained: no external domains declared, none called, matching the spec's restrictive CSP model. Anything further comes through a bridge tool call.

### Rules

- A widget renders only what its tool returned. No fetches to other hosts, no analytics, no hidden calls.
- Empty states are designed before the happy path. A not_reviewed field renders as a visibly marked gap with the reason and a link to the likely page, never as a blank cell, a dash, or a zero.
- Every value shows its page chip. Clicking it calls get_document_page and shows the page image with the quote highlighted.
- The reliability block (accuracy, n, as_of) appears in the widget footer, not only in the raw result.
- Light and dark themes, readable at the narrow width of a chat column, usable on mobile.

### The four widgets

1. tender_card — returned by get_tender. Approved fields grouped by section, collapsible, each with value, unit, page chip and a version tag where a corrigendum set it. Header: title, agency, type, capacity, bid deadline with days remaining, and the publication state banner when not published. Footer: review date, reviewer role, reliability block.
2. financial_model — returned by model_tender. Two visually separate panels. Left: parameters the tender fixes (tariff ceiling, CUF floor and ceiling, SCOD, PPA tenure, degradation cap, PBG cost and duration, ISTS waiver status, payment security), locked, each with its page chip. Right: the user's assumptions (capex per MW, O&M per MW-year and escalation, debt share, interest, tenor, tax rate, auxiliary consumption), editable, defaults clearly marked "assumed, not from the tender". Output: project IRR, equity IRR, levelised cost, payback, cashflow chart, labelled indicative.
3. changes_view — returned by list_changes. A version timeline; selecting a version lists the fields it changed, old to new, each with evidence from the amending document. Untouched fields are not listed.
4. comparison_table — returned by compare_tenders. Tenders as columns, field paths as rows, provenance on each cell, not_reviewed cells visibly marked. Sortable, exportable as CSV from the widget's own copy of the data.

### One financial engine

The widget is never the authoritative calculator. A single deterministic engine in core/ or tender/ serves the MCP widget, the enterprise front end and the API alike.

- The server is authoritative. The widget may compute a provisional figure for immediate feedback as a slider moves, shown as provisional, replaced by the server result when the debounced bridge call returns.
- Anything exported, saved, quoted or shown as final comes only from the server result.
- A test asserts widget and server agree within a rounding tolerance across a fixture set of assumption combinations. Divergence is a bug in the widget, never a reason to change the server.
- Read and write are separate tools: model_tender computes and returns, save_model_assumptions persists. No analytical tool silently changes state.
- Assumptions live in model_assumption, per user and tender. They are never canonical facts and never appear in get_tender, compare_tenders or the published view.

### Additional tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| find_matching_tender | title_or_number (text), agency?, capacity_mw? | the reviewed tender matching a document the user is holding, or no_match with up to three candidates |
| model_tender | tender_id, model_type, assumptions? | tender-fixed parameters with provenance, saved assumptions, computed figures from the server engine; renders financial_model. Read-only. |
| save_model_assumptions | tender_id, assumptions | persists the user's assumptions; returns what was saved |
| my_watchlist | add? / remove? (tender_ids), list? | followed tenders with bid deadlines and days remaining; drives an email digest from the enterprise product |

find_matching_tender never ingests or extracts from the user's document; it matches against the library only. A false match is worse than no match, because the user is holding the document and will assume the match is right. It normalises agency aliases, RfS and RFP numbering, Roman versus Arabic numerals (IX and 9), MW and MWh, tranche names and capacity ranges, and scores candidates. Below the confidence threshold it returns no_match with up to three candidates and their distinguishing attributes, never the nearest tender silently.

### Tests

- Each widget renders from a fixture tool result, every fixture containing at least one not_reviewed field.
- A widget bundle makes no outbound request to any host other than the bridge.
- Fallback: the same tool result with widgets disabled is a complete answer.
- Widget and server financial figures agree within tolerance on the fixture set.
- find_matching_tender: informal phrasings ("the 4800 FDRE one", "SECI BESS tender", "FDRE IX") resolve correctly; near-misses return no_match with candidates rather than a wrong match.
```

## Field catalogue (seed for tender/domain_packs/)

Stage 2 reads this section from the master prompt file. Field paths are snake\_case under their section; Stage 2 writes them into the schemas under the `core.*` and `sector.power.*` namespaces ("Field namespace and domain packs" in the Stage 2 prompt), so `key_dates.bid_submission_deadline` here becomes `core.key_dates.bid_submission_deadline` there. Mark a field required only if a reviewer would refuse to call the review complete without it.

**Common to every tender type**

| Section | Fields |
| --- | --- |
| summary | plain\_english\_summary (long\_text, 4 sentences: what, how much, where, by when) |
| identity | tender\_number, issuing\_agency, title, procurement\_mode (enum: single\_stage\_two\_envelope, two\_stage, e\_reverse\_auction, other), portal, tender\_type\_as\_stated |
| scope | total\_capacity\_mw, total\_capacity\_mwh, min\_bid\_mw, max\_bid\_mw, max\_projects\_per\_bidder, location\_constraint (enum: ists\_anywhere, state\_specific, named\_substation, named\_site), named\_states\_or\_sites (list), delivery\_point, metering\_point |
| key\_dates | nit\_date, pre\_bid\_meeting\_date, query\_deadline, bid\_submission\_deadline, technical\_opening\_date, era\_date, bid\_validity\_days, loa\_timeline, ppa\_signing\_window\_days, financial\_closure\_months, scod\_months, scod\_reference (enum: effective\_date, ppa\_signing, loa), ppa\_tenure\_years |
| eligibility | technical\_experience\_requirement (long\_text), min\_commissioned\_mw, under\_construction\_counts (bool), net\_worth\_per\_mw\_inr, turnover\_requirement\_inr, liquidity\_requirement\_inr, consortium\_allowed (bool), max\_consortium\_members, parent\_affiliate\_credentials\_allowed (bool), shareholding\_lock\_in (long\_text) |
| guarantees | emd\_per\_mw\_inr, emd\_form (enum: bg, insurance\_surety, cash, other), pbg\_per\_mw\_inr, pbg\_schedule (long\_text), success\_charge\_inr, processing\_fee\_inr, bg\_validity\_months, bg\_release\_conditions (long\_text) |
| commercial | tariff\_ceiling\_inr\_per\_kwh, tariff\_structure (enum: fixed, escalating, two\_part, capacity\_charge), payment\_security\_mechanism (long\_text), change\_in\_law\_clause (long\_text), deemed\_generation\_clause (long\_text), late\_payment\_surcharge, termination\_compensation (long\_text), offtaker |
| penalties | delay\_ld\_per\_mw\_per\_day\_inr, max\_scod\_extension\_months, shortfall\_penalty\_basis (long\_text), pbg\_encashment\_triggers (long\_text), termination\_delay\_months |
| connectivity | connectivity\_responsibility (enum: developer, procurer, shared), gna\_requirement (long\_text), ists\_waiver\_cutoff\_date, line\_to\_pooling\_station\_responsibility, almm\_required (bool), dcr\_required (bool), local\_content\_rule (long\_text), land\_responsibility, clearances\_responsibility |
| documents | required\_documents (list), annexure\_formats (list), draft\_agreements\_referenced (list) |

**Type-specific additions**

| Tender type | Section | Fields |
| --- | --- | --- |
| solar | solar\_tech | almm\_list\_requirement, dcr\_share\_percent, min\_cuf\_percent, max\_cuf\_percent, annual\_degradation\_cap\_percent, land\_type\_restrictions, repowering\_allowed (bool), augmentation\_rules |
| wind | wind\_tech | rlmm\_requirement, min\_cuf\_percent, resource\_data\_obligation, hub\_height\_or\_tech\_restrictions, site\_transmission\_constraints |
| hybrid | hybrid\_mix | min\_share\_per\_resource\_percent, combined\_cuf\_floor\_percent, oversizing\_allowance\_percent, storage\_permitted (bool), storage\_metering\_rule, excess\_generation\_treatment |
| fdre | fdre\_profile | demand\_profile (long\_text), peak\_window\_definition, assured\_availability\_percent, firmness\_definition (long\_text), availability\_shortfall\_penalty (long\_text), storage\_mandatory (bool), excess\_energy\_price\_inr\_per\_kwh, component\_disclosure\_required (bool), shortfall\_compensation\_multiple, capacity\_addition\_flexibility |
| bess | bess\_performance | capacity\_mw, capacity\_mwh, cycles\_per\_day, round\_trip\_efficiency\_guarantee\_percent, availability\_floor\_percent, availability\_penalty (long\_text), capacity\_charge\_inr\_lakh\_per\_mw\_month, vgf\_inr, degradation\_obligation, augmentation\_obligation, dispatch\_control (enum: procurer, developer, sldc), soc\_constraints, warranty\_years, end\_of\_life\_terms |
| transmission | tbcb\_elements | elements (list of {name, kind: line/substation/bay, kv, route\_km}), element\_wise\_cod (list), process\_stages (enum: rfq\_rfp, single), evaluation\_basis (enum: levelised\_charge, npv\_annual\_charges), row\_responsibility, forest\_clearance\_responsibility, tsa\_tenure\_years, spv\_acquisition\_terms, bpc, ctu\_role |
| generation | gen\_tech | fuel\_type, fuel\_supply\_arrangement, heat\_rate\_or\_design\_energy, tariff\_two\_part (bool), capacity\_charge\_recovery\_rule, availability\_norm\_percent, water\_clearance\_responsibility |
| epc | epc\_scope | scope\_matrix (list of {item, supply, erection, commissioning, om}), boq\_structure, price\_schedule\_structure, supply\_service\_split (bool), milestone\_payment\_schedule (long\_text), retention\_percent, defect\_liability\_months, performance\_ratio\_guarantee\_percent, ld\_delay, ld\_performance, warranty\_terms, drawing\_approval\_cycle, taxes\_duties\_treatment, om\_period\_months |
| ipp | ipp\_model\_inputs | tariff\_ceiling\_inr\_per\_kwh, cuf\_floor\_percent, cuf\_ceiling\_percent, scod\_months, ppa\_tenure\_years, degradation\_cap\_percent, pbg\_cost\_basis, pbg\_duration\_months, ists\_waiver\_status, payment\_security\_mechanism |

**IPP assumptions (not extracted, not canonical).** A separate `model_assumption` table keyed to the tender holds reviewer-entered capex\_inr\_per\_mw, om\_inr\_per\_mw\_year, om\_escalation\_percent, debt\_share\_percent, interest\_percent, tenor\_years, tax\_rate\_percent, auxiliary\_consumption\_percent. A quick IRR endpoint reads canonical inputs plus these assumptions and returns project IRR and equity IRR, clearly labelled as indicative. The UI shows assumptions in a visually separate panel with an "assumed" badge; they never appear in the published tender view.

## Definition of done per stage

Claude Code runs these itself before writing the stage report; you check the ticks before pasting the next stage.

Two numbers measure extraction in the table below and in every stage report from Stage 1 onward, always reported separately:

- **Evidence-location rate** = values with located evidence / values returned. Target 95%.
- **Answer rate** = fields with a value / fields in the schema. Reported, not targeted: it varies with what each document states. A field the document does not state returning null is a correct answer.

Every stage report from Stage 2 onward also prints the real-model cost of the stage and the running total since Stage 1.

| Stage | Checks before STOP |
| --- | --- |
| 0A | INHERITANCE.md names a file path for every keep/adapt; flaws list has at least five concrete items; stack recommendation stated |
| 0B | static IP recorded; firewall shows only allowlisted ranges on 22 and 443; `make deploy` answers https://\<static-ip>/health from an allowed IP; `make test` green; 11 tenders in /work/tenders with manifests; one mocked LLM call writes an llm\_call\_log row; tests watcher running and writing .ci/status.json; ARCHITECTURE.md committed |
| 1 | Candidate rows cannot be updated (test); every candidate has an evidence\_span (test); ApprovalService is the only writer to canonical\_fact (grep + test); e2e on one FDRE tender prints per-field value, confidence, page; evidence-location rate >= 95% on the 12 test fields; answer rate reported |
| 2 | All 9 schema YAMLs load; every validator has pass and fail tests; corrigendum carry-forward test green; all 11 tenders extracted; EXTRACTION-SUMMARY.md written with cost; evidence-location rate >= 95% and answer rate reported, per tender |
| 3 | Playwright suite green; user completes one real review from a token URL unaided; first PDF page under 3 s on the VM; no bulk-approve exists; make trace is clean and every schema field has a complete FIELD-TRACE row |
| 4 | `make gold`, `make eval`, `make report` run end to end on two completed reviews; dashboard reachable; URL list for all 11 tenders delivered; FEEDBACK-REPORT.md lists top corrected fields |
| 5A | Agent findings exist for every gold tender; no agent code path can write candidate or canonical\_fact (test) |
| 5B | THREEWAY-REPORT.md classifies every gold field into the six agreement classes |
| 5C | Cross-tenant read test returns zero rows under RLS; Cloud Run deploy green; published view exposes canonical facts only |

Nothing is left open on your side before Day 1 except what Claude Code will ask for in Part 0: the OpenAI key, the reviewer IPs and the admin IPs. Have the 11 tender PDFs reachable from the VM (a GCS bucket or a Drive link is easiest) before Part B.
