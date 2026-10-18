"""The three-way comparison: the six classes, the agent's findings read beside the engine's
candidates and the reviewer's gold, the report and the emphasis file."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.models import AgentFinding, AgentRun
from core.schemas import FieldDef, KeyDef, SchemaRegistry
from evals import threeway
from evals.gold import GoldField, GoldRecord, build_gold
from evals.runner import CandidateUnderTest, FieldScore
from evals.threeway import (
    ThreeWay,
    agent_findings,
    classify,
    compare_all,
    compare_record,
    emphasis_of,
    low_review_fields,
    render_report,
    summarise,
    write_threeway,
)
from tender.models import Tender
from tender.services.packs import build_registry
from tests.conftest import Pipeline
from tests.evals.test_gold import DEADLINE, EMD, completed_review

AGENCY = "core.identity.issuing_agency"
EMD_STRUCTURED = "core.guarantees.emd_structured"


@pytest.fixture(scope="module")
def registry() -> SchemaRegistry:
    return build_registry()[0]


def fs(
    outcome: str, value_type: str = "decimal", candidate: Any = None, gold: Any = 200
) -> FieldScore:
    return FieldScore(
        slug="t",
        tender_type="solar",
        issuing_agency="SECI",
        field_path="core.x.y",
        section="x",
        value_type=value_type,
        required=True,
        outcome=outcome,  # type: ignore[arg-type]
        gold_value=gold,
        candidate_value=candidate,
    )


def definition(value_type: str = "decimal", **extra: Any) -> FieldDef:
    return FieldDef(path="core.x.y", label="Y", group="x", value_type=value_type, **extra)


def test_classify_names_every_class(registry: SchemaRegistry) -> None:
    d = definition()
    assert classify(fs("correct", candidate=200), fs("correct", candidate=200), d, registry) == (
        "all_agree"
    )
    assert classify(
        fs("correct_abstention", candidate=None), fs("correct_abstention"), d, registry
    ) == ("all_agree")
    assert classify(fs("correct", candidate=200), fs("wrong_value", candidate=1), d, registry) == (
        "engine_right_agent_wrong"
    )
    assert classify(fs("missing"), fs("correct", candidate=200), d, registry) == (
        "agent_right_engine_wrong"
    )
    assert classify(fs("missing"), fs("missing"), d, registry) == "both_abstained"
    # The same wrong decimal, within half a percent of each other: one reading, twice.
    assert classify(
        fs("wrong_value", candidate=100.0), fs("wrong_value", candidate=100.3), d, registry
    ) == ("both_wrong_same_way")
    assert classify(
        fs("wrong_value", candidate=100.0), fs("wrong_value", candidate=150.0), d, registry
    ) == ("both_wrong_differently")
    assert classify(
        fs("needs_judgement", "long_text", "a"), fs("correct", "long_text", "a"), d, registry
    ) == ("needs_judgement")
    # A wrong value of the wrong form is compared as text when it cannot be coerced.
    assert classify(
        fs("format", candidate="2,00"), fs("wrong_value", candidate="2,00"), d, registry
    ) == ("both_wrong_same_way")


def test_classify_compares_records_key_by_key(registry: SchemaRegistry) -> None:
    d = definition(
        "record",
        keys=[
            KeyDef(name="basis", value_type="enum", enum_values=["per_mw", "lump_sum"]),
            KeyDef(name="rate_inr_per_mw", value_type="money_inr"),
        ],
    )
    same = {"basis": "per_mw", "rate_inr_per_mw": 900000}
    assert classify(
        fs("wrong_value", "record", same), fs("wrong_value", "record", dict(same)), d, registry
    ) == ("both_wrong_same_way")
    other = {"basis": "lump_sum", "rate_inr_per_mw": 900000}
    assert classify(
        fs("wrong_value", "record", same), fs("wrong_value", "record", other), d, registry
    ) == ("both_wrong_differently")


def gold_record(fields: list[GoldField], slug: str = "acme") -> GoldRecord:
    return GoldRecord(
        tenant_id="ergplan",
        tender_id=slug,
        slug=slug,
        tender_type="solar",
        issuing_agency="SECI",
        title=slug,
        schema_version="v4",
        reviewed_version=1,
        reviewer="Asha Rao",
        completed_at="2026-10-06T10:00:00+00:00",
        snapshot_id="s",
        made_at="2026-10-06T10:01:00+00:00",
        fields=fields,
    )


def gold_field(path: str, value_type: str, value: Any, decision: str = "approved") -> GoldField:
    return GoldField(
        field_path=path,
        section=path.split(".")[1],
        value_type=value_type,
        required=True,
        decision=decision,
        final_value=value,
        version_no=1,
        evidence_pages=[2],
        reviewer="Asha Rao",
        decided_at="2026-10-06T09:00:00+00:00",
        note=None,
        candidate=None,
    )


def test_compare_record_scores_both_models_with_the_same_rules(pipeline: Pipeline) -> None:
    record = gold_record(
        [
            gold_field(DEADLINE, "date", "2026-03-30"),
            gold_field(EMD, "money_inr", 928000),
            gold_field(AGENCY, "text", "SECI"),
            gold_field("core.identity.title", "text", None, decision="not_in_document"),
            gold_field("core.identity.portal", "text", None, decision=None),
            # Written from the record, not asked of the agent: left out of the comparison.
            gold_field("core.summary.plain_english_summary", "long_text", "What is procured…"),
        ]
    )
    engine = {
        DEADLINE: CandidateUnderTest(id="e1", value="30.03.2026", pages=[2]),
        EMD: CandidateUnderTest(id="e2", value=500000, pages=[3]),
        AGENCY: CandidateUnderTest(id="e3", value="SECI", pages=[1]),
    }
    agent = {
        DEADLINE: CandidateUnderTest(id="a1", value="2026-03-30", pages=[2]),
        EMD: CandidateUnderTest(id="a2", value=928000, pages=[2]),
        "core.identity.title": CandidateUnderTest(id="a4", value="Some title", pages=[1]),
    }
    rows = compare_record(record, engine, agent, None, pipeline.catalog, pipeline.schemas)
    by_path = {r.field_path: r for r in rows}
    assert set(by_path) == {DEADLINE, EMD, AGENCY, "core.identity.title"}, (
        "the undecided field and the summary are left out"
    )
    assert by_path[DEADLINE].agreement == "all_agree"
    assert by_path[EMD].agreement == "agent_right_engine_wrong"
    assert (by_path[EMD].engine_evidence_ok, by_path[EMD].agent_evidence_ok) == (False, True)
    assert by_path[AGENCY].agreement == "engine_right_agent_wrong"
    assert by_path[AGENCY].agent_outcome == "missing"
    assert by_path["core.identity.title"].agreement == "engine_right_agent_wrong"
    assert by_path["core.identity.title"].agent_outcome == "extra"
    assert all(r.agent_run_id is None for r in rows)


def _run(
    db: Session, tender_id: str, version: int, status: str, documents: list[dict[str, Any]]
) -> AgentRun:
    run = AgentRun(
        tenant_id="ergplan",
        created_by="pytest",
        object_type="tender",
        object_id=tender_id,
        object_version=version,
        schema_name="tender.solar",
        schema_version="v4",
        prompt_name="agent_pass",
        prompt_version="v1",
        model="test-model",
        status=status,
        finished_at=datetime.now(UTC) if status in ("done", "stopped") else None,
        documents=documents,
    )
    db.add(run)
    db.flush()
    return run


def _finding(
    db: Session, run: AgentRun, ordinal: int, path: str, value: Any, status: str, **span: Any
) -> AgentFinding:
    finding = AgentFinding(
        tenant_id="ergplan",
        created_by="pytest",
        agent_run_id=run.id,
        ordinal=ordinal,
        field_path=path,
        value=value,
        value_type="text",
        confidence=0.9,
        rationale="r",
        status=status,
        evidence=[span] if span else [],
    )
    db.add(finding)
    db.flush()
    return finding


def test_agent_findings_read_the_standing_findings_of_the_finished_pass_at_the_reviewed_version(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender, _ = completed_review(client, pipeline)
    row = db.scalars(select(Tender).where(Tender.id == tender["id"])).one()
    record = build_gold(db, pipeline.catalog, row)
    document_id = pipeline.tenders.versions(db, row)[0].documents[0][1].id
    docs = [{"number": 1, "document_id": document_id}]

    none_yet, found = agent_findings(db, "ergplan", record)
    assert none_yet is None and found == {}

    earlier = _run(db, row.id, 1, "done", docs)
    _finding(db, earlier, 1, DEADLINE, "2026-01-01", "accepted", document_no=1, page_no=1)
    run = _run(db, row.id, 1, "stopped", docs)
    _finding(db, run, 1, DEADLINE, "2026-03-30", "rejected", document_no=1, page_no=2)
    _finding(
        db,
        run,
        2,
        DEADLINE,
        "2026-03-30",
        "accepted",
        document_no=1,
        page_no=2,
        document_id=document_id,
    )
    _finding(
        db, run, 3, EMD, 900000, "superseded", document_no=1, page_no=3, document_id=document_id
    )
    _finding(db, run, 4, EMD, 928000, "accepted", document_no=9, page_no=3, document_id="other")
    _finding(db, run, 5, AGENCY, None, "not_found")
    _run(db, row.id, 2, "done", docs)  # a later version: not what the reviewer saw
    _run(db, row.id, 1, "running", docs)  # not finished
    db.commit()

    chosen, found = agent_findings(db, "ergplan", record)
    assert chosen is not None and chosen.id == run.id
    assert set(found) == {DEADLINE, EMD, AGENCY}
    assert found[DEADLINE].value == "2026-03-30" and found[DEADLINE].pages == [2]
    assert found[DEADLINE].prompt_name == "agent_pass" and found[DEADLINE].prompt_version == "v1"
    assert found[EMD].value == 928000 and found[EMD].pages == [], "a document not of the pass"
    assert found[AGENCY].value is None and found[AGENCY].pages == []

    rows, without = compare_all(
        db,
        "ergplan",
        [record, gold_record([gold_field(DEADLINE, "date", "2026-03-30")], slug="no-pass")],
        pipeline.review_state,
        pipeline.catalog,
        pipeline.schemas,
    )
    assert without == ["no-pass"]
    by_path = {r.field_path: r for r in rows if r.slug == record.slug}
    assert by_path[DEADLINE].agreement == "all_agree"
    assert by_path[DEADLINE].agent_run_id == run.id and by_path[DEADLINE].agent_status == "stopped"
    # The reviewer edited the EMD to 1,000,000; the engine read 928,000, the agent too.
    assert by_path[EMD].agreement == "both_wrong_same_way"


def row(path: str, agreement: str, slug: str = "t") -> ThreeWay:
    return ThreeWay(
        slug=slug,
        tender_type="solar",
        issuing_agency="SECI",
        field_path=path,
        section="x",
        value_type="decimal",
        required=True,
        agreement=agreement,  # type: ignore[arg-type]
        gold_value=1,
        engine_value=1,
        agent_value=1,
        engine_outcome="correct",
        agent_outcome="correct",
    )


def test_emphasis_needs_fifteen_instances_and_ninety_seven_percent() -> None:
    rows = [row("core.a.enough", "all_agree", f"t{i}") for i in range(15)]
    rows += [row("core.a.few", "all_agree", f"t{i}") for i in range(14)]
    rows += [row("core.a.shaky", "all_agree", f"t{i}") for i in range(14)]
    rows += [row("core.a.shaky", "both_abstained", "t14")]
    rows += [row("core.a.judged", "needs_judgement", f"t{i}") for i in range(20)]
    by_path = {e.field_path: e for e in emphasis_of(rows)}
    assert by_path["core.a.enough"].low_review and by_path["core.a.enough"].instances == 15
    assert not by_path["core.a.few"].low_review and by_path["core.a.few"].agreement == 1.0
    assert not by_path["core.a.shaky"].low_review and by_path["core.a.shaky"].agreement == round(
        14 / 15, 4
    )
    assert "core.a.judged" not in by_path


def test_render_report_on_nothing_and_on_rows() -> None:
    empty = summarise([], "ergplan", 0, ["a", "b"])
    text = render_report(empty, [])
    assert "0 gold tender(s) compared; 2 without an agent pass, left out: a, b" in text
    assert "Fields that qualify today: 0" in text

    rows = [row("core.a.x", "all_agree"), row("core.a.y", "agent_right_engine_wrong")]
    rows += [row("core.a.z", "both_wrong_same_way"), row("core.a.w", "needs_judgement")]
    summary = summarise(rows, "ergplan", 1, [])
    assert summary.by_class["all_agree"] == 1 and summary.by_class["needs_judgement"] == 1
    assert summary.by_type["solar"]["both_wrong_same_way"] == 1
    text = render_report(summary, rows)
    for label in (
        "All agree",
        "Engine right, agent wrong",
        "Agent right, engine wrong",
        "Both wrong the same way",
        "Both wrong, differently",
        "Both abstained",
    ):
        assert f"| {label} |" in text
    assert "### Fields with any disagreement" in text
    assert "| core.a.y |" in text and "| core.a.x |" not in text.split("disagreement")[1]
    assert "4 decided fields, 3 counted (1 long-text fields" in text


def test_write_threeway_writes_the_report_the_results_and_the_emphasis_file(
    client: TestClient, pipeline: Pipeline, db: Session, tmp_path: Path, monkeypatch: Any
) -> None:
    tender, _ = completed_review(client, pipeline)
    tender_row = db.scalars(select(Tender).where(Tender.id == tender["id"])).one()
    record = build_gold(db, pipeline.catalog, tender_row)
    document_id = pipeline.tenders.versions(db, tender_row)[0].documents[0][1].id
    run = _run(db, tender_row.id, 1, "done", [{"number": 1, "document_id": document_id}])
    _finding(
        db,
        run,
        1,
        DEADLINE,
        "2026-03-30",
        "accepted",
        document_no=1,
        page_no=2,
        document_id=document_id,
    )
    db.commit()
    monkeypatch.setattr(threeway, "load_all", lambda tenant_id: [record])

    out = tmp_path / "reports" / "THREEWAY-REPORT.md"
    results = tmp_path / "results"
    summary, path = write_threeway(
        db,
        "ergplan",
        pipeline.schemas,
        pipeline.catalog,
        pipeline.review_state,
        out=out,
        results_root=results,
    )
    assert path == out and out.is_file()
    assert summary.tenders == 1 and summary.fields > 0 and not summary.tenders_without_agent_pass
    text = out.read_text()
    assert "1 gold tender(s) compared." in text and "## Error patterns" in text
    assert (results / "review-emphasis-ergplan.json").is_file()
    assert low_review_fields("ergplan", results) == frozenset()
    assert low_review_fields("ergplan", tmp_path / "nowhere") == frozenset()
    dumped = [p for p in results.iterdir() if p.name.endswith("-threeway-ergplan.json")]
    assert len(dumped) == 1 and '"rows"' in dumped[0].read_text()

    only = write_threeway(
        db,
        "ergplan",
        pipeline.schemas,
        pipeline.catalog,
        pipeline.review_state,
        only={"nothing-of-the-kind"},
        out=out,
        results_root=results,
    )[0]
    assert only.tenders == 0 and only.fields == 0
