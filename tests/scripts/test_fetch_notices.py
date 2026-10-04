"""The notice fetcher on saved page fragments; no network."""

from datetime import date
from pathlib import Path

import pymupdf
import yaml

from scripts.fetch_notices import (
    add_notice,
    notice_lines,
    pairs_from_colon_labels,
    pairs_from_table_rows,
)
from scripts.ingest_tenders import read_manifests
from tests.scripts.test_ingest_tenders import shape

SECI_PAGE = """
<table><tbody><tr><td class="pageheader"><table><tbody><tr><td>Bid Details</td></tr>
</tbody></table></td></tr>
<tr><td><div><table><tbody>
<tr>
 <td class="fw-bold" width="25%"> Tender Publication Date </td>
 <td width="25%"><span
   style="font-size: 16px;">05/06/2026 18:49:11</span></td>
 <td class="fw-bold" width="25%"> Pre Bid Meeting Date </td>
 <td width="25%"><span>17/06/2026 14:30:21</span></td>
</tr>
<tr>
 <td class="fw-bold"> Bid Submission End Date (Online) </td>
 <td><span>07/08/2026 18:00:28</span></td>
</tr>
<tr><td class="fw-bold"> EMD </td><td><!-- hidden --><span>As per RfS document</span></td></tr>
</tbody></table></div></td></tr></tbody></table>
<script>var x = "<td class='fw-bold'>not a label</td><td>no</td>";</script>
"""
NTPC_PAGE = """
<div><b>NIT No. :</b> <span>NRE-CS-5846-004(PHES)-9</span></div>
<div><b>Date Of Issue of NIT :</b> <span>29/05/2026</span></div>
<div><b>EMD Cost :</b> <b>Tender Cost :</b></div>
<div><b>Bid Submission End Date :</b> <span>21/07/2026 :15:00</span></div>
"""


def test_label_and_value_pairs_are_read_from_nested_table_rows() -> None:
    assert pairs_from_table_rows(SECI_PAGE) == [
        ("Tender Publication Date", "05/06/2026 18:49:11"),
        ("Pre Bid Meeting Date", "17/06/2026 14:30:21"),
        ("Bid Submission End Date (Online)", "07/08/2026 18:00:28"),
        ("EMD", "As per RfS document"),
    ]
    assert pairs_from_table_rows(NTPC_PAGE) == []


def test_label_and_value_pairs_are_read_from_colon_labels() -> None:
    assert pairs_from_colon_labels(NTPC_PAGE) == [
        ("NIT No.", "NRE-CS-5846-004(PHES)-9"),
        ("Date Of Issue of NIT", "29/05/2026"),
        ("Bid Submission End Date", "21/07/2026 :15:00"),
    ], "a label followed by another label has no value"


def test_the_notice_is_the_pages_own_text_with_its_source() -> None:
    lines = notice_lines(
        "SECI", "A tender", "https://example.org/t/1", date(2026, 10, 4), SECI_PAGE
    )
    assert lines[2:4] == [
        "Source: https://example.org/t/1",
        "Retrieved on 2026-10-04. Dates are day-first (dd/mm/yyyy).",
    ]
    assert "Bid Submission End Date (Online): 07/08/2026 18:00:28" in lines


def test_a_notice_is_filed_once_as_a_nit_of_the_latest_version(tmp_path: Path) -> None:
    folder = tmp_path / "fdre" / "acme"
    folder.mkdir(parents=True)
    manifest = {
        "slug": "acme",
        "type": "fdre",
        "agency": "Acme",
        "external_ref": None,
        "title": "A tender",
        "notice_url": "https://example.org/t/1",
        "files": [
            {"file": "rfs.pdf", "role": "rfs", "issued_on": "2026-06-05"},
            {"file": "a1.pdf", "role": "amendment", "issued_on": "2026-07-08"},
        ],
    }
    path = folder / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest))
    name = add_notice(path, date(2026, 10, 4), page=SECI_PAGE)
    assert name == "Tender_notice_page_acme.pdf"
    assert add_notice(path, date(2026, 10, 5), page=SECI_PAGE) is None, "already filed"
    text = pymupdf.open(folder / name)[0].get_text()
    assert "Pre Bid Meeting Date: 17/06/2026 14:30:21" in text
    assert (folder / "Tender_notice_page_acme.html").read_text() == SECI_PAGE
    entry = yaml.safe_load(path.read_text())["files"][-1]
    assert entry == {
        "file": name,
        "role": "nit",
        "issued_on": None,
        "pages": 1,
        "attach_to": "latest",
        "source": "https://example.org/t/1",
        "retrieved_on": "2026-10-04",
    }
    (parsed,) = read_manifests(tmp_path)
    assert shape(parsed) == [("original", ["rfs.pdf"]), ("amendment", ["a1.pdf", name])]
    no_url = dict(manifest, slug="other")
    del no_url["notice_url"]
    other = tmp_path / "fdre" / "other"
    other.mkdir()
    (other / "manifest.yaml").write_text(yaml.safe_dump(no_url))
    assert add_notice(other / "manifest.yaml", date(2026, 10, 4), page=SECI_PAGE) is None
