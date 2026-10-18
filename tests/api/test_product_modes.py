"""Two products from one code base: the enterprise front end mounts everything, the
intelligence API mounts the read side only."""

from fastapi.testclient import TestClient

from api.main import create_app, routers_for
from tests.conftest import Pipeline


def _paths(client: TestClient) -> set[tuple[str, str]]:
    schema = client.get("/openapi.json").json()
    return {
        (method.upper(), path) for path, methods in schema["paths"].items() for method in methods
    }


def test_the_api_product_exposes_reads_only_and_keeps_the_openapi_document(
    pipeline: Pipeline,
) -> None:
    api = TestClient(
        create_app(
            pipeline.settings.model_copy(update={"product": "api"}),
            pipeline.schemas,
            pipeline.storage,
            pipeline.llm,
            pipeline.catalog,
        )
    )
    paths = _paths(api)
    assert ("GET", "/api/v1/tenders") in paths
    assert ("GET", "/api/v1/tenders/{tender_id}") in paths
    assert ("GET", "/api/v1/documents/{document_id}") in paths
    assert ("GET", "/api/v1/admin/reliability") in paths
    assert ("GET", "/api/v1/health") in paths and ("GET", "/health") in paths
    assert not any(path.startswith("/api/v1/approvals") for _, path in paths)
    assert ("POST", "/api/v1/admin/gold") not in paths
    assert ("POST", "/api/v1/tenders/{tender_id}/extract") not in paths
    assert ("POST", "/api/v1/review-tokens") not in paths
    assert all(method == "GET" for method, path in paths if path.startswith("/api/v1/"))
    assert api.get("/docs").status_code == 200
    assert api.post("/api/v1/tenders", json={}).status_code in (404, 405)


def test_the_enterprise_product_mounts_every_router(pipeline: Pipeline) -> None:
    enterprise = TestClient(
        create_app(
            pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
        )
    )
    paths = _paths(enterprise)
    assert ("POST", "/api/v1/approvals") in paths
    assert ("POST", "/api/v1/admin/gold") in paths
    assert len(routers_for("enterprise")) > len(routers_for("api"))
