from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings


def test_health_reports_database_and_tenant(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    for path in ("/health", "/api/v1/health"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json() == {"status": "ok", "tenant_id": "ergplan", "database": "ok"}
        assert response.headers["X-Request-Id"]


def test_health_echoes_a_supplied_request_id(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    response = client.get("/health", headers={"X-Request-Id": "abc123"})
    assert response.headers["X-Request-Id"] == "abc123"


def test_health_is_503_when_the_tenant_is_not_seeded(settings: Settings) -> None:
    client = TestClient(create_app(settings.model_copy(update={"tenant_id": "missing"})))
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["error_type"] == "dependency_unavailable"
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_health_is_503_when_the_database_is_unreachable(settings: Settings) -> None:
    broken = settings.model_copy(
        update={"database_url": "postgresql+psycopg://tender:tender@127.0.0.1:1/none"}
    )
    client = TestClient(create_app(broken))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_type"] == "dependency_unavailable"


def test_unknown_route_is_404(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/v1/nope").status_code == 404
