"""The library tier: search over what a principal may read, matching a document in the
user's hand, free sign-up, the watchlist, assumptions and the model."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.models import AppUser, CanonicalFact, Tenant
from core.services.identity import Principal, read_tenants_of
from tender.models import ModelAssumption, Tender
from tender.services import library
from tender.services.library import (
    LibraryError,
    Match,
    NoMatch,
    find_matching_tender,
    normalise,
    search_tenders,
    signup,
)
from tender.services.publication import PublicationState
from tests.conftest import Pipeline
from tests.evals.test_gold import completed_review


@pytest.fixture()
def client(pipeline: Pipeline) -> TestClient:
    """The API wired to the pipeline, for the completed review the fixtures need."""
    from api.main import create_app

    return TestClient(
        create_app(
            pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
        )
    )


# Library tenders as a user would describe them; none persisted.
LIBRARY: list[tuple[str, str, str, str]] = [
    (
        "fdre-ix",
        "Selection of RE Power Developers for 4800 MW FDRE Power with CfD (FDRE Tranche-IX)",
        "Solar Energy Corporation of India Limited",
        "SECI/C&P/IPP/15/0010/26-27",
    ),
    (
        "cni-1",
        "700 MW ISTS-Connected Solar PV Power Projects in India (C&I-1)",
        "SECI",
        "SECI/C&P/IPP/15/0009/26-27",
    ),
    (
        "ramagiri",
        "Setting up of 70 MW / 140 MWh Standalone BESS at Ramagiri",
        "SECI",
        "SECI/C&P/BESS/04/0003/26-27",
    ),
    (
        "ntpc-fdre-x",
        "1500 MW FDRE Power Projects (FDRE Tranche X)",
        "NTPC Renewable Energy Limited",
        "NTPC/REL/FDRE/X/2026",
    ),
    # The same agency and capacity as Tranche-IX, one numeral apart.
    (
        "seci-fdre-x",
        "Selection of RE Power Developers for 4,800 MW FDRE Power with CfD (FDRE Tranche-X)",
        "SECI",
        "SECI/C&P/IPP/15/0012/26-27",
    ),
]


def _synthetic(slug: str, title: str, agency: str, ref: str) -> Tender:
    tender = Tender(
        tenant_id="public",
        created_by="t",
        tender_type="bess" if "BESS" in title else "fdre" if "FDRE" in title else "solar",
        issuing_agency=agency,
        external_ref=ref,
        title=title,
        slug=slug,
        status="reviewed",
    )
    tender.id = slug.ljust(32, "0")
    return tender


@pytest.fixture()
def catalogue(monkeypatch: pytest.MonkeyPatch) -> list[Tender]:
    tenders = [_synthetic(*row) for row in LIBRARY]
    published = PublicationState(state="published", reviewed_version=1, current_version=1)

    def visible(session: Any, tenants: Any, catalog: Any) -> list[tuple[Tender, PublicationState]]:
        return [(t, published) for t in tenders]

    monkeypatch.setattr(library, "visible_tenders", visible)
    return tenders


def test_normalise_folds_aliases_numerals_and_units() -> None:
    assert normalise("Solar Energy Corporation of India Tranche-IX, 4,800 MW") == [
        "seci",
        "tranche",
        "9",
        "4800",
        "mw",
    ]
    assert normalise("1,50,000 and 12,000,000") == ["150000", "12000000"]
    assert normalise("NTPC Limited FDRE Tranche 9 (XX)") == ["ntpc", "fdre", "tranche", "9", "20"]
    assert normalise("RfS No. SECI/C&P/IPP/15/0009/26-27")[:4] == ["seci", "ipp", "15", "0009"]


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("FDRE IX", "fdre-ix"),
        ("SECI FDRE X", "seci-fdre-x"),
        ("SECI BESS tender", "ramagiri"),
        ("RfS No. SECI/C&P/IPP/15/0009", "cni-1"),
        ("NTPC FDRE Tranche X", "ntpc-fdre-x"),
    ],
)
def test_informal_phrasings_resolve_to_the_right_tender(
    catalogue: list[Tender], pipeline: Pipeline, db: Session, said: str, expected: str
) -> None:
    found = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), said
    )
    assert isinstance(found, Match), found
    assert found.tender.slug == expected and found.score >= pipeline.settings.match_threshold


def test_a_near_miss_is_no_match_with_candidates_never_the_nearest_tender(
    catalogue: list[Tender], pipeline: Pipeline, db: Session
) -> None:
    found = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), "SECI FDRE Tranche XI"
    )
    assert isinstance(found, NoMatch)
    assert 1 <= len(found.candidates) <= 3
    assert all(c.distinguishing for c in found.candidates)
    # Two tenders that fit the words equally well are told apart by nobody: no match.
    tie = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), "FDRE power projects"
    )
    assert isinstance(tie, NoMatch) and "equally" in tie.reason
    # Two 4800 MW FDRE tenders: "the 4800 FDRE one" names both, so neither is matched;
    # the candidates carry the number that tells them apart.
    both = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), "the 4800 FDRE one"
    )
    assert isinstance(both, NoMatch)
    assert {c.tender_id for c in both.candidates} >= {
        "fdre-ix".ljust(32, "0"),
        "seci-fdre-x".ljust(32, "0"),
    }
    assert both.authority_note and "authoritative" in both.authority_note
    # A numeral the user gave that the tender lacks counts against it even when the
    # capacity agrees: "FDRE IX" at 4800 MW is IX, "FDRE X" at 4800 MW is X.
    for said, slug in (("FDRE IX", "fdre-ix"), ("FDRE X", "seci-fdre-x")):
        sized = find_matching_tender(
            db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), said, capacity_mw=4800
        )
        assert isinstance(sized, Match) and sized.tender.slug == slug, said
        assert sized.authority_note and sized.tender.reviewed_at is None, "a synthetic tender"
    # An agency that contradicts the words caps the score; a capacity near the title's
    # figure lifts it.
    wrong_agency = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), "FDRE IX", agency="NHPC"
    )
    assert isinstance(wrong_agency, NoMatch)
    sized = find_matching_tender(
        db, pipeline.catalog, pipeline.settings, ("ergplan", "public"), "FDRE IX", capacity_mw=4800
    )
    assert isinstance(sized, Match) and sized.tender.slug == "fdre-ix"
    assert isinstance(
        find_matching_tender(db, pipeline.catalog, pipeline.settings, ("public",), "   "), NoMatch
    )


def test_search_narrows_by_words_type_agency_and_state(
    catalogue: list[Tender], pipeline: Pipeline, db: Session
) -> None:
    tenants = ("ergplan", "public")

    def slugs(**narrow: Any) -> list[str | None]:
        return [h.slug for h in search_tenders(db, pipeline.catalog, tenants, **narrow).hits]

    assert slugs() == [t.slug for t in catalogue]
    assert slugs(query="bess") == ["ramagiri"]
    assert slugs(tender_type="fdre") == ["fdre-ix", "ntpc-fdre-x", "seci-fdre-x"]
    assert slugs(agency="NTPC") == ["ntpc-fdre-x"]
    assert slugs(state="update_pending") == []
    result = search_tenders(db, pipeline.catalog, tenants, query="ramagiri")
    hit = result.hits[0]
    assert hit.publication.state == "published" and hit.banner is None
    assert "authoritative source" in result.authority_note


def test_only_a_reviewed_tender_is_visible_and_an_unreviewed_one_is_not(
    client: TestClient, pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    other = pipeline.tenders.create(
        db,
        tender_type="wind",
        issuing_agency="Acme",
        external_ref=None,
        title="Unreviewed wind tender",
        created_by="pytest",
    )
    hits = search_tenders(db, pipeline.catalog, ("ergplan", "public"), results_root=tmp_path).hits
    assert [h.tender_id for h in hits] == [reviewed["id"]]
    assert other.id not in {h.tender_id for h in hits}
    # The provenance every public response carries; the reliability block from the
    # results folder, none here.
    assert hits[0].reviewed_at is not None and hits[0].reviewer_role == "reviewer"
    assert hits[0].reliability is None


def test_signup_makes_a_free_tenant_that_reads_the_library_and_cannot_write_it(
    db: Session, settings: Settings
) -> None:
    public = make_session_factory(make_engine(settings), "public")
    with public() as lib:
        lib.add(
            Tender(
                tenant_id="public",
                created_by="t",
                tender_type="solar",
                issuing_agency="SECI",
                title="A library tender",
                status="ingested",
            )
        )
        lib.commit()
    tenant, user = signup(
        db, email="Reader@Example.org", display_name="A Reader", oidc_subject="sub-reader"
    )
    assert tenant.tenant_id.startswith("free-") and tenant.plan == "free"
    assert user.role == "reviewer" and user.email == "reader@example.org"
    assert read_tenants_of(tenant.tenant_id) == (tenant.tenant_id, "public")
    with pytest.raises(LibraryError, match="already exists"):
        signup(db, email="reader@example.org", display_name="Again", oidc_subject="sub-reader")
    theirs = make_session_factory(make_engine(settings), tenant.tenant_id, read_tenants=("public",))
    with theirs() as session:
        assert session.scalars(select(Tender.title)).all() == ["A library tender"]
        assert session.scalar(select(Tenant.plan).where(Tenant.tenant_id == tenant.tenant_id)) == (
            "free"
        )
        assert library.is_free(session, tenant.tenant_id)
        session.add(
            Tender(
                tenant_id="public",
                created_by="reader",
                tender_type="solar",
                issuing_agency="X",
                title="Defaced",
                status="ingested",
            )
        )
        with pytest.raises(ProgrammingError, match="row-level security"):
            session.commit()
        session.rollback()
        assert (
            session.execute(
                text("UPDATE tender SET title = 'defaced' WHERE tenant_id = 'public'")
            ).rowcount
            == 0
        )
        session.rollback()
    with public() as lib:
        assert lib.scalars(select(Tender.title)).all() == ["A library tender"]


def _principal(db: Session, email: str = "asha@acme.test") -> Principal:
    user = AppUser(
        tenant_id="ergplan",
        created_by="t",
        email=email,
        display_name=email,
        role="reviewer",
        status="active",
    )
    db.add(user)
    db.commit()
    return Principal(
        kind="user",
        tenant_id="ergplan",
        read_tenants=("ergplan", "public"),
        role="reviewer",
        user_id=user.id,
        name=email,
    )


def test_the_watchlist_follows_a_tender_with_its_deadline(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    who = _principal(db)
    library.watchlist_add(db, who, tender)
    library.watchlist_add(db, who, tender)  # once
    watched = library.watchlist(db, pipeline.catalog, pipeline.tenders, who)
    assert [w.tender_id for w in watched] == [tender.id]
    assert watched[0].publication_state == "published"
    assert watched[0].bid_deadline is not None and watched[0].days_remaining is not None
    assert library.watchlist_remove(db, who, tender.id) is True
    assert library.watchlist_remove(db, who, tender.id) is False
    assert library.watchlist(db, pipeline.catalog, pipeline.tenders, who) == []


def test_assumptions_are_the_users_and_never_a_fact_and_the_model_is_read_only(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    who = _principal(db)
    facts_before = db.scalar(select(func.count()).select_from(CanonicalFact))
    row = library.upsert_assumptions(
        db, who, tender, "power_project_finance", {"capex_inr_crore_per_mw": 3.9}
    )
    assert row.assumptions["capex_inr_crore_per_mw"] == 3.9
    assert row.assumptions["debt_share_percent"] == 75.0, "the rest are the defaults"
    again = library.upsert_assumptions(
        db, who, tender, "power_project_finance", {"capex_inr_crore_per_mw": 4.2}
    )
    assert again.id == row.id and again.assumptions["capex_inr_crore_per_mw"] == 4.2
    assert db.scalar(select(func.count()).select_from(ModelAssumption)) == 1
    with pytest.raises(LibraryError, match="unknown assumption"):
        library.upsert_assumptions(db, who, tender, "power_project_finance", {"magic": 1})
    with pytest.raises(LibraryError, match="unknown model type"):
        library.upsert_assumptions(db, who, tender, "astrology", {})

    result = library.model_tender(db, pipeline.catalog, who, tender, "power_project_finance")
    assert result.label == "indicative" and result.assumptions_saved
    assert result.assumptions.capex_inr_crore_per_mw == 4.2
    assert {p.name for p in result.fixed} >= {
        "capacity_mw",
        "tariff_inr_per_kwh",
        "payment_security",
    }
    assert all(
        p.status in ("reviewed", "not_reviewed", "possibly_superseded", "not_in_schema")
        for p in result.fixed
    )
    assert all(p.gap_reason for p in result.fixed if p.value is None)
    override = library.model_tender(
        db, pipeline.catalog, who, tender, "power_project_finance", {"capex_inr_crore_per_mw": 5.0}
    )
    assert override.assumptions.capex_inr_crore_per_mw == 5.0
    assert db.scalar(select(func.count()).select_from(ModelAssumption)) == 1, "a read saves nothing"
    assert db.scalar(select(func.count()).select_from(CanonicalFact)) == facts_before
    if override.outputs is not None:
        assert override.outputs.label == "indicative" and override.outputs.capex_crore > 0
    else:
        assert "capacity" in override.note
