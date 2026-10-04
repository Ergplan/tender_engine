# Decisions

One dated line per decision. Newest at the bottom.

- 2026-10-04 Static IP: promote the VM's existing ephemeral address 34.131.65.108 to the reserved address `tender-engine-ip` (region asia-south2) instead of creating a new one and reattaching. Same end state, no access-config swap, SSH session unaffected. Recorded in `infra/STATIC-IP.txt`; never changed after today.
- 2026-10-04 Port 443 is open to 0.0.0.0/0, departing from the locked decision "443 open only to reviewer IPs". User decision: reviewers are on dynamic wifi IPs, so access is by unguessable review token only. Consequence: the Stage 4 `/admin/reliability` dashboard cannot rely on the IP allowlist and needs its own guard (tracked in KNOWN-GAPS.md from Stage 0B).
- 2026-10-04 Port 22 is open only to Google's IAP TCP-forwarding range 35.235.240.0/20. No personal IPs. SSH is via the console or `gcloud compute ssh --tunnel-through-iap`. The default `default-allow-ssh` rule is removed.
- 2026-10-04 gcloud on the VM runs as the user's own account (`gcloud auth login`), because the VM's default service account has no compute scope. GCP mutations (address reservation, firewall rules) are run by the user in the Claude Code session with the `!` prefix; Claude Code performs read-only verification.
- 2026-10-04 Python toolchain is `uv` with a Python 3.12 venv at `.venv` (system python3 is 3.13; the locked decision pins 3.12).
- 2026-10-04 Tender set is 12 tenders (41 PDFs, 3191 pages) under `/work/tenders/<type>/<slug>/`, downloaded in Stage 0A at the user's request. The NHPC FDRE Tranche-II RfS in the FDRE reference repo is not added until the user says so.
- 2026-10-04 PPA, PSA and CfDA documents are held in the tender folders with roles in `manifest.yaml`; whether they are ingested as extraction inputs is decided in Stage 2 with the schemas.
- 2026-10-04 Refusal fallback to a second model is not enabled in `core/llm/`. The locked decision is one extraction model so eval results stay comparable; a refusal is logged in `llm_call_log` with status `refusal` and surfaces as a failed call.
- 2026-10-04 The watcher is one script, `infra/ci/run_checks.py`, using `watchfiles` rather than `pytest-watcher`, because every check must report into a single `.ci/status.json`. Behaviour matches the spec: changed-package pytest first, then the full suite.
- 2026-10-04 Tests and the watcher use a separate database `tender_ci` on the same Postgres container; pytest creates a throwaway schema per session inside it. The app database `tender` is never touched by tests.
- 2026-10-04 Python dependencies are locked with `uv.lock`; images install with `uv sync --frozen`.
- 2026-10-04 PDF libraries (`pdfplumber`, `pymupdf`) are not installed until Stage 1, when the parse service that needs them is written.
