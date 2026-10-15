"""Review tokens: the link a reviewer opens, and the only identity of phase 1.

A token belongs to one tender and one reviewer name. It is live until it expires (30
days), is replaced by a newer token for the same tender, or the review is completed.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
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
        self,
        session: Session,
        tender: Tender,
        reviewer_name: str,
        *,
        created_by: str,
        from_version: int | None = None,
    ) -> ReviewToken:
        """A new token for the tender. Any earlier live token of the tender is revoked:
        one reviewer per tender. The link of a completed review stays readable. With
        `from_version`, the token opens a round scoped to the fields that version and the
        ones after it touched (`open_round` is the usual way)."""
        name = reviewer_name.strip()
        if not name:
            raise ValueError("a reviewer name is required")
        now = datetime.now(UTC)
        self._revoke(session, tender, created_by, {"replaced_for": name})
        rounds = session.scalar(
            select(func.max(ReviewToken.round_no)).where(
                ReviewToken.tenant_id == self._tenant_id, ReviewToken.tender_id == tender.id
            )
        )
        row = ReviewToken(
            tenant_id=self._tenant_id,
            created_by=created_by,
            # 24 random bytes are 32 url-safe characters.
            token=secrets.token_urlsafe(24),
            tender_id=tender.id,
            reviewer_name=name,
            expires_at=now + timedelta(days=TOKEN_DAYS),
            round_no=(rounds or 0) + 1,
            from_version=from_version,
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
            after={
                "tender_id": tender.id,
                "reviewer_name": name,
                "round_no": row.round_no,
                "from_version": from_version,
            },
        )
        session.commit()
        return row

    def open_round(
        self, session: Session, tender: Tender, *, from_version: int, created_by: str
    ) -> ReviewToken | None:
        """A review round for a reviewed tender that a later version reached: a token for
        the reviewer who completed the last review, scoped to that version. None when the
        tender has a live link already (the round, or a review still open) or has never
        been reviewed (its first link is the whole tender)."""
        live = session.scalar(
            select(ReviewToken.id)
            .where(
                ReviewToken.tenant_id == self._tenant_id,
                ReviewToken.tender_id == tender.id,
                ReviewToken.revoked_at.is_(None),
                ReviewToken.completed_at.is_(None),
                ReviewToken.expires_at > datetime.now(UTC),
            )
            .limit(1)
        )
        if live is not None:
            return None
        last = session.scalar(
            select(ReviewToken)
            .where(
                ReviewToken.tenant_id == self._tenant_id,
                ReviewToken.tender_id == tender.id,
                ReviewToken.completed_at.is_not(None),
            )
            .order_by(ReviewToken.completed_at.desc())
            .limit(1)
        )
        if last is None:
            return None
        return self.create(
            session, tender, last.reviewer_name, created_by=created_by, from_version=from_version
        )

    def revoke(self, session: Session, tender: Tender, *, created_by: str) -> int:
        """Stop the tender's live links (a link that went to the wrong person). Returns
        how many were stopped. A completed review keeps its read-only link."""
        count = self._revoke(session, tender, created_by, {"reason": "revoked"})
        session.commit()
        return count

    def _revoke(self, session: Session, tender: Tender, actor: str, why: dict[str, str]) -> int:
        now = datetime.now(UTC)
        rows = list(
            session.scalars(
                select(ReviewToken).where(
                    ReviewToken.tenant_id == self._tenant_id,
                    ReviewToken.tender_id == tender.id,
                    ReviewToken.revoked_at.is_(None),
                    ReviewToken.completed_at.is_(None),
                )
            )
        )
        for row in rows:
            row.revoked_at = now
            audit.record(
                session,
                tenant_id=self._tenant_id,
                actor=actor,
                action="revoke",
                table_name="review_token",
                row_id=row.id,
                after=why,
            )
        return len(rows)

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
