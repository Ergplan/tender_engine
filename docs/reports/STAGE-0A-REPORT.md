# Stage 0A report: repo archaeology

Date: 2026-10-04. Read-only pass over `/work/ref/tariff-oder` and `/work/ref/FDRE`; output is `docs/INHERITANCE.md` (five parts: tariff-oder, FDRE, flaws, module table, stack comparison).

## Acceptance checks (section 14, row 0A)

| Check | Result |
| --- | --- |
| INHERITANCE.md names a file path for every keep/adapt | 25 keep/adapt rows, all with a repo-relative path (scripted check) |
| Flaws list has at least five concrete items | 21 items with file references (11 tariff-oder, 10 FDRE) |
| Stack recommendation stated | Yes, Part 5: follow the locked table; the only area where tariff-oder is materially better is the Postgres queue, which the table already allows |

## Headline findings

- **tariff-oder is the real inheritance.** Production-grade Postgres queue, append-only audit trigger, idempotent review decisions with evidence-view enforcement, per-call extraction run rows, output-salvage helpers, grounding checks, 240 tests with strong negative-path coverage. Its gaps are exactly the places the master prompt is strict: no char offsets or bboxes on evidence, inline prompts with a version constant that is never persisted, no HTTP retry, no eval harness, no tenant column, and two pre-review paths where model output shapes the displayed candidate.
- **FDRE contributes domain vocabulary and design, not code.** The production path makes no LLM calls; extraction is regex with defaults that masquerade as findings and a confidence function that returns "High" for any number. Review state lives in the browser. What is worth keeping: the FDRE field inventory and input dictionary, the lifecycle state vocabulary, the amendment operation model, the per-technology EMD/PBG formula shape, the synonym table, and the NHPC clause-to-parameter QA matrix as golden expectations.
- **Stack:** tariff-oder matches the locked backend (FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Postgres 16) and differs on Python (3.11 in practice), UI (Next.js 16, not Vite) and LLM client (raw httpx, no SDK). Recommendation is to follow the table on all three; no locked decision is reopened.

## Tender set (downloaded this stage at the user's request; Part B step 5 is therefore done early)

Arranged under `/work/tenders/<type>/<slug>/` with a `manifest.yaml` per tender (type, agency, external_ref, title, files with role rfs/amendment/clarification/ppa/psa/technical/contractual/nit, issued_on, pages, notes). Downloaded with a browser user-agent; all HTTP 200; every PDF opens with pypdf.

| Tender | Type | Agency | Reference | Files | Pages | Roles |
| --- | --- | --- | --- | --- | --- | --- |
| `bess/seci-ess-iv` | bess | SECI | SECI/C&P/IPP/15/0010/26-27 | 1 | 137 | rfs |
| `epc/seci-gaya-60mw` | epc | SECI | SECI/C&P/OP/11/0007/26-27 | 2 | 645 | contractual, technical |
| `epc/seci-ramagiri-70mw-bess` | epc | SECI | SECI/C&P/OP/11/0002/26-27 | 9 | 706 | contractual, technical x6, amendment x2 |
| `fdre/seci-cfd-i` | fdre | SECI | SECI/C&P/IPP/13/0002/26-27 | 5 | 341 | rfs x2, amendment x2, ppa |
| `fdre/seci-fdre-ix` | fdre | SECI | SECI/C&P/IPP/13/0006/26-27 | 4 | 256 | rfs, amendment, ppa, psa |
| `fdre/seci-fdre-rtc-v` | fdre | SECI | SECI/C&P/IPP/13/0020/25-26 | 7 | 305 | rfs, amendment x3, clarification, ppa, psa |
| `generation/ntpc-phes-2000mw` | generation | NTPC Renewable Energy Ltd | NRE-CS-5846-004 | 1 | 3 | nit |
| `hybrid/ntpc-hybrid-03` | hybrid | NTPC | NTPC/RE-CS/2024-25/HYBRID-03 | 1 | 138 | rfs |
| `solar/seci-cni-1-700mw` | solar | SECI | SECI/C&P/IPP/15/0009/26-27 | 4 | 241 | rfs, ppa, psa, clarification |
| `transmission/recpdcl-beed-tbcb` | transmission | RECPDCL | n/a | 1 | 166 | rfs |
| `wind/ntpc-rel-600mw-anantapur-wtg` | wind | NTPC Renewable Energy Ltd | NRE-CS-5924-003 | 2 | 14 | nit, technical |
| `wind/seci-wind-tranche-xx` | wind | SECI | SECI/C&P/IPP/12/0003/26-27 | 4 | 239 | rfs, amendment, ppa, psa |
| **Total** | 8 types (no ipp) | | | **41** | **3191** | |

Notes on the set:

- FDRE-IX Amendment-01 (08.07.2026, raises capacity to 6000 MWh / 1500 MW x 4 h) was found via the SECI archive detail page for TSC SECI-2026-TN000014 and downloaded, together with the FDRE-IX standard PPA and PSA.
- The Ramagiri Amendment-3 zip was unpacked; its PDFs are listed in the manifest, the .kml and .dwg are left in place and not listed. Ramagiri Amendment-01 was not in the provided links.
- NTPC Hybrid-03 came from a third-party mirror (JMK Research) and carries no printed issue date on its first pages. The two NTPC REL items are NIT-only; full documents are behind the NTPC e-tender login.
- The RECPDCL Beed RFP shows no reference number on its first pages; to be extracted.
- The ipp tender type has no sample in the set. Per operating rule 13, the `ipp.yaml` schema in Stage 2 will be seeded from section 13 only and flagged as untested against a real document.

## Open questions for the user

1. `/work/ref/FDRE/RFS.pdf` is the NHPC FDRE Tranche-II RfS (264 pages, tender id 2024_NHPC_800202_1). It is the only NHPC document available and would add agency-vocabulary diversity to the fdre type. Add it to `/work/tenders/fdre/` as a 13th tender?
2. The three SECI tenders with standard PPA/PSA/CfDA documents: should those contracts be ingested as `tender_version` documents of kind `original` alongside the RfS, or held as reference attachments outside extraction until a `ppa_terms` section exists? The field catalogue's commercial section (payment security, change in law, termination compensation) is mostly answered by the PPA, not the RfS.
3. Port 443 is open to the world by decision; the Stage 4 admin dashboard needs its own guard. A review-token-style admin token is the smallest change. Confirm in Part B or defer to Stage 4?

## Deviations and notes

- The FDRE analysis agent was killed once by an org-level API rate limit (100k input tokens per minute) and re-run with smaller reads after the tariff-oder agent finished.
- Reference repos were cloned with `gh repo clone` over SSH into `/work/ref/`; nothing from them is imported or submoduled.

Stopping here per Part A step 8. Waiting for the word "proceed" to start Part B.
