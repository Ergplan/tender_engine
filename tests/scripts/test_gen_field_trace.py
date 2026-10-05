"""FIELD-TRACE.md is generated from the code and fails when a field cannot be traced."""

import pytest

from scripts import gen_field_trace
from tender.services.packs import Catalog


def test_every_field_of_every_tender_type_has_a_complete_row(catalog: Catalog) -> None:
    text = gen_field_trace.build(catalog)
    paths = {field.path for compiled in catalog.types.values() for field in compiled.fields}
    rows = [line for line in text.splitlines() if line.startswith("| `")]
    assert len(rows) == len(paths)
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 6 and all(cells), row
        assert cells[2].startswith("review/FieldCard value (") and "review/EditForm" in cells[2]
        assert "approve()" in cells[3]
        assert "extract('" in cells[3] or "SummaryWriter.write()" in cells[3]
        assert cells[4].startswith("LLM ") and "; HUMAN approval" in cells[4]
        assert cells[5].startswith("RULE type, evidence_located")
    assert "GET /v1/tenders/{tender_id}/review" in text and "POST /v1/approvals" in text
    assert "candidate.value → approval.final_value → canonical_fact.value" in text


def test_rows_are_in_review_order_and_name_the_rules_of_a_field(catalog: Catalog) -> None:
    rows = [line for line in gen_field_trace.build(catalog).splitlines() if line.startswith("| `")]
    assert rows[0].startswith("| `core.summary.plain_english_summary` | all |")
    assert "LLM summary_record v1 from the record (narrative: LLM summary v2)" in rows[0]
    deadline = next(row for row in rows if "`core.key_dates.bid_submission_deadline`" in row)
    assert "required_present" in deadline and "date_order" in deadline
    assert "LLM extract/key_dates v1" in deadline and "date picker" in deadline
    emd = next(row for row in rows if "`core.guarantees.emd_per_mw_inr`" in row)
    assert "emd_pbg_within_10x" in emd and "number with unit" in emd
    elements = next(row for row in rows if "`sector.power.transmission.elements`" in row)
    assert "| transmission |" in elements and "elements_have_kv" in elements


def test_a_value_type_the_screen_cannot_show_fails_the_trace(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    known = gen_field_trace.ui_components()
    assert {"date", "money_inr", "enum", "long_text", "record_list", "bool"} <= set(known)
    monkeypatch.setattr(
        gen_field_trace, "ui_components", lambda: {k: v for k, v in known.items() if k != "date"}
    )
    with pytest.raises(gen_field_trace.TraceError, match="no UI component for value type 'date'"):
        gen_field_trace.build(catalog)


def test_a_missing_route_fails_the_trace(catalog: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen_field_trace, "routes", lambda: {("POST", "/api/v1/approvals")})
    with pytest.raises(gen_field_trace.TraceError, match="no route GET"):
        gen_field_trace.build(catalog)


def test_the_committed_file_is_current() -> None:
    assert gen_field_trace.main(["gen_field_trace", "--check"]) == 0


def test_rows_name_the_run_rules_that_concern_the_field(catalog: Catalog) -> None:
    rows = {
        line.split("`")[1]: line
        for line in gen_field_trace.build(catalog).splitlines()
        if line.startswith("| `")
    }
    # A rule on the whole run names no field paths; each says which fields it concerns.
    assert all("later_version_evidence" in row for row in rows.values())
    structured = {path for path, row in rows.items() if "structured_numbers_quoted" in row}
    with_keys = {
        field.path for compiled in catalog.types.values() for field in compiled.fields if field.keys
    }
    assert structured == with_keys and "core.guarantees.emd_structured" in structured
    assert "core.identity.tender_number" not in structured


def test_a_run_rule_that_does_not_say_which_fields_it_concerns_fails_the_trace(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gen_field_trace, "run_rule_fields", lambda: {})
    with pytest.raises(gen_field_trace.TraceError, match="does not say which fields it concerns"):
        gen_field_trace.build(catalog)
