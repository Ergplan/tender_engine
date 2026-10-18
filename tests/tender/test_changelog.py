"""The changelog across versions: facts changed, with evidence; unreviewed versions pending."""

from sqlalchemy.orm import Session

from tender.services.changelog import changelog
from tests.conftest import Pipeline
from tests.fixtures.published import complete_round
from tests.fixtures.tenders import DEADLINE, EMD, amended_tender
from tests.tender.test_rounds import reviewed_tender


def test_the_changelog_lists_what_each_reviewed_version_changed_and_what_is_pending(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    first = changelog(db, pipeline.catalog, tender)
    assert first.reviewed_version == 1 and [v.version_no for v in first.versions] == [1]
    (original,) = first.versions
    assert original.reviewed and original.kind == "original" and original.documents == ["rfs.pdf"]
    by_path = {c.field_path: c for c in original.changes}
    assert by_path[DEADLINE].before is None and by_path[DEADLINE].after == "2026-03-30"
    assert by_path[DEADLINE].evidence and by_path[DEADLINE].evidence[0].page_no == 2
    assert (
        by_path[DEADLINE].decided_at is not None and by_path[DEADLINE].reviewer_role == "reviewer"
    )
    assert all(c.field_path != "core.summary.plain_english_summary" for c in original.changes)

    amended_tender(pipeline, db, tender)
    pending = changelog(db, pipeline.catalog, tender)
    assert [v.version_no for v in pending.versions] == [1, 2]
    second = pending.versions[1]
    assert not second.reviewed and second.changes == [] and second.pending == [DEADLINE]
    assert second.kind == "amendment" and second.documents == ["amendment-01.pdf"]

    complete_round(pipeline, db, tender)
    done = changelog(db, pipeline.catalog, tender)
    assert done.reviewed_version == 2
    second = done.versions[1]
    assert second.reviewed and second.pending == []
    (change,) = [c for c in second.changes if c.field_path == DEADLINE]
    assert (change.before, change.after, change.withdrawn) == ("2026-03-30", "2026-04-15", False)
    assert change.evidence[0].filename == "amendment-01.pdf" and change.evidence[0].page_no == 1
    # A field the amendment did not touch is not listed as a change of it.
    assert all(c.field_path != EMD for c in second.changes)
