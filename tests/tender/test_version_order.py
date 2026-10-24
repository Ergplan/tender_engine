"""Block 3 b: a version keeps its arrival number and is projected in date order, so an
amendment that arrives late slots in where its date puts it, with no reseed. The Ramagiri
case: Amendment-01 arrived after Amendment-02 had been ingested."""

from datetime import date
from typing import Any

from tender.models import TenderVersion
from tender.services.tenders import ordered_versions
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf


def test_ordered_versions_puts_the_original_first_then_dates_then_undated() -> None:
    def v(no: int, kind: str, issued: date | None) -> TenderVersion:
        return TenderVersion(version_no=no, kind=kind, issued_on=issued, tender_id="t")

    original = v(1, "original", date(2026, 7, 1))
    a2 = v(2, "amendment", date(2026, 8, 3))
    a1_late = v(3, "amendment", date(2026, 7, 17))
    undated = v(4, "clarification", None)
    a3 = v(5, "corrigendum", date(2026, 10, 8))
    assert [x.version_no for x in ordered_versions([a3, undated, a2, a1_late, original])] == [
        1, 3, 2, 5, 4,
    ]  # fmt: skip
    # the original is first even when a later version carries an earlier date
    early = v(2, "corrigendum", date(2026, 1, 1))
    assert [x.version_no for x in ordered_versions([early, original])] == [1, 2]


def test_the_ramagiri_case_slots_the_late_amendment_before_the_earlier_arrival(
    pipeline: Pipeline, db: Any
) -> None:
    tenders = pipeline.tenders
    tender = tenders.create(
        db, tender_type="bess", issuing_agency="SECI", external_ref="SECI/C&P/OP/11/0002/26-27",
        title="BoS Tender (Package-1) for 70 MW Ramagiri", created_by="pytest", slug="ramagiri",
    )  # fmt: skip
    original = tenders.add_version(
        db, tender, pipeline.upload(db, name="rfs.pdf"), "original", date(2026, 7, 1),
        created_by="pytest",
    )  # fmt: skip
    a2 = tenders.add_version(
        db, tender, pipeline.upload(db, make_pdf([["Amendment-02"]]), name="a2.pdf"),
        "amendment", date(2026, 8, 3), created_by="pytest",
    )  # fmt: skip
    assert tender.current_version_id == a2.id
    a1 = tenders.add_version(
        db, tender, pipeline.upload(db, make_pdf([["Amendment-01"]]), name="a1.pdf"),
        "amendment", date(2026, 7, 17), created_by="pytest",
    )  # fmt: skip
    assert (original.version_no, a2.version_no, a1.version_no) == (1, 2, 3), "arrival numbers"
    assert [e.version.version_no for e in tenders.versions(db, tender)] == [1, 3, 2], "date order"
    assert tender.current_version_id == a2.id, "the latest dated version stays current"
    assert a1.supersedes_version_id == a2.id, "arrival chain is history, not order"
    a3 = tenders.add_version(
        db, tender, pipeline.upload(db, make_pdf([["Amendment-03"]]), name="a3.pdf"),
        "corrigendum", date(2026, 10, 8), created_by="pytest",
    )  # fmt: skip
    assert tender.current_version_id == a3.id
    assert [e.version.version_no for e in tenders.versions(db, tender)] == [1, 3, 2, 4]
