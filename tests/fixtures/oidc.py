"""A sign-in provider for the tests: the claims a code stands for, no network."""

from typing import Any
from urllib.parse import urlencode


class FakeOidc:
    def __init__(self, accounts: dict[str, dict[str, Any]] | None = None) -> None:
        # code -> claims (sub, email, email_verified, name, hd)
        self.accounts: dict[str, dict[str, Any]] = dict(accounts or {})
        self.exchanged: list[tuple[str, str, str]] = []

    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str:
        return "https://idp.test/authorize?" + urlencode(
            {"state": state, "nonce": nonce, "redirect_uri": redirect_uri}
        )

    def exchange(self, code: str, redirect_uri: str, nonce: str) -> dict[str, Any]:
        from core.services.oidc import OidcError

        self.exchanged.append((code, redirect_uri, nonce))
        if code not in self.accounts:
            raise OidcError("the sign-in could not be completed; try again")
        return {**self.accounts[code], "nonce": nonce}


def account(
    email: str,
    *,
    sub: str | None = None,
    name: str | None = None,
    verified: bool = True,
) -> dict[str, Any]:
    return {
        "sub": sub or f"sub-{email}",
        "email": email,
        "email_verified": verified,
        "name": name or email.split("@")[0].title(),
        "hd": email.rpartition("@")[2],
    }
