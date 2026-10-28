"""The snapshot (contract v1) and the extraction status (Stage 7, Block 6 a)."""

from sqlalchemy.orm import Session

from tender.services.snapshot import CONTRACT_VERSION, tender_snapshot
from tender.services.status import stage_of, tender_status
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD, PBG, amended_tender, extracted_tender, make_tender
from tests.tender.test_rounds import reviewed_tender


def _snapshot(pipeline: Pipeline, db: Session, tender_id: str):  # type: ignore[no-untyped-def]
    from tender.models import Tender

    tender = db.get(Tender, tender_id)
    assert tender is not None
    return tender_snapshot(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender)


def test_machine_readings_then_approved_facts_with_their_evidence(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    snap = _snapshot(pipeline, db, tender.id)
    assert snap.contract_version == CONTRACT_VERSION
    by_path = {f.path: f for f in snap.fields}
    emd = by_path[EMD]
    assert (emd.state, emd.source, emd.value) == ("value", "machine", 928000)
    assert emd.confidence == 0.9 and emd.version_no == 1 and emd.version_kind == "original"
    assert emd.evidence and emd.evidence[0].page_no == 3 and emd.evidence[0].located
    assert emd.evidence[0].filename == "rfs.pdf"
    assert snap.approved == 0 and snap.machine > 0 and snap.not_stated > 0
    unread = next(f for f in snap.fields if f.state == "not_stated")
    assert unread.source == "none" and unread.value is None
    assert "authoritative" in snap.authority_note
    # Reviewed: the decided fields are approved, with no confidence, same evidence.
    tender_id, _ = reviewed_tender(pipeline, db)
    snap = _snapshot(pipeline, db, tender_id)
    by_path = {f.path: f for f in snap.fields}
    assert by_path[EMD].source == "approved" and by_path[EMD].confidence is None
    assert by_path[EMD].value == 928000 and by_path[EMD].evidence[0].page_no == 3
    assert snap.approved > 0 and snap.reviewed_version == 1 and snap.publication == "published"


def test_an_amendment_moves_a_field_to_its_version(pipeline: Pipeline, db: Session) -> None:
    tender = extracted_tender(pipeline, db)
    before = {f.path: f for f in _snapshot(pipeline, db, tender.id).fields}[DEADLINE]
    assert before.version_no == 1 and before.value == "2026-03-30"
    amended_tender(pipeline, db, tender)
    after = {f.path: f for f in _snapshot(pipeline, db, tender.id).fields}
    assert after[DEADLINE].version_no == 2 and after[DEADLINE].version_kind == "amendment"
    assert after[DEADLINE].value == "2026-04-15"
    assert after[PBG].version_no == 1, "a field the amendment did not touch keeps its version"


def test_status_follows_the_chain(pipeline: Pipeline, db: Session) -> None:
    tender = make_tender(pipeline, db)
    status = tender_status(db, pipeline.catalog, pipeline.tenders, tender)
    assert status.versions == [] and not status.extraction_done
    tender = extracted_tender(pipeline, db)
    status = tender_status(db, pipeline.catalog, pipeline.tenders, tender)
    assert status.extraction_done and status.versions[0].stage == "validated"
    assert status.versions[0].documents[0].status == "parsed"
    assert status.versions[0].runs and status.versions[0].pending_jobs == []
    assert status.tender_type == "solar" and status.publication == "not_published"


def test_stage_of_covers_every_state() -> None:
    assert stage_of(["uploaded"], [], set()) == "parsing"
    assert stage_of(["failed"], [], set()) == "failed"
    assert stage_of(["parsed"], [], {"section_map"}) == "mapping"
    assert stage_of(["parsed"], [], {"classify_type"}) == "mapping"
    assert stage_of(["parsed"], [], {"tender_extract"}) == "extracting"
    assert stage_of(["parsed"], ["queued"], {"extract"}) == "extracting"
    assert stage_of(["parsed"], ["validated"], {"tender_summary"}) == "extracting"
    assert stage_of(["parsed"], ["validated"], {"index_document"}) == "validated"
    assert stage_of(["parsed"], ["validated", "failed"], set()) == "failed"
    assert stage_of(["parsed"], [], set()) == "submitted"
