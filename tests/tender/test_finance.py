"""The one financial engine: deterministic, indicative, honest about what it used."""

from tender.services.finance import Assumptions, FixedInputs, irr, power_project_finance

FIXED = FixedInputs(
    capacity_mw=100,
    tariff_inr_per_kwh=2.9,
    cuf_floor_percent=24,
    cuf_ceiling_percent=30,
    ppa_tenure_years=25,
    scod_months=24,
    degradation_cap_percent=0.5,
    pbg_inr_per_mw=2_320_000,
    pbg_duration_months=30,
    ists_waiver=True,
    sources={"tariff_inr_per_kwh": "RfS p.63", "cuf_floor_percent": "RfS p.38"},
)


def test_irr_by_bisection() -> None:
    assert irr([-100, 110]) is not None and abs(irr([-100, 110]) - 0.10) < 1e-6  # type: ignore[operator]
    assert irr([100, 110]) is None and irr([]) is None


def test_the_engine_is_deterministic_and_names_what_it_used() -> None:
    first = power_project_finance(FIXED, Assumptions())
    second = power_project_finance(FIXED, Assumptions())
    assert first == second
    assert first.label == "indicative" and first.capex_crore == 410.0
    assert first.used == {
        "tariff": "RfS p.63",
        "cuf": "RfS p.38",
        "tenure": "tender",
        "degradation": "tender",
    }
    assert first.project_irr_percent is not None and 5 < first.project_irr_percent < 15
    assert (
        first.equity_irr_percent is not None
        and first.equity_irr_percent > first.project_irr_percent
    )
    assert (
        first.levelised_cost_inr_per_kwh is not None and 0.8 < first.levelised_cost_inr_per_kwh < 2
    )
    assert first.payback_years is not None and 5 < first.payback_years < 15
    assert len(first.cashflows) == 25 and first.cashflows[0].year == 1
    # Degradation lowers generation year on year; the cap is honoured.
    assert first.cashflows[1].generation_mwh < first.cashflows[0].generation_mwh


def test_missing_tender_parameters_fall_back_to_assumptions_and_say_so() -> None:
    bare = FixedInputs(
        capacity_mw=50,
        tariff_inr_per_kwh=None,
        cuf_floor_percent=None,
        cuf_ceiling_percent=None,
        ppa_tenure_years=None,
        scod_months=None,
        degradation_cap_percent=None,
        pbg_inr_per_mw=None,
        pbg_duration_months=None,
        ists_waiver=None,
    )
    out = power_project_finance(bare, Assumptions(cuf_percent=20, tariff_inr_per_kwh=3.5))
    assert out.used == {
        "tariff": "assumed",
        "cuf": "assumed",
        "tenure": "assumed",
        "degradation": "none",
    }
    assert len(out.cashflows) == Assumptions().ppa_tenure_years


def test_a_higher_tariff_raises_the_returns_and_a_higher_capex_lowers_them() -> None:
    base = power_project_finance(FIXED, Assumptions())
    richer = power_project_finance(
        FixedInputs(**{**FIXED.__dict__, "tariff_inr_per_kwh": 3.5}), Assumptions()
    )
    dearer = power_project_finance(FIXED, Assumptions(capex_inr_crore_per_mw=5.5))
    assert richer.project_irr_percent > base.project_irr_percent  # type: ignore[operator]
    assert dearer.project_irr_percent < base.project_irr_percent  # type: ignore[operator]
    assert dearer.levelised_cost_inr_per_kwh > base.levelised_cost_inr_per_kwh  # type: ignore[operator]
