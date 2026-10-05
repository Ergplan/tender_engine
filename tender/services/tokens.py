"""Review tokens: the link a reviewer opens, and the only identity of phase 1.

A token belongs to one tender and one reviewer name. It is live until it expires (30
days), is replaced by a newer token for the same tender, or the review is completed.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.services import audit
from tender.models import ReviewToken, Tender

TOKEN_DAYS = 30


class TokenError(LookupError):
    """The token cannot be used. `reason` is unknown, revoked or expired."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"review token is {reason}")
        self.reason = reason


class TokenService:
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def create(
        self, session: Session, tender: Tender, reviewer_name: str, *, created_by: str
    ) -> ReviewToken:
        """A new token for the tender. Any earlier live token of the tender is revoked:
        one reviewer per tender."""
        name = reviewer_name.strip()
        if not name:
            raise ValueError("a reviewer name is required")
        now = datetime.now(UTC)
        for earlier in session.scalars(
            select(ReviewToken).where(
                ReviewToken.tenant_id == self._tenant_id,
                ReviewToken.tender_id == tender.id,
                ReviewToken.revoked_at.is_(None),
            )
        ):
            earlier.revoked_at = now
            audit.record(
                session,
                tenant_id=self._tenant_id,
                actor=created_by,
                action="revoke",
                table_name="review_token",
                row_id=earlier.id,
                after={"replaced_for": name},
            )
        row = ReviewToken(
            tenant_id=self._tenant_id,
            created_by=created_by,
            # 24 random bytes are 32 url-safe characters.
            token=secrets.token_urlsafe(24),
            tender_id=tender.id,
            reviewer_name=name,
            expires_at=now + timedelta(days=TOKEN_DAYS),
        )
        session.add(row)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="insert",
            table_name="review_token",
            row_id=row.id,
            after={"tender_id": tender.id, "reviewer_name": name},
        )
        session.commit()
        return row

    def resolve(self, session: Session, token: str) -> ReviewToken:
        """The token's row, or TokenError. A completed token resolves: its review can
        still be read, and the caller refuses writes."""
        row = session.scalar(
            select(ReviewToken).where(
                ReviewToken.tenant_id == self._tenant_id, ReviewToken.token == token
            )
        )
        if row is None:
            raise TokenError("unknown")
        if row.revoked_at is not None:
            raise TokenError("revoked")
        if row.expires_at <= datetime.now(UTC) and row.completed_at is None:
            raise TokenError("expired")
        return row
