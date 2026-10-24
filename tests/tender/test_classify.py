"""Tender type classification (Stage 7, Block 2 d): the bands, the core-only reading of an
unknown type, the job that writes the answer, and the reviewer's correction."""

from typing import Any

import pytest
from sqlalchemy import select

from core.models import Document, Job
from tender.services.classify import (
    Classification,
    TenderTypeOutput,
    TypeClassifier,
    core_groups,
    job_handlers,
    state_for,
)
from tender.services.packs import build_registry, schema_name
from tender.services.tenders import TenderError
from tests.conftest import Pipeline


def answer(tender_type: str, confidence: float, alternatives: list[str] | None = None) -> Any:
    return TenderTypeOutput(
        tender_type=tender_type,  # type: ignore[arg-type]
        confidence=confidence,
        reasons="because",
        alternatives=alternatives or [],
    )


def test_the_bands_decide_set_unsure_and_unknown_and_never_force_a_type() -> None:
    assert state_for(answer("solar", 0.95)) == Classification(
        tender_type="solar", state="set", confidence=0.95, reasons="because", alternatives=[]
    )
    unsure = state_for(answer("hybrid", 0.65, ["fdre"]))
    assert (unsure.tender_type, unsure.state, unsure.alternatives) == ("hybrid", "unsure", ["fdre"])
    assert unsure.ask_reviewer
    low = state_for(answer("wind", 0.3))
    assert (low.tender_type, low.state) == ("wind", "unknown"), "the guess is kept, as a guess"
    none = state_for(answer("unknown", 0.9, ["bess", "solar"]))
    assert (none.tender_type, none.state) == ("bess", "unknown"), "the first alternative"
    nothing = state_for(answer("unknown", 0.2))
    assert (nothing.tender_type, nothing.state) == ("ipp", "unknown"), "the generic schema"
    assert (
        state_for(answer("solar", 0.8)).state == "set"
        and state_for(answer("solar", 0.5)).state == "unsure"
    )


def test_an_unknown_type_is_read_with_the_core_sections_only() -> None:
    schemas, catalog = build_registry()
    compiled = catalog.get("ipp")
    schema = schemas.get(schema_name("ipp"), compiled.schema.version)
    groups = core_groups(schema)
    assert groups, "there are core groups to read"
    paths_by_group: dict[str, list[str]] = {}
    for field in schema.fields:
        paths_by_group.setdefault(field.group, []).append(field.path)
    for name in groups:
        assert all(p.startswith("core.") for p in paths_by_group[name])
    sector = [
        g.name
        for g in schema.groups
        if any(not p.startswith("core.") for p in paths_by_group.get(g.name, []))
    ]
    assert sector and not set(sector) & set(groups), "no sector section is read"


def test_the_job_classifies_a_parsed_document_and_writes_the_answer(
    pipeline: Pipeline, db: Any
) -> None:
    document = pipeline.parsed_document(db)
    pipeline.sdk.tender_type_answer = {
        "tender_type": "fdre",
        "confidence": 0.7,
        "reasons": "assured availability against a demand profile",
        "alternatives": ["hybrid", "solar"],
    }
    handler = job_handlers(TypeClassifier(pipeline.llm, "ergplan"))["classify_type"]
    handler(db, {"document_id": document.id, "created_by": "pytest", "is_fixture": True})
    db.expire_all()
    found = db.get(Document, document.id).classification
    assert found["tender_type"] == "fdre" and found["state"] == "unsure"
    assert found["confidence"] == 0.7 and found["alternatives"] == ["hybrid", "solar"]
    assert found["prompt_version"] == "v1"
    # the call went through the logged client with the classify prompt
    call = pipeline.sdk.calls[-1]
    assert call["output_format"].__name__ == "TenderTypeOutput"
    assert "classify" in str(call.get("system", "")).lower() or any(
        "page 1" in str(part) for part in call["messages"][0]["content"]
    )
    with pytest.raises(ValueError, match="not parsed"):
        TypeClassifier(pipeline.llm, "ergplan").classify(
            db, pipeline.upload(db, name="x.pdf").id, created_by="pytest"
        )


def test_a_tender_created_from_the_answer_carries_it_and_a_reviewer_can_settle_it(
    pipeline: Pipeline, db: Any
) -> None:
    tender = pipeline.tenders.create(
        db,
        tender_type="hybrid",
        issuing_agency="SECI",
        external_ref=None,
        title="Hybrid or FDRE?",
        created_by="pytest",
        type_source="model",
        type_state="unsure",
        type_confidence=0.65,
    )
    assert (tender.type_source, tender.type_state, tender.type_confidence) == (
        "model",
        "unsure",
        0.65,
    )
    with pytest.raises(TenderError, match="provenance"):
        pipeline.tenders.create(
            db, tender_type="solar", issuing_agency="x", external_ref=None, title="t",
            created_by="pytest", type_source="guess",
        )  # fmt: skip
    pipeline.tenders.set_type(db, tender, "fdre", created_by="reviewer@example.com")
    db.expire_all()
    tender = db.get(type(tender), tender.id)
    assert (tender.tender_type, tender.type_source, tender.type_state, tender.type_confidence) == (
        "fdre", "reviewer", "set", None,
    )  # fmt: skip
    from core.models import AuditLog

    row = db.scalars(select(AuditLog).where(AuditLog.action == "set_type")).one()
    assert row.before["tender_type"] == "hybrid" and row.after["tender_type"] == "fdre"
    # once the classifier runs again for this tender, a person's answer stands
    document = pipeline.parsed_document(db)
    handler = job_handlers(TypeClassifier(pipeline.llm, "ergplan"))["classify_type"]
    handler(db, {"document_id": document.id, "tender_id": tender.id, "is_fixture": True})
    db.expire_all()
    assert db.get(type(tender), tender.id).tender_type == "fdre"
    assert db.get(Document, document.id).classification["tender_type"] == "solar"
    assert db.scalar(select(Job).where(Job.kind == "classify_type")) is None, (
        "the handler ran directly"
    )
