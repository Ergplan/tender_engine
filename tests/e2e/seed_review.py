"""Seed the database of the browser-test stack (`make test-ui`): a synthetic solar tender
with an RfS and an amendment, extracted with a scripted model, and its review links.

  python -m tests.e2e.seed_review

Run by the api-e2e service before it starts. It empties the tender_e2e database first, so
every run of the browser tests starts from the same state. No real model is called.
"""

from datetime import date

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.storage import make_storage
from tender.models import ReviewToken
from tender.services.amendment_map import AmendmentMapper, job_handlers
from tender.services.packs import build_registry
from tender.services.tenders import TenderService
from tender.services.tokens import TokenService
from tests.fixtures.llm import ScriptedSDK
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import AMENDMENT_ANSWERS, AMENDMENT_PAGES, RFS_ANSWERS, RFS_PAGES
from worker.runner import Runner

# The browser tests open these links.
REVIEW_TOKEN = "e2e-review-token-0000000000000001"
REPLACED_TOKEN = "e2e-review-token-0000000000000002"
ACTOR = "seed_review"


def reset_database(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if not (url.database or "").endswith("_e2e"):
        raise SystemExit(f"refusing to empty {url.database!r}: not a browser-test database")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    config = Config("alembic.ini")
    config.attributes["settings"] = settings
    command.upgrade(config, "head")


def seed(settings: Settings) -> None:
    session_factory = make_session_factory(make_engine(settings))
    storage = make_storage(settings)
    schemas, catalog = build_registry()
    sdk = ScriptedSDK(dict(RFS_ANSWERS))
    llm = LLMClient(settings, session_factory, sdk=sdk.as_sdk(), prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, storage, schemas, settings)
    runner = Runner(
        settings,
        session_factory,
        storage,
        schemas,
        llm,
        job_handlers(AmendmentMapper(llm, catalog, extract, settings.tenant_id)),
    )
    ingest = IngestService(storage, settings.tenant_id)
    tenders = TenderService(catalog, extract, settings.tenant_id)
    tokens = TokenService(settings.tenant_id)
    with session_factory() as session:
        tender = tenders.create(
            session,
            tender_type="solar",
            issuing_agency="Acme Renewables Agency",
            external_ref="ACME/RE/2026/007",
            title="Selection of solar power developers for 600 MW solar PV projects",
            created_by=ACTOR,
        )
        rfs, _ = ingest.upload(
            session, filename="rfs.pdf", data=make_pdf(RFS_PAGES), created_by=ACTOR
        )
        runner.run_until_idle()
        session.refresh(rfs)
        tenders.add_version(session, tender, rfs, "original", None, created_by=ACTOR)
        tenders.start_extraction(session, tender, created_by=ACTOR, is_fixture=True)
        runner.run_until_idle()

        sdk.answers = dict(AMENDMENT_ANSWERS)
        amendment, _ = ingest.upload(
            session, filename="amendment-01.pdf", data=make_pdf(AMENDMENT_PAGES), created_by=ACTOR
        )
        runner.run_until_idle()
        session.refresh(amendment)
        tenders.add_version(
            session, tender, amendment, "amendment", date(2026, 3, 20), created_by=ACTOR
        )
        tenders.start_extraction(session, tender, created_by=ACTOR, is_fixture=True)
        runner.run_until_idle()

        # Two links: the first is replaced by the second, which is the one that works.
        replaced = tokens.create(session, tender, "Earlier Reviewer", created_by=ACTOR)
        live = tokens.create(session, tender, "Asha Rao", created_by=ACTOR)
        for row, fixed in ((replaced, REPLACED_TOKEN), (live, REVIEW_TOKEN)):
            session.execute(update(ReviewToken).where(ReviewToken.id == row.id).values(token=fixed))
        session.commit()
        count = len(list(session.scalars(select(ReviewToken))))
    print(f"seeded tender {tender.id} with {count} review links")


def main() -> None:
    settings = Settings()
    reset_database(settings)
    seed(settings)


if __name__ == "__main__":
    main()
