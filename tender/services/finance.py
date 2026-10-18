"""The one financial engine (Stage 5D): `power_project_finance`.

Serves the MCP widget, the enterprise front end and the API alike; the widget may show a
provisional figure while a slider moves, but anything saved, exported or quoted comes from
here. Deterministic: plain arithmetic on the tender-fixed parameters and the user's
assumptions, no model call, no randomness. Figures are indicative and labelled so by every
caller.

Units: capacity in MW, tariff in INR/kWh, capex in INR crore per MW, O&M in INR lakh per
MW-year, shares and rates in percent, years as years. Money out is INR crore.
"""

from dataclasses import dataclass, field

HOURS_PER_YEAR = 8760
CRORE = 1e7
LAKH = 1e5


@dataclass(frozen=True)
class FixedInputs:
    """What the tender fixes. A None is a parameter the reviewed reading does not hold;
    the caller passes the field path it came from in `sources`."""

    capacity_mw: float
    tariff_inr_per_kwh: float | None
    cuf_floor_percent: float | None
    cuf_ceiling_percent: float | None
    ppa_tenure_years: int | None
    scod_months: int | None
    degradation_cap_percent: float | None
    pbg_inr_per_mw: float | None
    pbg_duration_months: int | None
    ists_waiver: bool | None
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Assumptions:
    """The user's, never the tender's. Defaults are marked "assumed" by every caller."""

    capex_inr_crore_per_mw: float = 4.1
    om_inr_lakh_per_mw_year: float = 5.5
    om_escalation_percent: float = 3.0
    debt_share_percent: float = 75.0
    interest_percent: float = 9.25
    tenor_years: int = 18
    tax_rate_percent: float = 25.17
    auxiliary_consumption_percent: float = 1.0
    # The engine needs a CUF and a tariff; where the tender fixes neither the user's
    # assumption fills in, and the output says which it used.
    cuf_percent: float = 24.0
    tariff_inr_per_kwh: float = 3.0
    ppa_tenure_years: int = 25


@dataclass(frozen=True)
class YearRow:
    year: int
    generation_mwh: float
    revenue_crore: float
    om_crore: float
    debt_service_crore: float
    tax_crore: float
    project_cash_crore: float
    equity_cash_crore: float


@dataclass(frozen=True)
class Outputs:
    project_irr_percent: float | None
    equity_irr_percent: float | None
    levelised_cost_inr_per_kwh: float | None
    payback_years: float | None
    capex_crore: float
    used: dict[str, str]
    cashflows: list[YearRow]
    label: str = "indicative"


def irr(flows: list[float], lo: float = -0.99, hi: float = 10.0) -> float | None:
    """The rate at which the flows' present value is zero, by bisection; None when the
    flows do not change sign."""
    if not flows or not (min(flows) < 0 < max(flows)):
        return None

    def npv(rate: float) -> float:
        return sum(f / (1 + rate) ** t for t, f in enumerate(flows))

    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def power_project_finance(fixed: FixedInputs, assumptions: Assumptions) -> Outputs:
    """Project and equity IRR, levelised cost and payback for a power project under the
    tender's fixed parameters and the user's assumptions."""
    used: dict[str, str] = {}
    tariff = fixed.tariff_inr_per_kwh
    if tariff is None:
        tariff = assumptions.tariff_inr_per_kwh
        used["tariff"] = "assumed"
    else:
        used["tariff"] = fixed.sources.get("tariff_inr_per_kwh", "tender")
    cuf = fixed.cuf_floor_percent
    if cuf is None:
        cuf = assumptions.cuf_percent
        used["cuf"] = "assumed"
    else:
        used["cuf"] = fixed.sources.get("cuf_floor_percent", "tender")
    if fixed.cuf_ceiling_percent is not None:
        cuf = min(cuf, fixed.cuf_ceiling_percent)
    years = fixed.ppa_tenure_years or assumptions.ppa_tenure_years
    used["tenure"] = (
        fixed.sources.get("ppa_tenure_years", "tender") if fixed.ppa_tenure_years else "assumed"
    )
    degradation = (fixed.degradation_cap_percent or 0.0) / 100
    used["degradation"] = (
        fixed.sources.get("degradation_cap_percent", "tender")
        if fixed.degradation_cap_percent is not None
        else "none"
    )

    capex_crore = assumptions.capex_inr_crore_per_mw * fixed.capacity_mw
    debt = capex_crore * assumptions.debt_share_percent / 100
    equity = capex_crore - debt
    rate = assumptions.interest_percent / 100
    tenor = max(1, assumptions.tenor_years)
    annuity = debt * rate / (1 - (1 + rate) ** -tenor) if rate > 0 else debt / tenor
    tax = assumptions.tax_rate_percent / 100
    aux = assumptions.auxiliary_consumption_percent / 100
    straight_line = capex_crore / years

    rows: list[YearRow] = []
    project_flows = [-capex_crore]
    equity_flows = [-equity]
    balance = debt
    for year in range(1, years + 1):
        generation_mwh = (
            fixed.capacity_mw * HOURS_PER_YEAR * cuf / 100 * (1 - degradation) ** (year - 1)
        ) * (1 - aux)
        revenue = generation_mwh * 1000 * tariff / CRORE
        om = (
            assumptions.om_inr_lakh_per_mw_year
            * fixed.capacity_mw
            * LAKH
            / CRORE
            * (1 + assumptions.om_escalation_percent / 100) ** (year - 1)
        )
        interest = balance * rate if year <= tenor else 0.0
        principal = (annuity - interest) if year <= tenor else 0.0
        balance = max(0.0, balance - principal)
        debt_service = interest + principal
        taxable = revenue - om - interest - straight_line
        tax_paid = max(0.0, taxable * tax)
        project_cash = revenue - om - max(0.0, (revenue - om - straight_line) * tax)
        equity_cash = revenue - om - debt_service - tax_paid
        rows.append(
            YearRow(
                year=year,
                generation_mwh=round(generation_mwh, 1),
                revenue_crore=round(revenue, 4),
                om_crore=round(om, 4),
                debt_service_crore=round(debt_service, 4),
                tax_crore=round(tax_paid, 4),
                project_cash_crore=round(project_cash, 4),
                equity_cash_crore=round(equity_cash, 4),
            )
        )
        project_flows.append(project_cash)
        equity_flows.append(equity_cash)

    total_generation_kwh = sum(r.generation_mwh for r in rows) * 1000
    total_cost = capex_crore + sum(r.om_crore for r in rows)
    lcoe = (total_cost * CRORE / total_generation_kwh) if total_generation_kwh > 0 else None
    cumulative, payback = -capex_crore, None
    for r in rows:
        cumulative += r.project_cash_crore
        if cumulative >= 0 and payback is None:
            overshoot = cumulative - r.project_cash_crore
            payback = (
                r.year - 1 + (-overshoot / r.project_cash_crore if r.project_cash_crore else 0)
            )
    p_irr, e_irr = irr(project_flows), irr(equity_flows)
    return Outputs(
        project_irr_percent=round(p_irr * 100, 2) if p_irr is not None else None,
        equity_irr_percent=round(e_irr * 100, 2) if e_irr is not None else None,
        levelised_cost_inr_per_kwh=round(lcoe, 3) if lcoe is not None else None,
        payback_years=round(payback, 2) if payback is not None else None,
        capex_crore=round(capex_crore, 2),
        used=used,
        cashflows=rows,
    )
