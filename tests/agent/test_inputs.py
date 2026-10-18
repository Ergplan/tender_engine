"""What the agent is given: documents with the pages the section map names, the fields."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.inputs import InputsError, build_inputs, describe
from core.models import Page, Section
from core.services.extract import select_pages
from tender.models import Tender
from tender.services.summary import SUMMARY_FIELD
from tests.conftest import Pipeline
from tests.fixtures.tenders import AMENDMENT_PAGES, DEADLINE, EMD_STRUCTURED, make_tender, parsed


def test_every_document_of_the_versions_up_to_the_asked_one_is_offered_in_order(
    pipeline: Pipeline, db: Session, readable_tender: Tender
) -> None:
    compiled = pipeline.catalog.get(readable_tender.tender_type)
    one = build_inputs(db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 1)
    assert [d.number for d in one.documents] == [1]
    original = one.documents[0]
    assert (original.filename, original.version_no, original.version_kind, original.role) == (
        "rfs.pdf",
        1,
        "original",
        "rfs",
    )
    assert original.page_count == 3 and original.sections
    assert original.pages and set(original.pages) <= set(range(1, 4))

    # The pages are the union of the engine's own selection over the readable groups.
    sections = [
        (s, e, h, k)
        for s, e, h, k in db.execute(
            select(Section.start_page, Section.end_page, Section.heading, Section.kind).where(
                Section.document_id == original.document_id
            )
        )
    ]
    texts = dict(
        db.execute(
            select(Page.page_no, Page.text).where(Page.document_id == original.document_id)
        ).all()
    )
    expected: set[int] = set()
    for group in compiled.schema.groups:
        if group.derived:
            continue
        expected.update(
            select_pages(
                group.routing,
                sections,
                texts,
                max_pages=min(
                    group.max_pages or pipeline.settings.extract_max_pages_per_group,
                    pipeline.settings.extract_max_pages_per_group,
                ),
                fallback_pages=pipeline.settings.extract_max_pages_per_call,
                keyword_pages=pipeline.settings.extract_keyword_pages,
            )
        )
    assert set(original.pages) == expected

    amendment = parsed(pipeline, db, AMENDMENT_PAGES, "amendment-01.pdf")
    pipeline.tenders.add_version(
        db, readable_tender, amendment, "amendment", date(2026, 3, 20), created_by="pytest"
    )
    two = build_inputs(db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 2)
    assert [(d.number, d.filename, d.version_no) for d in two.documents] == [
        (1, "rfs.pdf", 1),
        (2, "amendment-01.pdf", 2),
    ]
    assert two.document(2) is not None and two.document(2).version_kind == "amendment"
    assert two.document(3) is None
    # Asking for version 1 again leaves the amendment out.
    assert [
        d.number
        for d in build_inputs(
            db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 1
        ).documents
    ] == [1]


def test_derived_groups_and_the_summary_are_not_asked_for(
    pipeline: Pipeline, db: Session, readable_tender: Tender
) -> None:
    compiled = pipeline.catalog.get(readable_tender.tender_type)
    inputs = build_inputs(db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 1)
    derived = {g.name for g in compiled.schema.groups if g.derived}
    assert derived, "the power pack has derived groups"
    assert not derived & {g.name for g in inputs.groups}
    assert SUMMARY_FIELD not in inputs.field_paths
    assert DEADLINE in inputs.field_paths and inputs.field(DEADLINE) is not None
    assert inputs.field("core.nope.x") is None
    readable = {
        f.path
        for g in compiled.schema.groups
        if not g.derived
        for f in compiled.schema.fields_in(g.name)
    }
    assert set(inputs.field_paths) == readable - {SUMMARY_FIELD}
    assert len(inputs.field_paths) == len(set(inputs.field_paths))


def test_an_unparsed_document_or_a_missing_version_is_refused(
    pipeline: Pipeline, db: Session, readable_tender: Tender
) -> None:
    compiled = pipeline.catalog.get(readable_tender.tender_type)
    with pytest.raises(InputsError, match="no version 2"):
        build_inputs(db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 2)

    bare = make_tender(pipeline, db)
    uploaded = pipeline.upload(db, None, "later.pdf")  # never parsed
    pipeline.tenders.add_version(db, bare, uploaded, "original", None, created_by="pytest")
    with pytest.raises(InputsError, match="not parsed"):
        build_inputs(db, pipeline.tenders, compiled, pipeline.settings, bare, 1)


def test_the_brief_names_documents_pages_and_every_field(
    pipeline: Pipeline, db: Session, readable_tender: Tender
) -> None:
    compiled = pipeline.catalog.get(readable_tender.tender_type)
    inputs = build_inputs(db, pipeline.tenders, compiled, pipeline.settings, readable_tender, 1)
    brief = describe(inputs)
    assert brief.startswith("Tender type: solar")
    assert "- Document 1: rfs.pdf — version 1 (original, role rfs), 3 pages." in brief
    assert "Pages the section map names:" in brief
    for path in inputs.field_paths:
        assert f"- {path} (" in brief
    assert SUMMARY_FIELD not in brief
    structured = next(line for line in brief.splitlines() if f"- {EMD_STRUCTURED} (" in line)
    assert "Object with keys:" in structured and "rate_inr_per_mw" in structured
    assert "components" in structured and "list of objects with keys" in structured
    assert "one of per_mw/per_component" in structured
    deadline = next(line for line in brief.splitlines() if f"- {DEADLINE} (" in line)
    assert "(date" in deadline
