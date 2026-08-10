"""The three Google account routes: start a connect, finish one, read the connection.

Thin, like every route module here. Each validates its inputs, resolves who is asking, calls one
service method, and maps the result onto a response.

``GET .../callback`` is the one route in this package Google addresses rather than the browser
application. Three things follow from that, and each is deliberate:

*It answers with a redirect, not a document.* The user arrives by top-level navigation, so a JSON
body would be a blank page with JSON in it. The outcome travels as one query value from a closed
set and Settings states what it means.

*It resolves a session like every other route.* The cookie is ``SameSite=Lax``, which a browser
sends on a top-level GET navigation, so Google's redirect carries it. Completing a connect without
a session would mean accepting a grant for whoever the state named, which is a grant nobody is
signed in to own.

*Its path is fixed by the OAuth client's registration.* Google matches a redirect URI as an exact
string, so changing this path means editing the Google Cloud console. The path is a constant and a
test asserts the served route equals the registered one.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Query
from starlette.responses import RedirectResponse

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.google_account.config import CALLBACK_PATH, CONNECT_PATH, CONNECTION_PATH
from syncr_api.google_account.injection import AppBaseUrlDep, GoogleConnectionServiceDep
from syncr_api.google_account.outcomes import settings_url
from syncr_api.google_account.schemas import GoogleConnectionResponse, GoogleConsentResponse

router = APIRouter()


@router.post(CONNECT_PATH, summary="Start a Google connect. Names the scopes and what is read")
async def begin_google_connect(
    principal: PrincipalDep, service: GoogleConnectionServiceDep
) -> GoogleConsentResponse:
    """The consent surface: the scopes, which calendars are read, and the URL to open."""
    return GoogleConsentResponse.of(await service.begin_connect(principal))


@router.get(
    CALLBACK_PATH,
    status_code=HTTPStatus.SEE_OTHER,
    response_class=RedirectResponse,
    summary="Where Google returns from consent. Redirects to Settings with the outcome",
)
async def complete_google_connect(
    principal: PrincipalDep,
    service: GoogleConnectionServiceDep,
    app_base_url: AppBaseUrlDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Finish the connect and send the browser to Settings with how it ended."""
    outcome = await service.complete_connect(principal, code=code, state=state, error=error)
    # 303 rather than 302: the browser must GET the Settings route, and a 302 on a GET is
    # ambiguous enough that some clients preserve the query string differently.
    return RedirectResponse(
        settings_url(outcome, app_base_url=app_base_url), status_code=HTTPStatus.SEE_OTHER
    )


@router.get(CONNECTION_PATH, summary="Whether Google is connected, and every notice it raises")
async def read_google_connection(
    principal: PrincipalDep, service: GoogleConnectionServiceDep
) -> GoogleConnectionResponse:
    """The account's state, including the write-target expiry notice when it applies."""
    return GoogleConnectionResponse.of(await service.describe_connection(principal))
