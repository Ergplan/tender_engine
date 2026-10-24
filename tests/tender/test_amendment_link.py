"""Block 3 a: an amending document is linked to its tender by the reference it prints,
else by its words above a clear margin, else a person is asked."""

from typing import Any

from tender.services.amendment_link import (
    link_amendment,
    link_from_text,
    normalise_reference,
    references_in,
)
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf


def test_references_are_found_and_amendment_suffixes_set_aside() -> None:
    text = (
        "Ref No. SECI/C&P/IPP/13/0002/26-27/Amendment-01 Date: 17.07.2026 "
        "RfS No. SECI/C&P/IPP/13/0002/26-27 dated 15.07.2026 Tel: 011-24666200"
    )
    assert references_in(text) == ["SECI/C&P/IPP/13/0002/26-27"]
    assert references_in("Tender ID On CPPP: 2026_SECI_850226_1 and NIT NRE-CS-5846-004") == [
        "2026_SECI_850226_1",
        "NRE-CS-5846-004",
    ]
    assert normalise_reference(" seci/c&p/ipp/13/0002/26-27 / Corrigendum-2 ") == (
        "SECI/C&P/IPP/13/0002/26-27"
    )


def tenders(pipeline: Pipeline, db: Any) -> dict[str, Any]:
    made = {}
    rows = [
        ("cfd-i", "SECI/C&P/IPP/13/0002/26-27", "SECI", "fdre",
         "RfS for assured Peak Supply under CfD Mechanism (SECI-CfD-I)"),
        ("fdre-ix", "SECI/C&P/IPP/13/0006/26-27", "SECI", "fdre",
         "RfS for assured Peak Supply of 4800 MWh (1200 MW x 4 Hrs.) FDRE-IX"),
        ("hybrid-03", "NTPC/RE-CS/2024-25/HYBRID-03", "NTPC", "hybrid",
         "RfS for Selection of Hybrid Power Generators for 1200 MW Hybrid-03"),
        ("beed", None, "RECPDCL", "transmission",
         "Single Stage RFP for Selection of Bidder as Transmission Service Provider Beed"),
    ]  # fmt: skip
    for slug, ref, agency, kind, title in rows:
        made[slug] = pipeline.tenders.create(
            db,
            tender_type=kind,
            issuing_agency=agency,
            external_ref=ref,
            title=title,
            created_by="pytest",
            slug=slug,
        )
    return made


def test_a_printed_reference_links_the_tender(pipeline: Pipeline, db: Any) -> None:
    made = tenders(pipeline, db)
    link = link_from_text(
        "SOLAR ENERGY CORPORATION OF INDIA LIMITED Ref No. SECI/C&P/IPP/13/0002/26-27/Amendment-02 "
        "Amendment-02 to RfS for Selection of RE Power Developers under CfD (SECI-CfD-I)",
        list(made.values()),
    )
    assert (link.state, link.tender_id, link.method) == ("linked", made["cfd-i"].id, "reference")
    assert link.confidence == 0.98 and link.references_found == ["SECI/C&P/IPP/13/0002/26-27"]


def test_without_a_reference_the_words_decide_only_with_a_clear_margin(
    pipeline: Pipeline, db: Any
) -> None:
    made = tenders(pipeline, db)
    clear = link_from_text(
        "Corrigendum 1 to the Single Stage RFP for Selection of Bidder as Transmission Service "
        "Provider Beed, RECPDCL",
        list(made.values()),
        filename="Corrigendum-1-Beed.pdf",
    )
    assert (clear.state, clear.tender_id, clear.method) == ("linked", made["beed"].id, "title")
    assert clear.confidence >= 0.85
    close = link_from_text(
        "Amendment to RfS for assured Peak Supply from ISTS-Connected RE Projects, SECI",
        list(made.values()),
    )
    assert close.state == "ask" and close.tender_id is None
    assert {c.slug for c in close.candidates[:2]} == {"cfd-i", "fdre-ix"}
    assert "chooses" in close.reason
    nothing = link_from_text("Minutes of the pre-bid meeting", [made["beed"]])
    assert nothing.state in ("ask", "none") and nothing.tender_id is None


def test_a_reference_two_tenders_share_asks(pipeline: Pipeline, db: Any) -> None:
    made = tenders(pipeline, db)
    twin = pipeline.tenders.create(
        db,
        tender_type="fdre",
        issuing_agency="SECI",
        external_ref="SECI/C&P/IPP/13/0002/26-27",
        title="The same reference again",
        created_by="pytest",
        slug="twin",
    )
    link = link_from_text("RfS No. SECI/C&P/IPP/13/0002/26-27", [*made.values(), twin])
    assert link.state == "ask" and {c.slug for c in link.candidates} == {"cfd-i", "twin"}


def test_the_service_reads_a_parsed_document(pipeline: Pipeline, db: Any) -> None:
    made = tenders(pipeline, db)
    document = pipeline.parsed_document(
        db,
        make_pdf([["Amendment-01 to RfS No. NTPC/RE-CS/2024-25/HYBRID-03", "NTPC Limited"]]),
    )
    link = link_amendment(db, "ergplan", document.id)
    assert (link.state, link.tender_id) == ("linked", made["hybrid-03"].id)
