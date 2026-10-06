"""The feedback report groups the corrections of standing decisions and suggests a change."""

from fastapi.testclient import TestClient

from evals.feedback_report import FeedbackRow, group, load_feedback, render, suggestion
from tests.api.test_review_tokens import current, decide, link, review
from tests.api.test_tenders import extracted
from tests.conftest import Pipeline

EMD = "core.guarantees.emd_per_mw_inr"


def row(
    path: str, kind: str, slug: str = "t1", agency: str = "SECI", version: str = "v1"
) -> FeedbackRow:
    return FeedbackRow(
        field_path=path,
        delta_kind=kind,
        tender_slug=slug,
        tender_type="solar",
        issuing_agency=agency,
        prompt_version=version,
        reviewer="Asha Rao",
        candidate_value=1,
        final_value=2,
        note="table says 2",
    )


def test_the_report_ranks_fields_by_corrections_and_suggests_one_change_each() -> None:
    rows = [
        row(EMD, "wrong_value"),
        row(EMD, "wrong_value", slug="t2", agency="NTPC", version="v2"),
        row(EMD, "format", slug="t3"),
        row("core.key_dates.pre_bid_meeting", "missing"),
        row("core.commercial.tariff_ceiling_inr_per_kwh", "extra"),
    ]
    grouped = group(rows)
    assert grouped[EMD]["delta_kind"] == {"wrong_value": 2, "format": 1}
    assert grouped[EMD]["issuing_agency"] == {"SECI": 2, "NTPC": 1}
    assert grouped[EMD]["prompt_version"] == {"v1": 2, "v2": 1}
    assert suggestion(grouped[EMD]["delta_kind"]).startswith("prompt: name the clause")
    assert suggestion(grouped["core.key_dates.pre_bid_meeting"]["delta_kind"]).startswith(
        "prompt or routing"
    )
    text = render(rows)
    assert "Corrections: 5 on 3 field(s), 3 tender(s)." in text
    assert "| wrong_value | 2 |" in text and "| extra | 1 |" in text
    first = text.index(f"### `{EMD}`: 3 correction(s)")
    assert first < text.index("### `core.key_dates.pre_bid_meeting`: 1 correction(s)")
    assert "| t1 | wrong_value | 1 | 2 | table says 2 |" in text
    assert "Suggested change: validator or normaliser" not in text
    assert render([]).count("No corrections yet.") == 1


def test_only_the_feedback_of_standing_decisions_is_read(
    client: TestClient,
    pipeline: Pipeline,
    db,  # type: ignore[no-untyped-def]
) -> None:
    tender = extracted(client, pipeline)
    tid = tender["id"]
    token = link(client, tid)["token"]
    body = review(client, tid, token)
    assert (
        decide(client, token, current(body, EMD), "edited", final_value=930000).status_code == 201
    )
    rows = load_feedback(db, pipeline.settings.tenant_id)
    assert [(r.field_path, r.delta_kind, r.final_value) for r in rows] == [
        (EMD, "wrong_value", 930000)
    ]
    assert rows[0].tender_slug == tid and rows[0].tender_type == "solar"
    # Cleared: the decision no longer stands, and its correction is history.
    body = review(client, tid, token)
    assert decide(client, token, current(body, EMD), "cleared").status_code == 201
    assert load_feedback(db, pipeline.settings.tenant_id) == []
