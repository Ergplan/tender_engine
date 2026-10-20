"""Awards over HTTP (Stage 6): the routes, the widened review token, and one end-to-end
case on a real one-page SECI result sheet from the dataset: import, review, approve, read
the approved row back as canonical."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, CanonicalFact
from core.services.parse import ParseService
from core.services.validate import ValidationService
from tender.models import Award, ReviewToken
from tender.services.results_import import Dataset, ResultsImporter
from tender.services.source_domains import SourceAllowlist
from tests.api.test_review_tokens import PUBLIC, as_reviewer
from tests.conftest import Pipeline
from tests.fixtures.tenders import extracted_tender

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "results"
# The RfS number the dataset's SECI research record keeps for this publication.
REAL_RFS = "SECI/C&P/SPD/RfS/A&N/4MW/012020"


def import_real(pipeline: Pipeline, db: Session) -> Award:
    importer = ResultsImporter(
        ingest=pipeline.ingest,
        parse=ParseService(pipeline.storage, pipeline.settings),
        extract=pipeline.extract,
        validate=ValidationService(pipeline.schemas, pipeline.settings.tenant_id),
        catalog=pipeline.catalog,
        allowlist=SourceAllowlist.load(),
        tenant_id=pipeline.settings.tenant_id,
    )
    report = importer.run(db, Dataset(REAL, commit="fixture"))
    assert report.count("imported") == 1, report.lines()
    return db.scalars(select(Award)).one()


def award_link(client: TestClient, award_id: str, reviewer: str = "Asha Rao") -> dict[str, Any]:
    response = client.post(
        "/api/v1/review-tokens", json={"award_id": award_id, "reviewer_name": reviewer}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def field(review: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        f for f in review["fields"] if f["field_path"] == f"result.award.{name}"
    )
    return found


def decide(client: TestClient, token: str, item: dict[str, Any], decision: str, **body: Any) -> Any:
    entry = item["entries"][item["current"]]
    approval = entry["state"]["approval"]
    return client.post(
        "/api/v1/approvals",
        json={
            "candidate_id": entry["state"]["candidate"]["id"],
            "decision": decision,
            "previous_approval_id": approval["id"] if approval else None,
            **body,
        },
        headers=as_reviewer(token),
    )


def test_real_result_sheet_imported_reviewed_approved_and_read_back_as_canonical(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    # A tender with the publication's RfS number, so the import links them.
    tender = pipeline.tenders.create(
        db,
        tender_type="bess",
        issuing_agency="SECI",
        external_ref=REAL_RFS,
        title="4 MW floating solar with 2 MW/1 MWh BESS at Kalpong Dam",
        created_by="pytest",
    )
    award = import_real(pipeline, db)
    assert award.procurer == "SECI" and award.reference == REAL_RFS
    assert award.result_kind == "auction_result" and award.row_count == 1
    assert (award.tender_id, award.tender_link_basis) == (tender.id, "rfs_number")

    listed = client.get("/api/v1/awards")
    assert listed.status_code == 200 and [a["id"] for a in listed.json()] == [award.id]
    assert listed.json()[0]["source_sha256"] == award.source_sha256
    assert client.get(f"/api/v1/awards?tender_id={tender.id}").json()[0]["id"] == award.id
    assert client.get(f"/api/v1/awards/{award.id}").json()["status"] == "imported"
    assert client.get(f"/api/v1/awards/{'0' * 32}").status_code == 404

    # Before any approval: no rows, and the publication's facts are empty.
    results = client.get(f"/api/v1/awards/{award.id}/results")
    assert results.status_code == 200
    assert results.json()["rows"] == [] and results.json()["reviewed"] is False
    assert (
        results.json()["procurer"] is None and "authoritative" in results.json()["authority_note"]
    )
    linked = client.get(f"/api/v1/tenders/{tender.id}/awards")
    assert linked.status_code == 200 and [a["award_id"] for a in linked.json()["awards"]] == [
        award.id
    ]
    assert linked.json()["awards"][0]["rows"] == []

    state = client.get(f"/api/v1/awards/{award.id}/review-state")
    assert state.status_code == 200 and state.json()["object_type"] == "award"
    assert state.json()["run"]["mode"] == "import"

    # The reviewer's link opens the award and names it in the session.
    link = award_link(client, award.id)
    assert link["object_type"] == "award" and link["object_id"] == award.id
    assert link["tender_id"] is None
    token = link["token"]
    session = client.get("/api/v1/review-session", headers=as_reviewer(token))
    assert session.status_code == 200
    assert session.json()["object_type"] == "award" and session.json()["object_id"] == award.id
    assert session.json()["tender_id"] is None

    review = client.get(f"/api/v1/awards/{award.id}/review", headers=as_reviewer(token))
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["award_id"] == award.id and body["title"] == "SECI000013_result_1.pdf"
    assert body["versions"][0]["documents"][0]["document_id"] == award.document_id
    assert [f["field_path"] for f in body["fields"]][-1] == "result.award.winners"
    winners = field(body, "winners")
    candidate = winners["entries"][0]["state"]["candidate"]
    assert candidate["prompt_name"] == "import/re-tender-results"
    assert candidate["value"][0]["bidder"] == "SUNSOURCE ENERGY PRIVATE LIMITED"
    assert candidate["value"][0]["price"] == 6.95 and candidate["value"][0]["capacity"] == 4.0
    # Bidder and tariff located on page 1 of the sheet.
    assert all(span["char_start"] is not None for span in candidate["evidence"])
    assert {span["page_no"] for span in candidate["evidence"]} == {1}
    assert candidate["status"] == "validated"
    assert field(body, "result_date")["current"] is None or (
        field(body, "result_date")["entries"][0]["state"]["candidate"]["value"] is None
    )

    # The sheet prints the NIT number as 04MW where the research record says 4MW: the
    # reference is shown unlocated and cannot be approved as it stands.
    reference = field(body, "reference")
    assert reference["entries"][0]["state"]["candidate"]["evidence"][0]["char_start"] is None
    refused = decide(client, token, reference, "approved")
    assert refused.status_code == 422

    # The link reaches the award's own file and nothing of a tender.
    client.cookies.set("review_token", token)
    pdf = client.get(f"/files/documents/{award.source_sha256}.pdf", headers=PUBLIC)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert (
        client.get(
            f"/api/v1/documents/{award.document_id}/pages", headers=as_reviewer(token)
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/tenders/{tender.id}", headers=as_reviewer(token)).status_code == 404
    assert (
        client.get(f"/api/v1/tenders/{tender.id}/review", headers=as_reviewer(token)).status_code
        == 404
    )
    assert client.get("/api/v1/awards", headers=as_reviewer(token)).status_code == 403
    client.cookies.clear()

    # Approve the table: the only path to a canonical fact.
    approved = decide(client, token, winners, "approved")
    assert approved.status_code == 201, approved.text
    assert approved.json()["canonical_fact_id"]
    facts = list(db.scalars(select(CanonicalFact).where(CanonicalFact.object_type == "award")))
    assert len(facts) == 1 and facts[0].object_id == award.id
    assert facts[0].field_path == "result.award.winners"
    results = client.get(f"/api/v1/awards/{award.id}/results").json()
    assert [row["bidder"] for row in results["rows"]] == ["SUNSOURCE ENERGY PRIVATE LIMITED"]
    assert results["evidence_pages"] == [1] and results["reviewed"] is False
    assert (
        client.get(f"/api/v1/tenders/{tender.id}/awards").json()["awards"][0]["rows"]
        == results["rows"]
    )

    # Completion waits for the required fields; the reviewer supplies the reference as printed.
    blocked = client.post(f"/api/v1/awards/{award.id}/complete-review", headers=as_reviewer(token))
    assert blocked.status_code == 422 and "required" in blocked.json()["detail"]
    fresh = client.get(f"/api/v1/awards/{award.id}/review", headers=as_reviewer(token)).json()
    assert decide(client, token, field(fresh, "procurer"), "approved").status_code == 201
    assert decide(client, token, field(fresh, "result_kind"), "approved").status_code == 201
    edited = decide(
        client,
        token,
        field(fresh, "reference"),
        "edited",
        final_value="SECI/C&P/SPD/RfS/A&N/04MW/012020",
        evidence=[{"page_no": 1, "quote": "SECI/C&P/SPD/RfS/A&N/04MW/012020"}],
    )
    assert edited.status_code == 201, edited.text
    done = client.post(f"/api/v1/awards/{award.id}/complete-review", headers=as_reviewer(token))
    assert done.status_code == 201, done.text
    assert done.json()["status"] == "reviewed"
    db.expire_all()
    completed = db.scalars(select(ReviewToken).where(ReviewToken.token == token)).one()
    assert completed.completed_at is not None and completed.object_type == "award"
    results = client.get(f"/api/v1/awards/{award.id}/results").json()
    assert results["reviewed"] is True and results["procurer"] == "SECI"
    assert results["reference"] == "SECI/C&P/SPD/RfS/A&N/04MW/012020"
    assert results["result_kind"] == "auction_result"
    # A completed review is readable and no longer changeable.
    assert (
        client.get(f"/api/v1/awards/{award.id}/review", headers=as_reviewer(token)).status_code
        == 200
    )
    assert decide(client, token, field(fresh, "winners"), "cleared").status_code == 409
    again = client.post(f"/api/v1/awards/{award.id}/complete-review", headers=as_reviewer(token))
    assert again.status_code == 409
    # Every write went through the audit log: the award, its run, the decisions.
    tables = set(db.scalars(select(AuditLog.table_name).distinct()))
    assert {"award", "extraction_run", "candidate", "approval", "canonical_fact"} <= tables
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "complete_review")
        )
        == 1
    )


def test_a_tender_link_opens_no_award_and_a_token_names_one_object(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    award = import_real(pipeline, db)
    tender_link = client.post(
        "/api/v1/review-tokens", json={"tender_id": tender.id, "reviewer_name": "Asha Rao"}
    ).json()
    assert tender_link["object_type"] == "tender" and tender_link["tender_id"] == tender.id
    headers = as_reviewer(tender_link["token"])
    assert client.get(f"/api/v1/tenders/{tender.id}/review", headers=headers).status_code == 200
    assert client.get(f"/api/v1/awards/{award.id}/review", headers=headers).status_code == 404
    assert client.get(f"/api/v1/awards/{award.id}", headers=headers).status_code == 404
    client.cookies.set("review_token", tender_link["token"])
    assert (
        client.get(f"/files/documents/{award.source_sha256}.pdf", headers=PUBLIC).status_code == 404
    )
    client.cookies.clear()
    # And the award's link reaches nothing of the tender's files.
    tender_sha = pipeline.tenders.versions(db, tender)[0].documents[0][1].sha256
    award_token = award_link(client, award.id)["token"]
    client.cookies.set("review_token", award_token)
    assert client.get(f"/files/documents/{tender_sha}.pdf", headers=PUBLIC).status_code == 404
    assert (
        client.get(f"/files/documents/{award.source_sha256}.pdf", headers=PUBLIC).status_code == 200
    )
    client.cookies.clear()
    both = client.post(
        "/api/v1/review-tokens",
        json={"tender_id": tender.id, "award_id": award.id, "reviewer_name": "Asha Rao"},
    )
    assert both.status_code == 422
    neither = client.post("/api/v1/review-tokens", json={"reviewer_name": "Asha Rao"})
    assert neither.status_code == 422
    missing = client.post(
        "/api/v1/review-tokens", json={"award_id": "0" * 32, "reviewer_name": "Asha Rao"}
    )
    assert missing.status_code == 404
    # A second link for the award stops the first.
    first = award_link(client, award.id)
    second = award_link(client, award.id, "Ravi Iyer")
    assert (
        client.get("/api/v1/review-session", headers=as_reviewer(first["token"])).status_code == 410
    )
    assert (
        client.get("/api/v1/review-session", headers=as_reviewer(second["token"])).json()[
            "reviewer_name"
        ]
        == "Ravi Iyer"
    )
    # The award's token decides nothing of the tender.
    review = client.get(f"/api/v1/tenders/{tender.id}/review").json()
    deadline = next(
        f for f in review["fields"] if f["field_path"] == "core.key_dates.bid_submission_deadline"
    )
    candidate = deadline["entries"][deadline["current"]]["state"]["candidate"]
    refused = client.post(
        "/api/v1/approvals",
        json={"candidate_id": candidate["id"], "decision": "approved"},
        headers=as_reviewer(second["token"]),
    )
    assert refused.status_code == 404


def test_the_api_product_serves_awards_read_only(pipeline: Pipeline, db: Session) -> None:
    from api.main import create_app

    award = import_real(pipeline, db)
    app = create_app(
        pipeline.settings.model_copy(update={"product": "api"}),
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
    )
    client = TestClient(app)
    assert client.get(f"/api/v1/awards/{award.id}/results").status_code == 200
    assert client.post(f"/api/v1/awards/{award.id}/complete-review").status_code in (404, 405)


def test_a_table_with_an_unlocated_row_is_not_approved_as_it_stands(
    client: TestClient, pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    """The invariant row by row: the reviewer drops the rows the page does not show, or
    keeps them and gives the page and words of each."""
    from tests.fixtures.pdfs import make_pdf
    from tests.tender.test_results_import import ORDER_PAGES, RESULT_PAGES, importer, write_dataset

    root = write_dataset(
        tmp_path / "ds", result_pdf=make_pdf(RESULT_PAGES), order_pdf=make_pdf(ORDER_PAGES)
    )
    importer(pipeline).run(db, Dataset(root, commit="fixture"), only=["src-result"])
    award = db.scalars(select(Award)).one()
    token = award_link(client, award.id)["token"]
    review = client.get(f"/api/v1/awards/{award.id}/review", headers=as_reviewer(token)).json()
    winners = field(review, "winners")
    rows = winners["entries"][0]["state"]["candidate"]["value"]
    assert [row["bidder"] for row in rows] == [
        "Alpha Power Private Limited",
        "Delta Unknown Limited",
    ]

    refused = decide(client, token, winners, "approved")
    assert refused.status_code == 422 and "Delta Unknown Limited" in refused.json()["detail"]
    # Keeping the row without its words is refused too.
    kept = decide(client, token, winners, "edited", final_value=rows)
    assert kept.status_code == 422 and "Delta Unknown Limited" in kept.json()["detail"]
    # Words that are not on the page do not count.
    wrong = decide(
        client,
        token,
        winners,
        "edited",
        final_value=rows,
        evidence=[{"page_no": 1, "quote": "Delta Unknown Limited 200 MW"}],
    )
    assert wrong.status_code == 422
    # Renaming the row does not free it from the words: a row that is not a located row of
    # the import kept as it was needs a quote that names it.
    renamed = decide(
        client, token, winners, "edited", final_value=[rows[0], {**rows[1], "bidder": "Zeta"}]
    )
    assert renamed.status_code == 422 and "Zeta" in renamed.json()["detail"]
    # A quote that does not name the row does not cover it either.
    unrelated = decide(
        client,
        token,
        winners,
        "edited",
        final_value=[rows[0], {**rows[1], "bidder": "Beta Energy Limited"}],
        evidence=[{"page_no": 1, "quote": "Successful bidders after e-Reverse Auction"}],
    )
    assert unrelated.status_code == 422
    # Nor may a located row be altered without words for it.
    altered = decide(
        client, token, winners, "edited", final_value=[{**rows[0], "price": 2.14}, rows[1]]
    )
    assert altered.status_code == 422
    # The page prints Beta Energy Limited where the dataset says Delta: the reviewer
    # corrects the row and quotes the page for its bidder and its price. The bidder alone
    # is not enough: the price is a value of the row too.
    corrected = [rows[0], {**rows[1], "bidder": "Beta Energy Limited"}]
    bidder_only = decide(
        client,
        token,
        winners,
        "edited",
        final_value=corrected,
        evidence=[{"page_no": 1, "quote": "Beta Energy Limited"}],
    )
    assert bidder_only.status_code == 422
    # A change to any value of a located row (here the status) needs words too.
    restatus = decide(
        client, token, winners, "edited", final_value=[{**rows[0], "status": "selected"}, rows[1]]
    )
    assert restatus.status_code == 422
    # A number is covered only by itself printed whole: 2.45 on the page does not cover a
    # price of 2.4, nor 200 a capacity of 20; and every number of the row is needed.
    for changed in ({"price": 2.4}, {"capacity": 20.0}, {"adopted_capacity": 150.0}):
        partial = decide(
            client,
            token,
            winners,
            "edited",
            final_value=[rows[0], {**rows[1], "bidder": "Beta Energy Limited", **changed}],
            evidence=[{"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"}],
        )
        assert partial.status_code == 422, changed
    # The same quote given twice is one printed occurrence, not two.
    twice = decide(
        client,
        token,
        winners,
        "edited",
        final_value=[
            rows[0],
            {**rows[1], "bidder": "Beta Energy Limited", "adopted_capacity": 200.0},
        ],
        evidence=[
            {"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"},
            {"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"},
        ],
    )
    assert twice.status_code == 422
    # A quote running over two rows lends the second row's figures to nobody: Alpha's row
    # cannot take Beta's numbers from a quote that names both.
    borrowed = decide(
        client,
        token,
        winners,
        "edited",
        final_value=[{**rows[0], "capacity": 200.0, "price": 2.45}, rows[1]],
        evidence=[
            {
                "page_no": 1,
                "quote": (
                    "Alpha Power Private Limited 380 MW 2.41 INR/kWh "
                    "2 Beta Energy Limited 200 MW 2.45 INR/kWh"
                ),
            }
        ],
    )
    assert borrowed.status_code == 422
    # A unit printed after a number names its quantity: 200 MW cannot stand for a price of
    # 200, nor 2.45 INR/kWh for a capacity of 2.45.
    swapped = decide(
        client,
        token,
        winners,
        "edited",
        final_value=[
            rows[0],
            {**rows[1], "bidder": "Beta Energy Limited", "capacity": 2.45, "price": 200.0},
        ],
        evidence=[{"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"}],
    )
    assert swapped.status_code == 422
    # One printed number covers one value: a quote printing 2.45 once does not cover a row
    # whose capacity and price are both 2.45.
    doubled = decide(
        client,
        token,
        winners,
        "edited",
        final_value=[rows[0], {**rows[1], "bidder": "Beta Energy Limited", "capacity": 2.45}],
        evidence=[{"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"}],
    )
    assert doubled.status_code == 422
    # Numbers count only in a quote that holds the row's bidder: a number quoted on its own
    # could belong to any row of the table.
    apart = decide(
        client,
        token,
        winners,
        "edited",
        final_value=corrected,
        evidence=[
            {"page_no": 1, "quote": "Beta Energy Limited"},
            {"page_no": 1, "quote": "200 MW   2.45 INR/kWh"},
        ],
    )
    assert apart.status_code == 422
    edited = decide(
        client,
        token,
        winners,
        "edited",
        final_value=corrected,
        evidence=[{"page_no": 1, "quote": "Beta Energy Limited 200 MW 2.45 INR/kWh"}],
    )
    assert edited.status_code == 201, edited.text
    results = client.get(f"/api/v1/awards/{award.id}/results").json()
    assert [row["bidder"] for row in results["rows"]] == [
        "Alpha Power Private Limited",
        "Beta Energy Limited",
    ]
    # Dropping the unlocated row is the other way: no quote needed.
    fresh = client.get(f"/api/v1/awards/{award.id}/review", headers=as_reviewer(token)).json()
    dropped = decide(client, token, field(fresh, "winners"), "edited", final_value=[rows[0]])
    assert dropped.status_code == 201, dropped.text
    assert len(client.get(f"/api/v1/awards/{award.id}/results").json()["rows"]) == 1
