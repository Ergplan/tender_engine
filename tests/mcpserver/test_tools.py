"""The library's tools over a session and a principal: every tool, its complete text,
the tiers, the metering and the free tier's limits."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine, make_session_factory
from core.models import Document, UsageRecord
from core.services.identity import Principal
from mcpserver import tools
from mcpserver.tools import ToolRefused
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE
from tests.mcpserver.conftest import context_for


def run(state: SimpleNamespace, db: Session, principal: Principal, name: str, **kwargs):  # type: ignore[no-untyped-def]
    ctx = context_for(state, db, principal)
    fn = {
        "search_tenders": tools.search_tenders,
        "get_tender": tools.get_tender,
        "get_field": tools.get_field,
        "get_document_page": tools.get_document_page,
        "find_matching_tender": tools.find_matching,
        "list_changes": tools.list_changes,
        "compare_tenders": tools.compare,
        "reliability_report": tools.reliability_report,
        "model_tender": tools.model_tender,
        "save_model_assumptions": tools.save_model_assumptions,
        "my_watchlist": tools.my_watchlist,
    }[name]
    return tools.run_tool(ctx, name, lambda tier: fn(ctx, **kwargs))


def test_the_free_tier_reads_the_library_and_every_text_is_complete(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    free_principal: Principal,
) -> None:
    _, public_db, tender_id = library
    found = run(state, db, free_principal, "search_tenders", query="solar")
    assert [t.tender_id for t in found.structured.tenders] == [tender_id]
    assert found.structured.tenders[0].publication.state == "published"
    assert "600 MW" in found.text and "authoritative source" in found.text

    card = run(state, db, free_principal, "get_tender", tender=tender_id)
    view = card.structured
    assert card.resource_tenant_id == "public"
    labels = [f.label for s in view.sections for f in s.fields]
    assert labels and all(label in card.text for label in labels), "the text names every field"
    assert card.structured.provenance.reviewed_at is not None
    assert "reviewed" in card.text and "Publication: published" in card.text
    dumped = json.dumps(card.structured_content())
    assert "candidate" not in dumped.lower() or "candidate_value" not in dumped

    field = run(state, db, free_principal, "get_field", tender=tender_id, field_path=DEADLINE)
    assert field.structured.field.status == "reviewed" and "2026-03-30" in field.text
    assert field.structured.field.evidence and field.structured.field.evidence[0].page_no == 2
    undecided = [f.path for s in view.sections for f in s.fields if f.status == "not_reviewed"]
    if undecided:
        gap = run(state, db, free_principal, "get_field", tender=tender_id, field_path=undecided[0])
        assert gap.structured.field.status == "not_reviewed" and "not reviewed" in gap.text

    document = public_db.scalar(select(Document))
    assert document is not None
    page = run(
        state,
        db,
        free_principal,
        "get_document_page",
        document_id=document.id,
        page_no=2,
        quote="The last date of bid submission is 30.03.2026",
    )
    assert page.structured.highlight is not None and page.structured.highlight.bbox
    assert page.structured.render_url.endswith(".png") and "30.03.2026" in page.text
    assert page.structured.image_data_url.startswith("data:image/png;base64,")
    assert page.text.rstrip().endswith("reading of it.") and page.resource_tenant_id == "public"

    changes = run(state, db, free_principal, "list_changes", tender=tender_id)
    assert [v.version_no for v in changes.structured.versions] == [1]
    assert "Version 1" in changes.text

    comparison = run(state, db, free_principal, "compare_tenders", tenders=[tender_id])
    assert len(comparison.structured.columns) == 1 and comparison.resource_tenant_id == "public"
    assert "Bid submission deadline" in comparison.text

    report = run(state, db, free_principal, "reliability_report")
    assert "Reliability" in report.text or "No evaluation" in report.text

    match = run(
        state, db, free_principal, "find_matching_tender", title_or_number="600 MW solar PV Acme"
    )
    assert match.structured.result.kind == "match"
    assert match.structured.result.tender.tender_id == tender_id and "Match:" in match.text
    miss = run(state, db, free_principal, "find_matching_tender", title_or_number="wind tranche XI")
    assert miss.structured.result.kind == "no_match" and "Nothing was matched silently" in miss.text


def test_usage_is_attributed_to_the_calling_tenant_with_the_library_as_resource(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    free_principal: Principal,
) -> None:
    _, _, tender_id = library
    run(state, db, free_principal, "get_tender", tender=tender_id)
    rows = list(db.scalars(select(UsageRecord).where(UsageRecord.tenant_id == "freeco")))
    assert len(rows) == 1
    assert rows[0].tool == "mcp:get_tender" and rows[0].tier == "free" and rows[0].status == 200
    assert rows[0].api_key_id == free_principal.api_key_id
    assert rows[0].resource_tenant_id == "public"
    assert db.scalars(select(UsageRecord).where(UsageRecord.tenant_id == "public")).first() is None


def test_the_free_tier_is_refused_the_paid_tools_and_rate_limited(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    free_principal: Principal,
) -> None:
    _, _, tender_id = library
    with pytest.raises(ToolRefused) as refused:
        run(state, db, free_principal, "model_tender", tender=tender_id)
    assert refused.value.error_type == "tier_required" and refused.value.status == 403
    refusals = list(db.scalars(select(UsageRecord).where(UsageRecord.status == 403)))
    assert len(refusals) == 1 and refusals[0].tool == "mcp:model_tender"

    state.settings = state.settings.model_copy(update={"free_rate_limit_per_min": 2})
    run(state, db, free_principal, "reliability_report")
    with pytest.raises(ToolRefused) as limited:
        run(state, db, free_principal, "reliability_report")
    assert limited.value.error_type == "rate_limited" and limited.value.status == 429
    # The allowance is the tenant's: a second key of the same tenant is as spent.
    identity = state.identity
    with make_session_factory(make_engine(state.settings), "freeco")() as theirs:
        _, raw = identity.create_api_key(
            theirs, "freeco", "second", ["public:read"], created_by="t"
        )
        second = identity.resolve_api_key(theirs, raw)
    assert second is not None
    with pytest.raises(ToolRefused) as also:
        run(state, db, second, "reliability_report")
    assert also.value.error_type == "rate_limited"


def test_a_library_only_token_reads_the_library_and_not_its_own_tenant(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    own_tender: str,
    enterprise_principal: Principal,
) -> None:
    _, _, public_id = library
    identity = state.identity
    _, raw = identity.create_api_key(db, "ergplan", "library only", ["public:read"], created_by="t")
    narrowed = identity.resolve_api_key(db, raw)
    assert narrowed is not None
    found = run(state, db, narrowed, "search_tenders")
    assert {t.tender_id for t in found.structured.tenders} == {public_id}
    with pytest.raises(ToolRefused) as hidden:
        run(state, db, narrowed, "get_tender", tender=own_tender)
    assert hidden.value.status == 404


def test_the_enterprise_tier_models_saves_assumptions_and_watches(
    state: SimpleNamespace,
    db: Session,
    library: tuple[Pipeline, Session, str],
    own_tender: str,
    enterprise_principal: Principal,
) -> None:
    _, _, public_id = library
    principal = Principal(
        kind="user",
        tenant_id="ergplan",
        read_tenants=("ergplan", "public"),
        role="approver",
        user_id=None,
        name="asha@ergplan.test",
    )
    # Both the own tender and the library's are readable; a free-plan tenant's is not.
    found = run(state, db, principal, "search_tenders")
    assert {t.tender_id for t in found.structured.tenders} == {own_tender, public_id}

    saved = run(
        state,
        db,
        principal,
        "save_model_assumptions",
        tender=own_tender,
        assumptions={"capex_inr_crore_per_mw": 3.9, "debt_share_percent": 70},
    )
    assert saved.structured.assumptions["capex_inr_crore_per_mw"] == 3.9
    assert saved.structured.assumptions["debt_share_percent"] == 70.0
    with pytest.raises(ToolRefused):
        run(state, db, principal, "save_model_assumptions", tender=own_tender, assumptions={"x": 1})

    model = run(
        state, db, principal, "model_tender", tender=own_tender, assumptions={"interest_percent": 9}
    )
    out = model.structured
    assert out.assumptions.capex_inr_crore_per_mw == 3.9, "saved assumptions are merged under"
    assert out.assumptions.interest_percent == 9.0 and out.assumptions_saved
    assert out.outputs is not None and out.label == "indicative" and out.outputs.capex_crore > 0
    assert any(p.name == "capacity_mw" and p.value == 600 for p in out.fixed)
    assert "Fixed by the tender" in model.text and "indicative" in model.text
    assert "Assumptions (assumed, not from the tender)" in model.text
    assert "Cashflows (INR crore)" in model.text and "Reliability" in model.text
    assert model.resource_tenant_id == "ergplan"

    watched = run(state, db, principal, "my_watchlist", add=[own_tender, public_id])
    assert sorted(watched.structured.added) == sorted([own_tender, public_id])
    assert len(watched.structured.tenders) == 2 and all(
        t.bid_deadline for t in watched.structured.tenders
    )
    assert "Watching 2 tender(s)" in watched.text
    again = run(state, db, principal, "my_watchlist", remove=[public_id])
    assert again.structured.removed == [public_id] and len(again.structured.tenders) == 1
    usage = list(db.scalars(select(UsageRecord).where(UsageRecord.tenant_id == "ergplan")))
    assert {u.tier for u in usage} == {"enterprise"}


def test_an_unknown_tender_and_too_many_tenders_are_refused(
    state: SimpleNamespace, db: Session, enterprise_principal: Principal
) -> None:
    with pytest.raises(ToolRefused) as missing:
        run(state, db, enterprise_principal, "get_tender", tender="nope")
    assert missing.value.status == 404
    with pytest.raises(ToolRefused) as many:
        run(state, db, enterprise_principal, "compare_tenders", tenders=["a"] * 7)
    assert many.value.status == 422
