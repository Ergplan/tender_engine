"""The shape every parsing layer returns, and the character boxes built from word or block
boxes.

pdfplumber gives one box per character. Docling and LlamaParse give boxes per text item
(a line, a paragraph, a table cell), so a page from them is laid out as text items
separated by newlines, and each item's characters share its box, divided evenly along the
item's width line by line. The evidence resolver then highlights the item (or the part of
it the quote covers), which is the honest box for text that was read as a block."""

from dataclasses import dataclass, field
from typing import Any

Box = list[float]  # [x0, top, x1, bottom] in PDF points, origin top-left


@dataclass(frozen=True)
class TextItem:
    """One piece of text with its box on the page, in reading order."""

    text: str
    box: Box | None
    kind: str = "text"  # text, table_cell, heading, ...


@dataclass(frozen=True)
class LayerPage:
    """What a layer read on one page."""

    page_no: int
    width: float
    height: float
    items: list[TextItem]
    detail: dict[str, Any] = field(default_factory=dict)

    def text_and_boxes(self) -> tuple[str, list[Box | None]]:
        """Items joined by newlines; one box per character, aligned with the text."""
        parts: list[str] = []
        boxes: list[Box | None] = []
        for index, item in enumerate(self.items):
            if index:
                parts.append("\n")
                boxes.append(None)
            text = item.text.replace("\x00", " ")
            parts.append(text)
            boxes.extend(character_boxes(text, item.box))
        text = "".join(parts)
        if len(boxes) != len(text):
            raise ValueError("text and character boxes are not aligned")
        return text, boxes


def character_boxes(text: str, box: Box | None) -> list[Box | None]:
    """A box per character of `text` inside `box`: the item's width divided evenly over
    the characters of each line, its height over the lines; whitespace gets None like
    pdfplumber's layout whitespace."""
    if box is None or not text:
        return [None] * len(text)
    x0, top, x1, bottom = box
    lines = text.split("\n")
    line_height = (bottom - top) / max(len(lines), 1)
    out: list[Box | None] = []
    for line_no, line in enumerate(lines):
        if line_no:
            out.append(None)  # the newline
        width = (x1 - x0) / max(len(line), 1)
        line_top = top + line_no * line_height
        for index, char in enumerate(line):
            if char.isspace():
                out.append(None)
            else:
                out.append(
                    [
                        round(x0 + index * width, 2),
                        round(line_top, 2),
                        round(x0 + (index + 1) * width, 2),
                        round(line_top + line_height, 2),
                    ]
                )
    return out
