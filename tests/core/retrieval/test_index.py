"""The indexer and the store (Stage 7, Block 5 a): a parsed document's chunks in the
pgvector table, with the tender's meta, under row-level security; keyword retrieval over
them; a re-index that replaces."""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core.models import RetrievalChunk
from core.retrieval import ChunkStores
from core.retrieval.store import or_terms
from tests.conftest import Pipeline, add_tenant
from tests.fixtures.tenders import RFS_PAGES, make_tender, parsed


def _filters(tender_id: str) -> dict:  # type: ignore[type-arg]
    return {"field": "meta.tender_id", "operator": "==", "value": tender_id}


def test_a_parsed_document_is_chunked_with_its_tender_meta_and_found_by_keyword(
    pipeline: Pipeline, db: Session
) -> None:
    tender = make_tender(pipeline, db)
    document = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    before = pipeline.store.chunks_of(document.id)
    assert before and all(c.meta.get("tender_id") is None for c in before), (
        "indexed after the section map, before the document belonged to a tender"
    )
    pipeline.tenders.add_version(db, tender, document, "original", None, created_by="pytest")
    pipeline.runner.run_until_idle()
    chunks = pipeline.store.chunks_of(document.id)
    assert len(chunks) == len(RFS_PAGES), "one chunk per short page"
    by_page = {c.meta["page_no"]: c for c in chunks}
    assert {c.meta["tender_id"] for c in chunks} == {tender.id}
    assert {c.meta["role"] for c in chunks} == {"rfs"} and {
        c.meta["version_no"] for c in chunks
    } == {1}
    assert by_page[3].meta["section_kind"] == "financial_security"
    assert by_page[3].meta["embedded"] is False and by_page[3].embedding is None
    assert "928000" in (by_page[3].content or "")
    page_text = db.execute(
        text("SELECT text FROM page WHERE document_id = :d AND page_no = 3"), {"d": document.id}
    ).scalar_one()
    assert (
        page_text[by_page[3].meta["char_start"] : by_page[3].meta["char_end"]] == by_page[3].content
    )

    hits, mode = pipeline.ask._retriever.retrieve(
        "earnest money deposit per MW", _filters(tender.id)
    )  # type: ignore[union-attr]
    assert mode == "keyword" and hits and hits[0].meta["page_no"] == 3
    assert (
        pipeline.ask._retriever.retrieve("pooling substation licensee", _filters(tender.id))[0]
        == []
    )  # type: ignore[union-attr]

    pipeline.indexer.index_document(db, document.id)
    assert len(pipeline.store.chunks_of(document.id)) == len(RFS_PAGES), "replaced, not doubled"
    assert db.scalar(select(func.count()).select_from(RetrievalChunk)) == len(RFS_PAGES)
    assert db.scalar(select(RetrievalChunk.tenant_id).limit(1)) == pipeline.settings.tenant_id


def test_another_tenant_sees_no_chunks(pipeline: Pipeline, db: Session) -> None:
    make_tender(pipeline, db)
    parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    assert pipeline.store.count_documents() == len(RFS_PAGES)
    add_tenant(pipeline.settings, "other")
    other = ChunkStores(pipeline.settings).for_tenant("other")
    assert other.count_documents() == 0
    assert other.filter_documents({"field": "meta.page_no", "operator": "==", "value": 3}) == []


def test_or_terms_is_the_question_as_an_any_word_expression() -> None:
    assert (
        or_terms("What PBG must the bidder furnish?")
        == "what | pbg | must | the | bidder | furnish"
    )
    assert or_terms("EMD, EMD and (EMD)!") == "emd | and"
    assert or_terms("?!") == ""


def test_keyword_retrieval_falls_back_to_any_word_and_finds_nothing_for_absent_words(
    pipeline: Pipeline, db: Session
) -> None:
    tender = make_tender(pipeline, db)
    document = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    pipeline.tenders.add_version(db, tender, document, "original", None, created_by="pytest")
    pipeline.runner.run_until_idle()
    retriever = pipeline.ask._retriever
    assert retriever is not None
    # "successful" is on no page: every-word finds nothing, any-word finds the PBG page.
    hits, mode = retriever.retrieve(
        "What performance bank guarantee must the successful bidder furnish?",
        _filters(tender.id),
    )
    assert mode == "keyword" and hits and hits[0].meta["page_no"] == 3
    # Every-word still ranks first when it holds: the page with both words.
    hits, _ = retriever.retrieve("earnest money deposit", _filters(tender.id))
    assert hits and hits[0].meta["page_no"] == 3
    # No word of the question is on any page: nothing, not the nearest page.
    assert retriever.retrieve("pooling substation licensee", _filters(tender.id))[0] == []
    # One common word in common ("power", on the cover) is not an answer either.
    assert retriever.retrieve("pooling substation power", _filters(tender.id))[0] == []
