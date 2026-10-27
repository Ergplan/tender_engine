"""The pure parts of the Block 4 check (scripts/blind_check.py): bands, rules, the
classification and linking outcomes."""

from scripts.blind_check import (
    FieldReading,
    band_table,
    classification_outcome,
    link_outcome,
    rate,
    rule_table,
)
from tender.services.amendment_link import AmendmentLink


def _reading(confidence: float, located: bool, status: str = "validated", rules=()) -> FieldReading:  # type: ignore[no-untyped-def]
    return FieldReading(
        path="core.x", section="s", version_no=1, confidence=confidence, located=located,
        status=status, rules=list(rules),
    )  # fmt: skip


def test_bands_count_answered_and_located_per_band() -> None:
    readings = [
        _reading(0.95, True),
        _reading(0.8, False),
        _reading(0.6, True),
        _reading(0.2, False),
    ]
    bands = band_table(readings)
    assert bands["high"] == {"answered": 2, "located": 1}
    assert bands["medium"] == {"answered": 1, "located": 1}
    assert bands["low"] == {"answered": 1, "located": 0}


def test_rules_count_passes_failures_by_severity_and_the_failing_rules() -> None:
    readings = [
        _reading(
            0.9, True, "needs_review", [("date_order", False, "error"), ("emd_band", True, "error")]
        ),
        _reading(
            0.9,
            True,
            "validated",
            [("emd_band", True, "error"), ("scalar_agree", False, "warning")],
        ),
    ]
    rules = rule_table(readings)
    assert (rules["rules_run"], rules["passed"]) == (4, 2)
    assert (rules["failed_errors"], rules["failed_warnings"]) == (1, 1)
    assert rules["failing_rules"] == {"date_order (error)": 1, "scalar_agree (warning)": 1}
    assert rules["fields_needs_review"] == 1


def test_link_outcomes_name_own_tender_elsewhere_and_ask() -> None:
    def link(state: str, tender_id: str | None) -> AmendmentLink:
        return AmendmentLink(
            state=state, tender_id=tender_id, confidence=0.9, method="reference",
            references_found=[], candidates=[], reason="",
        )  # type: ignore[arg-type]  # fmt: skip

    assert link_outcome(link("linked", "t1"), "t1") == "linked_to_own"
    assert link_outcome(link("linked", "t2"), "t1") == "linked_elsewhere"
    assert link_outcome(link("ask", None), "t1") == "ask"


def test_classification_outcomes_follow_the_bands() -> None:
    assert classification_outcome("solar", None) == "not_run"
    assert classification_outcome("solar", {"tender_type": "solar", "state": "set"}) == "agree"
    assert (
        classification_outcome("re_rtc", {"tender_type": "fdre", "state": "unsure"})
        == "differ_unsure"
    )
    assert (
        classification_outcome("solar", {"tender_type": "solar", "state": "unsure"})
        == "agree_unsure"
    )
    assert classification_outcome("solar", {"tender_type": "wind", "state": "set"}) == "differ"
    assert (
        classification_outcome("solar", {"tender_type": "unknown", "state": "unknown"}) == "unknown"
    )
    assert rate(1, 3) == "33.3%" and rate(0, 0) == "-"
