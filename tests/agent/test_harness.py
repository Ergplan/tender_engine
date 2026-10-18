"""The three tools and the judge of a finding."""

from agents import ToolOutputImage, ToolOutputText
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.harness import Harness, Quote
from agent.inputs import build_inputs
from agent.models import AgentFinding, AgentRun
from agent.service import AgentPassService
from core.models import AuditLog
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD

DEADLINE_QUOTE = "The last date of bid submission is 30.03.2026 at 15:00 hrs."


def harness_for(
    pipeline: Pipeline, db: Session, service: AgentPassService, tender: Tender
) -> Harness:
    run = service.start(db, tender, created_by="pytest", is_fixture=True)
    run.status = "running"
    db.commit()
    compiled = pipeline.catalog.get(tender.tender_type)
    inputs = build_inputs(db, pipeline.tenders, compiled, pipeline.settings, tender, 1)
    return Harness(db, pipeline.settings, pipeline.schemas, pipeline.storage, run, inputs)


def findings(db: Session, run: AgentRun) -> list[AgentFinding]:
    return list(
        db.scalars(
            select(AgentFinding)
            .where(AgentFinding.agent_run_id == run.id)
            .order_by(AgentFinding.ordinal)
        )
    )


def test_read_pages_returns_text_marks_pages_read_and_caps_a_call(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    harness = harness_for(pipeline, db, service, readable_tender)
    out = harness.read_pages(1, [2, 9, 2])
    texts = [o.text for o in out if isinstance(o, ToolOutputText)]
    assert any("[9] do not exist" in t for t in texts)
    assert any("Document 1, page 2" in t and "30.03.2026" in t for t in texts)
    assert not any(isinstance(o, ToolOutputImage) for o in out)
    assert harness.read == {1: {2}}
    assert harness.run.pages_read == {"1": [2]}

    with_images = harness.read_pages(1, [1], images=True)
    image = next(o for o in with_images if isinstance(o, ToolOutputImage))
    assert image.image_url and image.image_url.startswith("data:image/png;base64,")

    pipeline.settings.agent_max_pages_per_read = 1
    capped = harness.read_pages(1, [1, 2, 3])
    assert any(
        "At most 1 pages per call" in o.text for o in capped if isinstance(o, ToolOutputText)
    )
    assert harness.read[1] == {1, 2}
    assert "no document 7" in harness.read_pages(7, [1])[0].text


def test_search_text_finds_pages_across_documents(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    harness = harness_for(pipeline, db, service, readable_tender)
    hits = harness.search_text("earnest money")
    assert hits.startswith("Document 1 page 3:") and "Earnest Money Deposit (EMD)" in hits
    assert harness.search_text("nothing of the kind here") == (
        "No page contains 'nothing of the kind here'."
    )
    assert "at least three" in harness.search_text("ab")
    assert harness.read == {}, "searching does not count as reading"


def test_a_finding_needs_a_read_page_a_located_quote_and_a_typed_value(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    harness = harness_for(pipeline, db, service, readable_tender)
    quote = [Quote(document_no=1, page_no=2, quote=DEADLINE_QUOTE)]

    nothing_read = harness.submit_finding(EMD, "null", 0.0, "looked everywhere", [])
    assert "no page has been read yet" in nothing_read
    harness.read_pages(1, [1])
    unread = harness.submit_finding(DEADLINE, '"2026-03-30"', 0.9, "the bid sheet", quote)
    assert "was not read" in unread
    harness.read_pages(1, [2])
    assert "no rationale" in harness.submit_finding(DEADLINE, '"2026-03-30"', 0.9, "  ", quote)
    assert "page 9 does not exist" in harness.submit_finding(
        DEADLINE, '"2026-03-30"', 0.9, "r", [Quote(document_no=1, page_no=9, quote=DEADLINE_QUOTE)]
    )
    assert "document 4 page 2 does not exist" in harness.submit_finding(
        DEADLINE, '"2026-03-30"', 0.9, "r", [Quote(document_no=4, page_no=2, quote=DEADLINE_QUOTE)]
    )

    paraphrased = harness.submit_finding(
        DEADLINE,
        '"2026-03-30"',
        0.9,
        "the bid sheet",
        [Quote(document_no=1, page_no=2, quote="bids are due on the thirtieth of March")],
    )
    assert "not found on document 1 page 2" in paraphrased

    wrong_page = harness.submit_finding(
        DEADLINE, '"2026-03-30"', 0.9, "x", [Quote(document_no=1, page_no=3, quote=DEADLINE_QUOTE)]
    )
    assert "page 3 was not read" in wrong_page

    untyped = harness.submit_finding(DEADLINE, '"end of March"', 0.9, "the bid sheet", quote)
    assert untyped.startswith(f"{DEADLINE}: rejected")

    no_evidence = harness.submit_finding(DEADLINE, '"2026-03-30"', 0.9, "the bid sheet", [])
    assert "needs evidence" in no_evidence
    assert "unknown field" in harness.submit_finding("core.nope.x", "1", 0.5, "r", quote)
    assert "confidence must be" in harness.submit_finding(DEADLINE, "1", 1.5, "r", quote)

    accepted = harness.submit_finding(DEADLINE, '"30.03.2026"', 0.9, "the bid sheet", quote)
    assert accepted == f'{DEADLINE}: accepted, "2026-03-30" with evidence on document 1 page 2.'

    rows = findings(db, harness.run)
    assert [r.status for r in rows] == ["rejected"] * 11 + ["accepted"]
    assert [r.ordinal for r in rows] == list(range(1, 13))
    paraphrase = rows[5]
    assert paraphrase.reason and "not found" in paraphrase.reason
    assert paraphrase.evidence[0]["char_start"] is None and paraphrase.evidence[0]["quote"]
    standing = rows[-1]
    assert standing.value == "2026-03-30" and standing.value_type == "date"
    span = standing.evidence[0]
    assert span["document_id"] and span["page_no"] == 2 and span["char_start"] is not None
    assert span["bbox"] and span["match_method"]
    assert harness.standing == {DEADLINE: standing.id}
    audited = db.scalars(
        select(AuditLog).where(AuditLog.table_name == "agent_finding", AuditLog.action == "insert")
    ).all()
    assert len(audited) == 12 and all(a.actor == "agent_pass" for a in audited)


def test_a_later_finding_supersedes_the_earlier_and_null_is_not_found_or_withdrawn(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    harness = harness_for(pipeline, db, service, readable_tender)
    harness.read_pages(1, [2, 3])
    quote = [Quote(document_no=1, page_no=2, quote=DEADLINE_QUOTE)]
    harness.submit_finding(DEADLINE, '"30.03.2026"', 0.9, "first", quote)
    again = harness.submit_finding(DEADLINE, '"2026-03-30"', 0.95, "again", quote)
    assert again.startswith(f"{DEADLINE}: accepted")
    first, second = findings(db, harness.run)
    assert (first.status, second.status) == ("superseded", "accepted")

    assert harness.submit_finding(EMD, "null", 0.0, "looked in section 3", []) == (
        f"{EMD}: recorded as not found."
    )
    removed = harness.submit_finding(
        "core.guarantees.pbg_per_mw_inr",
        "null",
        0.8,
        "struck out",
        [Quote(document_no=1, page_no=3, quote="Performance Bank Guarantee (PBG) of INR 2320000")],
    )
    assert "withdrawn" in removed
    by_path = {f.field_path: f for f in findings(db, harness.run) if f.status != "superseded"}
    assert by_path[EMD].status == "not_found" and by_path[EMD].evidence == []
    assert by_path["core.guarantees.pbg_per_mw_inr"].status == "withdrawn"
    assert set(harness.unsubmitted()) == set(harness.inputs.field_paths) - {
        DEADLINE,
        EMD,
        "core.guarantees.pbg_per_mw_inr",
    }


def test_finish_sums_the_logged_turns_and_records_the_pages_read(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    harness = harness_for(pipeline, db, service, readable_tender)
    harness.read_pages(1, [1])
    run = harness.finish("done", None)
    assert (run.status, run.turns, run.tokens_in, run.cost_usd) == ("done", 0, 0, 0)
    assert run.pages_read == {"1": [1]} and run.finished_at is not None
    closing = db.scalars(
        select(AuditLog).where(AuditLog.table_name == "agent_run", AuditLog.action == "finish")
    ).one()
    assert closing.after["unsubmitted"] == harness.inputs.field_paths
