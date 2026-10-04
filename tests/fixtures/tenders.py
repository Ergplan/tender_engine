"""A synthetic tender: an RfS and an amendment, with the answers a scripted model gives."""

from typing import Any

from sqlalchemy.orm import Session

from core.models import Document
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf

RFS_PAGES = [
    [
        "REQUEST FOR SELECTION (RfS)",
        "RfS No. ACME/RE/2026/007",
        "Issued by Acme Renewables Agency, New Delhi.",
        "Selection of solar power developers for 600 MW solar PV projects.",
    ],
    [
        "SECTION 2: BID INFORMATION SHEET",
        "The pre-bid meeting shall be held on 12.03.2026 at the registered office.",
        "The last date of bid submission is 30.03.2026 at 15:00 hrs.",
    ],
    [
        "SECTION 3: EARNEST MONEY DEPOSIT AND PERFORMANCE BANK GUARANTEE",
        "Earnest Money Deposit (EMD) of INR 928000 per MW shall be furnished.",
        "Performance Bank Guarantee (PBG) of INR 2320000 per MW shall be furnished.",
    ],
]
AMENDMENT_PAGES = [
    [
        "AMENDMENT-01",
        "The last date of bid submission is extended to 15.04.2026 at 15:00 hrs.",
        "All other terms and conditions remain unchanged.",
    ]
]


def _answer(value: Any, quote: str, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "rationale": "Stated on the page.",
        "evidence": [{"page_no": 1, "quote": quote}],
    }


RFS_ANSWERS: dict[str, dict[str, Any]] = {
    "plain_english_summary": _answer(
        "Acme Renewables Agency invites solar developers. The tender is for 600 MW. "
        "Projects may be anywhere. Bids are due on 30 March 2026.",
        "Selection of solar power developers for 600 MW solar PV projects.",
    ),
    "tender_number": _answer("ACME/RE/2026/007", "RfS No. ACME/RE/2026/007"),
    "issuing_agency": _answer(
        "Acme Renewables Agency", "Issued by Acme Renewables Agency, New Delhi."
    ),
    "title": _answer(
        "Selection of solar power developers for 600 MW solar PV projects",
        "Selection of solar power developers for 600 MW solar PV projects.",
    ),
    "total_capacity_mw": _answer(
        600, "Selection of solar power developers for 600 MW solar PV projects."
    ),
    "pre_bid_meeting_date": _answer(
        "12.03.2026", "The pre-bid meeting shall be held on 12.03.2026"
    ),
    "bid_submission_deadline": _answer(
        "30.03.2026", "The last date of bid submission is 30.03.2026"
    ),
    "emd_per_mw_inr": _answer(
        928000, "Earnest Money Deposit (EMD) of INR 928000 per MW shall be furnished."
    ),
    "pbg_per_mw_inr": _answer(
        2320000, "Performance Bank Guarantee (PBG) of INR 2320000 per MW shall be furnished."
    ),
}
AMENDMENT_ANSWERS: dict[str, dict[str, Any]] = {
    "bid_submission_deadline": _answer(
        "15.04.2026", "The last date of bid submission is extended to 15.04.2026"
    ),
}
DEADLINE = "core.key_dates.bid_submission_deadline"
EMD = "core.guarantees.emd_per_mw_inr"
PBG = "core.guarantees.pbg_per_mw_inr"


def parsed(pipeline: Pipeline, db: Session, pages: list[list[str]], name: str) -> Document:
    document = pipeline.upload(db, make_pdf(pages), name)
    pipeline.runner.run_until_idle()
    db.refresh(document)
    return document


def make_tender(pipeline: Pipeline, db: Session, tender_type: str = "solar") -> Tender:
    return pipeline.tenders.create(
        db,
        tender_type=tender_type,
        issuing_agency="Acme Renewables Agency",
        external_ref="ACME/RE/2026/007",
        title="Selection of solar power developers for 600 MW solar PV projects",
        created_by="pytest",
    )


def extracted_tender(pipeline: Pipeline, db: Session, tender_type: str = "solar") -> Tender:
    """A tender whose original version (one RfS) is parsed, extracted and validated."""
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    tender = make_tender(pipeline, db, tender_type)
    document = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    pipeline.tenders.add_version(db, tender, document, "original", None, created_by="pytest")
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
    return tender


def amended_tender(pipeline: Pipeline, db: Session, tender: Tender) -> None:
    """Version 2: an amendment that moves the bid deadline, extracted and validated."""
    from datetime import date

    pipeline.sdk.answers = dict(AMENDMENT_ANSWERS)
    document = parsed(pipeline, db, AMENDMENT_PAGES, "amendment-01.pdf")
    pipeline.tenders.add_version(
        db, tender, document, "amendment", date(2026, 3, 20), created_by="pytest"
    )
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
