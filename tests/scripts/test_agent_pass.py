"""The agent pass command: one tender, every gold tender, nothing twice unless asked."""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent.models import AgentRun
from core.models import Job
from scripts import agent_pass
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.tenders import RFS_PAGES, make_tender, parsed


@pytest.fixture()
def readable_tender(pipeline: Pipeline, db: Session, monkeypatch: Any) -> Tender:
    monkeypatch.setattr(agent_pass, "Settings", lambda: pipeline.settings)
    tender = make_tender(pipeline, db)
    document = parsed(pipeline, db, RFS_PAGES, "rfs.pdf")
    pipeline.tenders.add_version(db, tender, document, "original", None, created_by="pytest")
    return tender


def runs(db: Session) -> list[AgentRun]:
    return list(db.scalars(select(AgentRun).order_by(AgentRun.created_at)))


def test_a_pass_is_queued_once_and_again_only_when_asked(
    db: Session, readable_tender: Tender, capsys: Any
) -> None:
    assert agent_pass.main(["agent_pass", "--tender", readable_tender.id]) == 0
    out = capsys.readouterr().out
    assert "queued run" in out and "at v1" in out and "1 pass(es) queued" in out
    queued = runs(db)
    assert len(queued) == 1 and queued[0].status == "queued" and queued[0].object_version == 1
    assert queued[0].created_by == "agent_pass_command"
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "agent_pass")) == 1

    assert agent_pass.main(["agent_pass", "--tender", readable_tender.id]) == 0
    assert "exists; skipped" in capsys.readouterr().out and len(runs(db)) == 1

    assert agent_pass.main(["agent_pass", "--tender", readable_tender.id, "--again"]) == 0
    assert "1 pass(es) queued" in capsys.readouterr().out and len(runs(db)) == 2


def test_gold_queues_each_gold_tender_at_its_reviewed_version(
    db: Session, readable_tender: Tender, capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        agent_pass,
        "load_all",
        lambda tenant_id: [SimpleNamespace(slug=readable_tender.id, reviewed_version=1)],
    )
    assert agent_pass.main(["agent_pass", "--gold"]) == 0
    out = capsys.readouterr().out
    assert "1 pass(es) queued" in out
    assert [r.object_version for r in runs(db)] == [1]


def test_a_version_that_does_not_exist_is_refused_and_an_unknown_tender_stops(
    db: Session, readable_tender: Tender, capsys: Any
) -> None:
    assert agent_pass.main(["agent_pass", "--tender", readable_tender.id, "--version", "7"]) == 0
    assert "refused" in capsys.readouterr().out and runs(db) == []
    with pytest.raises(SystemExit, match="no tender with slug or id"):
        agent_pass.main(["agent_pass", "--tender", "no-such-tender"])
    with pytest.raises(SystemExit):
        agent_pass.main(["agent_pass"])
