"""Source eligibility: for each possible source of supply, what the tender decides about it.

Rows come from the decided `source_mix_rules` (a clause naming the source: basis
`stated`), from the one general clause on non-RE supply (`any_non_re`: `thermal` and
`market_purchase` take its treatment with basis `inherited`, and say so), from the storage
fields of the FDRE and hybrid types, from the storage charging rule, and from a linked
build obligation (the technology it requires is `required`). Where nothing decided speaks
of a source the row is `not_addressed` with no clause, never a guess from the tender type.
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
FIELD = "sector.power.common.source_eligibility"
MIX = "sector.power.common.source_mix_rules"
CHARGING = "sector.power.common.bess_charging_rule"
STORAGE_MANDATORY = "sector.power.fdre.storage_mandatory"
STORAGE_PERMITTED = "sector.power.hybrid.storage_permitted"
GREEN_MIN = "sector.power.re_rtc.traceable_green_min_pct"
LINKED = "sector.power.re_rtc.linked_capacity_obligation"
INPUTS = (MIX, CHARGING, STORAGE_MANDATORY, STORAGE_PERMITTED, GREEN_MIN, LINKED)

SOURCES = (
    "solar",
    "wind",
    "hydro",
    "biomass",
    "bess",
    "pumped_storage",
    "thermal",
    "market_purchase",
    "other",
)
# The sources a general non-RE clause covers without naming them.
NON_RE = ("thermal", "market_purchase")
KEYWORDS = {
    "solar": "solar",
    "wind": "wind",
    "hydro": "hydro",
    "biomass": "biomass",
    "bess": "storage",
    "pumped_storage": "pumped",
    "thermal": "thermal",
    "market_purchase": "market",
    "other": "source",
}
# When two clauses speak of one source the stricter stands.
STRICTNESS = {"prohibited": 3, "required": 2, "allowed_with_limit": 1, "allowed": 0}


def _row(
    source: str,
    status: str,
    basis: str,
    inputs: tuple[str, ...],
    *,
    limit_value: float | None = None,
    limit_unit: str | None = None,
    condition: str | None = None,
    clause: str = "",
) -> Row:
    value: dict[str, Any] = {
        "source": source,
        "status": status,
        "basis": basis,
        "derived_from": ", ".join(inputs),
    }
    if limit_value is not None:
        value["limit_value"] = limit_value
    if limit_unit:
        value["limit_unit"] = limit_unit
    if condition:
        value["condition"] = condition
    if clause:
        value["clause"] = clause
    return Row(value=value, inputs=inputs, inherited=basis == "inherited")


def _stricter(candidate: Row, standing: Row | None) -> Row:
    if standing is None:
        return candidate
    if STRICTNESS[candidate.value["status"]] > STRICTNESS[standing.value["status"]]:
        merged = candidate
        other = standing
    else:
        merged = standing
        other = candidate
    value = dict(merged.value)
    conditions = [v for v in (merged.value.get("condition"), other.value.get("condition")) if v]
    if conditions:
        value["condition"] = "; ".join(dict.fromkeys(conditions))
    value["derived_from"] = ", ".join(dict.fromkeys([*merged.inputs, *other.inputs]))
    if not value.get("clause") and other.value.get("clause"):
        value["clause"] = other.value["clause"]
    return Row(
        value=value,
        inputs=tuple(dict.fromkeys([*merged.inputs, *other.inputs])),
        inherited=merged.inherited and other.inherited,
    )


def derive(inputs: Inputs) -> Derivation:
    rows: dict[str, Row] = {}
    notes: list[str] = []

    def take(row: Row) -> None:
        rows[row.value["source"]] = _stricter(row, rows.get(row.value["source"]))

    mix: Decided | None = inputs.get(MIX)
    general: dict[str, Any] | None = None
    for item in records_of(mix):
        source, treatment = item.get("source"), item.get("treatment")
        if not source or not treatment or mix is None:
            continue
        if source == "any_non_re":
            general = item
            continue
        if source not in SOURCES:
            continue
        take(
            _row(
                source,
                treatment,
                "stated",
                (MIX,),
                limit_value=item.get("limit_value"),
                limit_unit=item.get("limit_unit"),
                condition=item.get("condition"),
                clause=clause_of(mix, KEYWORDS[source]),
            )
        )

    green = inputs.get(GREEN_MIN)
    if general is not None and mix is not None:
        # The general clause covers the non-RE sources it does not name; the row says so.
        limit_value, limit_unit = general.get("limit_value"), general.get("limit_unit")
        treatment = general["treatment"]
        clause_inputs: tuple[str, ...] = (MIX,)
        if limit_value is None and treatment in ("allowed", "allowed_with_limit") and green:
            share = green.value
            if isinstance(share, int | float):
                limit_value, limit_unit = round(100 - float(share), 4), "percent_of_annual_energy"
                treatment = "allowed_with_limit"
                clause_inputs = (MIX, GREEN_MIN)
        for source in NON_RE:
            if source in rows:
                continue
            condition = "not named; covered by the general clause on non-RE supply"
            if general.get("condition"):
                condition += f"; {general['condition']}"
            take(
                _row(
                    source,
                    treatment,
                    "inherited",
                    clause_inputs,
                    limit_value=limit_value,
                    limit_unit=limit_unit,
                    condition=condition,
                    clause=clause_of(mix, "source"),
                )
            )
        notes.append("thermal and market purchase read off the general non-RE clause")

    mandatory = inputs.get(STORAGE_MANDATORY)
    if mandatory is not None and mandatory.value is True:
        take(_row("bess", "required", "stated", (STORAGE_MANDATORY,), clause=clause_of(mandatory)))
    permitted = inputs.get(STORAGE_PERMITTED)
    if permitted is not None and isinstance(permitted.value, bool):
        take(
            _row(
                "bess",
                "allowed" if permitted.value else "prohibited",
                "stated",
                (STORAGE_PERMITTED,),
                clause=clause_of(permitted),
            )
        )
    charging = inputs.get(CHARGING)
    rule = record_of(charging)
    if charging is not None and rule:
        conditions = []
        if rule.get("re_only"):
            conditions.append("charged from RE only")
        if rule.get("co_located_required"):
            conditions.append("co-located")
        if rule.get("regulation_reference"):
            conditions.append(f"per {rule['regulation_reference']}")
        if conditions:
            standing = rows.get("bess")
            status = standing.value["status"] if standing else "allowed"
            take(
                _row(
                    "bess",
                    status,
                    "stated",
                    (CHARGING,),
                    condition="; ".join(conditions),
                    clause=clause_of(charging),
                )
            )

    linked = inputs.get(LINKED)
    obligation = record_of(linked)
    technology = obligation.get("technology") if linked is not None else None
    if linked is not None and technology in ("solar", "wind"):
        multiple = obligation.get("multiple_of_contracted")
        condition = (
            f"must be installed at {multiple}x the contracted capacity"
            if multiple is not None
            else "must be installed under the linked build obligation"
        )
        take(
            _row(
                technology,
                "required",
                "stated",
                (LINKED,),
                condition=condition,
                clause=clause_of(linked),
            )
        )

    ordered = []
    for source in SOURCES:
        ordered.append(rows.get(source) or _row(source, "not_addressed", "none", ()))
    addressed = sum(1 for row in ordered if row.value["status"] != "not_addressed")
    if addressed == 0:
        notes.insert(
            0, "no decided clause addresses a source of supply; every source is not_addressed"
        )
    else:
        notes.insert(0, f"{addressed} of {len(SOURCES)} sources addressed by decided clauses")
    return Derivation(rows=ordered, note="; ".join(notes))


RULE = Rule(
    field_path=FIELD,
    module=__name__,
    version=VERSION,
    inputs=INPUTS,
    derive=derive,
    row_key="source",
)
