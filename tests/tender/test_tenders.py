"""TenderService: versions, extraction of a version, carry-forward and the current view."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AuditLog, Candidate, CanonicalFact, ExtractionRun, ValidationResult
from tender.models import TenderFieldDef, TenderVersionDocument
from tender.services.current_view import current_view
from tender.services.field_defs import sync_field_defs
from tender.services.tenders import TenderError
from tests.conftest import Pipeline
from tests.fixtures.tenders import (
    AMENDMENT_PAGES,
    DEADLINE,
    EMD,
    PBG,
    RFS_PAGES,
    amended_tender,
    extracted_tender,
    make_tender,
    parsed,
)


def live(db: Session, tender_id: str, version_no: int) -> dict[str, Candidate]:
    rows = db.scalars(
        select(Candidate)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(
            ExtractionRun.object_type == "tender",
            ExtractionRun.object_id == tender_id,
            ExtractionRun.object_version == version_no,
            Candidate.status != "superseded",
        )
    )
    return {row.field_path: row for row in rows}


def test_create_refuses_unknown_types_and_empty_names(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(TenderError, match="unknown tender type"):
        make_tender(pipeline, db, "nuclear")
    with pytest.raises(TenderError, match="needs an issuing agency"):
        pipeline.tenders.create(
            db,
            tender_type="solar",
            issuing_agency=" ",
            external_ref=None,
            title="T",
            created_by="x",
        )
    tender = make_tender(pipeline, db)
    assert (tender.status, tender.current_version_id) == ("ingested", None)
    assert pipeline.tenders.get(db, tender.id).id == tender.id
    with pytest.raises(LookupError):
        pipeline.tenders.get(db, "0" * 32)


def test_versions_are_numbered_linked_and_audited(pipeline: Pipeline, db: Session) -> None:
    tender = make_tender(pipeline, db)
    rfs = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    amendment = parsed(pipeline, db, AMENDMENT_PAGES, "amendment.pdf")
    with pytest.raises(TenderError, match="first version of a tender is the original"):
        pipeline.tenders.add_version(db, tender, amendment, "amendment", None, created_by="Asha")
    first = pipeline.tenders.add_version(db, tender, rfs, "original", None, created_by="Asha")
    with pytest.raises(TenderError, match="already has its original version"):
        pipeline.tenders.add_version(db, tender, amendment, "original", None, created_by="Asha")
    with pytest.raises(TenderError, match="unknown version kind"):
        pipeline.tenders.add_version(db, tender, amendment, "rewrite", None, created_by="Asha")
    second = pipeline.tenders.add_version(
        db,
        tender,
        amendment,
        "amendment",
        date(2026, 3, 20),
        created_by="Asha",
        summary_of_change="Bid deadline extended.",
    )
    assert (first.version_no, first.kind, first.supersedes_version_id) == (1, "original", None)
    assert (second.version_no, second.supersedes_version_id) == (2, first.id)
    assert second.issued_on == date(2026, 3, 20)
    db.refresh(tender)
    assert tender.current_version_id == second.id
    entries = pipeline.tenders.versions(db, tender)
    assert [(e.version.version_no, [link.role for link, _ in e.documents]) for e in entries] == [
        (1, ["rfs"]),
        (2, ["amendment"]),
    ]
    audits = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.table_name == "tender_version")
            .order_by(AuditLog.at, AuditLog.id)
        )
    )
    assert sorted((a.action, a.row_id, a.actor) for a in audits) == sorted(
        [
            ("insert", first.id, "Asha"),
            ("add_document", first.id, "Asha"),
            ("insert", second.id, "Asha"),
            ("add_document", second.id, "Asha"),
        ]
    )


def test_a_further_document_is_attached_to_an_existing_version_once(
    pipeline: Pipeline, db: Session
) -> None:
    tender = make_tender(pipeline, db)
    rfs = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    ppa = parsed(
        pipeline, db, [["DRAFT POWER PURCHASE AGREEMENT", "Article 10: tariff"]], "ppa.pdf"
    )
    pipeline.tenders.add_version(db, tender, rfs, "original", None, created_by="pytest")
    for _ in range(2):
        pipeline.tenders.attach_document(db, tender, 1, ppa, "ppa", created_by="pytest")
    (entry,) = pipeline.tenders.versions(db, tender)
    assert [link.role for link, _ in entry.documents] == ["rfs", "ppa"]
    with pytest.raises(TenderError, match="unknown document role"):
        pipeline.tenders.attach_document(db, tender, 1, ppa, "appendix", created_by="pytest")
    for role in ("amendment", "clarification"):
        with pytest.raises(TenderError, match="add it as a new version"):
            pipeline.tenders.attach_document(db, tender, 1, ppa, role, created_by="pytest")
    with pytest.raises(LookupError):
        pipeline.tenders.attach_document(db, tender, 7, ppa, "ppa", created_by="pytest")
    assert len(list(db.scalars(select(TenderVersionDocument)))) == 2


def test_extraction_of_the_original_reads_each_document_for_its_roles_groups(
    pipeline: Pipeline, db: Session
) -> None:
    tender = make_tender(pipeline, db)
    rfs = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    ppa = parsed(
        pipeline, db, [["DRAFT POWER PURCHASE AGREEMENT", "Article 10: tariff"]], "ppa.pdf"
    )
    pipeline.tenders.add_version(db, tender, rfs, "original", None, created_by="pytest")
    pipeline.tenders.attach_document(db, tender, 1, ppa, "ppa", created_by="pytest")
    runs = pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    by_document = {run.document_id: run for run in runs}
    assert by_document[rfs.id].groups == sorted(
        s.name for s in pipeline.catalog.get("solar").sections
    )
    assert by_document[ppa.id].groups == ["commercial", "penalties"]
    assert {(r.object_type, r.object_id, r.object_version, r.schema_name) for r in runs} == {
        ("tender", tender.id, 1, "tender.solar")
    }
    assert pipeline.tenders.refresh_status(db, tender) == "ingested"
    pipeline.runner.run_until_idle()
    assert pipeline.tenders.refresh_status(db, tender) == "extracted"
    state = pipeline.review_state.for_object(db, "tender", tender.id)
    assert state.total == len(pipeline.catalog.get("solar").fields) and len(state.runs) == 2


def test_extraction_needs_a_version_and_parsed_documents(pipeline: Pipeline, db: Session) -> None:
    tender = make_tender(pipeline, db)
    with pytest.raises(TenderError, match="no version yet"):
        pipeline.tenders.start_extraction(db, tender, created_by="pytest")
    unparsed = pipeline.upload(db, name="rfs.pdf")
    pipeline.tenders.add_version(db, tender, unparsed, "original", None, created_by="pytest")
    with pytest.raises(TenderError, match="not parsed yet"):
        pipeline.tenders.start_extraction(db, tender, created_by="pytest")
    with pytest.raises(LookupError):
        pipeline.tenders.start_extraction(db, tender, version_no=4, created_by="pytest")


def test_candidates_of_a_tender_carry_the_version_and_namespaced_paths(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    candidates = live(db, tender.id, 1)
    assert candidates[EMD].value == 928000 and candidates[EMD].status == "validated"
    assert candidates[DEADLINE].value == "30.03.2026"
    assert candidates[EMD].prompt_name == "extract/guarantees"
    assert candidates["core.summary.plain_english_summary"].prompt_name == "summary"
    rules = {
        row.rule_name: row.passed
        for row in db.scalars(
            select(ValidationResult).where(ValidationResult.candidate_id == candidates[EMD].id)
        )
    }
    assert rules["emd_pbg_within_10x"] is True and rules["range"] is True
    assert "later_version_evidence" not in rules


def test_an_amendment_is_extracted_only_where_it_touches_the_tender(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    amended_tender(pipeline, db, tender)
    (run,) = db.scalars(select(ExtractionRun).where(ExtractionRun.object_version == 2))
    assert run.groups == ["key_dates"] and run.status == "validated"
    second = live(db, tender.id, 2)
    assert second[DEADLINE].value == "15.04.2026" and second[DEADLINE].status == "validated"
    assert EMD not in second, "the amendment says nothing about guarantees"
    # Version 1 keeps its own candidates: a new version never touches an earlier one.
    assert live(db, tender.id, 1)[DEADLINE].value == "30.03.2026"
    rule = db.scalars(
        select(ValidationResult).where(
            ValidationResult.candidate_id == second[DEADLINE].id,
            ValidationResult.rule_name == "later_version_evidence",
        )
    ).one()
    assert rule.passed and rule.message == "evidence comes from a document of version 2"


def test_corrigendum_carry_forward_leaves_untouched_facts_and_their_evidence_unchanged(
    pipeline: Pipeline, db: Session
) -> None:
    """A version that changes the bid deadline leaves the EMD's canonical fact and its
    evidence exactly as they were, and the current view shows which version set each."""
    tender = extracted_tender(pipeline, db)
    first = live(db, tender.id, 1)
    for path in (EMD, DEADLINE):
        pipeline.approvals.approve(
            db, candidate_id=first[path].id, decision="approved", reviewer="Asha"
        )
    emd_before = db.scalars(select(CanonicalFact).where(CanonicalFact.field_path == EMD)).one()
    snapshot = (emd_before.id, emd_before.value, emd_before.evidence, emd_before.object_version)

    amended_tender(pipeline, db, tender)
    view = {f.field_path: f for f in current_view(db, pipeline.catalog, tender).fields}
    assert (view[DEADLINE].value, view[DEADLINE].version_no) == ("2026-03-30", 1), (
        "an unapproved candidate of the amendment changes nothing"
    )
    second = live(db, tender.id, 2)
    pipeline.approvals.approve(
        db, candidate_id=second[DEADLINE].id, decision="approved", reviewer="Asha"
    )
    db.expire_all()

    emd_after = db.scalars(select(CanonicalFact).where(CanonicalFact.field_path == EMD)).one()
    assert (emd_after.id, emd_after.value, emd_after.evidence, emd_after.object_version) == snapshot
    assert emd_after.is_current is True and emd_after.superseded_at is None
    deadlines = {
        fact.object_version: fact
        for fact in db.scalars(select(CanonicalFact).where(CanonicalFact.field_path == DEADLINE))
    }
    assert deadlines[1].value == "2026-03-30" and deadlines[1].is_current is True
    assert deadlines[2].value == "2026-04-15"
    documents = {
        entry.version.version_no: entry.documents[0][1].id
        for entry in pipeline.tenders.versions(db, tender)
    }
    assert {span["document_id"] for span in deadlines[2].evidence} == {documents[2]}
    assert {span["document_id"] for span in emd_after.evidence} == {documents[1]}

    result = current_view(db, pipeline.catalog, tender)
    view = {f.field_path: f for f in result.fields}
    assert (view[DEADLINE].value, view[DEADLINE].version_no, view[DEADLINE].version_kind) == (
        "2026-04-15",
        2,
        "amendment",
    )
    assert (view[EMD].value, view[EMD].version_no, view[EMD].version_kind) == (
        928000,
        1,
        "original",
    )
    assert view[EMD].canonical_fact_id == snapshot[0] and view[EMD].evidence == snapshot[2]
    assert (view[PBG].decided, view[PBG].value, view[PBG].version_no) == (False, None, None)
    assert (result.current_version_no, result.decided) == (2, 2)
    assert pipeline.tenders.refresh_status(db, tender) == "in_review"


def test_a_later_version_that_does_not_state_a_field_does_not_blank_the_earlier_fact(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    first = live(db, tender.id, 1)
    pipeline.approvals.approve(
        db, candidate_id=first[DEADLINE].id, decision="approved", reviewer="Asha"
    )
    pipeline.sdk.answers = {}
    amendment = parsed(pipeline, db, AMENDMENT_PAGES, "amendment.pdf")
    pipeline.tenders.add_version(db, tender, amendment, "amendment", None, created_by="pytest")
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
    empty = live(db, tender.id, 2)[DEADLINE]
    assert empty.value is None
    pipeline.approvals.approve(
        db, candidate_id=empty.id, decision="not_in_document", reviewer="Asha"
    )
    view = {f.field_path: f for f in current_view(db, pipeline.catalog, tender).fields}
    assert (view[DEADLINE].value, view[DEADLINE].version_no) == ("2026-03-30", 1)


def test_a_value_for_a_later_version_with_evidence_from_the_original_fails_the_corrigendum_rule(
    pipeline: Pipeline, db: Session
) -> None:
    """The rule guards against a run that reads the wrong document for a version."""
    tender = extracted_tender(pipeline, db)
    amendment = parsed(pipeline, db, AMENDMENT_PAGES, "amendment.pdf")
    pipeline.tenders.add_version(db, tender, amendment, "amendment", None, created_by="pytest")
    original = pipeline.tenders.versions(db, tender)[0].documents[0][1]
    run = pipeline.extract.start_run(
        db,
        document_id=original.id,
        schema_name="tender.solar",
        schema_version="v1",
        prompt_version="v1",
        created_by="pytest",
        object_type="tender",
        object_id=tender.id,
        object_version=2,
        groups=["guarantees"],
        is_fixture=True,
    )
    pipeline.runner.run_until_idle()
    emd = db.scalars(
        select(Candidate).where(Candidate.extraction_run_id == run.id, Candidate.field_path == EMD)
    ).one()
    assert emd.status == "needs_review"
    rule = db.scalars(
        select(ValidationResult).where(
            ValidationResult.candidate_id == emd.id,
            ValidationResult.rule_name == "later_version_evidence",
        )
    ).one()
    assert not rule.passed and "that version's own document" in rule.message


def test_field_defs_are_generated_from_the_packs_and_rewritten_only_on_change(
    pipeline: Pipeline, db: Session
) -> None:
    assert sync_field_defs(db, pipeline.catalog, "ergplan") is True
    assert sync_field_defs(db, pipeline.catalog, "ergplan") is False
    rows = list(db.scalars(select(TenderFieldDef).where(TenderFieldDef.tender_type == "fdre")))
    assert len(rows) == len(pipeline.catalog.get("fdre").fields)
    by_path = {row.field_path: row for row in rows}
    core_row = by_path["core.key_dates.bid_submission_deadline"]
    assert (core_row.namespace, core_row.domain, core_row.subdomain, core_row.section) == (
        "core",
        None,
        None,
        "key_dates",
    )
    assert core_row.required is True and core_row.value_type == "date"
    sector_row = by_path["sector.power.fdre.demand_profile"]
    assert (sector_row.namespace, sector_row.domain, sector_row.subdomain) == (
        "sector",
        "power",
        "fdre",
    )
    stale = by_path["core.identity.title"]
    stale.label = "Changed by hand"
    db.commit()
    assert sync_field_defs(db, pipeline.catalog, "ergplan") is True
    db.expire_all()
    assert (
        db.scalars(
            select(TenderFieldDef.label).where(
                TenderFieldDef.tender_type == "fdre",
                TenderFieldDef.field_path == "core.identity.title",
            )
        ).one()
        == "Title"
    )
