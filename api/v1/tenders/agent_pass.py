from fastapi import APIRouter
from sqlalchemy.orm import Session

from agent.inputs import asked_fields
from agent.models import AgentRun
from agent.service import AgentPassError, AgentPassService
from api.deps import ActorDep, AgentPassesDep, CatalogDep, SessionDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.agent import AgentFindingOut, AgentPassOut, AgentPassRequest, AgentRunOut
from core.llm.registry import UnregisteredPromptError
from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.tenders import TenderService

router = APIRouter(tags=["agent"])
STANDING = ("accepted", "not_found", "withdrawn")


def _tender(tenders: TenderService, session: Session, tender_id: str) -> Tender:
    try:
        return tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc


def _pass_out(
    session: Session, passes: AgentPassService, catalog: Catalog, tender: Tender, run: AgentRun
) -> AgentPassOut:
    findings = passes.findings(session, run)
    asked = asked_fields(catalog.get(tender.tender_type))
    standing = {f.field_path for f in findings if f.status in STANDING}
    return AgentPassOut(
        run=AgentRunOut.model_validate(run),
        findings=[AgentFindingOut.model_validate(f) for f in findings],
        unsubmitted=[path for path in asked if path not in standing],
    )


@router.post("/tenders/{tender_id}/agent-pass", response_model=AgentRunOut, status_code=202)
def start_agent_pass(
    tender_id: str,
    body: AgentPassRequest,
    session: SessionDep,
    tenders: TendersDep,
    passes: AgentPassesDep,
    actor: ActorDep,
) -> AgentRun:
    """Queue the independent agent pass over one version of the tender (the current one
    by default). The agent container runs it: a second model, from another family, reads
    the documents through its own tools and the field schema, without the engine's
    candidates, the gold values or any reviewer's decision. Its findings land in
    `agent_finding` and never become candidates or canonical facts."""
    tender = _tender(tenders, session, tender_id)
    try:
        return passes.start(session, tender, version_no=body.version_no, created_by=actor)
    except (AgentPassError, UnregisteredPromptError) as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc


@router.get("/tenders/{tender_id}/agent-pass", response_model=list[AgentRunOut])
def list_agent_passes(
    tender_id: str, session: SessionDep, tenders: TendersDep, passes: AgentPassesDep
) -> list[AgentRun]:
    """The agent passes of the tender, oldest first, with their turns, tokens and cost."""
    tender = _tender(tenders, session, tender_id)
    return passes.runs(session, tender)


@router.get("/tenders/{tender_id}/agent-pass/{run_id}", response_model=AgentPassOut)
def get_agent_pass(
    tender_id: str,
    run_id: str,
    session: SessionDep,
    tenders: TendersDep,
    passes: AgentPassesDep,
    catalog: CatalogDep,
) -> AgentPassOut:
    """One pass with every finding the agent submitted, accepted or refused (a refusal
    carries its reason), and the fields of the schema for which no finding stands."""
    tender = _tender(tenders, session, tender_id)
    try:
        run = passes.get(session, tender, run_id)
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return _pass_out(session, passes, catalog, tender, run)
