import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.conftest import Pipeline


@pytest.fixture()
def client(pipeline: Pipeline) -> TestClient:
    """The API wired to the same storage, schemas and scripted model as the pipeline."""
    app = create_app(pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm)
    return TestClient(app)
