"""OpenID Connect sign-in with Google, with no auth library in between.

`GoogleOidc` reads the provider's discovery document, sends the browser to the
authorisation endpoint, exchanges the code it comes back with for an ID token at the token
endpoint, and verifies that token against the provider's published keys (PyJWT): issuer,
audience, signature, expiry and the nonce the sign-in started with. The claims it returns
are what `IdentityService.login_from_claims` acts on. Tests hand the API a fake provider.
"""

import logging
import threading
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx2
import jwt

from core.config import Settings

log = logging.getLogger("oidc")
SCOPES = "openid email profile"


class OidcError(ValueError):
    """The provider did not sign the user in. The message is safe to show."""


class OidcProvider(Protocol):
    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str: ...

    def exchange(self, code: str, redirect_uri: str, nonce: str) -> dict[str, Any]: ...


class GoogleOidc:
    def __init__(self, settings: Settings, http: httpx2.Client | None = None) -> None:
        self._settings = settings
        self._http = http or httpx2.Client(timeout=20.0)
        self._discovery: dict[str, Any] | None = None
        self._jwks: jwt.PyJWKClient | None = None
        self._lock = threading.Lock()

    def _config(self) -> dict[str, Any]:
        with self._lock:
            if self._discovery is None:
                url = self._settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
                response = self._http.get(url)
                response.raise_for_status()
                self._discovery = dict(response.json())
            return self._discovery

    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str:
        if not self._settings.oidc_client_id:
            raise OidcError("sign-in is not configured (OIDC_CLIENT_ID)")
        query = urlencode(
            {
                "client_id": self._settings.oidc_client_id,
                "response_type": "code",
                "scope": SCOPES,
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "prompt": "select_account",
            }
        )
        return f"{self._config()['authorization_endpoint']}?{query}"

    def exchange(self, code: str, redirect_uri: str, nonce: str) -> dict[str, Any]:
        config = self._config()
        response = self._http.post(
            config["token_endpoint"],
            data={
                "code": code,
                "client_id": self._settings.oidc_client_id,
                "client_secret": self._settings.oidc_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            log.warning("token exchange answered %s", response.status_code)
            raise OidcError("the sign-in could not be completed; try again")
        id_token = response.json().get("id_token")
        if not id_token:
            raise OidcError("the provider returned no identity")
        with self._lock:
            if self._jwks is None:
                self._jwks = jwt.PyJWKClient(config["jwks_uri"])
            jwks = self._jwks
        try:
            key = jwks.get_signing_key_from_jwt(id_token)
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key.key,
                algorithms=["RS256"],
                audience=self._settings.oidc_client_id,
                issuer=[config["issuer"], "accounts.google.com", "https://accounts.google.com"],
            )
        except jwt.PyJWTError as exc:
            log.warning("id token rejected: %s", exc)
            raise OidcError("the identity the provider returned could not be verified") from exc
        if claims.get("nonce") != nonce:
            raise OidcError("the sign-in did not match the one that was started")
        return claims
