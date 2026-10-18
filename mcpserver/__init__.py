"""The MCP server of the public library tier (Stage 5D).

The Python package is `mcpserver`, not `mcp`, because `mcp` is the SDK's own package name
and a local package of that name would shadow it; the widgets live where the master
prompt puts them, `mcp/widgets/` (a plain folder, no Python in it).

Tools (free tier, over the public library and the caller's own tenant, read-only):
search_tenders, get_tender, get_field, get_document_page, find_matching_tender,
list_changes, compare_tenders, reliability_report. Paid: model_tender,
save_model_assumptions, my_watchlist. The base tool definitions were never specified by
the owner (DECISIONS 2026-10-04); they are defined here from the master prompt's widget
and tier text. Every tool returns a structured result and a complete plain-text rendering,
so a host without widgets has the whole answer.
"""
