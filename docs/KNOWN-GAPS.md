# Known gaps

Kept current every stage. Each gap says what is missing, why, and what closes it.

| Gap | Why it exists | What closes it |
| --- | --- | --- |
| Reviewers see a certificate warning once | Caddy issues the certificate from its internal CA because the app is served on a bare IP (`https://34.131.65.108`) and no public CA issues for that | Point a domain at the static IP, replace the site address in `infra/Caddyfile` with the domain and remove `tls internal`; Caddy then obtains a Let's Encrypt certificate automatically. Port 80 must be opened for the HTTP challenge, or use the TLS-ALPN challenge on 443 |
| Port 443 is open to the world | User decision on 2026-10-04: reviewers are on dynamic IPs, access is by review token only | Stage 3 token middleware guards every review route. The Stage 4 `/admin/reliability` dashboard needs its own guard (an admin token is the smallest change); decide before Stage 4 |
| No sample tender of type `ipp` | The 12-tender set covers fdre, bess, solar, wind, hybrid, transmission, generation and epc | `tender/schemas/ipp.yaml` will be seeded from the field catalogue only and flagged untested until an IPP document is added to `/work/tenders/ipp/` |
| Three tenders are incomplete | NTPC REL Anantapur WTG and NTPC PHES are NIT-only (full documents behind the NTPC e-tender login); Ramagiri Amendment-01 was not in the link set | Add the missing files to the tender folders and update `manifest.yaml` |
| VM is small: 2 vCPU, 3 GB RAM, 10 GB disk | The VM was created before the stack was sized | Resize the disk and machine type before Stage 2 (11 tenders of page renders at 150 dpi need several GB); no code change needed |
| `make trace` and `make report` do not exist yet | FIELD-TRACE needs schemas, routes and UI (Stage 3); the reliability report is Stage 4 | Added in those stages |
| GCP mutations cannot be run by the build agent | The Claude Code permission classifier blocks firewall and address changes from the agent session | The user runs `infra/firewall.sh` with the `!` prefix; the agent verifies read-only |
