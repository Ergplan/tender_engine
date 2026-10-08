"""Optimiser constraints: what an optimisation engine must satisfy, typed, each from one
decided field.

Three kinds. `quantity`: a subject with a comparator, a value and a unit, over a period.
`temporal`: a date, or an offset from an event. `obligation`: something that holds or not.
Every row names the field it comes from and the clause behind it; a row read off a general
clause (the non-RE share implied by a minimum green share) is marked `inherited`. Nothing
decided, nothing derived.
"""

from typing import Any

from tender.domain_packs.power.derivations import (
    Decided,
    Derivation,
    Inputs,
    Row,
    Rule,
    clause_of,
    record_of,
    records_of,
)

VERSION = "v1"
FIELD = "sector.power.common.optimizer_constraints"
RTC = "sector.power.re_rtc."
GREEN_MIN = RTC + "traceable_green_min_pct"
REC = RTC + "rec_obligation"
CUF_ANNUAL = RTC + "cuf_annual_min_pct"
CUF_MONTHLY = RTC + "cuf_monthly_min_pct"
CUF_PEAK = RTC + "cuf_peak_min_pct"
PEAK_WINDOW = RTC + "peak_window"
SUPPLY_START = RTC + "supply_start_date"
GREENSHOE_MW = RTC + "greenshoe_capacity_mw"
GREENSHOE_OFFER = RTC + "greenshoe_exercise_deadline"
GREENSHOE_SSD = RTC + "greenshoe_ssd"
GREENSHOE_PPA_DAYS = RTC + "greenshoe_ppa_signing_days"
LINKED = RTC + "linked_capacity_obligation"
TARIFF_SPLIT = RTC + "non_re_tariff_split"
CHARGING = "sector.power.common.bess_charging_rule"
MIX = "sector.power.common.source_mix_rules"
CAPACITY = "sector.power.common.total_capacity_mw"
TENURE = "sector.power.common.ppa_tenure_years"
STORAGE_MANDATORY = "sector.power.fdre.storage_mandatory"
INPUTS = (
    GREEN_MIN,
    REC,
    CUF_ANNUAL,
    CUF_MONTHLY,
    CUF_PEAK,
    PEAK_WINDOW,
    SUPPLY_START,
    GREENSHOE_MW,
    GREENSHOE_OFFER,
    GREENSHOE_SSD,
    GREENSHOE_PPA_DAYS,
    LINKED,
    TARIFF_SPLIT,
    CHARGING,
    MIX,
    CAPACITY,
    TENURE,
    STORAGE_MANDATORY,
)


