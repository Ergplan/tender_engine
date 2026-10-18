"""The server as a client sees it: the tools with their widget metadata, the widget
resources, a call's structured and text content; and the bearer requirement over HTTP."""

from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from sqlalchemy.orm import Session

from api.main import create_app
from core.services.identity import Principal
from mcpserver.server import WIDGET_MIME, WIDGETS
from tests.conftest import Pipeline
from tests.mcpserver.conftest import server_for


async def _with_client(server: Any, work: Any) -> Any:
    lowlevel = server._lowlevel_server
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lowlevel.run, server_read, server_write, lowlevel.create_initialization_options()
            )
            async with ClientSession(client_read, client_write) as session:
                init = await session.initialize()
                result = await work(session, init)
            tg.cancel_scope.cancel()
    return result


def test_tools_resources_and_a_call_through_a_client_session(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    free_principal: Principal,
) -> None:
    _, _, tender_id = library
    server = server_for(state, free_principal)

    async def work(session: ClientSession, init: Any) -> dict[str, Any]:
        tools = (await session.list_tools()).tools
        resources = (await session.list_resources()).resources
        widget = await session.read_resource("ui://widgets/tender_card.html")
        card = await session.call_tool("get_tender", {"tender": tender_id})
        refused = await session.call_tool("model_tender", {"tender": tender_id})
        return {
            "tools": tools,
            "resources": resources,
            "widget": widget,
            "card": card,
            "refused": refused,
            "capabilities": init.capabilities,
        }

    got = anyio.run(_with_client, server, work)
    names = [t.name for t in got["tools"]]
    assert len(names) == 11 and names[:3] == ["search_tenders", "get_tender", "get_field"]
    with_ui = {
        t.name: t.meta["ui"]["resourceUri"] for t in got["tools"] if t.meta and "ui" in t.meta
    }
    assert with_ui == {name: f"ui://widgets/{widget}.html" for name, widget in WIDGETS.items()}
    assert {str(r.uri) for r in got["resources"]} == {
        f"ui://widgets/{w}.html" for w in WIDGETS.values()
    }
    assert all(r.mime_type == WIDGET_MIME for r in got["resources"])
    assert got["widget"].contents[0].mime_type == WIDGET_MIME
    assert "<html" in got["widget"].contents[0].text.lower()
    # The extension is advertised under the server's capabilities (SEP-2133); what the
    # client keeps of it after negotiation is the SDK's business.
    advertised = server._lowlevel_server.create_initialization_options().capabilities.extensions
    assert "io.modelcontextprotocol/ui" in (advertised or {})
    assert (advertised or {})["io.modelcontextprotocol/ui"] == {"mimeTypes": [WIDGET_MIME]}

    card = got["card"]
    assert not card.is_error
    assert card.structured_content["tender_id"] == tender_id
    assert "provenance" in card.structured_content and "sections" in card.structured_content
    assert card.content[0].text.startswith("Selection of solar power developers")
    assert got["refused"].is_error
    assert got["refused"].structured_content["error_type"] == "tier_required"


def test_the_http_endpoint_needs_a_bearer_token(pipeline: Pipeline) -> None:
    settings = pipeline.settings.model_copy(update={"session_secret": "s" * 32})
    app = create_app(settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog)
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
        assert "resource_metadata" in response.headers.get("www-authenticate", "")
        metadata = client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        body = metadata.json()
        assert body["registration_endpoint"].endswith("/register")
        assert "code" in body["response_types_supported"]
        protected = client.get("/.well-known/oauth-protected-resource/mcp")
        assert protected.status_code == 200 and "authorization_servers" in protected.json()


@pytest.mark.parametrize("widget", list(WIDGETS.values()))
def test_every_widget_resource_is_html(widget: str) -> None:
    from mcpserver.server import widget_html

    assert "<html" in widget_html(widget).lower()


def test_every_tool_answers_in_text_without_the_ui_extension(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    own_tender: str,
) -> None:
    """A host without MCP Apps gets the whole answer as text, authority note included."""
    from sqlalchemy import select

    from core.models import Document
    from core.services.identity import Principal

    _, public_db, public_id = library
    document = public_db.scalar(select(Document))
    assert document is not None
    principal = Principal(
        kind="user",
        tenant_id="ergplan",
        read_tenants=("ergplan", "public"),
        role="approver",
        name="asha@ergplan.test",
    )
    server = server_for(state, principal)
    calls = {
        "search_tenders": {},
        "get_tender": {"tender_id": public_id},
        "get_field": {"tender": public_id, "field_path": "core.key_dates.bid_submission_deadline"},
        "get_document_page": {"document_id": document.id, "page_no": 2},
        "find_matching_tender": {"title_or_number": "600 MW solar PV Acme"},
        "list_changes": {"tender_id": public_id},
        "compare_tenders": {"tenders": [public_id, own_tender]},
        "reliability_report": {},
        "model_tender": {"tender_id": own_tender},
        "save_model_assumptions": {"tender_id": own_tender, "assumptions": {"tenor_years": 15}},
        "my_watchlist": {"add": [public_id]},
    }

    async def work(session: ClientSession, init: Any) -> dict[str, Any]:
        return {name: await session.call_tool(name, args) for name, args in calls.items()}

    got = anyio.run(_with_client, server, work)
    for name, result in got.items():
        assert not result.is_error, (name, result.content)
        text = result.content[0].text
        assert text.strip() and "authoritative source" in text, name
        assert result.structured_content, name
