"""Evidence resolution on a synthetic page."""

from core.services.evidence import PageText, locate, normalise

LINE_1 = "The Earnest Money Deposit shall be INR 928000 per MW."
LINE_2 = "Bids must be submitted on or before 30 March 2026."
TEXT = f"{LINE_1}\n{LINE_2}"


def page(text: str = TEXT, has_text_layer: bool = True) -> PageText:
    """Each character gets a 6x10 box; line 1 at y=100, line 2 at y=120; newline has none."""
    boxes: list[list[float] | None] = []
    x, y = 72.0, 100.0
    for char in text:
        if char == "\n":
            boxes.append(None)
            x, y = 72.0, y + 20.0
        else:
            boxes.append([x, y, x + 6.0, y + 10.0])
            x += 6.0
    return PageText(page_no=7, text=text, char_boxes=boxes, has_text_layer=has_text_layer)


def test_exact_quote_gives_char_range_and_a_tight_bbox() -> None:
    found = locate("INR 928000 per MW", page(), 85)
    assert found is not None
    assert TEXT[found.char_start : found.char_end] == "INR 928000 per MW"
    assert found.page_no == 7 and found.score == 100.0
    start = TEXT.index("INR")
    assert found.bbox == [72.0 + 6 * start, 100.0, 72.0 + 6 * (start + 17), 110.0]


def test_case_whitespace_and_typographic_quotes_do_not_matter() -> None:
    found = locate("the  earnest money\nDEPOSIT shall be", page(), 85)
    assert found is not None
    assert TEXT[found.char_start : found.char_end] == "The Earnest Money Deposit shall be"
    curly = page("The “Effective Date” means the date – as notified.")
    assert locate('the "effective date" means the date - as notified', curly, 85) is not None


def test_quote_spanning_two_lines_gets_a_box_covering_both() -> None:
    found = locate("per MW. Bids must be submitted", page(), 85)
    assert found is not None and found.bbox is not None
    assert found.bbox[1] == 100.0 and found.bbox[3] == 130.0
    assert found.bbox[0] == 72.0


def test_a_small_transcription_error_is_matched_fuzzily_above_the_threshold() -> None:
    found = locate("The Earnest Money Deposit shall be INR 928,000 per MW", page(), 85)
    assert found is not None and 85 <= found.score < 100
    assert "928000" in TEXT[found.char_start : found.char_end]


def test_a_paraphrase_is_not_located() -> None:
    assert locate("Bidders have to pay nine lakh rupees for each megawatt", page(), 85) is None


def test_the_threshold_decides() -> None:
    quote = "The Earnest Money Deposit shall be INR 928,000 per MW"
    assert locate(quote, page(), 99.9) is None
    assert locate(quote, page(), 85) is not None


def test_short_quotes_must_match_exactly() -> None:
    assert locate("928000", page(), 85) is not None
    assert locate("928001", page(), 85) is None


def test_nothing_is_located_on_a_page_without_a_text_layer_or_for_an_empty_quote() -> None:
    assert locate("INR 928000 per MW", page(has_text_layer=False), 85) is None
    assert locate("   ", page(), 85) is None
    assert locate("anything", page(""), 85) is None


def test_normalise_maps_every_character_back_to_the_original() -> None:
    text = "  A  “B”\n\nc – d  "
    normalised, index_map = normalise(text)
    assert normalised == 'a "b" c - d'
    assert len(index_map) == len(normalised)
    assert text[index_map[0]] == "A" and text[index_map[-1]] == "d"
