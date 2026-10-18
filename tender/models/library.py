"""The public library tier and what sits beside it (Stage 5D): a user's model assumptions,
a watchlist, correction cases on a published tender, publication holds (takedown), and the
OAuth clients and codes the MCP server issues scoped access through.

Every table carries `tenant_id` and is under row-level security (migration 0019). The
tenant of a correction case and of a publication hold is the tender's tenant (the public
library for library tenders): the service writes them in the system scope on the claimant's
behalf, since no end-user principal may write to `public`; the claimant is recorded on the
row. The tenant of an assumption, a watchlist entry, an OAuth client and a code is the
calling tenant."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

MODEL_TYPES = ("power_project_finance",)
CORRECTION_STATUSES = ("open", "accepted", "rejected")
HOLD_KINDS = ("takedown", "correction")


class ModelAssumption(IdMixin, TenantAuditMixin, Base):
    """A user's assumptions for one financial model of one tender. Never a canonical fact;
    never shown in the published view."""

    __tablename__ = "model_assumption"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "tender_id", "model_type", name="uq_model_assumption_owner"
        ),
    )

    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    tender_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # The tender's own tenant (the public library, or the caller's), for the read.
    tender_tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class WatchlistEntry(IdMixin, TenantAuditMixin, Base):
    """A tender a user follows; the digest reads these."""

    __tablename__ = "watchlist_entry"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "tender_id", name="uq_watchlist_owner_tender"),
    )

    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    tender_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tender_tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)


class CorrectionCase(IdMixin, TenantAuditMixin, Base):
    """A claim that a published field is wrong. It never changes a value: it queues the
    field for re-review; a reviewer's new approval, through the normal pipeline, is the
    only thing that can."""

    __tablename__ = "correction_case"

    tender_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    claimed_error: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    claimant_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimant_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimant_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicationHold(IdMixin, TenantAuditMixin, Base):
    """A takedown (an agency's or rights-holder's request) or a correction hold: while it
    stands, the tender's publication is suspended whatever its review state."""

    __tablename__ = "publication_hold"

    tender_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    # When the request arrived, as the operator states it (the master prompt's "within
    # one business day" is measured from here); the row's created_at is when the hold
    # was placed.
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class OAuthClient(IdMixin, TenantAuditMixin, Base):
    """An MCP client registered with the library's authorization server (dynamic
    registration, RFC 7591). Public clients (PKCE), no secret."""

    __tablename__ = "oauth_client"

    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    redirect_uris: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthCode(IdMixin, TenantAuditMixin, Base):
    """An authorization code issued to a signed-in user for a client, exchanged once for an
    access token (an `api_key` row scoped to `public:read`, tier free)."""

    __tablename__ = "oauth_code"

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    code_challenge: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
