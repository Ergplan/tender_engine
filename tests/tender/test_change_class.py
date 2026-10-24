"""Block 3 c: every registered change kind is told from the kind, the value type and the
field, and the amendment view counts them per version."""

from tender.services.amendments import change_class


def test_each_registered_change_kind_is_recognised() -> None:
    assert change_class("removed", "text", "core.penalties.shortfall_rules") == "clause_withdrawn"
    assert (
        change_class("added", "money_inr", "core.guarantees.pbg_per_mw_inr") == "requirement_added"
    )
    assert change_class("restated", "int", "core.key_dates.bid_validity") == "restated"
    assert change_class("changed", "date", "core.key_dates.bid_submission_deadline") == "date_moved"
    assert (
        change_class("changed", "list_text", "core.documents.annexure_formats")
        == "annexure_replaced"
    )
    assert (
        change_class("changed", "text", "core.documents.required_documents") == "annexure_replaced"
    )
    assert change_class("changed", "money_inr", "core.guarantees.emd_per_mw_inr") == "value_changed"
    assert (
        change_class("changed", "enum", "sector.power.common.land_responsibility")
        == "value_changed"
    )
