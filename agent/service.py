"""AgentPassService: start a pass (a queued run and its job), run it (the job handler in
the agent container), read it back (the API)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent.harness import Driver, Harness, RunOutcome, brief_for
from agent.inputs import InputsError, PassInputs, build_inputs
from agent.models import AgentFinding, AgentRun
from core.config import Settings
from core.llm.registry import Prompt, load_prompt
from core.schemas import SchemaRegistry
from core.services import audit, jobs
from core.storage import Storage
from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.tenders import OBJECT_TYPE, TenderService

log = logging.getLogger("agent")
JOB_KIND = "agent_pass"
PROMPT_NAME = "agent_pass"
PROMPT_VERSION = "v1"
ACTOR = "agent_pass"


class AgentPassError(ValueError):
    """The pass cannot be started as asked. The message is safe to show."""


class AgentPassService:
    def __init__(
        self,
        catalog: Catalog,
        schemas: SchemaRegistry,
        tenders: TenderService,
        settings: Settings,
        storage: Storage,
    ) -> None:
        self._catalog = catalog
        self._schemas = schemas
        self._tenders = tenders
        self._settings = settings
        self._storage = storage
        self._tenant_id = settings.tenant_id

    def prompt(self) -> Prompt:
        return load_prompt(PROMPT_NAME, PROMPT_VERSION, self._catalog.prompt_roots)

    def start(
        self,
        session: Session,
        tender: Tender,
        *,
        version_no: int | None = None,
        created_by: str,
        is_fixture: bool = False,
    ) -> AgentRun:
        """Queue a pass over the tender at a version (the current one by default). The
        inputs are checked now so that a pass that cannot run is refused here."""
        if tender.status == "superseded":
            raise AgentPassError("the tender was superseded; run the pass on its successor")
        compiled = self._catalog.get(tender.tender_type)
        entries = self._tenders.versions(session, tender)
        if not entries:
            raise AgentPassError("the tender has no version yet")
        at = version_no if version_no is not None else entries[-1].version.version_no
        try:
            inputs = build_inputs(session, self._tenders, compiled, self._settings, tender, at)
        except InputsError as exc:
            raise AgentPassError(str(exc)) from exc
        prompt = self.prompt()
        run = AgentRun(
            tenant_id=self._tenant_id,
            created_by=created_by,
            object_type=OBJECT_TYPE,
            object_id=tender.id,
            object_version=at,
            schema_name=compiled.schema.name,
            schema_version=compiled.schema.version,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            model=self._settings.openai_model,
            status="queued",
            pages_offered={str(d.number): list(d.pages) for d in inputs.documents},
            documents=[
                {
                    "number": d.number,
                    "document_id": d.document_id,
                    "filename": d.filename,
                    "version_no": d.version_no,
                }
                for d in inputs.documents
            ],
            is_fixture=is_fixture,
        )
        session.add(run)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="insert",
            table_name="agent_run",
            row_id=run.id,
            after={
                "object_id": tender.id,
                "object_version": at,
                "model": run.model,
                "prompt": f"{prompt.name}/{prompt.version}",
                "fields": len(inputs.field_paths),
            },
        )
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind=JOB_KIND,
            payload={"agent_run_id": run.id},
            created_by=created_by,
        )
        session.commit()
        return run

    def get(self, session: Session, tender: Tender, run_id: str) -> AgentRun:
        run = session.scalar(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.tenant_id == self._tenant_id,
                AgentRun.object_type == OBJECT_TYPE,
                AgentRun.object_id == tender.id,
            )
        )
        if run is None:
            raise LookupError(f"tender {tender.id} has no agent pass {run_id}")
        return run

    def runs(self, session: Session, tender: Tender) -> list[AgentRun]:
        return list(
            session.scalars(
                select(AgentRun)
                .where(
                    AgentRun.tenant_id == self._tenant_id,
                    AgentRun.object_type == OBJECT_TYPE,
                    AgentRun.object_id == tender.id,
                )
                .order_by(AgentRun.created_at, AgentRun.id)
            )
        )

    def findings(self, session: Session, run: AgentRun) -> list[AgentFinding]:
        return list(
            session.scalars(
                select(AgentFinding)
                .where(
                    AgentFinding.agent_run_id == run.id,
                    AgentFinding.tenant_id == self._tenant_id,
                )
                .order_by(AgentFinding.ordinal)
            )
        )

    def run(self, session: Session, run_id: str, driver: Driver) -> AgentRun:
        """The job: build the inputs again, run the agent loop through `driver`, close the
        run. A run that is not queued (done already, or running elsewhere) is left alone."""
        run = session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == self._tenant_id)
        )
        if run is None:
            raise LookupError(f"agent run {run_id} not found")
        if run.status != "queued":
            log.warning("agent run %s is %s; not run again", run.id, run.status)
            return run
        tender = self._tenders.get(session, run.object_id)
        compiled = self._catalog.get(tender.tender_type)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        self._audit_status(session, run, "queued", "running")
        session.commit()
        try:
            inputs = build_inputs(
                session, self._tenders, compiled, self._settings, tender, run.object_version
            )
        except InputsError as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(UTC)
            self._audit_status(session, run, "running", "failed", error=str(exc))
            session.commit()
            return run
        harness = Harness(session, self._settings, self._schemas, self._storage, run, inputs)
        outcome = self._drive(harness, inputs, driver)
        missing = harness.unsubmitted()
        note = f"{len(missing)} field(s) without a finding: {', '.join(missing)}" if missing else ""
        if outcome.stopped:
            return harness.finish("stopped", "; ".join(p for p in (outcome.stopped, note) if p))
        return harness.finish("done", note or None)

    def _audit_status(
        self, session: Session, run: AgentRun, before: str, after: str, *, error: str | None = None
    ) -> None:
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=ACTOR,
            action="status_change",
            table_name="agent_run",
            row_id=run.id,
            before={"status": before},
            after={"status": after, **({"error": error} if error else {})},
        )

    def _drive(self, harness: Harness, inputs: PassInputs, driver: Driver) -> RunOutcome:
        try:
            return driver(harness, self.prompt().text, brief_for(inputs))
        except Exception as exc:  # the provider, the network: the findings so far stand
            log.exception("agent run %s stopped on an error", harness.run.id)
            return RunOutcome(stopped=f"{type(exc).__name__}: {exc}")


def job_handlers(
    service: AgentPassService, driver: Driver
) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    def handle(session: Session, payload: dict[str, Any]) -> None:
        service.run(session, payload["agent_run_id"], driver)

    return {JOB_KIND: handle}


def real_driver(
    settings: Settings, session_factory: sessionmaker[Session], catalog: Catalog
) -> Driver:
    from agent.harness import sdk_driver

    return sdk_driver(
        settings, session_factory, load_prompt(PROMPT_NAME, PROMPT_VERSION, catalog.prompt_roots)
    )
