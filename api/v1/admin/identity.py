"""An admin's routes (Stage 5C): the tenant's users, the intelligence API's keys, review
links for one-off reviewers, and the usage the keys have made. Behind the admin policy of
api.middleware.auth: an admin's session, or the admin token for automation.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from api.deps import ActorDep, SessionDep, SettingsDep, TenantDep, TendersDep, TokensDep
from api.middleware.errors import AppError
from api.v1.schemas.identity import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ReviewTokenMint,
    UsageByKey,
    UsageByTool,
    UsageOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from api.v1.schemas.tenders import ReviewTokenOut
from api.v1.tenders.review import review_url
from core.models import ApiKey, AppUser, UsageRecord
from core.services import audit
from core.services.identity import IdentityError, IdentityService
from tender.models import Tender

router = APIRouter(prefix="/admin", tags=["admin"])


def _identity(request: Request) -> IdentityService:
    identity: IdentityService = request.app.state.identity
    return identity


@router.get("/users", response_model=list[UserOut])
def list_users(session: SessionDep, tenant_id: TenantDep) -> list[AppUser]:
    """The tenant's users, newest last."""
    return list(
        session.scalars(
            select(AppUser).where(AppUser.tenant_id == tenant_id).order_by(AppUser.created_at)
        )
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> AppUser:
    """Invite a user: the row exists with its role before their first sign-in, which then
    attaches the identity provider's subject."""
    email = body.email.strip().lower()
    if session.scalar(
        select(AppUser.id).where(AppUser.tenant_id == tenant_id, AppUser.email == email)
    ):
        raise AppError("conflict", f"{email} already has an account")
    user = AppUser(
        tenant_id=tenant_id,
        created_by=actor,
        email=email,
        display_name=body.display_name.strip(),
        role=body.role,
        status="active",
    )
    session.add(user)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="insert",
        table_name="app_user",
        row_id=user.id,
        after={"email": email, "role": body.role, "invited": True},
    )
    session.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: str, body: UserPatch, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> AppUser:
    """Change a user's role or disable them. Nothing else about a user is edited here."""
    user = session.scalar(
        select(AppUser).where(AppUser.id == user_id, AppUser.tenant_id == tenant_id)
    )
    if user is None:
        raise AppError("not_found", f"user {user_id} does not exist")
    before = {"role": user.role, "status": user.status}
    if body.role is not None:
        user.role = body.role
    if body.status is not None:
        user.status = body.status
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="update",
        table_name="app_user",
        row_id=user.id,
        before=before,
        after={"role": user.role, "status": user.status},
    )
    session.commit()
    return user


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(session: SessionDep, tenant_id: TenantDep) -> list[ApiKey]:
    """The tenant's keys, revoked ones included (never the secret)."""
    return list(
        session.scalars(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at)
        )
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    body: ApiKeyCreate, request: Request, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> ApiKeyCreated:
    """A new key of the intelligence API. The secret is in this response and nowhere else."""
    principal = getattr(request.state, "principal", None)
    try:
        key, secret = _identity(request).create_api_key(
            session,
            tenant_id,
            body.name,
            body.scopes,
            created_by=actor,
            user_id=getattr(principal, "user_id", None),
            rate_limit_per_min=body.rate_limit_per_min,
            daily_cap=body.daily_cap,
        )
    except IdentityError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return ApiKeyCreated(key=ApiKeyOut.model_validate(key), secret=secret)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
def revoke_api_key(
    key_id: str, request: Request, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> ApiKey:
    """Revoke a key. It stays listed; calls with it are refused from now on."""
    try:
        _identity(request).revoke_api_key(session, tenant_id, key_id, by=actor)
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return session.scalars(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    ).one()


@router.post("/review-tokens", response_model=ReviewTokenOut, status_code=201)
def mint_review_token(
    body: ReviewTokenMint,
    session: SessionDep,
    tenant_id: TenantDep,
    tenders: TendersDep,
    tokens: TokensDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> ReviewTokenOut:
    """A review link for a one-off external reviewer, minted by an admin: the same link
    the management command makes, for one tender and one name, 30 days."""
    tender = session.scalar(
        select(Tender).where(
            Tender.tenant_id == tenant_id, (Tender.slug == body.tender) | (Tender.id == body.tender)
        )
    )
    if tender is None:
        raise AppError("not_found", f"tender {body.tender} does not exist")
    try:
        token = tokens.create(session, tender, body.reviewer_name, created_by=actor)
    except ValueError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return ReviewTokenOut(
        url=review_url(settings.public_base_url, token.token),
        token=token.token,
        tender_id=token.tender_id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
    )


@router.get("/usage", response_model=UsageOut)
def usage(session: SessionDep, tenant_id: TenantDep, days: int = 30) -> UsageOut:
    """Metered calls of the tenant over the last `days`: by tool, and by API key."""
    days = max(1, min(days, 365))
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(
            UsageRecord.tool,
            func.count(),
            func.sum(func.cast(UsageRecord.status >= 400, type_=func.count().type)),
        )
        .where(UsageRecord.tenant_id == tenant_id, UsageRecord.created_at >= since)
        .group_by(UsageRecord.tool)
        .order_by(func.count().desc())
    ).all()
    by_tool = [
        UsageByTool(tool=tool, calls=int(calls), errors=int(errors or 0))
        for tool, calls, errors in rows
    ]
    keyed = session.execute(
        select(UsageRecord.api_key_id, ApiKey.name, func.count())
        .outerjoin(ApiKey, ApiKey.id == UsageRecord.api_key_id)
        .where(UsageRecord.tenant_id == tenant_id, UsageRecord.created_at >= since)
        .group_by(UsageRecord.api_key_id, ApiKey.name)
        .order_by(func.count().desc())
    ).all()
    by_key = [
        UsageByKey(api_key_id=key_id, name=name, calls=int(calls)) for key_id, name, calls in keyed
    ]
    return UsageOut(days=days, calls=sum(t.calls for t in by_tool), by_tool=by_tool, by_key=by_key)
