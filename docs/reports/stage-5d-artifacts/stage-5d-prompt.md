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

## The owner's instruction

2026-10-18: "Please continue the build to the final application." Stage 5D follows Stage 5C without waiting at the boundary. Standing facts: the master prompt's Stage 5D text names the MCP server and the base tools (`search_tenders`, `get_tender`, `get_field`, `get_document_page`, `list_changes`, `compare_tenders`, `reliability_report`) without specifying them, and the owner's decision of 2026-10-04 said the text would follow — it has not, so the base definitions in this stage are ours, listed in DECISIONS and in the stage report for the owner to correct; the Stage 4 stability bar is not met (epc and wind have one reviewed tender each of two; one required field below 75%); eleven of fourteen reviews are completed and gold; every cloud mutation is the owner's step with the `!` prefix.
