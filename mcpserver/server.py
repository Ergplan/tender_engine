"""The MCP server: the tools registered with the SDK, the widget resources, the auth.

`build_server` makes an `MCPServer` over the API's state (session factory, catalog,
identity service, settings). Each tool opens a session scoped to the caller's principal
(from the SDK's auth context: the bearer token the verifier resolved), runs the pure
function in `mcpserver.tools` and returns its structured content and its plain-text
rendering. The four tools that render declare their widget under `_meta.ui.resourceUri`;
the widgets are `ui://widgets/<name>.html` resources served with the MCP Apps media type
from `mcp/widgets/` (a placeholder line until the file exists, so a host never gets a
missing resource). The extension `io.modelcontextprotocol/ui` is advertised through the
SDK's `Extension` hook, which puts it under `capabilities.extensions`.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import Extension, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import BaseRoute, Route

from core.retrieval import Retriever
from core.services.extract import ExtractService
from core.services.identity import Principal
from mcpserver import tools
from mcpserver.auth import SCOPES, LibraryAccessToken, LibraryOAuthProvider
from mcpserver.tools import ToolContext, ToolRefused, ToolResult
from tender.services.ask import AskService
from tender.services.tenders import TenderService

ROOT = Path(__file__).resolve().parent.parent
WIDGETS_DIR = ROOT / "mcp" / "widgets"
WIDGET_MIME = "text/html;profile=mcp-app"
UI_EXTENSION = "io.modelcontextprotocol/ui"
WIDGETS = {
    "get_tender": "tender_card",
    "model_tender": "financial_model",
    "list_changes": "changes_view",
    "compare_tenders": "comparison_table",
}
TOOL_NAMES = (*tools.FREE_TOOLS, *tools.PAID_TOOLS)


class UiExtension(Extension):
    """MCP Apps: a tool may name a `ui://` HTML resource the host renders in a sandbox."""

    identifier = UI_EXTENSION

    def settings(self) -> dict[str, Any]:
        return {"mimeTypes": [WIDGET_MIME]}


def widget_html(name: str) -> str:
    path = WIDGETS_DIR / f"{name}.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        "<!doctype html><html><body><p>The widget "
        f"{name} is not bundled on this server; the tool's text result is complete.</p>"
        "</body></html>"
    )


def _principal(principal_for_tests: Principal | None) -> Principal:
    if principal_for_tests is not None:
        return principal_for_tests
    token = get_access_token()
    if isinstance(token, LibraryAccessToken):
        return token.principal
    raise ToolRefused("login_required", "the call carries no valid bearer token", 401)


def _ref(tender: str | None, tender_id: str | None) -> str:
    """The tender named either way (`tender` a slug or id; `tender_id` the widgets' name)."""
    ref = tender or tender_id
    if not ref:
        raise ToolRefused("validation_failed", "name the tender (tender or tender_id)", 422)
    return ref


def _result(result: ToolResult) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=result.text)],
        structured_content=result.structured_content(),
    )


def _refusal(exc: ToolRefused) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"{exc.error_type}: {exc.message}")],
        structured_content={
            "error_type": exc.error_type,
            "message": exc.message,
            "status": exc.status,
        },
        is_error=True,
    )


