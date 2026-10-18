"""The review's default emphasis (Stage 5B): a field the three-way comparison found
reviewer, engine and agent agreeing on is shown as low-review; nothing else changes."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import create_app
from evals.threeway import Emphasis, ThreeWaySummary, low_review_fields, write_emphasis
from tender.services.review import tender_review
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD, extracted_tender


def summary_with(tenant_id: str, low: list[str], full: list[str]) -> ThreeWaySummary:
    return ThreeWaySummary(
        tenant_id=tenant_id,
        made_at="2026-10-18T12:00:00+00:00",
        tenders=15,
        tenders_without_agent_pass=[],
        fields=0,
        by_class={},
        by_type={},
        by_agency={},
        by_field={},
        emphasis=[
            *(Emphasis(field_path=p, instances=15, agreement=1.0, low_review=True) for p in low),
            *(Emphasis(field_path=p, instances=15, agreement=0.8, low_review=False) for p in full),
        ],
    )


def test_the_emphasis_file_names_the_low_review_fields(tmp_path: Path) -> None:
    assert low_review_fields("ergplan", tmp_path) == frozenset()
    path = write_emphasis(summary_with("ergplan", [DEADLINE], [EMD]), tmp_path)
    assert path == tmp_path / "review-emphasis-ergplan.json"
    assert low_review_fields("ergplan", tmp_path) == frozenset({DEADLINE})
    assert low_review_fields("other", tmp_path) == frozenset()


def test_a_low_review_field_is_marked_and_the_rest_are_full(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    tender = extracted_tender(pipeline, db)
    plain = tender_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender)
    assert {f.emphasis for f in plain.fields} == {"full"}
    marked = tender_review(
        db,
        pipeline.catalog,
        pipeline.tenders,
        pipeline.review_state,
        tender,
        low_review=frozenset({DEADLINE}),
    )
    by_path = {f.field_path: f for f in marked.fields}
    assert by_path[DEADLINE].emphasis == "low" and by_path[EMD].emphasis == "full"
    # Nothing but the emphasis differs: the same decisions, counts and entries.
    assert (marked.decided, marked.total, marked.can_complete) == (
        plain.decided,
        plain.total,
        plain.can_complete,
    )
    assert by_path[DEADLINE].decided is False and by_path[DEADLINE].current is not None

    # Through the API the set comes from the emphasis file under settings.results_root.
    write_emphasis(summary_with(pipeline.settings.tenant_id, [EMD], []), tmp_path)
    settings = pipeline.settings.model_copy(update={"results_root": str(tmp_path)})
    client = TestClient(
        create_app(settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog)
    )
    served = client.get(f"/api/v1/tenders/{tender.id}/review").json()
    emphasis = {f["field_path"]: f["emphasis"] for f in served["fields"]}
    assert emphasis[EMD] == "low" and emphasis[DEADLINE] == "full"
