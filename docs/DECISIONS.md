# Decisions

One dated line per decision. Newest at the bottom.

- 2026-10-04 Static IP: promote the VM's existing ephemeral address 34.131.65.108 to the reserved address `tender-engine-ip` (region asia-south2) instead of creating a new one and reattaching. Same end state, no access-config swap, SSH session unaffected. Recorded in `infra/STATIC-IP.txt`; never changed after today.
- 2026-10-04 Port 443 is open to 0.0.0.0/0, departing from the locked decision "443 open only to reviewer IPs". User decision: reviewers are on dynamic wifi IPs, so access is by unguessable review token only. Consequence: the Stage 4 `/admin/reliability` dashboard cannot rely on the IP allowlist and needs its own guard (tracked in KNOWN-GAPS.md from Stage 0B).
- 2026-10-04 Port 22 is open only to Google's IAP TCP-forwarding range 35.235.240.0/20. No personal IPs. SSH is via the console or `gcloud compute ssh --tunnel-through-iap`. The default `default-allow-ssh` rule is removed.
- 2026-10-04 gcloud on the VM runs as the user's own account (`gcloud auth login`), because the VM's default service account has no compute scope. GCP mutations (address reservation, firewall rules) are run by the user in the Claude Code session with the `!` prefix; Claude Code performs read-only verification.
- 2026-10-04 Python toolchain is `uv` with a Python 3.12 venv at `.venv` (system python3 is 3.13; the locked decision pins 3.12).
