from fastapi import APIRouter
from sqlalchemy import select

from api.deps import ActorDep, ExtractDep, SessionDep, TenantDep
from api.middleware.errors import AppError
from api.v1.schemas.core import ExtractionRunOut, ExtractRequest
from core.llm.registry import UnregisteredPromptError
from core.models import ExtractionRun
from core.schemas import UnknownSchemaError
from core.services.extract import ExtractionError

router = APIRouter(tags=["extraction"])


@router.post("/documents/{document_id}/extract", response_model=ExtractionRunOut, status_code=202)
def start_extraction(
    document_id: str,
    body: ExtractRequest,
    session: SessionDep,
    extract: ExtractDep,
    actor: ActorDep,
) -> ExtractionRun:
    """Queue an extraction run. The worker runs it; poll GET /extraction-runs/{id}."""
    try:
        return extract.start_run(
            session,
            document_id=document_id,
            schema_name=body.schema_name,
            schema_version=body.schema_version,
            prompt_version=body.prompt_version,
            created_by=actor,
        )
    except (UnknownSchemaError, UnregisteredPromptError, ExtractionError) as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc


@router.get("/extraction-runs/{run_id}", response_model=ExtractionRunOut)
def get_extraction_run(run_id: str, session: SessionDep, tenant_id: TenantDep) -> ExtractionRun:
    run = session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.id == run_id, ExtractionRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise AppError("not_found", f"extraction run {run_id} does not exist")
    return run
