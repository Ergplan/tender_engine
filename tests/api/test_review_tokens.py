"""Review tokens, the reviewer's view of a tender, and completing a review, through HTTP."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AuditLog, Document
from scripts import review_token as review_token_command
from tender.models import ReviewToken, Tender, TenderReviewSnapshot
from tests.api.test_tenders import ASHA, add_version, create, extracted
from tests.conftest import Pipeline
from tests.fixtures.tenders import (
    AMENDMENT_ANSWERS,
    AMENDMENT_PAGES,
    DEADLINE,
    EMD,
    RFS_PAGES,
)

PUBLIC = {"X-Public-Request": "1"}


def link(client: TestClient, tender_id: str, reviewer: str = "Asha Rao") -> dict[str, Any]:
    response = client.post(
        "/api/v1/review-tokens", json={"tender_id": tender_id, "reviewer_name": reviewer}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def as_reviewer(token: str) -> dict[str, str]:
    """The headers of a reviewer's browser: through the public proxy, with the token."""
    return {**PUBLIC, "X-Review-Token": token}


def review(client: TestClient, tender_id: str, token: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/tenders/{tender_id}/review", headers=as_reviewer(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def field(review_body: dict[str, Any], path: str) -> dict[str, Any]:
    found: dict[str, Any] = next(f for f in review_body["fields"] if f["field_path"] == path)
    return found


def current(review_body: dict[str, Any], path: str) -> dict[str, Any]:
    item = field(review_body, path)
    entry: dict[str, Any] = item["entries"][item["current"]]
    return entry


def decide(
    client: TestClient, token: str, entry: dict[str, Any], decision: str, **body: Any
) -> Any:
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


def test_a_token_is_32_characters_opens_its_tender_and_names_the_reviewer(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    created = link(client, tender["id"])
    token = created["token"]
    assert len(token) == 32 and created["url"] == f"https://34.131.65.108/review/{token}"
    row = db.scalars(select(ReviewToken)).one()
    assert row.expires_at - row.created_at > timedelta(days=29, hours=23)

    session = client.get("/api/v1/review-session", headers=as_reviewer(token))
    assert session.status_code == 200
    assert session.json()["tender_id"] == tender["id"]
    assert session.json()["reviewer_name"] == "Asha Rao" and session.json()["completed_at"] is None

    body = review(client, tender["id"], token)
    approved = decide(client, token, current(body, EMD), "approved")
    assert approved.status_code == 201, approved.text
    assert approved.json()["reviewer"] == "Asha Rao", "the reviewer is the token's, not a header"
    spoofed = client.post(
        "/api/v1/approvals",
        json={
            "candidate_id": current(body, DEADLINE)["state"]["candidate"]["id"],
            "decision": "approved",
        },
        headers={**as_reviewer(token), "X-Reviewer": "Someone Else"},
    )
    assert spoofed.status_code == 201 and spoofed.json()["reviewer"] == "Asha Rao"


def test_a_second_token_revokes_the_first(client: TestClient, pipeline: Pipeline) -> None:
    tender = extracted(client, pipeline)
    first = link(client, tender["id"])["token"]
    second = link(client, tender["id"], "Bela Shah")["token"]
    refused = client.get("/api/v1/review-session", headers=as_reviewer(first))
    assert refused.status_code == 410 and refused.json()["error_type"] == "review_link_revoked"
    assert refused.headers["cache-control"] == "no-store", "a browser must not reuse a refusal"
    assert "newer one" in refused.json()["message"]
    assert client.get("/api/v1/review-session", headers=as_reviewer(second)).status_code == 200


def test_expired_and_unknown_tokens_are_refused_in_plain_words(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    token = link(client, tender["id"])["token"]
    row = db.scalars(select(ReviewToken)).one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    expired = client.get(f"/api/v1/tenders/{tender['id']}/review", headers=as_reviewer(token))
    assert expired.status_code == 410 and expired.json()["error_type"] == "review_link_expired"
    assert expired.json()["message"] == "This review link has expired. Ask for a new one."
    unknown = client.get("/api/v1/review-session", headers=as_reviewer("x" * 32))
    assert unknown.status_code == 401 and unknown.json()["error_type"] == "review_link_invalid"
    by_cookie = client.get("/api/v1/review-session", headers=PUBLIC, cookies={"review_token": "y"})
    assert by_cookie.status_code == 401


def test_a_public_request_without_a_token_reaches_nothing_but_health(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = extracted(client, pipeline)
    for method, path in (
        ("GET", "/api/v1/tenders"),
        ("GET", f"/api/v1/tenders/{tender['id']}/review"),
        ("POST", "/api/v1/review-tokens"),
        ("POST", "/api/v1/approvals"),
        ("GET", "/api/v1/reports/extraction-summary"),
    ):
        response = client.request(method, path, headers=PUBLIC, json={})
        assert response.status_code == 401, (method, path)
        assert response.json()["error_type"] == "review_link_required"
    assert client.get("/api/v1/health", headers=PUBLIC).status_code == 200


def test_a_token_reaches_only_its_own_tender_and_only_the_review_routes(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    other = create(client, external_ref="ACME/RE/2026/008", title="Another tender")
    added = add_version(client, other["id"], [["OTHER RFS", "page"]], "other.pdf", kind="original")
    assert added.status_code == 201
    other_document = added.json()["documents"][0]["document_id"]
    token = link(client, tender["id"])["token"]
    headers = as_reviewer(token)

    assert client.get(f"/api/v1/tenders/{other['id']}/review", headers=headers).status_code == 404
    assert (
        client.get(f"/api/v1/documents/{other_document}/pages", headers=headers).status_code == 404
    )
    for method, path in (
        ("GET", "/api/v1/tenders"),
        ("POST", "/api/v1/tenders"),
        ("POST", "/api/v1/review-tokens"),
        ("POST", f"/api/v1/tenders/{tender['id']}/extract"),
        ("POST", f"/api/v1/tenders/{tender['id']}/versions"),
        ("GET", "/api/v1/reports/extraction-summary"),
        ("GET", "/api/v1/review-state"),
        ("GET", "/api/v1/canonical"),
    ):
        response = client.request(method, path, headers=headers, json={})
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error_type"] == "not_allowed"

    # A candidate of another tender cannot be decided with this token.
    pipeline.runner.run_until_idle()
    client.post(f"/api/v1/tenders/{other['id']}/extract", json={}, headers=ASHA)
    pipeline.runner.run_until_idle()
    foreign = client.get(f"/api/v1/tenders/{other['id']}/review").json()
    candidate = next(
        entry["state"]["candidate"]["id"] for f in foreign["fields"] for entry in f["entries"]
    )
    refused = client.post(
        "/api/v1/approvals",
        json={"candidate_id": candidate, "decision": "not_in_document"},
        headers=headers,
    )
    assert refused.status_code == 404

    own_document = db.scalars(select(Document).where(Document.filename == "rfs.pdf")).one()
    pages = client.get(f"/api/v1/documents/{own_document.id}/pages", headers=headers)
    assert pages.status_code == 200 and len(pages.json()) == len(RFS_PAGES)


def test_a_stale_decision_is_refused_and_a_flag_decides_nothing(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = extracted(client, pipeline)
    token = link(client, tender["id"])["token"]
    before = review(client, tender["id"], token)
    entry = current(before, EMD)

    first = decide(client, token, entry, "approved")
    assert first.status_code == 201
    stale = decide(client, token, entry, "not_in_document")  # still says "undecided"
    assert stale.status_code == 409 and stale.json()["error_type"] == "conflict"
    after = review(client, tender["id"], token)
    assert field(after, EMD)["decided"] and after["decided"] == before["decided"] + 1

    flagged = decide(client, token, current(after, EMD), "flagged", note="check the band")
    assert flagged.status_code == 201 and flagged.json()["canonical_fact_id"] is None
    again = review(client, tender["id"], token)
    item = field(again, EMD)
    assert item["flagged"] and not item["decided"]
    assert current(again, EMD)["state"]["approval"]["note"] == "check the band"
    view = client.get(f"/api/v1/tenders/{tender['id']}/view", headers=as_reviewer(token)).json()
    assert next(f for f in view["fields"] if f["field_path"] == EMD)["value"] is None


def with_amendment(client: TestClient, pipeline: Pipeline) -> dict[str, Any]:
    tender = extracted(client, pipeline)
    pipeline.sdk.answers = dict(AMENDMENT_ANSWERS)
    added = add_version(
        client,
        tender["id"],
        AMENDMENT_PAGES,
        "amendment-01.pdf",
        kind="amendment",
        issued_on="2026-03-20",
    )
    assert added.status_code == 201
    pipeline.runner.run_until_idle()
    client.post(f"/api/v1/tenders/{tender['id']}/extract", json={}, headers=ASHA)
    pipeline.runner.run_until_idle()
    return tender


def test_the_review_shows_each_field_once_with_the_latest_version_that_states_it(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = with_amendment(client, pipeline)
    token = link(client, tender["id"])["token"]
    body = review(client, tender["id"], token)

    assert [v["version_no"] for v in body["versions"]] == [1, 2]
    assert body["versions"][1]["kind"] == "amendment"
    assert body["versions"][1]["documents"][0]["filename"] == "amendment-01.pdf"
    assert [s["name"] for s in body["sections"]][:3] == [
        "summary",
        "identity_and_scope",
        "key_dates",
    ]
    assert len(body["fields"]) == body["total"] and body["decided"] == 0

    deadline = field(body, DEADLINE)
    assert [e["version_no"] for e in deadline["entries"]] == [1, 2] and deadline["current"] == 1
    assert current(body, DEADLINE)["version_kind"] == "amendment"
    assert current(body, DEADLINE)["state"]["candidate"]["value"] == "15.04.2026"
    emd = field(body, EMD)
    assert [e["version_no"] for e in emd["entries"]] == [1] and emd["current"] == 0

    # The reviewer finds that the amendment does not change the deadline after all: the
    # original becomes the entry to decide again.
    set_aside = decide(client, token, current(body, DEADLINE), "not_in_document")
    assert set_aside.status_code == 201
    body = review(client, tender["id"], token)
    deadline = field(body, DEADLINE)
    assert deadline["current"] == 0 and not deadline["decided"]
    assert decide(client, token, current(body, DEADLINE), "approved").status_code == 201
    body = review(client, tender["id"], token)
    assert field(body, DEADLINE)["decided"] and body["decided"] == 1


def test_complete_review_needs_every_required_field_then_snapshots_and_locks(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = with_amendment(client, pipeline)
    tid = tender["id"]
    token = link(client, tid)["token"]
    headers = as_reviewer(token)
    body = review(client, tid, token)
    assert body["required_undecided"] > 0 and body["can_complete"] is False
    early = client.post(f"/api/v1/tenders/{tid}/complete-review", headers=headers)
    assert early.status_code == 422 and "required field" in early.json()["detail"]
    assert client.get(f"/api/v1/tenders/{tid}/snapshot", headers=headers).status_code == 404

    for item in body["fields"]:
        if not item["required"] or item["current"] is None:
            continue
        entry = item["entries"][item["current"]]
        candidate = entry["state"]["candidate"]
        located = any(e["char_start"] is not None for e in candidate["evidence"])
        decision = "approved" if candidate["value"] is not None and located else "not_in_document"
        made = decide(client, token, entry, decision)
        assert made.status_code == 201, (item["field_path"], made.text)
    body = review(client, tid, token)
    assert body["required_undecided"] == 0 and body["can_complete"] is True

    done = client.post(f"/api/v1/tenders/{tid}/complete-review", headers=headers)
    assert done.status_code == 201, done.text
    snapshot = done.json()["snapshot"]
    assert snapshot["reviewer"] == "Asha Rao" and snapshot["decided"] == body["decided"]
    values = {f["field_path"]: f for f in snapshot["view"]["fields"]}
    assert (values[DEADLINE]["value"], values[DEADLINE]["version_no"]) == ("2026-04-15", 2)
    assert values[DEADLINE]["evidence"][0]["quote"]
    served = client.get(f"/api/v1/tenders/{tid}/snapshot", headers=headers)
    assert served.status_code == 200 and served.json()["snapshot"] == snapshot

    assert db.scalars(select(TenderReviewSnapshot)).one().tender_id == tid
    assert db.scalars(select(Tender).where(Tender.id == tid)).one().status == "reviewed"
    assert client.get(f"/api/v1/tenders/{tid}", headers=headers).json()["status"] == "reviewed"
    session = client.get("/api/v1/review-session", headers=headers).json()
    assert session["completed_at"] is not None
    # Completed: still readable, no longer writable.
    assert client.get(f"/api/v1/tenders/{tid}/review", headers=headers).status_code == 200
    late = decide(client, token, current(body, EMD), "approved")
    assert late.status_code == 409 and late.json()["error_type"] == "review_completed"
    twice = client.post(f"/api/v1/tenders/{tid}/complete-review", headers=headers)
    assert twice.status_code == 409
    audited = db.scalars(select(AuditLog).where(AuditLog.action == "complete_review")).one()
    assert audited.actor == "Asha Rao" and audited.after is not None
    assert audited.after["status"] == "reviewed"


def test_complete_review_needs_a_review_token(client: TestClient, pipeline: Pipeline) -> None:
    tender = extracted(client, pipeline)
    response = client.post(f"/api/v1/tenders/{tender['id']}/complete-review", headers=ASHA)
    assert response.status_code == 401


def test_pages_search_and_file_authorisation_for_the_viewer(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    other = create(client, external_ref="ACME/RE/2026/009", title="Other")
    add_version(client, other["id"], [["OTHER RFS", "page"]], "other.pdf", kind="original")
    pipeline.runner.run_until_idle()
    token = link(client, tender["id"])["token"]
    headers = as_reviewer(token)
    own = db.scalars(select(Document).where(Document.filename == "rfs.pdf")).one()
    foreign = db.scalars(select(Document).where(Document.filename == "other.pdf")).one()

    document = client.get(f"/api/v1/documents/{own.id}", headers=headers).json()
    assert document["file_url"] == f"/files/documents/{own.sha256}.pdf"
    pages = client.get(f"/api/v1/documents/{own.id}/pages", headers=headers).json()
    assert [p["page_no"] for p in pages] == [1, 2, 3]
    assert pages[0]["width"] == 595 and pages[0]["height"] == 842 and pages[0]["has_text_layer"]
    assert pages[1]["render_url"] == f"/files/renders/{own.sha256}/2.png"

    hits = client.get(
        f"/api/v1/documents/{own.id}/search", params={"q": "earnest money"}, headers=headers
    ).json()
    assert [h["page_no"] for h in hits] == [3, 3], "the heading and the clause, ignoring case"
    x0, top, x1, bottom = hits[1]["bbox"]
    assert 60 < x0 < x1 < 595 and hits[0]["bbox"][1] < top < bottom < 842
    assert "Earnest Money Deposit (EMD)" in hits[1]["snippet"]
    short = client.get(f"/api/v1/documents/{own.id}/search", params={"q": "e"}, headers=headers)
    assert short.status_code == 422

    def may_fetch(uri: str, **extra: Any) -> int:
        code: int = client.get(
            "/api/v1/files-auth", headers={**headers, "X-Forwarded-Uri": uri}, **extra
        ).status_code
        return code

    assert may_fetch(f"/files/documents/{own.sha256}.pdf") == 204
    assert may_fetch(f"/files/renders/{own.sha256}/1.png") == 204
    assert may_fetch(f"/files/documents/{foreign.sha256}.pdf") == 404
    assert may_fetch("/files/documents/../.env") == 404
    no_token = client.get(
        "/api/v1/files-auth",
        headers={**PUBLIC, "X-Forwarded-Uri": f"/files/documents/{own.sha256}.pdf"},
    )
    assert no_token.status_code == 401
    by_cookie = client.get(
        "/api/v1/files-auth",
        headers={**PUBLIC, "X-Forwarded-Uri": f"/files/documents/{own.sha256}.pdf"},
        cookies={"review_token": token},
    )
    assert by_cookie.status_code == 204


def test_every_change_request_is_audited_with_the_reviewer_and_its_outcome(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    token = link(client, tender["id"])["token"]
    body = review(client, tender["id"], token)
    decide(client, token, current(body, EMD), "approved")
    client.post(f"/api/v1/tenders/{tender['id']}/complete-review", headers=as_reviewer(token))
    rows = list(
        db.scalars(
            select(AuditLog).where(AuditLog.table_name == "request", AuditLog.actor == "Asha Rao")
        )
    )
    outcomes = {(row.after["path"], row.after["status"]) for row in rows if row.after}
    assert ("/api/v1/approvals", 201) in outcomes
    assert (f"/api/v1/tenders/{tender['id']}/complete-review", 422) in outcomes
    assert all(row.after and row.after["review_token_id"] for row in rows)
    reads = db.scalars(select(AuditLog).where(AuditLog.action == "http_get")).all()
    assert reads == []


def test_the_command_prints_a_link_and_lists_links(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = extracted(client, pipeline)
    row = db.scalars(select(Tender).where(Tender.id == tender["id"])).one()
    row.slug = "acme-solar-600"
    db.commit()
    url = review_token_command.create(pipeline.settings, "acme-solar-600", "Asha Rao")
    token = url.rsplit("/", 1)[1]
    assert url.startswith("https://34.131.65.108/review/") and len(token) == 32
    assert client.get("/api/v1/review-session", headers=as_reviewer(token)).status_code == 200
    review_token_command.create(pipeline.settings, tender["id"], "Bela Shah")
    lines = review_token_command.listing(pipeline.settings)
    assert len(lines) == 2 and "revoked" in lines[0] and "live until" in lines[1]
    assert "Bela Shah" in lines[1]
