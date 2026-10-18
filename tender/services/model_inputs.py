"""What the tender fixes for the financial model, read from the published view only.

Each parameter is taken from the first of its candidate field paths that the published
view holds a reviewed value for (the common pack, then the type packs); the source names
the document and page the fact was approved from, so the widget's lock icon carries a
page chip. Nothing here reads a candidate: a field the reviewer has not decided is a
parameter the model does not have, and the engine says so (`Outputs.used`)."""

from datetime import date
from typing import Any

from tender.services.finance import FixedInputs
from tender.services.published import PublishedField, PublishedTender

PATHS: dict[str, tuple[str, ...]] = {
    "capacity_mw": ("sector.power.common.total_capacity_mw",),
    "tariff_inr_per_kwh": (
        "sector.power.common.tariff_ceiling_inr_per_kwh",
        "sector.power.ipp.tariff_ceiling_inr_per_kwh",
    ),
    "cuf_floor_percent": (
        "sector.power.ipp.cuf_floor_percent",
        "sector.power.solar.min_cuf_percent",
        "sector.power.wind.min_cuf_percent",
        "sector.power.hybrid.combined_cuf_floor_percent",
    ),
    "cuf_ceiling_percent": (
        "sector.power.ipp.cuf_ceiling_percent",
        "sector.power.solar.max_cuf_percent",
    ),
    "ppa_tenure_years": (
        "sector.power.common.ppa_tenure_years",
        "sector.power.ipp.ppa_tenure_years",
    ),
    "scod_months": ("sector.power.common.scod_months", "sector.power.ipp.scod_months"),
    "degradation_cap_percent": (
        "sector.power.solar.annual_degradation_cap_percent",
        "sector.power.ipp.degradation_cap_percent",
    ),
    "pbg_inr_per_mw": ("core.guarantees.pbg_per_mw_inr",),
    "pbg_duration_months": (
        "core.guarantees.bg_validity_months",
        "sector.power.ipp.pbg_duration_months",
    ),
    "ists_waiver_cutoff_date": ("sector.power.common.ists_waiver_cutoff_date",),
}


def _reviewed(view: PublishedTender) -> dict[str, PublishedField]:
    return {
        field.path: field
        for section in view.sections
        for field in section.fields
        if field.status == "reviewed" and field.value is not None and not field.withdrawn
    }


def _source(field: PublishedField) -> str:
    if field.evidence:
        first = field.evidence[0]
        return f"{first.filename or first.document_id} p.{first.page_no}"
    return field.path


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fixed_inputs(view: PublishedTender, *, today: date | None = None) -> FixedInputs:
    """The tender's fixed parameters from its published facts; a parameter the review
    does not hold is None and absent from `sources`."""
    fields = _reviewed(view)
    found: dict[str, PublishedField] = {}
    for parameter, paths in PATHS.items():
        for path in paths:
            if path in fields:
                found[parameter] = fields[path]
                break
    sources = {name: _source(field) for name, field in found.items()}

    def number(name: str) -> float | None:
        return _number(found[name].value) if name in found else None

    def whole(name: str) -> int | None:
        value = number(name)
        return int(value) if value is not None else None

    waiver: bool | None = None
    if "ists_waiver_cutoff_date" in found:
        raw = str(found["ists_waiver_cutoff_date"].value)
        try:
            waiver = date.fromisoformat(raw[:10]) >= (today or date.today())
            sources["ists_waiver"] = sources.pop("ists_waiver_cutoff_date")
        except ValueError:
            sources.pop("ists_waiver_cutoff_date", None)
    return FixedInputs(
        capacity_mw=number("capacity_mw") or 0.0,
        tariff_inr_per_kwh=number("tariff_inr_per_kwh"),
        cuf_floor_percent=number("cuf_floor_percent"),
        cuf_ceiling_percent=number("cuf_ceiling_percent"),
        ppa_tenure_years=whole("ppa_tenure_years"),
        scod_months=whole("scod_months"),
        degradation_cap_percent=number("degradation_cap_percent"),
        pbg_inr_per_mw=number("pbg_inr_per_mw"),
        pbg_duration_months=whole("pbg_duration_months"),
        ists_waiver=waiver,
        sources=sources,
    )
