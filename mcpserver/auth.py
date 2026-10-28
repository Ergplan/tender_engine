"""Who calls the MCP server, and the OAuth authorization server behind it.

A bearer token on `/mcp` is one of our API keys (`tie_live_…`), minted either by an admin
in the enterprise product or by this authorization server for an MCP client on a signed-in
user's behalf. The SDK drives the OAuth routes (`/authorize`, `/token`, `/register`,
`/.well-known/oauth-authorization-server`); `LibraryOAuthProvider` keeps the clients and
codes in `oauth_client` and `oauth_code` and issues access tokens as `api_key` rows scoped
to `public:read` (and `own:read` for a user of an enterprise tenant). Codes are PKCE
(S256, checked by the SDK), single-use and expire in ten minutes. No refresh tokens are
issued: a client signs in again when its token is revoked. Consent is a page of the API
(`/api/v1/oauth/consent`) that needs the user's session; `authorize` sends the browser
there with the request signed, so nothing in it can be changed on the way.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import anyio
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    TokenVerifier,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import SYSTEM_TENANT, set_tenant
from core.models import AppUser, Tenant
from core.services import audit
from core.services.identity import IdentityService, Principal
from tender.models import OAuthClient, OAuthCode

CODE_TTL = timedelta(minutes=10)
SCOPES = ("public:read", "own:read", "own:write")
CLIENT_TENANT = "public"
ACTOR = "oauth"


class LibraryAccessToken(AccessToken):
    """The SDK's access token with the principal the tools act as."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    principal: Principal


class LibraryAuthorizationCode(AuthorizationCode):
    row_id: str = ""
    tenant_id: str = ""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _system(session: Session) -> None:
    set_tenant(session, SYSTEM_TENANT)


def sign_request(secret: str, payload: dict[str, Any]) -> str:
    """The authorization request as one signed token for the consent page."""
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_request(secret: str, token: str) -> dict[str, Any] | None:
    body, _, sig = token.rpartition(".")
    if not body or not hmac.compare_digest(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest(), sig
    ):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


def principal_token(principal: Principal, raw: str) -> LibraryAccessToken:
    # A token scoped to the library alone reads the library alone.
    if set(principal.scopes) - {"read"} == {"public:read"}:
        principal = replace(principal, read_tenants=("public",))
    return LibraryAccessToken(
        token=raw,
        client_id=principal.name or "api-key",
        scopes=list(principal.scopes) or ["own:read"],
        expires_at=None,
        subject=principal.user_id,
        principal=principal,
    )


class LibraryTokenVerifier(TokenVerifier):
    """Resolves a bearer token to our principal (API keys and OAuth access tokens alike)."""

    def __init__(self, session_factory: sessionmaker[Session], identity: IdentityService) -> None:
        self._session_factory = session_factory
        self._identity = identity

    def _verify(self, token: str) -> LibraryAccessToken | None:
        with self._session_factory() as session:
            principal = self._identity.resolve_api_key(session, token)
        return principal_token(principal, token) if principal else None

    async def verify_token(self, token: str) -> AccessToken | None:
        return await anyio.to_thread.run_sync(self._verify, token)


