"""Identity (Stage 5C): users, their login sessions, API keys and the usage each call records.

A principal is a user or an API key: it carries its own tenant and the tenants it may
read (its own, and `public` from Stage 5D). Roles: reviewer (reads, decides on fields),
approver (reviewer plus completing a review and gold), admin (everything in the tenant:
users, keys, review links), api_client (the intelligence API: reads, the model with the
`model` scope; never a write to a field). Review tokens stay for one-off external
reviewers and are minted by an admin.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

ROLES = ("reviewer", "approver", "admin", "api_client")
USER_STATUSES = ("active", "disabled")
# read/model: the intelligence API. public:read / own:read: an MCP access token issued by
# the library's OAuth server (Stage 5D) for a signed-in user.
API_KEY_SCOPES = ("read", "model", "public:read", "own:read")
# What a tenant is: an enterprise customer, a free account (reads public only), or the
# reserved public library tenant itself (Stage 5D).
TENANT_PLANS = ("enterprise", "free", "public")
USAGE_TIERS = ("internal", "enterprise", "free", "api")


class AppUser(IdMixin, TenantAuditMixin, Base):
    """A person who signs in (OIDC). One row per tenant and email."""

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # The identity provider's stable subject for the account (Google `sub`).
    oidc_subject: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginSession(IdMixin, TenantAuditMixin, Base):
    """A signed-in browser: the cookie holds a random token, the row its hash."""

    __tablename__ = "login_session"

    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(IdMixin, TenantAuditMixin, Base):
    """A key of the intelligence API (Product B). Shown once at creation; the row keeps the
    hash and the prefix the holder recognises it by."""

    __tablename__ = "api_key"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # The user who made it; null for a key made by a management command.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageRecord(IdMixin, TenantAuditMixin, Base):
    """One row per metered call. `tenant_id` is the calling (actor) tenant, never the
    resource's: free-tier limits are enforced on the caller. `resource_tenant_id` says
    whose data was read."""

    __tablename__ = "usage_record"

    resource_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_key.id"), nullable=True, index=True
    )
    # The route or MCP tool called, and the tier it was billed under.
    tool: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