def build_server(
    state: Any,
    *,
    principal_for_tests: Principal | None = None,
    with_auth: bool = True,
) -> MCPServer:
    """The server over an app's state. `principal_for_tests` stands in for the bearer
    token in in-memory tests; `with_auth` off builds it without the OAuth routes."""
    settings = state.settings
    results_root = Path(settings.results_root) if settings.results_root else None
    provider = LibraryOAuthProvider(settings, state.session_factory, state.identity)
    base = settings.public_base_url.rstrip("/")
    auth = (
        AuthSettings(
            issuer_url=AnyHttpUrl(base),
            resource_server_url=AnyHttpUrl(f"{base}/mcp"),
            required_scopes=["public:read"],
            # Our tokens are keys of this deployment; the verifier is the authority.
            validate_token_resource=False,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=list(SCOPES), default_scopes=["public:read"]
            ),
        )
        if with_auth
        else None
    )
    server = MCPServer(
        name="tender-library",
        title="Tender Intelligence Library",
        instructions=(
            "Reviewed readings of power-sector tenders. Every value carries its page and its "
            "review; a field not reviewed is a marked gap, never a blank. The tender document "
            "is the authoritative source."
        ),
        version="0.5.0",
        auth=auth,
        # The SDK makes the token verifier from the provider (`load_access_token`).
        auth_server_provider=provider if with_auth else None,
        extensions=[UiExtension()],
    )

    def run(name: str, call: Callable[[ToolContext], ToolResult]) -> CallToolResult:
        try:
            principal = _principal(principal_for_tests)
        except ToolRefused as exc:
            return _refusal(exc)
        with state.session_factory() as session:
            local = settings.model_copy(update={"tenant_id": principal.tenant_id})
            tenders = TenderService(
                state.catalog,
                ExtractService(state.llm, state.storage, state.schemas, local),
                principal.tenant_id,
            )
            ask = None
            if settings.retrieval_enabled and getattr(state, "retrieval", None) is not None:
                store = state.retrieval.for_tenant(
                    principal.tenant_id, tuple(principal.read_tenants)
                )
                ask = AskService(
                    state.llm,
                    state.catalog,
                    state.schemas,
                    tenders,
                    Retriever(store, state.embedders, top_k=settings.ask_top_k),
                    local,
                )
            ctx = ToolContext(
                session=session,
                principal=principal,
                settings=settings,
                catalog=state.catalog,
                identity=state.identity,
                storage=state.storage,
                tenders=tenders,
                results_root=results_root,
                ask=ask,
            )
            try:
                return _result(tools.run_tool(ctx, name, lambda tier: call(ctx)))
            except ToolRefused as exc:
                return _refusal(exc)

    def meta(name: str) -> dict[str, Any] | None:
        widget = WIDGETS.get(name)
        return {"ui": {"resourceUri": f"ui://widgets/{widget}.html"}} if widget else None

    @server.tool(name="search_tenders", meta=meta("search_tenders"))
    def search_tenders(
        query: str | None = None,
        tender_type: str | None = None,
        agency: str | None = None,
        state_filter: str | None = None,
    ) -> CallToolResult:
        """Find published tenders by words in their title, number or agency; filter by
        type, agency or publication state (published, update_pending)."""
        return run(
            "search_tenders",
            lambda ctx: tools.search_tenders(ctx, query, tender_type, agency, state_filter),
        )

    @server.tool(name="get_tender", meta=meta("get_tender"))
    def get_tender(tender: str | None = None, tender_id: str | None = None) -> CallToolResult:
        """The published view of a tender (slug or id): reviewed facts by section with
        their pages, the publication state and banner, the review's date and role."""
        return run("get_tender", lambda ctx: tools.get_tender(ctx, _ref(tender, tender_id)))

    @server.tool(name="get_field", meta=meta("get_field"))
    def get_field(tender: str, field_path: str) -> CallToolResult:
        """One field of a tender with its provenance; a field not reviewed is a gap with
        its reason and the page it is likely on."""
        return run("get_field", lambda ctx: tools.get_field(ctx, tender, field_path))

    @server.tool(name="get_document_page", meta=meta("get_document_page"))
    def get_document_page(
        document_id: str, page_no: int, quote: str | None = None
    ) -> CallToolResult:
        """A page of a tender document: its text, its image URL, and where a quote sits."""
        return run(
            "get_document_page",
            lambda ctx: tools.get_document_page(ctx, document_id, page_no, quote),
        )

    @server.tool(name="find_matching_tender", meta=meta("find_matching_tender"))
    def find_matching_tender(
        title_or_number: str, agency: str | None = None, capacity_mw: float | None = None
    ) -> CallToolResult:
        """The reviewed tender behind a document you are holding, or no_match with up to
        three candidates and what tells them apart. The document is never read."""
        return run(
            "find_matching_tender",
            lambda ctx: tools.find_matching(ctx, title_or_number, agency, capacity_mw),
        )

    @server.tool(name="list_changes", meta=meta("list_changes"))
    def list_changes(tender: str | None = None, tender_id: str | None = None) -> CallToolResult:
        """The changelog across a tender's versions: old to new, with evidence."""
        return run("list_changes", lambda ctx: tools.list_changes(ctx, _ref(tender, tender_id)))

    @server.tool(name="compare_tenders", meta=meta("compare_tenders"))
    def compare_tenders(tenders: list[str]) -> CallToolResult:
        """Up to six tenders side by side: fields as rows, provenance on every cell."""
        return run("compare_tenders", lambda ctx: tools.compare(ctx, tenders))

    @server.tool(name="ask_tender", meta=meta("ask_tender"))
    def ask_tender(
        question: str, tender: str | None = None, tender_id: str | None = None
    ) -> CallToolResult:
        """Ask one question about a tender (slug or id). A question that names a field is
        answered from the approved fact; any other from the tender's pages, every claim
        cited to a page and quote the evidence resolver located. The answer says whether it
        is approved or a machine reading; it is never a fact. Paid tier."""
        return run(
            "ask_tender", lambda ctx: tools.ask_tender(ctx, _ref(tender, tender_id), question)
        )

    @server.tool(name="reliability_report", meta=meta("reliability_report"))
    def reliability_report(tender_type: str | None = None) -> CallToolResult:
        """Accuracy per tender type from the latest evaluation of the gold set."""
        return run("reliability_report", lambda ctx: tools.reliability_report(ctx, tender_type))

    @server.tool(name="model_tender", meta=meta("model_tender"))
    def model_tender(
        tender: str | None = None,
        tender_id: str | None = None,
        model_type: str = "power_project_finance",
        assumptions: dict[str, float] | None = None,
    ) -> CallToolResult:
        """The financial model (paid): the tender's fixed parameters with pages, your
        assumptions, the server's indicative figures. Read-only; see save_model_assumptions."""
        return run(
            "model_tender",
            lambda ctx: tools.model_tender(ctx, _ref(tender, tender_id), model_type, assumptions),
        )

    @server.tool(name="save_model_assumptions", meta=meta("save_model_assumptions"))
    def save_model_assumptions(
        assumptions: dict[str, float],
        tender: str | None = None,
        tender_id: str | None = None,
        model_type: str = "power_project_finance",
    ) -> CallToolResult:
        """Keep your assumptions for a tender (paid). Returns what was saved."""
        return run(
            "save_model_assumptions",
            lambda ctx: tools.save_model_assumptions(
                ctx, _ref(tender, tender_id), assumptions, model_type
            ),
        )

    @server.tool(name="my_watchlist", meta=meta("my_watchlist"))
    def my_watchlist(
        add: list[str] | None = None, remove: list[str] | None = None
    ) -> CallToolResult:
        """The tenders you follow (paid), with bid deadlines and days remaining."""
        return run("my_watchlist", lambda ctx: tools.my_watchlist(ctx, add, remove))

    for widget in WIDGETS.values():

        def make(name: str) -> Callable[[], str]:
            def read() -> str:
                return widget_html(name)

            read.__name__ = f"widget_{name}"
            return read

        server.resource(
            f"ui://widgets/{widget}.html",
            name=widget,
            title=widget.replace("_", " "),
            description=f"The {widget} widget (MCP Apps): renders only what its tool returned.",
            mime_type=WIDGET_MIME,
        )(make(widget))

    return server


