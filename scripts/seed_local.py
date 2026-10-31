"""Seed the stack on a developer's machine (`make local`): an admin who signs in with a
username and password, and, with --demo, one synthetic solar tender (an RfS and an
amendment, read by a scripted model, so no Anthropic key and no spend) with a review link.

    docker compose ... run --rm api python -m scripts.seed_local [--demo]

Safe to run again: an existing user keeps its password, and the demo tender is made once.
Refuses to run unless PUBLIC_BASE_URL points at localhost, so it can never seed the VM.
"""

import argparse
import sys
from urllib.parse import urlparse

from sqlalchemy import select

from core.config import Settings
from core.db import make_engine, make_session_factory, set_tenant
from core.models.identity import AppUser
from core.services.identity import IdentityService
from tender.models import ReviewToken, Tender

LOCAL_USERNAME = "admin"
# Local only: the stack listens on 127.0.0.1 (infra/local/compose.yml).
LOCAL_PASSWORD = "admin-local-dev"
DEMO_REF = "ACME/RE/2026/007"
ACTOR = "seed_local"


def is_local(settings: Settings) -> bool:
    return urlparse(settings.public_base_url).hostname in {"localhost", "127.0.0.1"}


def ensure_admin(settings: Settings) -> bool:
    """Create the local admin when missing. True when it was created."""
    factory = make_session_factory(make_engine(settings), settings.tenant_id)
    with factory() as session:
        set_tenant(session, settings.tenant_id)
        exists = session.scalar(
            select(AppUser.id).where(
                AppUser.tenant_id == settings.tenant_id, AppUser.email == LOCAL_USERNAME
            )
        )
        if exists:
            return False
        IdentityService(settings).set_password(
            session, LOCAL_USERNAME, LOCAL_PASSWORD, role="admin", created_by=ACTOR
        )
    return True


def ensure_demo(settings: Settings) -> str | None:
    """Seed the synthetic tender once. The token of its review link, or None if it existed."""
    # The demo reuses the browser tests' seed: the real job chain with a scripted model.
    from tests.e2e.seed_review import REVIEW_TOKEN, seed

    factory = make_session_factory(make_engine(settings), settings.tenant_id)
    with factory() as session:
        set_tenant(session, settings.tenant_id)
        found = session.scalar(
            select(Tender.id).where(
                Tender.tenant_id == settings.tenant_id, Tender.external_ref == DEMO_REF
            )
        )
        if found:
            return None
    seed(settings)
    with factory() as session:
        set_tenant(session, settings.tenant_id)
        token = session.scalar(
            select(ReviewToken.token).where(
                ReviewToken.tenant_id == settings.tenant_id, ReviewToken.token == REVIEW_TOKEN
            )
        )
    return token


def run(settings: Settings, demo: bool) -> int:
    if not is_local(settings):
        print(
            f"refused: PUBLIC_BASE_URL is {settings.public_base_url}, not localhost",
            file=sys.stderr,
        )
        return 2
    # Seeding writes as the table owner, as migrations do; the app itself stays tender_app.
    owner = settings.model_copy(
        update={"database_url": settings.migration_database_url or settings.database_url}
    )
    base = settings.public_base_url.rstrip("/")
    if ensure_admin(owner):
        print(f"admin created: sign in at {base}/ as {LOCAL_USERNAME} / {LOCAL_PASSWORD}")
    else:
        print(f"admin exists: sign in at {base}/ as {LOCAL_USERNAME}")
    if demo:
        token = ensure_demo(owner)
        if token:
            print(f"demo tender seeded; review link: {base}/review/{token}")
        else:
            print("demo tender already present")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="also seed the synthetic tender")
    args = parser.parse_args(argv)
    return run(Settings(), args.demo)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