class _Rows:
    def __init__(self) -> None:
        self.rows: list[Row] = []

    def add(
        self,
        kind: str,
        subject: str,
        decided: Decided,
        *,
        inherited: bool = False,
        keyword: str | None = None,
        inputs: tuple[str, ...] | None = None,
        **keys: Any,
    ) -> None:
        inputs = inputs or (decided.path,)
        value: dict[str, Any] = {
            "id": f"c{len(self.rows) + 1}",
            "kind": kind,
            "subject": subject,
            "basis": "inherited" if inherited else "stated",
            "derived_from": ", ".join(inputs),
            "clause": clause_of(decided, keyword),
        }
        value.update({k: v for k, v in keys.items() if v is not None and v != ""})
        self.rows.append(Row(value=value, inputs=inputs, inherited=inherited))


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def derive(inputs: Inputs) -> Derivation:
    out = _Rows()

    green = inputs.get(GREEN_MIN)
    share = _number(green.value) if green else None
    if green and share is not None:
        out.add(
            "quantity", "traceable_green_share", green, comparator=">=", value=share,
            unit="percent_of_annual_energy", period="annual",
        )  # fmt: skip
        out.add(
            "quantity", "non_re_share", green, inherited=True, comparator="<=",
            value=round(100 - share, 4), unit="percent_of_annual_energy", period="annual",
            condition="the balance of the minimum green share; not printed as a limit",
        )  # fmt: skip

    for path, subject, unit, period in (
        (CUF_ANNUAL, "cuf_annual", "percent_of_annual_energy", "annual"),
        (CUF_MONTHLY, "cuf_monthly", "percent_of_monthly_energy", "monthly"),
        (CUF_PEAK, "cuf_peak", "percent_of_peak_energy", "peak_hours"),
    ):
        decided = inputs.get(path)
        number = _number(decided.value) if decided else None
        if decided and number is not None:
            out.add(
                "quantity", subject, decided, keyword="cuf", comparator=">=", value=number,
                unit=unit, period=period,
            )  # fmt: skip

    window = inputs.get(PEAK_WINDOW)
    record = record_of(window)
    if window and record:
        hours = _number(record.get("hours_per_day"))
        if hours is not None:
            out.add(
                "quantity", "peak_window_hours", window, keyword="peak", comparator="==",
                value=hours, unit="hours_per_day", period="daily",
            )  # fmt: skip
        if record.get("set_by") == "procurer":
            stretches = {
                "single": "one stretch",
                "multiple": "several stretches",
                "procurer_discretion": "one stretch or several, at the procurer's discretion",
            }.get(record.get("stretches") or "")
            out.add(
                "obligation", "peak_window_set_by_procurer", window, keyword="peak", holds=True,
                condition=stretches,
            )  # fmt: skip

    rec = inputs.get(REC)
    record = record_of(rec)
    if rec and record.get("applies_to") in ("all_non_re_energy", "shortfall_below_minimum"):
        out.add(
            "obligation", "rec_for_non_re_supply", rec, keyword="certificate", holds=True,
            condition="for every unit supplied from non-RE sources"
            if record["applies_to"] == "all_non_re_energy"
            else "for the shortfall below the minimum green share",
        )  # fmt: skip

    charging = inputs.get(CHARGING)
    record = record_of(charging)
    if charging and record:
        reference = record.get("regulation_reference")
        if record.get("re_only") is True:
            out.add("obligation", "bess_re_charged_only", charging, keyword="charg", holds=True)
        if record.get("co_located_required") is True:
            out.add(
                "obligation", "bess_co_located", charging, keyword="co-locat", holds=True,
                condition=f"per {reference}" if reference else None,
            )  # fmt: skip

    linked = inputs.get(LINKED)
    record = record_of(linked)
    if linked and record:
        technology = record.get("technology")
        multiple = _number(record.get("multiple_of_contracted"))
        capacity = _number(record.get("capacity_mw"))
        acres = _number(record.get("acres_per_mw"))
        if technology:
            out.add(
                "obligation", "linked_capacity_installation", linked, keyword="install", holds=True,
                source=technology, condition=record.get("location"),
            )  # fmt: skip
        if multiple is not None:
            out.add(
                "quantity", "linked_capacity_multiple", linked, keyword="twice", comparator=">=",
                value=multiple, unit="multiple_of_contracted_mw", source=technology,
            )  # fmt: skip
        if capacity is not None:
            out.add(
                "quantity", "linked_capacity", linked, keyword="install", comparator=">=",
                value=capacity, unit="mw", source=technology,
            )  # fmt: skip
        if acres is not None:
            out.add(
                "quantity", "linked_land_per_mw", linked, keyword="acre", comparator=">=",
                value=acres, unit="acres_per_mw",
            )  # fmt: skip
        for stage in record.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            months = _number(stage.get("months_from_loa"))
            if months is None:
                continue
            out.add(
                "temporal", "linked_capacity_documents", linked, keyword="within",
                relative_to="loa", offset_months=months,
                share_pct=_number(stage.get("share_pct")), condition=stage.get("documents"),
            )  # fmt: skip

    for path, subject in (
        (SUPPLY_START, "supply_start"),
        (GREENSHOE_SSD, "supply_start_greenshoe"),
        (GREENSHOE_OFFER, "greenshoe_offer_deadline"),
    ):
        decided = inputs.get(path)
        if decided and isinstance(decided.value, str) and decided.value:
            out.add("temporal", subject, decided, on_date=decided.value)

    greenshoe = inputs.get(GREENSHOE_MW)
    number = _number(greenshoe.value) if greenshoe else None
    if greenshoe and number is not None:
        out.add(
            "quantity", "greenshoe_capacity", greenshoe, keyword="greenshoe", comparator="==",
            value=number, unit="mw",
        )  # fmt: skip
    ppa_days = inputs.get(GREENSHOE_PPA_DAYS)
    number = _number(ppa_days.value) if ppa_days else None
    if ppa_days and number is not None:
        out.add(
            "temporal", "greenshoe_ppa_signing", ppa_days, keyword="ppa",
            relative_to="greenshoe_offer", offset_days=number,
        )  # fmt: skip

    split = inputs.get(TARIFF_SPLIT)
    record = record_of(split)
    if split and record:
        for key, subject in (
            ("fixed_pct", "non_re_tariff_fixed_share"),
            ("variable_pct", "non_re_tariff_variable_share"),
        ):
            number = _number(record.get(key))
            if number is not None:
                out.add(
                    "quantity", subject, split, keyword="charge", comparator="==", value=number,
                    unit="percent_of_tariff",
                )  # fmt: skip
        if record.get("merit_order_treatment") in (
            "merit_order_on_variable_charge",
            "merit_order_on_full_tariff",
        ):
            out.add(
                "obligation", "non_re_merit_order_despatch", split, keyword="merit", holds=True,
                condition="on the variable charge"
                if record["merit_order_treatment"] == "merit_order_on_variable_charge"
                else "on the full tariff",
            )  # fmt: skip

    contracted = inputs.get(CAPACITY)
    number = _number(contracted.value) if contracted else None
    if contracted and number is not None:
        out.add(
            "quantity", "contracted_capacity", contracted, comparator="==", value=number, unit="mw"
        )
    tenure = inputs.get(TENURE)
    number = _number(tenure.value) if tenure else None
    if tenure and number is not None:
        out.add(
            "quantity", "contract_term", tenure, comparator="==", value=number, unit="years",
            period="contract_term",
        )  # fmt: skip

    mandatory = inputs.get(STORAGE_MANDATORY)
    if mandatory and mandatory.value is True:
        out.add(
            "obligation",
            "storage_mandatory",
            mandatory,
            keyword="storage",
            holds=True,
            source="bess",
        )
    mix = inputs.get(MIX)
    for item in records_of(mix):
        if mix and item.get("treatment") == "prohibited" and item.get("source"):
            out.add(
                "obligation", "source_prohibited", mix, keyword=str(item["source"]).split("_")[0],
                holds=True, source=item["source"], condition=item.get("condition"),
            )  # fmt: skip

    fields_used = {p for row in out.rows for p in row.inputs}
    note = (
        f"{len(out.rows)} constraint(s) from {len(fields_used)} decided field(s)"
        if out.rows
        else "no decided field yields a constraint"
    )
    return Derivation(rows=out.rows, note=note)


RULE = Rule(
    field_path=FIELD,
    module=__name__,
    version=VERSION,
    inputs=INPUTS,
    derive=derive,
    row_key="id",
)