def asgi_app(server: MCPServer) -> Starlette:
    """The streamable-HTTP app with the OAuth routes, to mount at the API's root."""
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def routes_of(server: MCPServer) -> list[BaseRoute]:
    """The MCP app's routes (`/mcp`, the OAuth endpoints, the well-known documents) to
    add to the API's own router. They are added one by one rather than mounted as a
    sub-application: a mounted Starlette app takes over `request.app` for the request,
    and the API's middleware reads the outer app's state after every request. The
    bearer-token middleware the SDK puts on its whole app is wrapped around the `/mcp`
    route alone, which is the only route that needs it."""
    inner = asgi_app(server)
    routes: list[BaseRoute] = []
    for route in inner.routes:
        if isinstance(route, Route) and route.path == "/mcp":
            app: Any = route.app
            for middleware in reversed(inner.user_middleware):
                app = middleware.cls(app, *middleware.args, **middleware.kwargs)
            routes.append(Route("/mcp", app, methods=sorted(route.methods or ["GET", "POST"])))
        else:
            routes.append(route)
    return routes


@contextlib.asynccontextmanager
async def run_session_manager(server: MCPServer) -> AsyncIterator[None]:
    """The session manager must run for the life of the process that mounts the app."""
    async with server.session_manager.run():
        yield
