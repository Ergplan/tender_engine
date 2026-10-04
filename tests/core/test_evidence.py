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


WRAPPED_CELL = (
    "v) Online Bid Submission Start 02.04.2024 (11:30 Hrs.)\n"
    "Date & Time\n"
    "vi) Online Bid Submission Closing 12.04.2024 (17:30 Hrs.)\n"
    "Date & Time\n"
    "vii) Last date of Offline submission 15.04.2024 (upto 17:00 Hrs.)"
)


def test_a_quote_read_across_a_wrapped_table_cell_is_located_by_its_words() -> None:
    """The reader sees the cell label then the value; the text layer interleaves them."""
    found = locate(
        "Online Bid Submission Closing Date & Time 12.04.2024 (17:30 Hrs.)", page(WRAPPED_CELL), 85
    )
    assert found is not None and found.score >= 85
    located = WRAPPED_CELL[found.char_start : found.char_end]
    assert "Closing 12.04.2024 (17:30 Hrs.)" in located and "02.04.2024" not in located
    with_row_label = locate(
        "vi) Online Bid Submission Closing Date & Time 12.04.2024 (17:30 Hrs.)",
        page(WRAPPED_CELL),
        85,
    )
    assert with_row_label is not None
    assert WRAPPED_CELL[with_row_label.char_start : with_row_label.char_end] == (
        "vi) Online Bid Submission Closing 12.04.2024 (17:30 Hrs.)\nDate & Time"
    )


def test_reordered_matching_refuses_a_different_number_and_very_short_quotes() -> None:
    wrapped = page(WRAPPED_CELL)
    assert (
        locate("Online Bid Submission Closing Date & Time 19.05.2024 (10:00 Hrs.)", wrapped, 85)
        is None
    )
    assert locate("Time & Date", wrapped, 85) is None


def test_a_quote_is_not_located_inside_a_longer_number_or_word() -> None:
    amounts = page("EMD of Rs. 1250 Lakh for a Capacity of 250 MW and 50 MW blocks.")
    assert locate("50 MW", amounts, 85) is not None
    found = locate("50 MW", amounts, 85)
    assert found is not None and amounts.text[found.char_start - 1] == " "
    assert amounts.text[found.char_start - 4 : found.char_start] == "and "
    assert locate("250", page("EMD of Rs. 1250 Lakh"), 85) is None


def test_words_alone_are_never_matched_out_of_order() -> None:
    clause = page("The seller shall not pay the buyer any amount under this clause.")
    assert locate("the buyer shall not pay the seller any amount", clause, 85) is None


def test_characters_that_lower_case_to_two_keep_the_index_map_aligned() -> None:
    text = "İstanbul rate 12 percent"
    normalised, index_map = normalise(text)
    assert len(normalised) == len(index_map)
    found = locate("rate 12 percent", page(text), 85)
    assert found is not None and text[found.char_start : found.char_end] == "rate 12 percent"


# An amendment table as the text layer gives it: "existing clause" and "amended clause"
# side by side, read line by line across both columns.
TWO_COLUMNS = (
    "6. 5.1 A Bidder, including its Parent, Affiliate or Ultimate A Bidder, including its "
    "Parent, Affiliate or\n"
    "Parent or any Group Company shall submit a single Ultimate Parent or any Group Company\n"
    "bid offering a minimum quantum of cumulative shall submit a single bid offering a\n"
    "Contracted Capacity of 50 MW and a maximum minimum quantum of cumulative\n"
    "quantum of 600 MW, … Contracted Capacity of 50 MW and a\n"
    "maximum quantum of 750 MW, …"
)
AMENDED = (
    "shall submit a single bid offering a minimum quantum of cumulative Contracted "
    "Capacity of 50 MW and a maximum quantum of 750 MW"
)


def test_a_quote_read_down_one_column_of_a_two_column_table_is_located() -> None:
    table = page(TWO_COLUMNS)
    found = locate(AMENDED, table, 85)
    assert found is not None and found.score == 100.0
    located = TWO_COLUMNS[found.char_start : found.char_end]
    assert located.startswith("shall submit a single bid offering a\n")
    assert located.endswith("maximum quantum of 750 MW")
    # The box is the union of the matched words: it starts at the amended column on the
    # third line (y=140) and does not reach back to the lines above it.
    assert found.bbox is not None and found.bbox[1] == 140.0
    assert found.bbox[3] == 210.0


def test_the_other_column_of_the_table_is_located_as_itself_not_as_its_neighbour() -> None:
    existing = AMENDED.replace("750 MW", "600 MW")
    found = locate(existing, page(TWO_COLUMNS), 85)
    assert found is not None
    located = TWO_COLUMNS[found.char_start : found.char_end]
    assert "quantum of 600 MW" in located and "750" not in located


def test_interleaved_matching_needs_every_number_and_nearly_every_word() -> None:
    table = page(TWO_COLUMNS)
    assert locate(AMENDED.replace("750 MW", "900 MW"), table, 85) is None
    assert locate(AMENDED.replace("50 MW and", "75 MW and"), table, 85) is None
    reworded = (
        "must tender one offer for a least amount of total Contracted Capacity of 50 MW "
        "and a largest amount of 750 MW"
    )
    assert locate(reworded, table, 85) is None


def test_a_quote_whose_word_the_column_layout_broke_is_still_located() -> None:
    """A narrow column hyphenates "e-Reverse" across two lines."""
    text = (
        "Contracted Capacity of 1200 MW will be carried Contracted Capacity of 1500 MW will be\n"
        "out through e-bidding followed by e-Reverse carried out through e-bidding followed by e-\n"
        "Auction (e-RA) process. Reverse Auction (e-RA) process."
    )
    quote = (
        "Contracted Capacity of 1500 MW will be carried out through e-bidding followed by "
        "e-Reverse Auction (e-RA) process."
    )
    found = locate(quote, page(text), 85)
    assert found is not None and found.score >= 85
    assert "1500 MW" in text[found.char_start : found.char_end]
    assert locate(quote.replace("1500 MW", "1800 MW"), page(text), 85) is None
