"""The published view, its PDF, the changelog and the comparison over HTTP."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import Pipeline
from tests.evals.test_gold import completed_review
from tests.fixtures.tenders import DEADLINE, EMD, amended_tender


def test_published_pdf_changes_and_compare_are_served(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender, _ = completed_review(client, pipeline)
    tid = tender["id"]
    published = client.get(f"/api/v1/tenders/{tid}/published")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["publication"]["state"] == "published" and body["reviewed_version"] == 1
    assert body["reviewer_role"] == "reviewer" and body["reviewed_at"]
    fields = {f["path"]: f for s in body["sections"] for f in s["fields"]}
    assert fields[EMD]["value"] == 1000000
    assert "rationale" not in published.text and "confidence" not in published.text
    assert fields[DEADLINE]["evidence"][0]["page_no"] == 2
    assert set(fields[DEADLINE]) >= {
        "path",
        "section",
        "label",
        "value_type",
        "unit",
        "value",
        "version_no",
        "set_by",
        "evidence",
        "reviewed_at",
        "reviewer_role",
        "withdrawn",
        "withdrawn_from_version",
        "status",
        "gap",
    }

    pdf = client.get(f"/api/v1/tenders/{tid}/published.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert (
        pdf.content.startswith(b"%PDF") and "-published.pdf" in pdf.headers["content-disposition"]
    )

    changes = client.get(f"/api/v1/tenders/{tid}/changes")
    assert changes.status_code == 200
    assert [v["version_no"] for v in changes.json()["versions"]] == [1]
    assert changes.json()["versions"][0]["reviewed"] is True

    other, _ = completed_review(client, pipeline)
    compare = client.get(f"/api/v1/tenders/compare?ids={tid},{other['id']}")
    assert compare.status_code == 200, compare.text
    assert [c["tender_id"] for c in compare.json()["columns"]] == [tid, other["id"]]
    row = next(r for r in compare.json()["rows"] if r["path"] == EMD)
    assert [cell["value"] for cell in row["cells"]] == [1000000, 1000000]


def test_a_suspended_tender_and_the_refusals(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender, _ = completed_review(client, pipeline)
    tid = tender["id"]
    amended_tender(pipeline, db, pipeline.tenders.get(db, tid))
    body = client.get(f"/api/v1/tenders/{tid}/published").json()
    assert body["publication"]["state"] == "publication_suspended"
    assert body["sections"] == [] and body["suspension"]["fields"] == [DEADLINE]
    assert body["suspension"]["version_no"] == 2 and len(body["suspension"]["document_ids"]) == 1
    compare = client.get(f"/api/v1/tenders/compare?ids={tid}")
    assert compare.json()["columns"] == [] and compare.json()["excluded"][0]["tender_id"] == tid
    # No value, old or new, while suspended: the changelog keeps its versions and what each
    # may touch, and nothing else.
    changes = client.get(f"/api/v1/tenders/{tid}/changes").json()
    assert [v["version_no"] for v in changes["versions"]] == [1, 2]
    assert all(v["changes"] == [] for v in changes["versions"])
    assert changes["versions"][1]["pending"] == [DEADLINE]

    missing = "0" * 32
    assert client.get(f"/api/v1/tenders/{missing}/published").status_code == 404
    assert client.get(f"/api/v1/tenders/{missing}/published.pdf").status_code == 404
    assert client.get(f"/api/v1/tenders/{missing}/changes").status_code == 404
    too_many = client.get("/api/v1/tenders/compare?ids=" + ",".join([tid] * 7))
    assert too_many.status_code == 422 and "at most 6" in too_many.json()["detail"]
    assert client.get("/api/v1/tenders/compare?ids=,").status_code == 422
