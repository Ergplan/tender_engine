"""Full-tender query (Stage 7, Block 5): one question about one tender, answered from the
approved fact when the question names a field and from retrieved pages otherwise; and the
cross-tender question, a structured search over approved facts. Nothing here writes a fact.
Unlike every other route, `ask` calls the model inside the request (DECISIONS 2026-10-25):
a question wants its answer now, and the call is logged like any other."""

from fastapi import APIRouter

from api.deps import ActorDep, AskDep, CatalogDep, SessionDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.tenders import AskRequest, CrossAskRequest
from api.v1.tenders.tenders import _tender
from core.llm.registry import UnregisteredPromptError
from core.services import jobs
from tender.services.ask import AskAnswer, AskError
from tender.services.ask_across import CrossAnswer, CrossQuery, parse_cross_question, search_facts

router = APIRouter(tags=["ask"])


@router.post("/tenders/ask", response_model=CrossAnswer)
def ask_across_tenders(
    body: CrossAskRequest, session: SessionDep, tenders: TendersDep, catalog: CatalogDep
) -> CrossAnswer:
    """Which tenders satisfy a condition on one field, over approved facts only. Send the
    structured query (`field_path`, `operator`, `value`), or a `question` that is read into
    one; the answer returns the query that ran."""
    rows = tenders.all(session)
    if body.field_path:
        query = CrossQuery(field_path=body.field_path, operator=body.operator, value=body.value)
        for tender in rows:
            field = next(
                (
                    f
                    for f in catalog.get(tender.tender_type).schema.fields
                    if f.path == body.field_path
                ),
                None,
            )
            if field is not None:
                query.label = field.label
                break
        return search_facts(session, catalog, rows, query, question=body.question)
    if not body.question or not body.question.strip():
        raise AppError("validation_failed", "send a question or a field_path")
    parsed: CrossQuery | None = None
    for tender_type in sorted({t.tender_type for t in rows}) or ["ipp"]:
        parsed = parse_cross_question(body.question, catalog.get(tender_type).schema)
        if parsed is not None:
            break
    if parsed is None:
        raise AppError(
            "validation_failed",
            "the question names no field of the record; ask one tender with /tenders/{id}/ask",
        )
    return search_facts(session, catalog, rows, parsed, question=body.question)


@router.post("/tenders/{tender_id}/ask", response_model=AskAnswer)
def ask_tender(
    tender_id: str,
    body: AskRequest,
    session: SessionDep,
    tenders: TendersDep,
    ask: AskDep,
    actor: ActorDep,
) -> AskAnswer:
    """Ask one question about a tender. The answer names its source (`approved` fact,
    `machine` reading) and cites pages with quotes the evidence resolver located; an
    unresolved quote is shown as such. Never a fact."""
    tender = _tender(tenders, session, tender_id)
    try:
        return ask.ask(session, tender, body.question, created_by=actor)
    except UnregisteredPromptError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except AskError as exc:
        if "empty" in str(exc):
            raise AppError("validation_failed", str(exc)) from exc
        raise AppError("model_unavailable", str(exc)) from exc


@router.post("/tenders/{tender_id}/index", status_code=202)
def index_tender(
    tender_id: str, session: SessionDep, tenders: TendersDep, actor: ActorDep
) -> dict[str, int]:
    """Queue the chunks of every document of the tender for retrieval again (after a
    re-parse, or for documents parsed before retrieval existed)."""
    tender = _tender(tenders, session, tender_id)
    queued = 0
    for entry in tenders.versions(session, tender):
        for _, document in entry.documents:
            if document.status != "parsed":
                continue
            jobs.enqueue(
                session,
                tenant_id=tender.tenant_id,
                kind="index_document",
                payload={"document_id": document.id},
                created_by=actor,
            )
            queued += 1
    session.commit()
    return {"queued": queued}
