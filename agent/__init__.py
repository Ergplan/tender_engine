"""Stage 5A: the independent agent pass.

A second model, from a different family than the extraction model, reads a tender with
three tools (read pages, search text, submit a finding) and the field schema; it never
sees the engine's candidates, the gold values or the reviewer's decisions. Its findings
land in `agent_finding` and nowhere else: never in candidate, never in canonical_fact.
The three-way comparison of Stage 5B reads them beside the engine's candidates and the
reviewer's gold.
"""
