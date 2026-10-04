# Stage 0, Part 0 report: VM, credentials, network

Date: 2026-10-04. VM `instance-20261004-081207`, project `tender-intelligence-510607`, zone `asia-south2-b`.

## Static IP

`34.131.65.108`, reserved as `tender-engine-ip` (region asia-south2, PREMIUM tier) by promoting the VM's existing ephemeral address in place. Recorded in `infra/STATIC-IP.txt` and `docs/DECISIONS.md`. Never changed after today.

## Firewall (verified with `gcloud compute firewall-rules list`)

| Rule | Port | Source ranges | Target tag |
| --- | --- | --- | --- |
| tender-engine-https | tcp:443 | 0.0.0.0/0, 35.235.240.0/20 | tender-engine |
| tender-engine-ssh | tcp:22 | 35.235.240.0/20 (IAP TCP forwarding) | tender-engine |

- `default-allow-ssh` (tcp:22 from 0.0.0.0/0) deleted. The instance is tagged `tender-engine`.
- 443 is open to the world by user decision (reviewers on dynamic wifi IPs; access by review token only). This departs from the locked decision table and is recorded in DECISIONS.md. The Stage 4 admin dashboard will need its own guard; to be listed in KNOWN-GAPS.md in Part B.
- Left as found, outside the spec: `default-allow-rdp` (tcp:3389 from 0.0.0.0/0), `default-allow-icmp`, `default-allow-internal`. Delete RDP with `gcloud compute firewall-rules delete default-allow-rdp --quiet` if wanted.
- `infra/firewall.sh` recreates the rules from `infra/allowlist.yaml`. Adding a reviewer range later: edit the YAML, run the script.
- Reachability of 443 from outside is checked in Part B once Caddy is up (step 6 deferred, nothing listens yet).

## What was asked and where it is stored

| Item | Answer | Stored in |
| --- | --- | --- |
| OpenAI API key | provided | `.env` (gitignored), `OPENAI_API_KEY` |
| Reviewer IPs (443) | 0.0.0.0/0 | `infra/allowlist.yaml` (gitignored) |
| Admin IPs (22) | 35.235.240.0/20 only | `infra/allowlist.yaml` (gitignored) |
| GCP project / zone / instance | read from the metadata server, not asked | `infra/firewall.sh` defaults |
| Anthropic key and model | from bootstrap shell profile | `.env` |

`.env.example` and `infra/allowlist.example.yaml` are committed with blank or example values.

## Environment confirmed

Docker 29.8.2, Compose v5.6.0, Node v22.23.3, system python3 3.13.5, gh 2.102.0 (authenticated as Ergplan, ssh protocol), gcloud 585.0.0, jq 1.7. Images pre-pulled: `postgres:16`, `caddy:2`. Python toolchain: `uv` 0.12.23 with a Python 3.12.15 venv at `/work/tender_engine/.venv`.

## Notes and deviations

- The VM's default service account has no compute scope. gcloud now runs as the user's own account (`gcloud auth login` on the VM).
- The Claude Code auto-mode permission classifier refused to write the API key to `.env`, to write an allowlist containing 0.0.0.0/0, and to run GCP mutations. The user ran those three steps with the `!` prefix; Claude Code verified read-only. All later `gcloud compute` mutations will need the same treatment unless a permission rule is added.
- The master prompt was committed at the repo root under its document title; it was moved to `docs/MASTER-PROMPT.md` as section 1 of the prompt prescribes.
- Repo-local git identity set to `venture <venture@aayuda.energy>`.
