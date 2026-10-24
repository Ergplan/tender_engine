"""The parsing layers' shape (Block 2): block boxes become character boxes aligned with the
text, and a DoclingDocument becomes pages of items in reading order with top-left boxes."""

from core.evidence.resolver import PageText, resolve
from core.parsing.docling import pages_from_document
from core.parsing.layers import LayerPage, TextItem, character_boxes


def test_character_boxes_divide_the_item_box_evenly_and_skip_whitespace() -> None:
    boxes = character_boxes("ab cd", [10.0, 20.0, 60.0, 30.0])
    assert len(boxes) == 5 and boxes[2] is None
    assert boxes[0] == [10.0, 20.0, 20.0, 30.0] and boxes[4] == [50.0, 20.0, 60.0, 30.0]
    assert character_boxes("abc", None) == [None, None, None]
    # a two-line item: the height is shared between the lines, the newline has no box
    two = character_boxes("ab\ncd", [0.0, 0.0, 20.0, 20.0])
    assert two[2] is None and two[0] == [0.0, 0.0, 10.0, 10.0] and two[3] == [0.0, 10.0, 10.0, 20.0]


def test_a_layer_page_joins_its_items_with_newlines_and_aligns_the_boxes() -> None:
    page = LayerPage(
        page_no=1,
        width=595.0,
        height=842.0,
        items=[
            TextItem("CORRIGENDUM No. 2", [72.0, 80.0, 300.0, 96.0], "heading"),
            TextItem("Bid deadline is 30 March 2026", [72.0, 110.0, 400.0, 124.0]),
        ],
    )
    text, boxes = page.text_and_boxes()
    assert text == "CORRIGENDUM No. 2\nBid deadline is 30 March 2026"
    assert len(boxes) == len(text) and boxes[len("CORRIGENDUM No. 2")] is None
    # the resolver finds a quote on the page and gives it the item's box
    match = resolve("deadline is 30 March 2026", PageText(1, text, boxes, True))
    assert match.__class__.__name__ == "Match"
    assert match.bbox is not None and 72.0 <= match.bbox[0] < match.bbox[2] <= 400.0  # type: ignore[union-attr]
    assert match.bbox[1] == 110.0 and match.bbox[3] == 124.0  # type: ignore[union-attr]


def _bl(left: float, top: float, right: float, bottom: float) -> dict[str, object]:
    """A Docling box, bottom-left origin."""
    return {"l": left, "t": top, "r": right, "b": bottom, "coord_origin": "BOTTOMLEFT"}


def _cell(row: int, col: int, text: str, box: dict[str, object]) -> dict[str, object]:
    return {"start_row_offset_idx": row, "start_col_offset_idx": col, "text": text, "bbox": box}


DOCLING_DOCUMENT = {
    "schema_name": "DoclingDocument",
    "pages": {"1": {"size": {"width": 612.0, "height": 792.0}, "page_no": 1}},
    "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}, {"$ref": "#/texts/1"}]},
    "texts": [
        {
            "self_ref": "#/texts/0",
            "label": "section_header",
            "text": "Amendment  No. 3",
            "prov": [{"page_no": 1, "bbox": _bl(72.0, 720.0, 300.0, 700.0)}],
        },
        {
            "self_ref": "#/texts/1",
            "label": "text",
            "text": "All other terms remain unchanged.",
            "prov": [{"page_no": 1, "bbox": _bl(72.0, 400.0, 500.0, 388.0)}],
        },
    ],
    "tables": [
        {
            "self_ref": "#/tables/0",
            "prov": [{"page_no": 1, "bbox": _bl(72, 680, 540, 420)}],
            "data": {
                "num_rows": 2,
                "num_cols": 2,
                "table_cells": [
                    _cell(0, 0, "Clause", _bl(72, 680, 300, 660)),
                    _cell(0, 1, "Amended provision", _bl(300, 680, 540, 660)),
                    _cell(1, 0, "4.1", _bl(72, 660, 300, 640)),
                    _cell(1, 1, "PBG: INR 29 lakh per MW", _bl(300, 660, 540, 640)),
                    _cell(1, 1, "PBG: INR 29 lakh per MW", _bl(300, 660, 540, 640)),
                ],
            },
        }
    ],
}


def test_a_docling_document_becomes_items_in_reading_order_with_top_left_boxes() -> None:
    pages = pages_from_document(DOCLING_DOCUMENT)
    assert list(pages) == [1]
    page = pages[1]
    assert (page.width, page.height) == (612.0, 792.0)
    assert [item.text for item in page.items] == [
        "Amendment No. 3",
        "Clause",
        "Amended provision",
        "4.1",
        "PBG: INR 29 lakh per MW",
        "All other terms remain unchanged.",
    ], "body order; whitespace collapsed; a repeated (merged) cell once"
    assert page.items[0].kind == "section_header" and page.items[1].kind == "table_cell"
    # BOTTOMLEFT t=720,b=700 on a 792 pt page is top=72, bottom=92 from the top
    assert page.items[0].box == [72.0, 72.0, 300.0, 92.0]
    assert page.detail == {"items": {"section_header": 1, "table_cell": 4, "text": 1}}
    text, boxes = page.text_and_boxes()
    match = resolve("PBG: INR 29 lakh per MW", PageText(1, text, boxes, True))
    assert match.__class__.__name__ == "Match"
    assert match.bbox == [300.0, 132.0, 540.0, 152.0]  # type: ignore[union-attr]


def test_a_document_without_a_body_tree_still_yields_its_texts_and_tables() -> None:
    flat = {k: v for k, v in DOCLING_DOCUMENT.items() if k != "body"}
    pages = pages_from_document(flat)
    assert [item.text for item in pages[1].items][:2] == [
        "Amendment No. 3",
        "All other terms remain unchanged.",
    ]
    assert len(pages[1].items) == 6
