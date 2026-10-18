"""A tender the agent can read: parsed and section-mapped, never extracted, and the
service wired the way the agent container wires it."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from agent.harness import Driver, Harness, RunOutcome
from agent.service import AgentPassService
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.tenders import RFS_PAGES, make_tender, parsed


@pytest.fixture()
def service(pipeline: Pipeline) -> AgentPassService:
    return AgentPassService(
        pipeline.catalog, pipeline.schemas, pipeline.tenders, pipeline.settings, pipeline.storage
    )


@pytest.fixture()
def readable_tender(pipeline: Pipeline, db: Session) -> Tender:
    tender = make_tender(pipeline, db)
    document = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    pipeline.tenders.add_version(db, tender, document, "original", None, created_by="pytest")
    return tender


Script = Callable[[Harness], str]


def scripted(script: Script) -> Driver:
    """A driver that plays `script` against the harness instead of a model."""

    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        return RunOutcome(final_output=script(harness))

    return drive
