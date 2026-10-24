"""Management command: review links.

  python -m scripts.review_token create --tender <slug or id> --reviewer "Name"
  python -m scripts.review_token create --award <source id, sha256 or id> --reviewer "Name"
  python -m scripts.review_token create-awards --reviewer "Name" [--out <path>]
  python -m scripts.review_token revoke --tender <slug or id> | --award <id>
  python -m scripts.review_token round --tender <slug or id> --from-version N
  python -m scripts.review_token list

`create` prints the link to send to the reviewer (WhatsApp, email). An object (a tender,
or an award since Stage 6) has one live link: creating another stops the earlier one, and
`revoke` stops it without a new one. A link is valid for 30 days. The link of a completed
review stays readable. `create-awards` mints a link for every imported award that has no
live or completed link and writes them to `--out` (a file outside the repository: links are
credentials) or prints them. `round` opens a review round for a reviewed tender that a
later version reached before rounds existed (Stage 4, 2026-10-15): the round goes to the
reviewer who completed the review, scoped to that version, and the link is printed.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import agent.models  # noqa: F401  (registers the agent pass tables on Base.metadata)
from core.config import Settings
from core.db import make_engine, make_session_factory
from tender.models import Award, ReviewToken, Tender
from tender.services.tokens import AWARD, TENDER, TokenService

ACTOR = "review_token"


def review_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/review/{token}"


def _tender(session: Session, settings: Settings, tender_ref: str) -> Tender:
    tender = session.scalar(
        select(Tender).where(
            Tender.tenant_id == settings.tenant_id,
            (Tender.slug == tender_ref) | (Tender.id == tender_ref),
        )
    )
    if tender is None:
        raise SystemExit(f"no tender with slug or id {tender_ref!r}")
    return tender


def _award(session: Session, settings: Settings, award_ref: str) -> Award:
    award = session.scalar(
        select(Award).where(
            Award.tenant_id == settings.tenant_id,
            (Award.source_id == award_ref)
            | (Award.source_sha256 == award_ref)
            | (Award.id == award_ref),
        )
    )
    if award is None:
        raise SystemExit(f"no award with source id, sha256 or id {award_ref!r}")
    return award


def create(settings: Settings, tender_ref: str, reviewer: str) -> str:
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        tender = _tender(session, settings, tender_ref)
        token = TokenService(settings.tenant_id).create(session, tender, reviewer, created_by=ACTOR)
        return review_url(settings.public_base_url, token.token)


def create_award(settings: Settings, award_ref: str, reviewer: str) -> str:
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        award = _award(session, settings, award_ref)
        token = TokenService(settings.tenant_id).create_for(
            session, AWARD, award.id, reviewer, created_by=ACTOR
        )
        return review_url(settings.public_base_url, token.token)


def create_awards(settings: Settings, reviewer: str) -> list[str]:
    """A link for every award without a live or completed link; one line per award:
    source id, name, link."""
    lines: list[str] = []
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        tokens = TokenService(settings.tenant_id)
        now = datetime.now(UTC)
        for award in session.scalars(
            select(Award)
            .where(Award.tenant_id == settings.tenant_id)
            .order_by(Award.procurer, Award.reference, Award.id)
        ):
            standing = session.scalar(
                select(ReviewToken.id)
                .where(
                    ReviewToken.tenant_id == settings.tenant_id,
                    ReviewToken.object_type == AWARD,
                    ReviewToken.object_id == award.id,
                    ReviewToken.revoked_at.is_(None),
                    (ReviewToken.completed_at.is_not(None)) | (ReviewToken.expires_at > now),
                )
                .limit(1)
            )
            if standing is not None:
                continue
            token = tokens.create_for(session, AWARD, award.id, reviewer, created_by=ACTOR)
            lines.append(
                f"{award.source_id}  {award.source_name}  "
                f"{review_url(settings.public_base_url, token.token)}"
            )
    return lines


def open_round(settings: Settings, tender_ref: str, from_version: int) -> str:
    """A round for the reviewer of a completed review, scoped to `from_version` on. Refused
    when the tender has a live link or no completed review (`TokenService.open_round`)."""
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        tender = _tender(session, settings, tender_ref)
        token = TokenService(settings.tenant_id).open_round(
            session, tender, from_version=from_version, created_by=ACTOR
        )
        if token is None:
            raise SystemExit(
                f"no round opened for {tender_ref!r}: it has a live link already, or no "
                "completed review"
            )
        return review_url(settings.public_base_url, token.token)


def revoke(settings: Settings, tender_ref: str) -> int:
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        tender = _tender(session, settings, tender_ref)
        return TokenService(settings.tenant_id).revoke(session, tender, created_by=ACTOR)


def revoke_award(settings: Settings, award_ref: str) -> int:
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        award = _award(session, settings, award_ref)
        return TokenService(settings.tenant_id).revoke_for(
            session, AWARD, award.id, created_by=ACTOR
        )


REPOSITORY = Path(__file__).resolve().parents[1]


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPOSITORY)
    except ValueError:
        return False
    return True


def _state(token: ReviewToken) -> str:
    if token.revoked_at:
        return "revoked"
    if token.completed_at:
        return "completed"
    return f"live until {token.expires_at:%Y-%m-%d}"


def listing(settings: Settings) -> list[str]:
    lines = []
    with make_session_factory(make_engine(settings), settings.tenant_id)() as session:
        rows = session.execute(
            select(ReviewToken, Tender)
            .join(Tender, Tender.id == ReviewToken.tender_id)
            .where(
                ReviewToken.tenant_id == settings.tenant_id,
                ReviewToken.object_type == TENDER,
                Tender.tenant_id == settings.tenant_id,
            )
            .order_by(Tender.slug, ReviewToken.created_at)
        )
        for token, tender in rows:
            scope = (
                f"round {token.round_no} from v{token.from_version}"
                if token.from_version
                else f"round {token.round_no}"
            )
            lines.append(
                f"{tender.slug or tender.id}  {token.reviewer_name}  {scope}  {_state(token)}  "
                f"{review_url(settings.public_base_url, token.token)}"
            )
        awards = session.execute(
            select(ReviewToken, Award)
            .join(Award, Award.id == ReviewToken.object_id)
            .where(
                ReviewToken.tenant_id == settings.tenant_id,
                ReviewToken.object_type == AWARD,
                Award.tenant_id == settings.tenant_id,
            )
            .order_by(Award.procurer, Award.reference, ReviewToken.created_at)
        )
        for token, award in awards:
            lines.append(
                f"award {award.source_id} ({award.source_name})  {token.reviewer_name}  "
                f"{_state(token)}  {review_url(settings.public_base_url, token.token)}"
            )
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="review_token", description=__doc__)
    parser.add_argument("command", choices=("create", "create-awards", "revoke", "round", "list"))
    parser.add_argument("--tender", default="")
    parser.add_argument("--award", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--out", type=Path, help="create-awards: write the links here")
    parser.add_argument("--from-version", type=int, default=0, help="round: the version")
    args = parser.parse_args(argv[1:])
    settings = Settings()
    if args.command == "create":
        if bool(args.tender) == bool(args.award) or not args.reviewer:
            parser.error("create needs --reviewer and one of --tender, --award")
        if args.tender:
            print(create(settings, args.tender, args.reviewer))
        else:
            print(create_award(settings, args.award, args.reviewer))
    elif args.command == "create-awards":
        if not args.reviewer:
            parser.error("create-awards needs --reviewer")
        lines = create_awards(settings, args.reviewer)
        if args.out:
            if _inside_repository(args.out):
                parser.error("--out must be a path outside the repository: links are credentials")
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            args.out.chmod(0o600)
            print(f"{len(lines)} link(s) written to {args.out}")
        else:
            print("\n".join(lines))
    elif args.command == "round":
        if not args.tender or args.from_version < 2:
            parser.error("round needs --tender and --from-version (2 or more)")
        print(open_round(settings, args.tender, args.from_version))
    elif args.command == "revoke":
        if bool(args.tender) == bool(args.award):
            parser.error("revoke needs one of --tender, --award")
        count = revoke(settings, args.tender) if args.tender else revoke_award(settings, args.award)
        print(f"{count} link(s) stopped")
    else:
        print("\n".join(listing(settings)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
