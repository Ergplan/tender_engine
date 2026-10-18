# Stage 5A prompt

The "STAGE 5A" block of `docs/MASTER-PROMPT.md` ("Stage 5 (after the 11-tender review): independent agent, three-way comparison, production"), verbatim, followed by the instruction under which the stage was opened. This file is what the independent reviewer (operating rule 15) receives as the stage prompt.

# STAGE 5A: independent agent pass (agent/)

- Build agent/ as a separate container using the OpenAI Agents SDK on the current GPT model. It receives: the tender type, the compiled field schema, and the raw page renders plus page text for the sections the section map names. It does NOT receive the engine's candidates, the gold values, or the reviewer's decisions.
- The agent has three tools: read_pages(page_nos), search_text(query), and submit_finding(field_path, value, confidence, evidence pages and quotes). It must call read_pages before any submit_finding for a field, and the harness rejects findings whose quotes are not found on the cited page, same rule as core.
- Results land in agent_finding, a separate table, never in candidate or canonical_fact.
- POST /tenders/{id}/agent-pass runs it; GET /tenders/{id}/agent-pass/{run_id} returns findings.


## The owner's instruction

On 2026-10-18 the owner, asked how many reviews were completed (11 of 14, all theirs; three not completed: Ramagiri, Wind-XX, RECPDCL), wrote: "use whatever is completed and please move ahead with build".

The standing constraints that bear on it:

- The master prompt says Stage 5 "starts only when the stability bar in Stage 4 is met". The bar is not met: `epc` and `wind` have one reviewed tender each of the two the bar asks for, and one required field is below 75% (`docs/reports/RELIABILITY-REPORT.md`, "Stability bar for Stage 5"). The owner opened the stage over that; recorded in `docs/DECISIONS.md` (2026-10-18) and carried in the Stage 5A report, not reopened.
- Stage 5A is the first of four Stage 5 sessions; each stops. 5B (three-way comparison) runs over the 11 gold tenders that exist.
- The non-negotiable invariants hold: the agent's findings land in `agent_finding` only, never in `candidate` or `canonical_fact`; every model call goes through `core/llm/`; every finding carries located evidence or is an explicit abstention.
- Spend: the agent pass costs OpenAI tokens per tender; the measured cost of the first pass is reported before the rest are run.
