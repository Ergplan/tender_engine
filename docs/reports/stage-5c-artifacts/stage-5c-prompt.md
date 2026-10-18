# STAGE 5C: production hardening

- Auth: OIDC login (Google Workspace first), roles reviewer/approver/admin/api_client, API keys for the intelligence product. Review tokens stay for external one-off reviewers but now require a logged-in admin to mint them.
- Tenant isolation: Postgres row-level security policies on every table keyed by tenant_id, set from the session; a test that a cross-tenant read returns zero rows even with a bug in the service layer.
- Deployment: split api, worker, agent and web into Cloud Run services; Cloud SQL; GCS via the existing storage interface; Secret Manager; Cloud Armor allowlist replacing the VM firewall. docker compose stays for local dev.
- Client-facing output: a published tender view (GET /tenders/{id}/published) that exposes only canonical facts with their evidence pages, a PDF export with a page-reference appendix, and a changelog across versions. Everything published shows its review date and reviewer role, never the raw candidate.
- Two products from one core: Product A, the enterprise front end, is web/ with auth and multi-tenant admin. Product B, the intelligence API, is the same api/ with API-key auth, rate limits, usage metering per tenant and OpenAPI docs. Neither has code the other lacks; they differ in deployment config and which routes are exposed.


## The owner's instruction

2026-10-18: "Please continue the build to the final application." Stage 5C follows Stage 5B without waiting at the boundary. Standing facts: the Stage 4 stability bar is not met (epc and wind have one reviewed tender each of two; one required field below 75%); eleven of fourteen reviews are completed and gold; every cloud mutation (Cloud SQL, GCS, Secret Manager, Cloud Run, Cloud Armor, the load balancer, DNS, the OIDC client) is the owner's step, run with the `!` prefix from the commands the build agent prepares.
