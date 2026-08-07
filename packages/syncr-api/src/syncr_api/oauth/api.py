"""The Authorization Server's routes.

Thin, on purpose. Each handler reads a request, calls exactly one collaborator method, and
turns the result into a response. No authorization decision is made here and no row is
touched: those belong to ``service.py`` and ``tokens.py``, and
``tests/test_authorization_boundary.py`` asserts this file cannot reach persistence at all.

Two handlers choose between two response shapes, and that choice is presentation rather than
dispatch: the consent service answers either "here is what is being asked" or "send the
browser back with this error", and which HTTP response carries which is exactly a route's
job.

Discovery and JWKS are built per request from process-wide state rather than captured at
router construction, so a test can build an app with a different key set and read the
document that app publishes.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query
from starlette.responses import HTMLResponse, RedirectResponse, Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.oauth.authorization import AuthorizeParams, RedirectedRejection
from syncr_api.oauth.config import (
    AS_METADATA_PATH,
    AUTHORIZE_PATH,
    CONSENT_DECISION_PATH,
    JWKS_PATH,
    REVOKE_PATH,
    TOKEN_PATH,
)
from syncr_api.oauth.consent import (
    DECISION_APPROVE,
    HTML_MEDIA_TYPE,
    render_consent_screen,
)
from syncr_api.oauth.consent_injection import AuthorizationServiceDep
from syncr_api.oauth.injection import OAuthStateDep, TokenServiceDep
from syncr_api.oauth.metadata import build_metadata
from syncr_api.oauth.schemas import JsonWebKeySet, TokenResponse
from syncr_api.oauth.tokens import TokenRequest

# RFC 6749 section 5.1: a token response must not be cached, by anything, ever. Applied to the
# consent screen and the redirects too, because each one carries either an account's identity
# or a single-use code in a URL.
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

# The browser is sent to the client's loopback listener with a 303, not a 302. The consent
# decision arrives as a POST, and 303 is the status that says "repeat this as a GET": a 302
# leaves the method up to the browser, and a POST to a loopback listener expecting a GET is a
# failure that appears only in a real browser.
SEE_OTHER = HTTPStatus.SEE_OTHER

router = APIRouter()
well_known_router = APIRouter()


@router.get(AUTHORIZE_PATH, summary="Ask the account holder to authorize a client")
async def authorize(
    principal: PrincipalDep,
    service: AuthorizationServiceDep,
    client_id: Annotated[str, Query()] = "",
    redirect_uri: Annotated[str, Query()] = "",
    response_type: Annotated[str, Query()] = "",
    code_challenge: Annotated[str, Query()] = "",
    code_challenge_method: Annotated[str, Query()] = "",
    scope: Annotated[str, Query()] = "",
    state: Annotated[str | None, Query()] = None,
) -> Response:
    """The consent screen, or a redirect carrying the client's rejection.

    Every parameter defaults to empty rather than being required, so a malformed request is
    answered by the protocol's own rules rather than by a 422 that names framework fields: a
    client that omits ``code_challenge`` needs to be told PKCE is required, not that a query
    parameter failed validation.
    """
    described = await service.describe_consent(
        principal,
        AuthorizeParams(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            state=state,
        ),
    )
    if isinstance(described, RedirectedRejection):
        return RedirectResponse(described.url, status_code=SEE_OTHER, headers=NO_STORE)
    return HTMLResponse(
        render_consent_screen(described), media_type=HTML_MEDIA_TYPE, headers=NO_STORE
    )


@router.post(CONSENT_DECISION_PATH, summary="Record the account holder's answer")
async def decide(
    principal: PrincipalDep,
    service: AuthorizationServiceDep,
    decision: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    response_type: Annotated[str, Form()] = "",
    code_challenge: Annotated[str, Form()] = "",
    code_challenge_method: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "",
    state: Annotated[str | None, Form()] = None,
) -> Response:
    """Send the browser to the client's redirect with a code, or with a refusal."""
    outcome = await service.decide(
        principal,
        AuthorizeParams(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            state=state,
        ),
        approved=decision == DECISION_APPROVE,
    )
    return RedirectResponse(outcome.url, status_code=SEE_OTHER, headers=NO_STORE)


@router.post(TOKEN_PATH, summary="Exchange a code, or refresh a token")
async def issue_token(
    service: TokenServiceDep,
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    code: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
) -> Response:
    """The token pair, as RFC 6749 shapes it.

    Form encoded in, JSON out, both because the specification says so. Rendered through an
    explicit response rather than returned as a model, so the no-store headers cannot be
    forgotten on the one response in the api that carries two live credentials.
    """
    issued = await service.exchange(
        TokenRequest(
            grant_type=grant_type,
            client_id=client_id,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            refresh_token=refresh_token,
        )
    )
    return Response(
        content=TokenResponse.of(issued).model_dump_json(),
        media_type="application/json",
        headers=NO_STORE,
    )


@router.post(
    REVOKE_PATH,
    status_code=HTTPStatus.OK,
    summary="Revoke a refresh token and its family",
)
async def revoke(
    service: TokenServiceDep,
    token: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "",
    token_type_hint: Annotated[str | None, Form()] = None,
) -> Response:
    """Revoke server-side, and answer the same way whatever was presented.

    ``token_type_hint`` is accepted and unused: RFC 7009 defines it as a hint for a server
    that stores several token types under one lookup, and there is one lookup here. Accepting
    it keeps a conforming client from having to know that.
    """
    await service.revoke(token, client_id)
    return Response(status_code=HTTPStatus.OK, headers=NO_STORE)


@well_known_router.get(AS_METADATA_PATH, summary="Authorization Server metadata")
async def as_metadata(state: OAuthStateDep, response: Response) -> dict[str, Any]:
    """The RFC 8414 document, built from the pinned issuer and nothing else."""
    response.headers.update(NO_STORE)
    return build_metadata(state.config)


@well_known_router.get(JWKS_PATH, summary="The signing keys, current and previous")
async def jwks(state: OAuthStateDep, response: Response) -> JsonWebKeySet:
    """The public keys a verifier needs.

    Both keys, so a token signed a moment before a rotation still verifies. Public material
    only: :meth:`~syncr_api.oauth.keys.SigningKeySet.jwks` builds it from the public halves and
    has no path to a private one.

    Not cached, deliberately. A verifier holding a stale key set is exactly the failure keeping
    two keys exists to prevent, and this document is read once per verifier rather than per
    request.
    """
    response.headers.update(NO_STORE)
    return JsonWebKeySet(**state.keys.jwks())
