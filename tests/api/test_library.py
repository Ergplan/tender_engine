"""The library tier over HTTP: search and matching, the model and its tier wall, the
watchlist, the public correction form, an admin's cases and holds."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.main import create_app
from tests.api.test_auth import PUBLIC, SETTINGS, sign_in
from tests.conftest import Pipeline
from tests.evals.test_gold import completed_review
from tests.fixtures.oidc import FakeOidc, account
from tests.fixtures.tenders import EMD

BOSS = {"X-Admin-Token": SETTINGS["admin_token"]}


@pytest.fixture()
def stack(make_pipeline: Callable[..., Pipeline]) -> tuple[Pipeline, TestClient, FakeOidc]:
    pipeline = make_pipeline(**{**SETTINGS, "free_signup_enabled": True})
    oidc = FakeOidc(
        {
            "code-boss": account("boss@acme.test"),
            "code-asha": account("asha@acme.test"),
            "code-reader": account("reader@elsewhere.test", name="A Reader"),
        }
    )
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    return pipeline, TestClient(app, base_url="https://testserver", follow_redirects=False), oidc


def _browser(stack: tuple[Pipeline, TestClient, FakeOidc], code: str) -> TestClient:
    client = TestClient(stack[1].app, base_url="https://testserver", follow_redirects=False)
    assert sign_in(client, code).status_code == 302
    return client


def test_search_match_model_assumptions_and_watchlist(
    stack: tuple[Pipeline, TestClient, FakeOidc], db: Session
) -> None:
    pipeline, internal, _ = stack
    reviewed, _ = completed_review(internal, pipeline)
    tid = reviewed["id"]
    asha = _browser(stack, "code-asha")

    hits = asha.get("/api/v1/tenders/search", headers=PUBLIC)
    assert hits.status_code == 200, hits.text
    found = hits.json()
    assert [h["tender_id"] for h in found["hits"]] == [tid]
    assert found["hits"][0]["reviewed_at"] and found["hits"][0]["reviewer_role"] == "reviewer"
    assert "reliability" in found["hits"][0] and "authoritative source" in found["authority_note"]
    assert asha.get("/api/v1/tenders/search?tender_type=wind", headers=PUBLIC).json()["hits"] == []
    match = asha.get(
        "/api/v1/tenders/match", params={"title_or_number": "ACME/RE/2026/007"}, headers=PUBLIC
    )
    assert match.status_code == 200 and match.json()["kind"] == "match"
    assert match.json()["tender"]["tender_id"] == tid and match.json()["authority_note"]
    nothing = asha.get(
        "/api/v1/tenders/match", params={"title_or_number": "zzz qqq"}, headers=PUBLIC
    )
    assert nothing.json()["kind"] == "no_match" and nothing.json()["authority_note"]

    modelled = asha.post(
        f"/api/v1/tenders/{tid}/model",
        json={"assumptions": {"capex_inr_crore_per_mw": 3.8}},
        headers=PUBLIC,
    )
    assert modelled.status_code == 200, modelled.text
    body = modelled.json()
    assert body["label"] == "indicative" and body["assumptions_saved"] is False
    assert body["assumptions"]["capex_inr_crore_per_mw"] == 3.8
    assert {p["name"] for p in body["fixed"]} >= {"capacity_mw", "tariff_inr_per_kwh"}
    assert "note" in body
    bad = asha.post(f"/api/v1/tenders/{tid}/model", json={"model_type": "x"}, headers=PUBLIC)
    assert bad.status_code == 422

    saved = asha.put(
        f"/api/v1/tenders/{tid}/assumptions",
        json={"assumptions": {"capex_inr_crore_per_mw": 4.4}},
        headers=PUBLIC,
    )
    assert saved.status_code == 200 and saved.json()["assumptions"]["capex_inr_crore_per_mw"] == 4.4
    again = asha.post(f"/api/v1/tenders/{tid}/model", json={}, headers=PUBLIC).json()
    assert again["assumptions_saved"] is True
    assert again["assumptions"]["capex_inr_crore_per_mw"] == 4.4

    assert asha.get("/api/v1/me/watchlist", headers=PUBLIC).json() == []
    added = asha.post("/api/v1/me/watchlist", json={"tender_id": tid}, headers=PUBLIC)
    assert added.status_code == 201 and added.json()[0]["tender_id"] == tid
    assert added.json()[0]["days_remaining"] is not None
    missing = asha.post("/api/v1/me/watchlist", json={"tender_id": "0" * 32}, headers=PUBLIC)
    assert missing.status_code == 404
    removed = asha.request(
        "DELETE", "/api/v1/me/watchlist", json={"tender_id": tid}, headers=PUBLIC
    )
    assert removed.status_code == 200 and removed.json() == []


def test_a_free_account_reads_the_library_and_is_refused_the_model(
    stack: tuple[Pipeline, TestClient, FakeOidc], db: Session
) -> None:
    pipeline, internal, _ = stack
    reviewed, _ = completed_review(internal, pipeline)
    reader = _browser(stack, "code-reader")
    me = reader.get("/api/v1/auth/me", headers=PUBLIC).json()
    assert me["tenant_id"].startswith("free-") and me["read_tenants"] == [me["tenant_id"], "public"]
    # Their own tenant has no tenders; the library has none yet either: an empty search.
    assert reader.get("/api/v1/tenders/search", headers=PUBLIC).json()["hits"] == []
    assert reader.get("/api/v1/tenders", headers=PUBLIC).json() == []
    # The watchlist is a paid tier's tool.
    for method, body in (
        ("GET", None),
        ("POST", {"tender_id": reviewed["id"]}),
        ("DELETE", {"tender_id": reviewed["id"]}),
    ):
        shut = reader.request(method, "/api/v1/me/watchlist", json=body, headers=PUBLIC)
        assert shut.status_code == 403 and shut.json()["error_type"] == "tier_required", method
    refused = reader.post(f"/api/v1/tenders/{reviewed['id']}/model", json={}, headers=PUBLIC)
    assert refused.status_code == 403 and refused.json()["error_type"] == "tier_required"
    refused = reader.put(
        f"/api/v1/tenders/{reviewed['id']}/assumptions", json={"assumptions": {}}, headers=PUBLIC
    )
    assert refused.status_code == 403
    # A second sign-in is the same account.
    again = _browser(stack, "code-reader")
    assert again.get("/api/v1/auth/me", headers=PUBLIC).json()["tenant_id"] == me["tenant_id"]


def test_programmatic_signup_and_a_closed_signup(
    make_pipeline: Callable[..., Pipeline],
) -> None:
    oidc = FakeOidc({"code-reader": account("reader@elsewhere.test")})
    pipeline = make_pipeline(**{**SETTINGS, "free_signup_enabled": True})
    client = TestClient(
        create_app(
            pipeline.settings,
            pipeline.schemas,
            pipeline.storage,
            pipeline.llm,
            pipeline.catalog,
            oidc=oidc,
        ),
        base_url="https://testserver",
    )
    made = client.post("/api/v1/auth/signup", json={"code": "code-reader"}, headers=PUBLIC)
    assert made.status_code == 201, made.text
    assert "tie_session" in client.cookies
    assert client.get("/api/v1/auth/me", headers=PUBLIC).json()["tenant_id"].startswith("free-")
    unknown = client.post("/api/v1/auth/signup", json={"code": "nope"}, headers=PUBLIC)
    assert unknown.status_code == 403

    closed = make_pipeline(**{**SETTINGS, "free_signup_enabled": False})
    shut = TestClient(
        create_app(
            closed.settings, closed.schemas, closed.storage, closed.llm, closed.catalog, oidc=oidc
        ),
        base_url="https://testserver",
        follow_redirects=False,
    )
    assert (
        shut.post("/api/v1/auth/signup", json={"code": "code-reader"}, headers=PUBLIC).status_code
        == 403
    )
    refused = sign_in(shut, "code-reader")
    assert refused.status_code == 403 and refused.json()["error_type"] == "login_refused"


def test_the_public_correction_form_and_the_admins_cases_and_holds(
    stack: tuple[Pipeline, TestClient, FakeOidc], db: Session
) -> None:
    pipeline, internal, _ = stack
    reviewed, _ = completed_review(internal, pipeline)
    tid = reviewed["id"]
    anyone = TestClient(stack[1].app, base_url="https://testserver")
    claim: dict[str, Any] = {
        "tender_id": tid,
        "field_path": EMD,
        "claimed_error": "per project, not per MW",
        "reasoning": "clause 17",
    }
    no_email = anyone.post("/api/v1/public/corrections", json=claim, headers=PUBLIC)
    assert no_email.status_code == 422 and "email" in no_email.json()["detail"]
    opened = anyone.post(
        "/api/v1/public/corrections", json={**claim, "claimant_email": "x@y.z"}, headers=PUBLIC
    )
    assert opened.status_code == 201, opened.text
    case = opened.json()
    assert case["status"] == "open" and case["claimant_email"] == "x@y.z"
    assert case["claimant_tenant_id"] is None
    # The value stands as it was.
    published = internal.get(f"/api/v1/tenders/{tid}/published").json()
    emd = next(f for s in published["sections"] for f in s["fields"] if f["path"] == EMD)
    assert emd["value"] == 1000000

    asha = _browser(stack, "code-asha")
    signed = asha.post(
        "/api/v1/public/corrections",
        json={**claim, "field_path": "core.identity.title"},
        headers=PUBLIC,
    )
    assert signed.status_code == 201 and signed.json()["claimant_tenant_id"] == "ergplan"
    assert asha.get("/api/v1/admin/corrections", headers=PUBLIC).status_code == 403

    cases = internal.get("/api/v1/admin/corrections", headers=BOSS)
    assert cases.status_code == 200 and [c["id"] for c in cases.json()] == [
        case["id"],
        signed.json()["id"],
    ]
    resolved = internal.post(
        f"/api/v1/admin/corrections/{case['id']}/resolve",
        json={"accepted": False, "resolution": "the clause reads per MW"},
        headers=BOSS,
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "rejected"
    assert (
        internal.post(
            f"/api/v1/admin/corrections/{case['id']}/resolve",
            json={"accepted": True, "resolution": "x"},
            headers=BOSS,
        ).status_code
        == 409
    )
    assert (
        internal.get("/api/v1/admin/corrections?status=open", headers=BOSS).json()[0]["id"]
        == signed.json()["id"]
    )

    held = internal.post(
        "/api/v1/admin/holds",
        json={
            "tender_id": tid,
            "kind": "correction",
            "reason": "under review",
            "requested_at": "2026-10-17T09:30:00+00:00",
        },
        headers=BOSS,
    )
    assert held.status_code == 201, held.text
    assert held.json()["requested_at"].startswith("2026-10-17T09:30")
    suspended = internal.get(f"/api/v1/tenders/{tid}/published").json()
    assert suspended["publication"]["state"] == "publication_suspended"
    assert suspended["sections"] == [] and suspended["suspension"]["fields"] == ["hold:correction"]
    assert asha.get("/api/v1/tenders/search", headers=PUBLIC).json()["hits"] == []
    listed = internal.get("/api/v1/admin/holds", headers=BOSS).json()
    assert [h["id"] for h in listed] == [held.json()["id"]]
    lifted = internal.delete(f"/api/v1/admin/holds/{held.json()['id']}", headers=BOSS)
    assert lifted.status_code == 200 and lifted.json()["lifted_at"]
    assert (
        internal.get(f"/api/v1/tenders/{tid}/published").json()["publication"]["state"]
        == "published"
    )
    assert (
        internal.delete(f"/api/v1/admin/holds/{held.json()['id']}", headers=BOSS).status_code == 409
    )
    assert (
        internal.post(
            "/api/v1/admin/holds", json={"tender_id": "0" * 32, "reason": "r"}, headers=BOSS
        ).status_code
        == 404
    )
