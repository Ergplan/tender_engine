# Known gaps

Kept current every stage. Each gap says what is missing, why, and what closes it.

| Gap | Why it exists | What closes it |
| --- | --- | --- |
| Reviewers see a certificate warning once | Caddy issues the certificate from its internal CA because the app is served on a bare IP (`https://34.131.65.108`) and no public CA issues for that | Point a domain at the static IP, replace the site address in `infra/Caddyfile` with the domain and remove `tls internal`; Caddy then obtains a Let's Encrypt certificate automatically. Port 80 must be opened for the HTTP challenge, or use the TLS-ALPN challenge on 443 |
| Port 443 is open to the world | User decision on 2026-10-04: reviewers are on dynamic IPs, access is by review token only | Stage 3 token middleware guards every review route. The Stage 4 `/admin/reliability` dashboard needs its own guard (an admin token is the smallest change); decide before Stage 4 |
| No sample tender of type `ipp` | The 13-tender set covers fdre, bess, solar, wind, hybrid, transmission, generation and epc | `tender/schemas/ipp.yaml` will be seeded from the field catalogue only and flagged untested until an IPP document is added to `/work/tenders/ipp/` |
| Three tenders are incomplete | NTPC REL Anantapur WTG and NTPC PHES are NIT-only (full documents behind the NTPC e-tender login); Ramagiri Amendment-01 was not in the link set | Add the missing files to the tender folders and update `manifest.yaml` |
| VM is small on CPU and memory: 2 vCPU, 3.9 GB RAM | The VM was created before the stack was sized. The disk was grown to 200 GB on 2026-10-04 (182 GB free) | Change the machine type if the watcher (mypy plus pytest plus vitest) or page rendering in Stage 1 runs short of memory; it needs a VM stop and start, and the static IP stays attached |
| `make trace` and `make report` do not exist yet | FIELD-TRACE needs schemas, routes and UI (Stage 3); the reliability report is Stage 4 | Added in those stages |
| GCP mutations cannot be run by the build agent | The Claude Code permission classifier blocks firewall and address changes from the agent session | The user runs `infra/firewall.sh` with the `!` prefix; the agent verifies read-only |
| `make check` and `make test` need the `web_node_modules` volume | The tests container runs tsc and vitest from a volume that the web image populates | Run `make up` (or `make deploy`) once before them on a fresh machine; `make deploy` refreshes the volume with `npm ci` |
| Containers run in development mode | `uvicorn --reload` and the Vite dev server are used in phase 1 so the build agent's edits are live | Stage 5C builds production images (static web bundle, no reload) for Cloud Run |
| Postgres password is the compose default `tender` | The database listens only on the compose network and on 127.0.0.1 of the VM | Move to a generated secret in `.env` when Cloud SQL arrives in Stage 5C |
| Rule 15 checklist item (d) cannot run in Stages 1 and 2 | `make trace` and `FIELD-TRACE.md` are built in Stage 3, when schemas, routes and UI components all exist | The reviewer reports item (d) as not applicable until Stage 3; from Stage 3 it is checked |
