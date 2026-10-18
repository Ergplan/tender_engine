# STAGE 5B: three-way comparison (evals/threeway.py)

- For every gold tender: human (gold), engine (candidate), agent (agent_finding) per field. Classify each field into: all agree; engine right agent wrong; agent right engine wrong; both wrong same way; both wrong differently; both abstained. Report by field, tender type and agency.
- Error pattern analysis written to THREEWAY-REPORT.md: where both models fail the same way, the schema or the document is the problem (ambiguous clause, table/clause conflict); where they disagree, the field is a candidate for mandatory second-pass in production; where the agent catches engine misses, promote the agent's evidence strategy into the extract prompt and re-evaluate.
- Production confidence rule, written into config and the report: a field is "auto-surface with low-review" only if human-engine-agent agreement >= 97% over at least 15 gold instances; otherwise it stays full review. Still no auto-approval: this only changes the UI's default emphasis, never the truth pipeline.


## The owner's instruction

2026-10-18: "use whatever is completed and please move ahead with build", then "Please continue the build to the final application." Stage 5B runs on the eleven gold tenders (the stability bar is not met: epc and wind have one reviewed tender each of two; one required field below 75%); the three tenders without a completed review (Ramagiri, Wind-XX, RECPDCL) are outside the comparison until reviewed.
