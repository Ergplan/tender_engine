"""Row-level security (migration 0018): a session sees its own tenant's rows and nothing
else, whatever the service layer asks for; a write to another tenant, `public` included, is
refused by the database."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from core.config import Settings
from core.db import SYSTEM_TENANT, make_engine, make_session_factory, set_tenant
from tender.models import Tender
from tests.conftest import add_tenant


def _tender(tenant_id: str, title: str) -> Tender:
    return Tender(
        tenant_id=tenant_id,
        created_by="pytest",
        tender_type="solar",
        issuing_agency="Acme",
        title=title,
        status="ingested",
    )


@pytest.fixture()
def other_tenant(db: Session, settings: Settings) -> sessionmaker[Session]:
    """A second tenant with one tender, written through a session scoped to it."""
    add_tenant(settings, "other")
    factory = make_session_factory(make_engine(settings), "other")
    with factory() as session:
        session.add(_tender("other", "Other's tender"))
        session.commit()
    return factory


def test_a_cross_tenant_read_returns_zero_rows_even_without_a_tenant_filter(
    db: Session, other_tenant: sessionmaker[Session]
) -> None:
    db.add(_tender("ergplan", "Ours"))
    db.commit()
    # No tenant filter at all: what a bug in a service would do.
    titles = sorted(db.scalars(select(Tender.title)))
    assert titles == ["Ours"]
    assert db.execute(text("SELECT count(*) FROM tender")).scalar() == 1
    with other_tenant() as theirs:
        assert sorted(theirs.scalars(select(Tender.title))) == ["Other's tender"]
    # The system scope, used only to resolve an identity, sees across.
    set_tenant(db, SYSTEM_TENANT)
    db.commit()
    assert sorted(db.scalars(select(Tender.title))) == ["Other's tender", "Ours"]


def test_a_write_into_another_tenant_or_the_public_library_is_refused_by_the_database(
    db: Session, other_tenant: sessionmaker[Session]
) -> None:
    for foreign in ("other", "public"):
        db.add(_tender(foreign, f"into {foreign}"))
        with pytest.raises(ProgrammingError, match="row-level security"):
            db.commit()
        db.rollback()
    assert db.execute(text("SELECT count(*) FROM tender")).scalar() == 0


def test_the_public_library_is_readable_but_not_writable_by_a_tenant(
    db: Session, settings: Settings
) -> None:
    public = make_session_factory(make_engine(settings), "public")
    with public() as library:
        library.add(_tender("public", "A public tender"))
        library.commit()
    # The test session reads its own tenant and `public` (conftest).
    assert sorted(db.scalars(select(Tender.title))) == ["A public tender"]
    shown = db.scalars(select(Tender).where(Tender.tenant_id == "public")).one()
    shown.title = "defaced"
    # The update policy hides the row from the writer: no row is matched, nothing changes.
    with pytest.raises(StaleDataError, match="0 were matched"):
        db.commit()
    db.rollback()
    assert (
        db.execute(text("UPDATE tender SET title = 'defaced' WHERE tenant_id = 'public'")).rowcount
        == 0
    )
    db.rollback()
    with public() as library:
        assert library.scalars(select(Tender.title)).one() == "A public tender"


def test_a_session_without_a_tenant_sees_nothing(db: Session, settings: Settings) -> None:
    db.add(_tender("ergplan", "Ours"))
    db.commit()
    blind = make_session_factory(make_engine(settings))
    with blind() as session:
        assert list(session.scalars(select(Tender.title))) == []
        set_tenant(session, "ergplan")
        assert list(session.scalars(select(Tender.title))) == ["Ours"]
