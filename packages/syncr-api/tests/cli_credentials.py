"""Minting a real CLI credential, for the suites that need one rather than a constructed principal.

A principal built in a test proves that a service authorizes a value; it proves nothing about
whether a request carrying an access token ever reaches that service. So the token here is issued
the way the CLI obtains one: a browser signs in, approves the consent screen for a named scope, and
the single-use code is exchanged at the token endpoint with the PKCE verifier.

One deep function rather than a step per call site. ``test_oauth_flow_integration.py`` keeps its own
granular helpers because it perturbs each step; a caller that only wants a credential should not
have to know that the flow has four of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs, urlsplit

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.credentials import AUTHORIZATION_HEADER
from syncr_api.core.scopes import SCOPE_SEPARATOR, Scope
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.oauth.config import (
    CLI_CLIENT_ID,
    CONSENT_DECISION_PATH,
    GRANT_TYPE_AUTHORIZATION_CODE,
    OAUTH_PREFIX,
    TOKEN_PATH,
    TOKEN_TYPE_BEARER,
)
from syncr_api.oauth.consent import DECISION_APPROVE, DECISION_FIELD
from syncr_api.oauth.pkce import derive_s256_challenge
from tests.live_tenants import PASSWORD

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

BROWSER_ORIGIN: Final = DEV_ALLOWED_ORIGINS[0]

# RFC 7636 appendix B's published verifier, so it is a specification value and not a secret.
VERIFIER: Final = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
CHALLENGE: Final = derive_s256_challenge(VERIFIER)

# The CLI's own loopback listener, on a port nothing here binds: the redirect is read out of the
# `Location` header rather than followed.
LOOPBACK: Final = "http://127.0.0.1:54321/callback"
STATE: Final = "cli-supplied-state"

# What the CLI asks for, and the whole of it. `admin` is deliberately absent.
CLI_SCOPES: Final = (Scope.PLAN_READ, Scope.PLAN_WRITE)


def cli_bearer_header(
    http: TestClient, email: str, *, scopes: tuple[Scope, ...] = CLI_SCOPES
) -> dict[str, str]:
    """An access token for ``email``, issued through the real flow, as a request header."""
    return {
        AUTHORIZATION_HEADER: (
            f"{TOKEN_TYPE_BEARER} {cli_access_token(http, email, scopes=scopes)}"
        )
    }


def cli_access_token(
    http: TestClient, email: str, *, scopes: tuple[Scope, ...] = CLI_SCOPES
) -> str:
    """The access token the flow issues for ``scopes``."""
    session = _signed_in(http, email)
    code = _approved_code(http, session, scope=SCOPE_SEPARATOR.join(one.value for one in scopes))
    issued = http.post(
        f"{OAUTH_PREFIX}{TOKEN_PATH}",
        data={
            "grant_type": GRANT_TYPE_AUTHORIZATION_CODE,
            "client_id": CLI_CLIENT_ID,
            "code": code,
            "code_verifier": VERIFIER,
            "redirect_uri": LOOPBACK,
        },
    )
    assert issued.status_code == 200, issued.text
    token: str = issued.json()["access_token"]
    return token


def _signed_in(http: TestClient, email: str) -> dict[str, str]:
    """The cookie header a signed-in browser sends.

    Set as a header rather than left to the client's jar: the cookie is ``Secure``, and a client
    honoring that attribute will not send it back over ``http://testserver``.
    """
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == 200, response.text
    token = response.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _approved_code(http: TestClient, session: dict[str, str], *, scope: str) -> str:
    """The single-use code the consent redirect delivers to the loopback listener."""
    response = http.post(
        f"{OAUTH_PREFIX}{CONSENT_DECISION_PATH}",
        data={
            "client_id": CLI_CLIENT_ID,
            "redirect_uri": LOOPBACK,
            "response_type": "code",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": STATE,
            DECISION_FIELD: DECISION_APPROVE,
        },
        headers={**session, "Origin": BROWSER_ORIGIN},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    delivered: dict[str, str] = {
        key: value[0]
        for key, value in parse_qs(urlsplit(response.headers["location"]).query).items()
    }
    assert "code" in delivered, delivered
    return delivered["code"]
