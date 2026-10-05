"""Management command: review links.

  python -m scripts.review_token create --tender <slug or id> --reviewer "Name"
  python -m scripts.review_token list

`create` prints the link to send to the reviewer (WhatsApp, email). A tender has one live
link: creating another stops the earlier one. A link is valid for 30 days.
"""

import argparse
import sys

from sqlalchemy import select

from core.config import Settings
from core.db import make_engine, make_session_factory
from tender.models import ReviewToken, Tender
from tender.services.tokens import TokenService

ACTOR = "review_token"


def review_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/review/{token}"


def create(settings: Settings, tender_ref: str, reviewer: str) -> str:
    with make_session_factory(make_engine(settings))() as session:
        tender = session.scalar(
            select(Tender).where(
                Tender.tenant_id == settings.tenant_id,
                (Tender.slug == tender_ref) | (Tender.id == tender_ref),
            )
        )
        if tender is None:
            raise SystemExit(f"no tender with slug or id {tender_ref!r}")
        token = TokenService(settings.tenant_id).create(session, tender, reviewer, created_by=ACTOR)
        return review_url(settings.public_base_url, token.token)


def listing(settings: Settings) -> list[str]:
    lines = []
    with make_session_factory(make_engine(settings))() as session:
        rows = session.execute(
            select(ReviewToken, Tender)
            .join(Tender, Tender.id == ReviewToken.tender_id)
            .where(ReviewToken.tenant_id == settings.tenant_id)
            .order_by(Tender.slug, ReviewToken.created_at)
        )
        for token, tender in rows:
            state = (
                "revoked"
                if token.revoked_at
                else "completed"
                if token.completed_at
                else f"live until {token.expires_at:%Y-%m-%d}"
            )
            lines.append(
                f"{tender.slug or tender.id}  {token.reviewer_name}  {state}  "
                f"{review_url(settings.public_base_url, token.token)}"
            )
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="review_token", description=__doc__)
    parser.add_argument("command", choices=("create", "list"))
    parser.add_argument("--tender", default="")
    parser.add_argument("--reviewer", default="")
    args = parser.parse_args(argv[1:])
    settings = Settings()
    if args.command == "create":
        if not args.tender or not args.reviewer:
            parser.error("create needs --tender and --reviewer")
        print(create(settings, args.tender, args.reviewer))
    else:
        print("\n".join(listing(settings)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
