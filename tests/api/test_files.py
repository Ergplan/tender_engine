"""`GET /files/...`: the stored PDF and page images served by the API itself (Cloud Run),
gated like `/files-auth`."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Document
from tests.api.test_review_tokens import PUBLIC, add_version, as_reviewer, create, extracted, link
from tests.conftest import Pipeline


def _documents(db: Session) -> tuple[Document, Document]:
    own = db.scalars(select(Document).where(Document.filename == "rfs.pdf")).one()
    foreign = db.scalars(select(Document).where(Document.filename == "other.pdf")).one()
    return own, foreign


def test_a_review_link_fetches_its_tenders_files_and_no_others(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    other = create(client, external_ref="ACME/RE/2026/009", title="Other")
    add_version(client, other["id"], [["OTHER RFS", "page"]], "other.pdf", kind="original")
    pipeline.runner.run_until_idle()
    headers = as_reviewer(link(client, tender["id"])["token"])
    own, foreign = _documents(db)

    pdf = client.get(f"/files/documents/{own.sha256}.pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and "immutable" in pdf.headers["cache-control"]
    png = client.get(f"/files/renders/{own.sha256}/1.png", headers=headers)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")

    assert client.get(f"/files/documents/{foreign.sha256}.pdf", headers=headers).status_code == 404
    assert client.get("/files/documents/../.env", headers=headers).status_code == 404
    assert client.get(f"/files/renders/{own.sha256}/99.png", headers=headers).status_code == 404

    # The link in the cookie, as the browser sends it for the PDF viewer.
    client.cookies.set("review_token", headers["X-Review-Token"])
    assert client.get(f"/files/documents/{own.sha256}.pdf", headers=PUBLIC).status_code == 200
    client.cookies.clear()

    # From outside without a link: refused. From inside (no public mark): served.
    outside = client.get(f"/files/documents/{own.sha256}.pdf", headers=PUBLIC)
    assert outside.status_code == 401 and outside.json()["error_type"] == "review_link_required"
    assert client.get(f"/files/documents/{own.sha256}.pdf").status_code == 200
    bad = client.get(
        f"/files/documents/{own.sha256}.pdf", headers={**PUBLIC, "X-Review-Token": "x" * 32}
    )
    assert bad.status_code == 401 and bad.json()["error_type"] == "review_link_invalid"


def test_a_byte_range_of_the_pdf_is_served_with_206(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    headers = as_reviewer(link(client, tender["id"])["token"])
    own = db.scalars(select(Document).where(Document.filename == "rfs.pdf")).one()
    whole = client.get(f"/files/documents/{own.sha256}.pdf", headers=headers).content
    part = client.get(
        f"/files/documents/{own.sha256}.pdf", headers={**headers, "Range": "bytes=0-3"}
    )
    assert part.status_code == 206 and part.content == whole[:4]
    assert part.headers["content-range"] == f"bytes 0-3/{len(whole)}"
    tail = client.get(
        f"/files/documents/{own.sha256}.pdf", headers={**headers, "Range": "bytes=-5"}
    )
    assert tail.status_code == 206 and tail.content == whole[-5:]
    beyond = client.get(
        f"/files/documents/{own.sha256}.pdf",
        headers={**headers, "Range": f"bytes={len(whole) + 10}-"},
    )
    assert beyond.status_code == 416 and beyond.headers["content-range"] == f"bytes */{len(whole)}"
