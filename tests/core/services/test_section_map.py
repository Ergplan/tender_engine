import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import LLMCallLog, Section
from core.services.section_map import SectionMapper
from tests.conftest import Pipeline
from tests.fixtures.llm import ScriptedSDK


def test_mapper_makes_one_call_over_the_page_digest_and_stores_sections(
    pipeline: Pipeline, db: Session
) -> None:
    document = pipeline.parsed_document(db)
    sections = list(db.scalars(select(Section).order_by(Section.start_page)))
    assert [(s.start_page, s.end_page, s.kind) for s in sections] == [
        (1, 1, "cover_and_notice"),
        (2, 2, "dates_and_schedule"),
        (3, 3, "financial_security"),
    ]
    assert all(s.document_id == document.id and s.prompt_version == "v1" for s in sections)
    assert all(s.tenant_id == "ergplan" and s.created_by == "worker" for s in sections)
    [call] = pipeline.sdk.calls
    digest = call["messages"][0]["content"][0]["text"]
    assert "Pages: 1 to 3" in digest and "=== page 2 ===" in digest
    assert "Heading-like lines: SECTION 2: KEY DATES" in digest
    assert "map the structure" in call["system"]
    [log] = db.scalars(select(LLMCallLog))
    assert (log.prompt_name, log.prompt_version, log.status) == ("section_map", "v1", "ok")


def test_ranges_are_clamped_kinds_normalised_and_rerun_replaces(
    make_pipeline: object, db: Session
) -> None:
    sdk = ScriptedSDK(
        sections=[
            {
                "start_page": 0,
                "end_page": 2,
                "heading": " A ",
                "kind": "Cover & Notice",
                "confidence": 1.7,
            },
            {"start_page": 3, "end_page": 40, "heading": "", "kind": "", "confidence": -1},
            {"start_page": 9, "end_page": 4, "heading": "bad", "kind": "x", "confidence": 0.5},
        ]
    )
    pipeline: Pipeline = make_pipeline(sdk)  # type: ignore[operator]
    document = pipeline.parsed_document(db)
    rows = [
        (s.start_page, s.end_page, s.heading, s.kind, s.confidence)
        for s in db.scalars(select(Section).order_by(Section.start_page))
    ]
    assert rows == [(1, 2, "A", "cover_notice", 1.0), (3, 3, "(untitled)", "other", 0.0)]
    SectionMapper(pipeline.llm, "ergplan").map(db, document.id)
    assert len(list(db.scalars(select(Section)))) == 2


def test_an_unparsed_document_cannot_be_mapped(pipeline: Pipeline, db: Session) -> None:
    document = pipeline.upload(db)
    with pytest.raises(LookupError, match="not parsed"):
        SectionMapper(pipeline.llm, "ergplan").map(db, document.id)