class LibraryOAuthProvider(
    OAuthAuthorizationServerProvider[LibraryAuthorizationCode, RefreshToken, LibraryAccessToken]
):
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        identity: IdentityService,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._identity = identity
        self._verifier = LibraryTokenVerifier(session_factory, identity)

    # -- clients -------------------------------------------------------------------------

    def _get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._session_factory() as session:
            _system(session)
            # Clients are registered in the library's tenant.
            row = session.scalar(
                select(OAuthClient).where(
                    OAuthClient.tenant_id == CLIENT_TENANT,
                    OAuthClient.client_id == client_id,
                    OAuthClient.revoked_at.is_(None),
                )
            )
            if row is None:
                return None
            return OAuthClientInformationFull(
                client_id=row.client_id,
                client_name=row.client_name,
                redirect_uris=list(row.redirect_uris),
                scope=" ".join(row.scopes) if row.scopes else None,
                token_endpoint_auth_method="none",
                grant_types=["authorization_code"],
                response_types=["code"],
            )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await anyio.to_thread.run_sync(self._get_client, client_id)

    def _register_client(self, info: OAuthClientInformationFull) -> None:
        with self._session_factory() as session:
            _system(session)
            row = OAuthClient(
                tenant_id=CLIENT_TENANT,
                created_by=ACTOR,
                client_id=info.client_id,
                client_name=info.client_name or info.client_id,
                redirect_uris=[str(u) for u in info.redirect_uris or []],
                scopes=[s for s in (info.scope or "").split() if s in SCOPES] or ["public:read"],
            )
            session.add(row)
            session.flush()
            audit.record(
                session,
                tenant_id=CLIENT_TENANT,
                actor=ACTOR,
                action="insert",
                table_name="oauth_client",
                row_id=row.id,
                after={"client_id": row.client_id, "client_name": row.client_name},
            )
            session.commit()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await anyio.to_thread.run_sync(self._register_client, client_info)

    # -- authorization -----------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Send the browser to the consent page with the request signed."""
        if not self._settings.session_secret:
            raise AuthorizeError(
                error="server_error", error_description="sign-in is not configured on this server"
            )
        payload = {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "redirect_uri": str(params.redirect_uri),
            "explicit": params.redirect_uri_provided_explicitly,
            "scopes": [s for s in (params.scopes or []) if s in SCOPES] or ["public:read"],
            "state": params.state,
            "code_challenge": params.code_challenge,
            "resource": params.resource,
            "exp": time.time() + CODE_TTL.total_seconds(),
        }
        token = sign_request(self._settings.session_secret, payload)
        base = self._settings.public_base_url.rstrip("/")
        return f"{base}/api/v1/oauth/consent?{urlencode({'request': token})}"

    def issue_code(self, session: Session, request: dict[str, Any], user: AppUser) -> str:
        """The consent page's approval: a code for the user, bound to the request."""
        raw = secrets.token_urlsafe(32)
        row = OAuthCode(
            tenant_id=user.tenant_id,
            created_by=user.email,
            code_hash=_hash(raw),
            client_id=request["client_id"],
            user_id=user.id,
            redirect_uri=request["redirect_uri"],
            scopes=request["scopes"],
            code_challenge=request["code_challenge"],
            expires_at=datetime.now(UTC) + CODE_TTL,
        )
        session.add(row)
        session.flush()
        audit.record(
            session,
            tenant_id=user.tenant_id,
            actor=user.email,
            action="insert",
            table_name="oauth_code",
            row_id=row.id,
            after={"client_id": row.client_id, "scopes": row.scopes},
        )
        session.commit()
        return raw

    def _load_code(self, client_id: str, code: str) -> LibraryAuthorizationCode | None:
        with self._session_factory() as session:
            # The identity step: a code names its tenant only once found, so this one
            # look-up is by hash in the system scope.
            _system(session)
            row = session.scalar(select(OAuthCode).where(OAuthCode.code_hash == _hash(code)))
            if row is None or row.client_id != client_id or row.used_at is not None:
                return None
            if row.expires_at <= datetime.now(UTC):
                return None
            return LibraryAuthorizationCode(
                code=code,
                scopes=list(row.scopes),
                expires_at=row.expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=row.redirect_uri,
                redirect_uri_provided_explicitly=True,
                subject=row.user_id,
                row_id=row.id,
                tenant_id=row.tenant_id,
            )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> LibraryAuthorizationCode | None:
        return await anyio.to_thread.run_sync(self._load_code, client.client_id, authorization_code)

    def _exchange(self, code: LibraryAuthorizationCode) -> OAuthToken:
        with self._session_factory() as session:
            _system(session)
            # Locked for the exchange: a second exchange of the same code waits here and
            # then finds it used.
            row = session.scalar(
                select(OAuthCode)
                .where(OAuthCode.id == code.row_id, OAuthCode.tenant_id == code.tenant_id)
                .with_for_update()
            )
            if row is None or row.used_at is not None:
                raise TokenError(
                    error="invalid_grant", error_description="the code was used or is unknown"
                )
            user = session.scalar(
                select(AppUser).where(AppUser.id == row.user_id, AppUser.tenant_id == row.tenant_id)
            )
            if user is None or user.status != "active":
                raise TokenError(
                    error="invalid_grant", error_description="the user behind the code is gone"
                )
            plan = session.scalar(select(Tenant.plan).where(Tenant.tenant_id == user.tenant_id))
            scopes = ["public:read"]
            if plan == "enterprise" and "own:read" in row.scopes:
                scopes.append("own:read")
            # Block 6 c: the write tools, when the client asked and the user consented.
            if plan == "enterprise" and "own:write" in row.scopes:
                scopes.append("own:write")
            row.used_at = datetime.now(UTC)
            session.flush()
            # The token itself: a key of the user's tenant, written in that tenant's scope,
            # in the same transaction as the code's use.
            set_tenant(session, user.tenant_id)
            key, raw = self._identity.create_api_key(
                session,
                user.tenant_id,
                f"mcp:{code.client_id}",
                scopes,
                created_by=user.email,
                user_id=user.id,
                rate_limit_per_min=(
                    self._settings.free_rate_limit_per_min if plan != "enterprise" else None
                ),
                daily_cap=self._settings.free_daily_cap if plan != "enterprise" else None,
            )
            audit.record(
                session,
                tenant_id=user.tenant_id,
                actor=user.email,
                action="status_change",
                table_name="oauth_code",
                row_id=row.id,
                before={"used_at": None},
                after={"used_at": row.used_at.isoformat(), "api_key_id": key.id},
            )
            session.commit()
        return OAuthToken(
            access_token=raw, token_type="Bearer", expires_in=None, scope=" ".join(scopes)
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: LibraryAuthorizationCode
    ) -> OAuthToken:
        return await anyio.to_thread.run_sync(self._exchange, authorization_code)

    # -- tokens ------------------------------------------------------------------------

    async def load_access_token(self, token: str) -> LibraryAccessToken | None:
        return await anyio.to_thread.run_sync(self._verifier._verify, token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None  # no refresh tokens are issued

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise TokenError(
            error="unsupported_grant_type", error_description="refresh tokens are not issued"
        )

    def _revoke(self, token: str) -> None:
        with self._session_factory() as session:
            principal = self._identity.resolve_api_key(session, token)
            if principal and principal.api_key_id:
                set_tenant(session, principal.tenant_id)
                self._identity.revoke_api_key(
                    session, principal.tenant_id, principal.api_key_id, by=principal.name or ACTOR
                )

    async def revoke_token(self, token: LibraryAccessToken | RefreshToken) -> None:
        await anyio.to_thread.run_sync(self._revoke, token.token)

    @property
    def verifier(self) -> LibraryTokenVerifier:
        return self._verifier
