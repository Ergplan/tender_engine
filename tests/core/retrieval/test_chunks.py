"""The page chunker (Stage 7, Block 5 a): clause boundaries, sizes and offsets."""

from core.retrieval.chunks import Chunk, chunk_page, clause_of, last_clause

PAGE = "\n".join(
    [
        "SECTION 3: SECURITY AND CAPACITY",
        "3.1 Earnest Money Deposit",
        "The Earnest Money Deposit shall be INR 928000 per MW of the quoted capacity, "
        "furnished as a bank guarantee valid for 45 days beyond the bid validity.",
        "The EMD of unsuccessful bidders is returned within 30 days of the award.",
        "3.2 Performance Bank Guarantee",
        "The successful bidder shall furnish a PBG of INR 2320000 per MW within 30 days.",
        "30 March 2026 is the last date of bid submission.",
        "600 MW is the total capacity under this RfS.",
        "Clause 4 Bid validity",
        "Bids remain valid for 180 days from the last date of submission.",
    ]
)


def test_clause_lines_are_told_from_dates_and_quantities() -> None:
    assert clause_of("3.1 Earnest Money Deposit") == "3.1"
    assert clause_of("12.3.4) The bidder shall") == "12.3.4"
    assert clause_of("Clause 4 Bid validity") == "4"
    assert clause_of("Article 10: Tariff") == "10"
    assert clause_of("SECTION 3: SECURITY AND CAPACITY") is None, "a part heading"
    assert clause_of("Section 3 Instructions to bidders") == "3"
    assert clause_of("7 General conditions") == "7"
    assert clause_of("30 March 2026 is the last date") is None, "a date is not a clause"
    assert clause_of("600 MW is the total capacity") is None, "a quantity is not a clause"
    assert clause_of("2026 Annual report") is None, "a year is not a clause"
    assert clause_of("5 of the bidders") is None, "a lowercase word follows a count"
    assert clause_of("The Earnest Money Deposit shall be") is None


def test_chunks_follow_clauses_and_keep_their_offsets() -> None:
    chunks = chunk_page(3, PAGE, min_chars=60, max_chars=400)
    assert [c.clause for c in chunks] == ["3.1", "3.2", "4"], [c.text[:30] for c in chunks]
    for chunk in chunks:
        assert PAGE[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.page_no == 3
    assert chunks[0].text.startswith(
        "SECTION 3: SECURITY AND CAPACITY\n3.1 Earnest Money Deposit"
    ), "a short part heading is merged into the first clause and takes its number"
    assert "928000" in chunks[0].text and "PBG" not in chunks[0].text
    assert "30 March 2026" in chunks[1].text, "a date line stays in the clause above it"
    assert last_clause(chunks) == "4"


def test_short_clauses_merge_and_long_text_splits() -> None:
    merged = chunk_page(1, PAGE, min_chars=5000, max_chars=10000)
    assert len(merged) == 1 and merged[0].clause == "3.1", "nothing reaches the minimum"
    split = chunk_page(1, "x" * 50 + "\n" + "y" * 50 + "\n" + "z" * 50, max_chars=110, min_chars=10)
    assert [len(c.text) for c in split] == [101, 50]
    assert all("x" * 50 in c.text or "z" * 50 in c.text for c in split)


def test_the_carried_clause_names_text_before_the_first_heading() -> None:
    chunks = chunk_page(
        4,
        "continued from the previous page.\n5.1 Next clause\nwords",
        carry_clause="4.9",
        min_chars=1,
    )
    assert [c.clause for c in chunks] == ["4.9", "5.1"]
    assert chunk_page(1, "   \n\n") == []
    assert Chunk(1, None, 0, 3, "abc").id("doc") == Chunk(1, None, 0, 3, "abc").id("doc")
    assert Chunk(1, None, 0, 3, "abc").id("doc") != Chunk(2, None, 0, 3, "abc").id("doc")
