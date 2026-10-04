"""Synthetic PDFs with known text, built with pymupdf. No real tender is needed for unit tests."""

import pymupdf

PAGE_1 = [
    "MASTER SUPPLY AGREEMENT",
    "Agreement No. ACME/2026/001",
    "Issued by Acme Power Limited, New Delhi.",
]
PAGE_2 = [
    "SECTION 2: KEY DATES",
    "The pre-bid meeting shall be held on 12.03.2026 at the registered office.",
    "Bids must be submitted on or before 30 March 2026 at 15:00 hrs.",
]
PAGE_3 = [
    "SECTION 3: SECURITY AND CAPACITY",
    "The Earnest Money Deposit shall be INR 928000 per MW of quoted capacity.",
    "The total contracted capacity under this agreement is 600 MW.",
    "The agreement shall remain in force for a tenure of 25 years.",
]


def make_pdf(pages: list[list[str]] | None = None, *, scanned_last_page: bool = False) -> bytes:
    """A PDF with one text page per list of lines; optionally a final image-only page."""
    document = pymupdf.open()
    for lines in pages if pages is not None else [PAGE_1, PAGE_2, PAGE_3]:
        page = document.new_page(width=595, height=842)
        for index, line in enumerate(lines):
            page.insert_text((72, 100 + index * 28), line, fontsize=11)
    if scanned_last_page:
        source = pymupdf.open()
        text_page = source.new_page(width=595, height=842)
        text_page.insert_text(
            (72, 100), "This page is an image and has no text layer.", fontsize=11
        )
        pixmap = text_page.get_pixmap(dpi=72)
        image_page = document.new_page(width=595, height=842)
        image_page.insert_image(image_page.rect, pixmap=pixmap)
        source.close()
    data: bytes = document.tobytes()
    document.close()
    return data
