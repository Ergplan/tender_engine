"""The results importer on a fixture dataset: hash equality enforced, a rejected host
imports nothing, evidence located and not located, a repeat imports nothing twice, no
canonical fact after the import, the tender links by RfS number and by page text, and the
HTML registers left out."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import (
    Candidate,
    CanonicalFact,
    Document,
    EvidenceSpan,
    ExtractionRun,
    Page,
    ValidationResult,
)
from core.services.parse import ParseService
from core.services.validate import ValidationService
from tender.models import Award
from tender.services.results_import import (
    Dataset,
    ResultsImporter,
    ResultsImportError,
    _commit_of,
    _printed_number,
)
from tender.services.source_domains import SourceAllowlist
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import make_tender

RESULT_PAGES = [
    [
        "Solar Energy Corporation of India Limited",
        "RfS No. ACME/RE/2026/007 dated 01.10.2025",
        "Successful bidders after e-Reverse Auction held on 23.12.2025",
        "1  Alpha Power Private Limited   380 MW   2.41 INR/kWh",
        "2  Beta Energy Limited           200 MW   2.45 INR/kWh",
    ]
]
ORDER_PAGES = [
    [
        "CENTRAL ELECTRICITY REGULATORY COMMISSION, NEW DELHI",
        "Petition No. 721/AT/2020",
        "Order dated 15.03.2026 on the adoption of tariff for the",
        "Tender No. ACME/RE/2026/007 of Acme Renewables Agency",
    ],
    ["The tariff of Gamma Renewables Limited for 300 MW at Rs. 2.50 per kWh is adopted."],
]


def record(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agency": "SECI",
        "bidder": "Alpha Power Private Limited",
        "project": "600 MW solar",
        "reference": "SECI000777",
        "technology": "Solar",
        "capacity": 380.0,
        "capacityUnit": "MW",
        "price": 2.41,
        "priceUnit": "INR/kWh",
        "adopted": None,
        "adoptedPrice": None,
        "allocation": "Published result",
        "status": "Awarded",
        "date": "23.12.2025",
        "dateType": "Auction / LoA date",
        "notes": "",
        "page": 1,
        "source": "src-result",
        "related": "https://seci.co.in/tender-details/X",
        "verification": "Official SECI result publication",
        "dataset": "SECI",
        "flag": False,
        "id": "r1",
        "nlc": False,
    }
    base.update(over)
    return base


def write_dataset(
    root: Path,
    *,
    result_pdf: bytes,
    order_pdf: bytes,
    order_host: str = "cercind.gov.in",
    tamper: bool = False,
) -> Path:
    public = root / "tender-results-viewer" / "public"
    (public / "sources").mkdir(parents=True)
    (root / "seci-data").mkdir()
    (public / "sources" / "src-result.pdf").write_bytes(result_pdf)
    (public / "sources" / "src-order.pdf").write_bytes(order_pdf)
    (public / "sources" / "src-register.html").write_text("<table></table>", encoding="utf-8")
    sources = [
        {
            "id": "src-result",
            "url": "https://www.seci.co.in/Upload/Bidder/1.pdf",
            "file": "sources/src-result.pdf",
            "name": "SECI000777_result_1.pdf",
            "sha256": hashlib.sha256(result_pdf).hexdigest(),
            "kind": "PDF",
            "checked": "2026-10-07",
        },
        {
            "id": "src-order",
            "url": f"https://{order_host}/2026/orders/721-AT-2020.pdf",
            "file": "sources/src-order.pdf",
            "name": "CERC_721_AT_2020.pdf",
            # A tampered hash on the second source: the first must not be imported either.
            "sha256": hashlib.sha256(order_pdf).hexdigest() if not tamper else "0" * 64,
            "kind": "PDF",
            "checked": "2026-10-07",
        },
        {
            "id": "src-register",
            "url": "https://sjvn.nic.in/en/tender-awarded?page=2",
            "file": "sources/src-register.html",
            "name": "sjvn_awards_2.html",
            "sha256": hashlib.sha256(b"<table></table>").hexdigest(),
            "kind": "Web page",
            "checked": "2026-10-07",
            "text": "sources/src-register.txt",
        },
    ]
    records = [
        record(),
        # A bidder the page does not name: its row cannot be located.
        record(id="r2", bidder="Delta Unknown Limited", capacity=200.0, price=2.45),
        record(
            id="r3",
            agency="NTPC",
            bidder="Gamma Renewables Limited",
            reference="721/AT/2020",
            capacity=300.0,
            price=2.50,
            adopted=300.0,
            adoptedPrice=2.50,
            allocation="Base",
            status="Tariff adopted",
            date="15-03-2026",
            dateType="CERC order date",
            notes="Adopted in full.",
            page="1–2",
            source="src-order",
            verification="Official CERC order; historical award and adoption recorded separately",
            dataset="NTPC",
        ),
        record(
            id="r4",
            agency="SJVN",
            bidder="Epsilon Wind Limited",
            reference="Wind-2 (1200 MW tender)",
            price=None,
            priceUnit="",
            status="Company register disclosure",
            date="",
            dateType="Publication / order date",
            page="HTML award register",
            source="src-register",
            verification="Official company register checked; missing fields left blank",
            dataset="SJVN",
        ),
    ]
    (public / "data.json").write_text(
        json.dumps(
            {"asOf": "7 October 2026", "records": records, "sources": sources, "coverage": []}
        ),
        encoding="utf-8",
    )
    (root / "seci-data" / "records.json").write_text(
        json.dumps([{"tender_id": "SECI000777", "tender_reference": "ACME/RE/2026/007"}]),
        encoding="utf-8",
    )
    return root


def importer(pipeline: Pipeline) -> ResultsImporter:
    return ResultsImporter(
        ingest=pipeline.ingest,
        parse=ParseService(pipeline.storage, pipeline.settings),
        extract=pipeline.extract,
        validate=ValidationService(pipeline.schemas, pipeline.settings.tenant_id),
        catalog=pipeline.catalog,
        allowlist=SourceAllowlist(("seci.co.in", "cercind.gov.in", "sjvn.nic.in")),
        tenant_id=pipeline.settings.tenant_id,
    )


@pytest.fixture()
def dataset(tmp_path: Path) -> Dataset:
    root = write_dataset(
        tmp_path / "ds", result_pdf=make_pdf(RESULT_PAGES), order_pdf=make_pdf(ORDER_PAGES)
    )
    return Dataset(root, commit="fixture")


def candidates(db: Session, award: Award) -> dict[str, Candidate]:
    run = db.scalars(
        select(ExtractionRun).where(
            ExtractionRun.object_type == "award", ExtractionRun.object_id == award.id
        )
    ).one()
    assert run.mode == "import" and run.status == "validated"
    assert run.model == "RE-tender-results@fixture" and run.schema_name == "result.award"
    return {
        c.field_path.rsplit(".", 1)[1]: c
        for c in db.scalars(select(Candidate).where(Candidate.extraction_run_id == run.id))
    }


def spans(db: Session, candidate: Candidate) -> list[EvidenceSpan]:
    return list(db.scalars(select(EvidenceSpan).where(EvidenceSpan.candidate_id == candidate.id)))


def test_import_writes_candidates_with_located_evidence_and_no_fact(
    pipeline: Pipeline, db: Session, dataset: Dataset
) -> None:
    tender = make_tender(pipeline, db)  # external_ref ACME/RE/2026/007
    report = importer(pipeline).run(db, dataset)
    assert report.hosts == {"cercind.gov.in": True, "sjvn.nic.in": True, "www.seci.co.in": True}
    assert report.count("imported") == 2 and report.count("left_out_html") == 1
    html = next(o for o in report.outcomes if o.action == "left_out_html")
    assert html.rows == 1
    awards = {a.source_id: a for a in db.scalars(select(Award))}
    assert set(awards) == {"src-result", "src-order"}

    result = awards["src-result"]
    assert result.procurer == "SECI" and result.reference == "ACME/RE/2026/007"
    assert result.result_kind == "auction_result" and result.row_count == 2
    assert result.status == "imported" and result.dataset == "RE-tender-results@fixture"
    document = db.get(Document, result.document_id)
    assert document is not None and document.status == "parsed"
    assert document.source_url == "https://www.seci.co.in/Upload/Bidder/1.pdf"
    assert str(document.retrieved_on) == "2026-10-07" and document.sha256 == result.source_sha256
    assert (
        db.scalar(select(func.count()).select_from(Page).where(Page.document_id == document.id))
        == 1
    )
    # Linked by the exact RfS number of the SECI research record; the order by its page text.
    assert (result.tender_id, result.tender_link_basis, result.tender_link_page) == (
        tender.id,
        "rfs_number",
        None,
    )
    order = awards["src-order"]
    assert (order.tender_id, order.tender_link_basis, order.tender_link_page) == (
        tender.id,
        "page_text",
        1,
    )
    assert order.result_kind == "cerc_adoption_order" and order.reference == "721/AT/2020"

    by_field = candidates(db, result)
    assert set(by_field) == {"procurer", "reference", "result_kind", "result_date", "winners"}
    for candidate in by_field.values():
        assert candidate.prompt_name == "import/re-tender-results"
        assert candidate.prompt_version == "v1" and candidate.llm_call_log_id is None
        assert candidate.confidence <= 0.8
    assert by_field["procurer"].value == "SECI" and by_field["procurer"].status == "validated"
    assert spans(db, by_field["procurer"])[0].quote == "Solar Energy Corporation of India"
    assert by_field["reference"].value == "ACME/RE/2026/007"
    assert by_field["result_kind"].value == "auction_result"
    assert spans(db, by_field["result_kind"])[0].quote.lower() == "e-reverse auction"
    assert by_field["result_date"].value == "23.12.2025"
    assert spans(db, by_field["result_date"])[0].char_start is not None
    winners = by_field["winners"]
    rows = winners.value
    assert [r["bidder"] for r in rows] == ["Alpha Power Private Limited", "Delta Unknown Limited"]
    assert rows[0] == {
        "bidder": "Alpha Power Private Limited",
        "allocation": "published_result",
        "capacity": 380.0,
        "capacity_unit": "mw",
        "price": 2.41,
        "price_unit": "inr_per_kwh",
        "adopted_capacity": None,
        "adopted_price": None,
        "status": "awarded",
        "notes": None,
    }
    # Row 1: bidder and price located. Row 2: its price "2.45" is printed, its bidder is not;
    # a number alone proves nothing, so the row counts as not located.
    by_row: dict[int, list[bool]] = {}
    for span in spans(db, winners):
        by_row.setdefault(span.ordinal or 0, []).append(span.char_start is not None)
    assert by_row == {1: [True, True], 2: [False, True]}
    assert next(o for o in report.outcomes if o.source_id == "src-result").rows_located == 1
    # The row that was not located sends the table to review and is named.
    assert winners.status == "needs_review"
    messages = {
        (name, passed): message
        for name, passed, message in db.execute(
            select(
                ValidationResult.rule_name, ValidationResult.passed, ValidationResult.message
            ).where(ValidationResult.candidate_id == winners.id)
        )
    }
    assert "Delta Unknown Limited" in messages[("award_rows_located", False)]
    assert ("evidence_not_located", False) in messages
    assert ("award_price_in_band", True) in messages

    order_fields = candidates(db, order)
    order_rows = order_fields["winners"]
    assert order_rows.status == "validated" and order_rows.value[0]["adopted_capacity"] == 300.0
    assert {s.page_no for s in spans(db, order_rows)} == {2}
    assert order_fields["result_date"].value == "15.03.2026"
    assert order_fields["reference"].status == "validated"
    assert db.scalar(select(func.count()).select_from(CanonicalFact)) == 0


def test_a_repeat_run_imports_nothing_twice(
    pipeline: Pipeline, db: Session, dataset: Dataset
) -> None:
    first = importer(pipeline).run(db, dataset)
    again = importer(pipeline).run(db, dataset)
    assert first.count("imported") == 2
    assert again.count("imported") == 0 and again.count("already_imported") == 2
    assert db.scalar(select(func.count()).select_from(Award)) == 2
    assert db.scalar(select(func.count()).select_from(ExtractionRun)) == 2
    assert db.scalar(select(func.count()).select_from(Document)) == 2


def test_a_hash_mismatch_stops_the_import_before_anything_is_written(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = write_dataset(
        tmp_path / "ds",
        result_pdf=make_pdf(RESULT_PAGES),
        order_pdf=make_pdf(ORDER_PAGES),
        tamper=True,
    )
    with pytest.raises(ResultsImportError, match="CERC_721_AT_2020.pdf.*nothing was imported"):
        importer(pipeline).run(db, Dataset(root, commit="fixture"))
    db.rollback()
    # The first source's hash was right; it is not imported either.
    assert db.scalar(select(func.count()).select_from(Award)) == 0
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert db.scalar(select(func.count()).select_from(ExtractionRun)) == 0


def test_a_host_off_the_allowlist_imports_nothing(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = write_dataset(
        tmp_path / "ds",
        result_pdf=make_pdf(RESULT_PAGES),
        order_pdf=make_pdf(ORDER_PAGES),
        order_host="jmkresearch.com",
    )
    with pytest.raises(ResultsImportError, match="jmkresearch.com"):
        importer(pipeline).run(db, Dataset(root, commit="fixture"))
    db.rollback()
    # Not even the admissible sources: the owner decides first.
    assert db.scalar(select(func.count()).select_from(Award)) == 0
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_only_the_named_sources_are_imported(
    pipeline: Pipeline, db: Session, dataset: Dataset
) -> None:
    report = importer(pipeline).run(db, dataset, only=["src-order"])
    assert [o.source_id for o in report.outcomes] == ["src-order"]
    assert db.scalar(select(func.count()).select_from(Award)) == 1


def test_numbers_are_quoted_as_the_page_prints_them() -> None:
    assert _printed_number("Tariff 2.410 INR/kWh", 2.41) == "2.410"
    assert _printed_number("Capacity 1,200 MW", 1200.0) == "1,200"
    assert _printed_number("Rs. 1,10,44,800 per MW", 11044800.0) == "1,10,44,800"
    assert _printed_number("nothing here", 2.41) == "2.41"
    assert _printed_number("12.41 is not 2.41's row", 2.41) == "2.41"
    # A rounded print is another number: 2.4 does not evidence 2.41.
    assert _printed_number("Tariff 2.4 INR/kWh", 2.41) == "2.41"
    assert _printed_number("Capacity 380.0 MW", 380.0) == "380.0"
    # Nothing printed: the number itself, without loss, never a rounding of it.
    assert _printed_number("Tariff 2.41 INR/kWh", 2.410001) == "2.410001"
    assert _printed_number("nothing", 1200.0) == "1200"


def test_the_dataset_commit_is_read_from_the_clone_without_git(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("f6d1d33415d669d7e7bcaea56c4aca0bf38e572d\n")
    assert _commit_of(tmp_path) == "f6d1d33"
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled\nabcdef0123456789abcdef0123456789abcdef01 refs/heads/main\n"
    )
    assert _commit_of(tmp_path) == "abcdef0"
    (git / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    assert _commit_of(tmp_path) == "0123456"
    with pytest.raises(ResultsImportError):
        _commit_of(tmp_path / "nowhere")
