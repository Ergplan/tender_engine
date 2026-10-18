"""Management command: queue the independent agent pass (Stage 5A).

  python -m scripts.agent_pass --tender <slug or id> [--version N]
  python -m scripts.agent_pass --gold            every gold tender, at its reviewed version

Each pass is an agent_run row and an `agent_pass` job the agent container claims; the
command prints the run ids and returns. `--gold` reads the version from each gold record so
that the pass reads the documents the reviewer saw and no later ones (what Stage 5B
compares). A tender with a finished pass at that version is skipped unless --again.
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent.models import AgentRun
from agent.service import AgentPassError, AgentPassService
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.services.extract import ExtractService
from core.storage import make_storage
from evals.gold import load_all
from tender.models import Tender
from tender.services.packs import build_registry
from tender.services.tenders import TenderService

ACTOR = "agent_pass_command"


def _service(
    settings: Settings,
) -> tuple[AgentPassService, TenderService, sessionmaker[Session]]:
    session_factory = make_session_factory(make_engine(settings), settings.tenant_id)
    schemas, catalog = build_registry()
    storage = make_storage(settings)
    llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
    tenders = TenderService(
        catalog, ExtractService(llm, storage, schemas, settings), settings.tenant_id
    )
    return AgentPassService(catalog, schemas, tenders, settings, storage), tenders, session_factory


def _tender(session: Session, settings: Settings, ref: str) -> Tender:
    tender = session.scalar(
        select(Tender).where(
            Tender.tenant_id == settings.tenant_id, (Tender.slug == ref) | (Tender.id == ref)
        )
    )
    if tender is None:
        raise SystemExit(f"no tender with slug or id {ref!r}")
    return tender


def _finished(session: Session, settings: Settings, tender: Tender, version_no: int) -> bool:
    return (
        session.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.tenant_id == settings.tenant_id,
                AgentRun.object_type == "tender",
                AgentRun.object_id == tender.id,
                AgentRun.object_version == version_no,
                AgentRun.status.in_(("queued", "running", "done", "stopped")),
            )
            .limit(1)
        )
        is not None
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agent_pass", description=__doc__)
    parser.add_argument("--tender", default="")
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--gold", action="store_true")
    parser.add_argument("--again", action="store_true", help="queue even where a pass exists")
    args = parser.parse_args(argv[1:])
    if not args.tender and not args.gold:
        parser.error("give --tender or --gold")
    settings = Settings()
    service, tenders, session_factory = _service(settings)
    wanted: list[tuple[str, int | None]] = []
    if args.gold:
        wanted = [(record.slug, record.reviewed_version) for record in load_all(settings.tenant_id)]
    else:
        wanted = [(args.tender, args.version)]
    queued = 0
    with session_factory() as session:
        for ref, version_no in wanted:
            tender = _tender(session, settings, ref)
            at = version_no
            if at is None:
                entries = tenders.versions(session, tender)
                at = entries[-1].version.version_no if entries else None
            if at is not None and not args.again and _finished(session, settings, tender, at):
                print(f"{ref}: a pass at v{at} exists; skipped (--again to queue another)")
                continue
            try:
                run = service.start(session, tender, version_no=version_no, created_by=ACTOR)
            except AgentPassError as exc:
                print(f"{ref}: refused: {exc}")
                continue
            queued += 1
            print(f"{ref}: queued run {run.id} at v{run.object_version} ({run.model})")
    print(f"{queued} pass(es) queued")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
